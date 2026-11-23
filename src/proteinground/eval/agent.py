"""Runs one question through a model: a manual tool-use loop on the Messages API.

A manual loop rather than the SDK tool runner, because the eval needs per-turn token
accounting, a hard turn cap, and to stop the moment the model calls submit_answer.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import ValidationError

from proteinground.eval.schema import Question, Submission
from proteinground.fetch import Fetcher
from proteinground.tools import anthropic_tool_defs, run_tool

Arm = Literal["tools", "closed_book"]

SUBMIT_TOOL: dict[str, Any] = {
    "name": "submit_answer",
    "description": "Record your final answer. Call it exactly once, as your last action.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "premise_ok": {
                "type": "boolean",
                "description": (
                    "false if the question rests on a false premise or asks about "
                    "something that does not exist"
                ),
            },
            "answer": {
                "type": "string",
                "description": "Short answer in the format the question asks; empty when "
                "premise_ok is false",
            },
            "explanation": {"type": "string", "description": "One or two sentences"},
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Record IDs you took values from, e.g. P04637, 4HHB, AF-P04637-F1",
            },
        },
        "required": ["premise_ok", "answer", "explanation", "sources"],
        "additionalProperties": False,
    },
}

_COMMON = (
    "Some questions contain a false premise, or ask about a record, position or "
    "feature that does not exist. When that happens, set premise_ok to false, leave "
    "answer empty and say what is wrong in the explanation. Otherwise set premise_ok to "
    "true and answer in the format the question asks. Finish by calling submit_answer "
    "exactly once."
)
SYSTEM_PROMPTS: dict[Arm, str] = {
    "tools": (
        "You answer questions about proteins from public database records: UniProtKB, "
        "RCSB PDB and AlphaFold DB. Look every value up with the tools; do not answer a "
        "value from memory. A tool result with found=false means the database has no such "
        "record or feature. " + _COMMON + " In sources, list the record IDs the tool "
        "results came from."
    ),
    "closed_book": (
        "You answer questions about proteins (UniProtKB, RCSB PDB, AlphaFold DB records) "
        "from your own knowledge; you have no lookup tools. " + _COMMON + " In sources, "
        "list the record IDs you believe hold the answer."
    ),
}
NUDGE = "Call submit_answer now with your final answer."
EARLY_SUBMIT = json.dumps(
    {
        "error": "submit_answer was called in the same turn as lookups; read their results, "
        "then call submit_answer on its own"
    }
)

# Server-side refusal fallbacks exist for these models only.
FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-2"})


class MessagesClient(Protocol):
    def create(self, **params: Any) -> Any: ...


class AnthropicMessages:
    """Thin wrapper so the loop can run against the real API or a stub."""

    def __init__(self, fallbacks: bool = True) -> None:
        import anthropic  # optional dependency: pip install 'proteinground[eval]'

        self._client = anthropic.Anthropic()
        self.fallbacks = fallbacks

    def create(self, **params: Any) -> Any:
        if self.fallbacks and params.get("model") in FALLBACK_MODELS:
            return self._client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
            )
        return self._client.messages.create(**params)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    def add(self, raw: Any) -> None:
        self.input_tokens += int(getattr(raw, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(raw, "output_tokens", 0) or 0)
        self.cache_write_tokens += int(getattr(raw, "cache_creation_input_tokens", 0) or 0)
        self.cache_read_tokens += int(getattr(raw, "cache_read_input_tokens", 0) or 0)


@dataclass
class Episode:
    question_id: str
    arm: Arm
    model: str
    status: str = "ok"
    submission: Submission | None = None
    served_by: list[str] = field(default_factory=list)
    fallback_ran: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    retrieved: set[str] = field(default_factory=set)
    turns: int = 0
    nudged: bool = False
    usage: Usage = field(default_factory=Usage)
    usage_by_model: dict[str, Usage] = field(default_factory=dict)
    early_submits: int = 0
    seconds: float = 0.0
    error: str | None = None
    transcript: list[dict[str, Any]] = field(default_factory=list)

    def to_record(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "arm": self.arm,
            "model": self.model,
            "status": self.status,
            "submission": self.submission.model_dump() if self.submission else None,
            "served_by": self.served_by,
            "fallback_ran": self.fallback_ran,
            "tool_calls": self.tool_calls,
            "retrieved": sorted(self.retrieved),
            "turns": self.turns,
            "nudged": self.nudged,
            "usage": self.usage.__dict__,
            "usage_by_model": {m: u.__dict__ for m, u in self.usage_by_model.items()},
            "early_submits": self.early_submits,
            "seconds": round(self.seconds, 2),
            "error": self.error,
            "transcript": self.transcript,
        }


def _account(episode: Episode, usage: Any, requested: str) -> None:
    """Add one response's tokens, split by the model that produced them.

    With server-side fallbacks a single response can hold a declined hop on the requested
    model and a serving hop on the fallback model; usage.iterations prices each one.
    """
    episode.usage.add(usage)
    iterations = [
        i for i in getattr(usage, "iterations", None) or []
        if getattr(i, "type", "") in ("message", "fallback_message")
    ]  # fmt: skip
    if not iterations:
        episode.usage_by_model.setdefault(requested, Usage()).add(usage)
        return
    for item in iterations:
        if getattr(item, "type", "") == "fallback_message":
            episode.fallback_ran = True
        name = str(getattr(item, "model", None) or requested)
        episode.usage_by_model.setdefault(name, Usage()).add(item)


def _block_dict(block: Any) -> dict[str, Any]:
    if hasattr(block, "model_dump"):
        dumped: dict[str, Any] = block.model_dump(exclude_none=True)
        return dumped
    return dict(block)


def _collect_sources(result_json: str, into: set[str]) -> None:
    try:
        payload = json.loads(result_json)
    except ValueError:
        return
    for src in payload.get("sources", []) if isinstance(payload, dict) else []:
        for key in ("record_id", "url"):
            if src.get(key):
                into.add(str(src[key]))


def run_episode(
    client: MessagesClient,
    fetcher: Fetcher,
    question: Question,
    arm: Arm,
    model: str,
    effort: str = "medium",
    max_turns: int = 12,
    max_tokens: int = 16000,
) -> Episode:
    episode = Episode(question_id=question.id, arm=arm, model=model)
    tools = ([*anthropic_tool_defs(), SUBMIT_TOOL]) if arm == "tools" else [SUBMIT_TOOL]
    system = [{"type": "text", "text": SYSTEM_PROMPTS[arm], "cache_control": {"type": "ephemeral"}}]
    messages: list[dict[str, Any]] = [{"role": "user", "content": question.text}]
    started = time.monotonic()
    try:
        while episode.turns < max_turns:
            episode.turns += 1
            response = client.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=tools,
                messages=messages,
                output_config={"effort": effort},
                cache_control={"type": "ephemeral"},
            )
            _account(episode, response.usage, model)
            episode.served_by.append(str(getattr(response, "model", model)))
            content = list(response.content)
            episode.transcript.append(
                {
                    "role": "assistant",
                    "stop_reason": response.stop_reason,
                    "content": [_block_dict(b) for b in content],
                }
            )
            if response.stop_reason == "refusal":
                episode.status = "refused"
                break
            messages.append({"role": "assistant", "content": content})
            tool_uses = [b for b in content if getattr(b, "type", "") == "tool_use"]
            if not tool_uses:
                if response.stop_reason == "max_tokens" or episode.nudged:
                    break
                episode.nudged = True
                messages.append({"role": "user", "content": NUDGE})
                episode.transcript.append({"role": "user", "content": NUDGE})
                continue

            results: list[dict[str, Any]] = []
            lookups_this_turn = any(b.name != "submit_answer" for b in tool_uses)
            for block in tool_uses:
                if block.name == "submit_answer" and lookups_this_turn:
                    # Written before the lookups came back, so it cannot be grounded in them.
                    episode.early_submits += 1
                    text, is_error = EARLY_SUBMIT, True
                elif block.name == "submit_answer":
                    try:
                        episode.submission = Submission.model_validate(block.input)
                        text, is_error = '{"recorded": true}', False
                    except ValidationError as exc:
                        text, is_error = json.dumps({"error": str(exc)}), True
                else:
                    text, is_error = run_tool(fetcher, block.name, block.input)
                    if not is_error:
                        _collect_sources(text, episode.retrieved)
                    episode.tool_calls.append(
                        {"name": block.name, "input": block.input, "is_error": is_error}
                    )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": text,
                        **({"is_error": True} if is_error else {}),
                    }
                )
            episode.transcript.append({"role": "user", "content": results})
            if episode.submission is not None:
                break
            messages.append({"role": "user", "content": results})
    except Exception as exc:  # recorded per item so one failure does not sink the run
        episode.status = "error"
        episode.error = f"{type(exc).__name__}: {exc}"
    episode.seconds = time.monotonic() - started
    return episode
