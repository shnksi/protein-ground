"""A zero-cost stand-in for the Messages API, for dry runs.

It drives the real loop, tools, snapshot and graders without a network call to a model.
Token counts are estimated from request size (about four characters per token), so a dry
run also gives a first cost estimate before any paid call.
"""

from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass, field
from typing import Any

_ACCESSION = re.compile(r"\b([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9][A-Z][A-Z0-9]{2}[0-9])\b")
_PDB = re.compile(r"\bPDB entry ([1-9][A-Z0-9]{3})\b")
_ids = itertools.count(1)


@dataclass
class StubBlock:
    type: str
    text: str | None = None
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        raw = {
            "type": self.type,
            "text": self.text,
            "id": self.id,
            "name": self.name,
            "input": self.input,
        }
        return {k: v for k, v in raw.items() if v is not None or not exclude_none}


@dataclass
class StubUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    iterations: list[Any] = field(default_factory=list)


@dataclass
class StubMessage:
    content: list[StubBlock]
    stop_reason: str
    usage: StubUsage
    model: str


def _estimate_tokens(obj: Any) -> int:
    return max(1, len(json.dumps(obj, default=lambda o: getattr(o, "__dict__", str(o)))) // 4)


class StubMessages:
    """Looks up the first ID in the question once, then submits an empty answer.

    policy="lookup" always claims the premise holds; policy="abstain" always says it
    does not. Both are decoys: the first must score 0% on planted items, the second must
    score 100% on them and 100% false alarms, which is why the two metrics are read together.
    """

    def __init__(self, output_tokens_per_turn: int = 600, policy: str = "lookup") -> None:
        self.output_tokens_per_turn = output_tokens_per_turn
        self.policy = policy
        self.calls = 0

    def create(self, **params: Any) -> StubMessage:
        self.calls += 1
        messages: list[dict[str, Any]] = params["messages"]
        tool_names = {t["name"] for t in params.get("tools", [])}
        question = str(messages[0]["content"])
        usage = StubUsage(
            input_tokens=_estimate_tokens([params.get("system"), params.get("tools"), messages]),
            output_tokens=self.output_tokens_per_turn,
        )
        first_turn = len(messages) == 1
        pdb_match, acc_match = _PDB.search(question), _ACCESSION.search(question)
        if first_turn and "get_structure" in tool_names and pdb_match:
            block = StubBlock(
                "tool_use",
                id=f"stub_{next(_ids)}",
                name="get_structure",
                input={"pdb_id": pdb_match.group(1)},
            )
            return StubMessage([block], "tool_use", usage, "stub")
        if first_turn and "get_protein" in tool_names and acc_match:
            block = StubBlock(
                "tool_use",
                id=f"stub_{next(_ids)}",
                name="get_protein",
                input={"accession": acc_match.group(1)},
            )
            return StubMessage([block], "tool_use", usage, "stub")
        sources = [m.group(1) for m in (pdb_match, acc_match) if m]
        submit = StubBlock(
            "tool_use",
            id=f"stub_{next(_ids)}",
            name="submit_answer",
            input={
                "premise_ok": self.policy != "abstain",
                "answer": "",
                "explanation": "stub",
                "sources": sources,
            },
        )
        return StubMessage([submit], "tool_use", usage, "stub")
