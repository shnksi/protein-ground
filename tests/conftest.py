from __future__ import annotations

from pathlib import Path

import pytest

from proteinground.eval.schema import Question, load_questions
from proteinground.fetch import Fetcher, Mode

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "evals" / "snapshot"
QUESTIONS = ROOT / "evals" / "questions.jsonl"


@pytest.fixture
def offline() -> Fetcher:
    """Tools read the frozen snapshot only; any network need fails the test."""
    return Fetcher(cache_dir=SNAPSHOT, mode=Mode.OFFLINE)


@pytest.fixture(scope="session")
def questions() -> list[Question]:
    return load_questions(QUESTIONS)
