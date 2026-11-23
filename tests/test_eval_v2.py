"""Eval v2: the drawn question set, its gold check, the two prompts and the stub decoys."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from test_eval import Scripted, msg, tool
from test_grade import natural_and_hedged

from proteinground.eval import agent
from proteinground.eval.agent import run_episode
from proteinground.eval.cli import main
from proteinground.eval.goldcheck import check
from proteinground.eval.grade import check_answer, grade
from proteinground.eval.schema import Question, Submission, load_questions
from proteinground.eval.stub import StubMessages
from proteinground.fetch import Fetcher, Mode

ROOT = Path(__file__).resolve().parent.parent
V2 = ROOT / "evals" / "v2"
NEW_FAMILIES = {
    "structure_numbering",
    "structure_residue",
    "modelled_residue",
    "insertion_code",
    "engineered_mutation",
    "variant_lookup",
    "isoform_residue",
    "obsolete_replacement",
}
SUBTLE_TRAPS = {
    "wrong_wild_type",
    "author_number_as_uniprot",
    "unmodelled_residue",
    "no_difference",
    "isoform_missing",
    "obsolete_no_successor",
}


@pytest.fixture(scope="module")
def v2() -> list[Question]:
    return load_questions(V2 / "questions.jsonl")


@pytest.fixture
def v2_offline() -> Fetcher:
    return Fetcher(cache_dir=V2 / "snapshot", mode=Mode.OFFLINE)


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((V2 / "MANIFEST.json").read_text())
    return loaded


def test_v2_shape(v2: list[Question], manifest: dict[str, Any]) -> None:
    assert len(v2) >= 150 and len({q.id for q in v2}) == len(v2)
    planted = [q for q in v2 if not q.premise_ok]
    assert 0.17 <= len(planted) / len(v2) <= 0.23
    assert all(q.trap and q.evidence_signal is not None for q in planted)
    families = Counter(q.family for q in v2)
    assert set(families) >= NEW_FAMILIES
    answerable = len(v2) - len(planted)
    assert 1 / answerable < 0.01  # one item moves the headline by less than a point
    assert {k for k, n in manifest["planted_kinds"].items() if n} >= SUBTLE_TRAPS
    assert manifest["questions"] == len(v2) and manifest["proteins"] >= 38
    assert manifest["unreviewed"] >= 8 and manifest["organisms"] >= 25


def test_v2_proteins_are_drawn_not_picked(manifest: dict[str, Any]) -> None:
    drawn = [a for s in manifest["strata"].values() for a in s["drawn"]]
    assert len(drawn) == len(set(drawn)) == manifest["proteins"]
    assert all("organism_id:9606" in s["query"] for s in manifest["strata"].values())
    v1_panel = {"P04637", "P01116", "P00533", "P01308", "P68871", "P69905", "P61626", "P42212"}
    assert not v1_panel & set(drawn)


def test_v2_gold_is_reachable_through_the_tools(v2_offline: Fetcher, v2: list[Question]) -> None:
    failures = {q.id: reason for q in v2 if (reason := check(v2_offline, q))}
    assert failures == {}


def test_v2_items_accept_natural_answers_and_reject_hedges(v2: list[Question]) -> None:
    failures = []
    for q in v2:
        if not q.premise_ok:
            continue
        good, bad = natural_and_hedged(q)
        failures += [(q.id, a, "rejected") for a in good if not check_answer(q, a)[0]]
        failures += [(q.id, a, "accepted") for a in bad if check_answer(q, a)[0]]
    assert failures == []


def test_every_planted_item_asks_for_something_that_is_not_there(v2: list[Question]) -> None:
    """No planted item has a literal answer, except where the answer itself is the correction."""
    for q in v2:
        if q.premise_ok:
            continue
        kind = q.family.removeprefix("false_premise.")
        if kind == "wrong_wild_type":
            assert q.answer_type == "mutation" and q.gold and q.gold[0] not in q.id.split("-")[-1]
        else:
            assert q.answer_type is None and q.gold is None, q.id
        assert kind not in ("wrong_method", "wrong_organism", "wrong_name")


def test_obsolete_answers_may_repeat_the_id_the_question_gave(v2: list[Question]) -> None:
    q = next(q for q in v2 if q.family == "obsolete_replacement")
    old, new = q.record_ids[0], q.gold[0]
    assert check_answer(q, f"{old} was superseded by {new}")[0]
    assert not check_answer(q, old)[0]
    assert not check_answer(q, f"{new} or 1ABC")[0]


def test_primed_prompt_is_the_one_v1_ran_with() -> None:
    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()[:16]

    assert digest(agent.PROMPTS["primed"]["tools"]) == "7561f2bb2e93f2e0"
    assert digest(agent.PROMPTS["primed"]["closed_book"]) == "780d59978eb7428a"
    form = json.dumps(agent.SUBMIT_TOOLS["primed"], sort_keys=True)
    assert digest(form) == "949a198256e0ebe7"


@pytest.mark.parametrize("arm", ["tools", "closed_book"])
def test_unprimed_prompt_gives_no_warning_and_no_lookup_instruction(arm: agent.Arm) -> None:
    text = agent.PROMPTS["unprimed"][arm].lower()
    form = json.dumps(agent.SUBMIT_TOOLS["unprimed"]).lower()
    for word in ("premise", "does not exist", "false", "look every", "do not answer", "memory"):
        assert word not in text, word
    for word in ("premise", "does not exist"):
        assert word not in form, word
    # The tool descriptions are the product under test and are the same under both prompts.
    # They do say what found=false means; the preregistration states that.
    assert "premise" in agent.PROMPTS["primed"][arm].lower()
    assert "submit_answer" in text


def test_unprimed_form_records_answerable_as_the_premise_flag(
    v2_offline: Fetcher, v2: list[Question]
) -> None:
    q = next(q for q in v2 if not q.premise_ok)
    client = Scripted(
        [
            msg(tool("submit_answer", premise_ok=False, answer="", explanation="", sources=[])),
            msg(tool("submit_answer", answerable=False, answer="", explanation="no", sources=[])),
        ]
    )
    episode = run_episode(client, v2_offline, q, "closed_book", "m", prompt="unprimed")
    assert episode.prompt == "unprimed" and episode.to_record()["prompt"] == "unprimed"
    assert episode.submission == Submission(
        premise_ok=False, answer="", explanation="no", sources=[]
    )
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True  # the first try
    properties = client.requests[0]["tools"][-1]["input_schema"]["properties"]
    assert "answerable" in properties and "premise_ok" not in properties
    assert client.requests[0]["system"][0]["text"] == agent.PROMPTS["unprimed"]["closed_book"]
    assert grade(q, episode.submission, episode.status, None).outcome == "correct"


@pytest.mark.parametrize("prompt", ["primed", "unprimed"])
def test_v2_stub_decoys_bracket_the_false_premise_metric(
    v2_offline: Fetcher, v2: list[Question], prompt: agent.Prompt
) -> None:
    for policy, caught, alarms in (("lookup", 0.0, 0.0), ("abstain", 1.0, 1.0)):
        stub = StubMessages(policy=policy)
        grades = []
        for q in v2:
            ep = run_episode(stub, v2_offline, q, "tools", "m", prompt=prompt)
            grades.append(grade(q, ep.submission, ep.status, ep.retrieved))
        planted = [g for g in grades if not g.premise_ok_gold]
        answerable = [g for g in grades if g.premise_ok_gold]
        assert sum(g.outcome == "correct" for g in planted) / len(planted) == caught
        assert sum(g.outcome == "false_alarm" for g in answerable) / len(answerable) == alarms
        assert not any(g.outcome == "correct" for g in answerable)


@pytest.mark.parametrize("arm", ["tools", "closed_book"])
@pytest.mark.parametrize("prompt", ["primed", "unprimed"])
def test_cli_dry_run_covers_every_arm_and_prompt(
    tmp_path: Path, v2: list[Question], arm: str, prompt: str
) -> None:
    out = tmp_path / f"{arm}-{prompt}"
    code = main(
        [
            "run", "--arm", arm, "--prompt", prompt, "--stub", "--strict-offline",
            "--questions", str(V2 / "questions.jsonl"), "--snapshot", str(V2 / "snapshot"),
            "--out", str(out),
        ]
    )  # fmt: skip
    assert code == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["items"] == len(v2) and summary["snapshot_misses"] == 0
    assert (summary["arm"], summary["prompt"]) == (arm, prompt)
    assert summary["outcomes"].get("error", 0) == 0
    assert f"| {arm}, {prompt} |" in (out / "report.md").read_text()


def test_published_v1_grades_do_not_move_under_the_current_graders() -> None:
    v1 = {q.id: q for q in load_questions(ROOT / "evals" / "questions.jsonl")}
    results = ROOT / "evals" / "results" / "2026-11-23-opus-5-5"
    checked = 0
    for name in ("tools-episodes.jsonl", "closed-episodes.jsonl"):
        for line in (results / name).read_text().splitlines():
            record = json.loads(line)
            submission = (
                Submission.model_validate(record["submission"]) if record["submission"] else None
            )
            retrieved = set(record["retrieved"]) if record["arm"] == "tools" else None
            regraded = grade(v1[record["question_id"]], submission, record["status"], retrieved)
            assert regraded.model_dump() == record["grade"], record["question_id"]
            checked += 1
    assert checked == 136


def test_run_stops_once_too_many_episodes_miss_the_snapshot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty-snapshot"
    empty.mkdir()
    code = main(
        [
            "run", "--arm", "tools", "--stub", "--strict-offline", "--max-miss-episodes", "2",
            "--questions", str(V2 / "questions.jsonl"), "--snapshot", str(empty),
            "--out", str(tmp_path / "out"),
        ]
    )  # fmt: skip
    assert code == 0
    assert "STOP: 3 episodes read records outside the snapshot" in capsys.readouterr().out
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["items"] == 3 and summary["snapshot_misses"] == 3
