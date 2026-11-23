"""Question, submission and grade records. Questions are JSONL, one per line."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AnswerType = Literal["residue", "int", "range", "method_resolution", "float", "id_set", "token"]
Outcome = Literal[
    "correct",
    "wrong",
    "false_alarm",
    "accepted_false_premise",
    "no_answer",
    "refused",
    "error",
]


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    input: dict[str, Any]


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    family: str
    text: str
    premise_ok: bool
    answer_type: AnswerType | None = Field(description="None for false-premise items")
    gold: Any = None
    tolerance: float | None = None
    record_ids: list[str] = Field(description="Records that hold the answer or refute it")
    evidence: list[ToolCall] = Field(description="Tool calls whose output settles the item")
    trap: str | None = Field(default=None, description="What is false, for planted items")
    evidence_signal: Any = Field(
        default=None,
        description="For planted items: 'not_found', or a value in the evidence that "
        "contradicts the premise",
    )
    reject: list[str] = Field(
        default_factory=list, description="Wrong alternatives; an answer naming one fails"
    )


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    premise_ok: bool
    answer: str
    explanation: str
    sources: list[str]


class Grade(BaseModel):
    question_id: str
    family: str
    premise_ok_gold: bool
    outcome: Outcome
    answer_correct: bool | None
    cited: bool | None = Field(description="Submission names a record that holds the answer")
    grounded: bool | None = Field(
        description="That record was actually retrieved by a tool during the episode"
    )
    detail: str


def load_questions(path: Path) -> list[Question]:
    return [
        Question.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()
    ]


def write_questions(path: Path, questions: list[Question]) -> None:
    path.write_text("".join(q.model_dump_json() + "\n" for q in questions))
