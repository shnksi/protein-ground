"""The question set, the gold check and the agent loop, all offline and free."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from proteinground.eval.agent import NUDGE, run_episode
from proteinground.eval.goldcheck import check
from proteinground.eval.grade import grade
from proteinground.eval.schema import Question
from proteinground.eval.stub import StubBlock, StubMessage, StubMessages, StubUsage
from proteinground.fetch import Fetcher


def test_question_set_shape(questions: list[Question]) -> None:
    assert len({q.id for q in questions}) == len(questions)
    planted = [q for q in questions if not q.premise_ok]
    assert 0.15 <= len(planted) / len(questions) <= 0.25
    assert all(q.trap and q.evidence_signal is not None for q in planted)
    assert Counter(q.family for q in questions)["residue_at"] >= 10


def test_every_gold_answer_is_reachable_through_the_tools(
    offline: Fetcher, questions: list[Question]
) -> None:
    failures = {q.id: reason for q in questions if (reason := check(offline, q))}
    assert failures == {}


class Scripted:
    """Replays a fixed list of responses, recording the requests it was sent."""

    def __init__(self, responses: list[StubMessage]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def create(self, **params: Any) -> StubMessage:
        # The loop keeps appending to the same list, so record a copy of this turn's view.
        self.requests.append({**params, "messages": list(params["messages"])})
        return self.responses.pop(0)


def msg(*blocks: StubBlock, stop: str = "tool_use") -> StubMessage:
    return StubMessage(list(blocks), stop, StubUsage(input_tokens=100, output_tokens=20), "m")


def tool(name: str, **kwargs: Any) -> StubBlock:
    return StubBlock("tool_use", id=f"t-{name}", name=name, input=kwargs)


def by_id(questions: list[Question], qid: str) -> Question:
    return next(q for q in questions if q.id == qid)


def test_loop_runs_tools_then_grades_a_correct_grounded_answer(
    offline: Fetcher, questions: list[Question]
) -> None:
    q = next(q for q in questions if q.family == "residue_at")
    pos = q.evidence[0].input["start"]
    acc = q.evidence[0].input["accession"]
    client = Scripted(
        [
            msg(tool("get_sequence_window", accession=acc, start=pos, end=pos)),
            msg(
                tool(
                    "submit_answer",
                    premise_ok=True,
                    answer=str(q.gold),
                    explanation="looked up",
                    sources=[acc],
                )
            ),
        ]
    )
    episode = run_episode(client, offline, q, "tools", "claude-opus-5-5")
    result = grade(q, episode.submission, episode.status, episode.retrieved)
    assert (result.outcome, result.grounded) == ("correct", True)
    assert episode.usage.input_tokens == 200 and episode.turns == 2
    second = client.requests[1]["messages"]
    assert second[-1]["content"][0]["type"] == "tool_result"
    assert client.requests[0]["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_loop_catches_a_planted_premise(offline: Fetcher, questions: list[Question]) -> None:
    q = by_id(questions, "trap-p01308-pos450")
    client = Scripted(
        [
            msg(tool("get_sequence_window", accession="P01308", start=450, end=450)),
            msg(
                tool(
                    "submit_answer",
                    premise_ok=False,
                    answer="",
                    explanation="only 110 aa",
                    sources=["P01308"],
                )
            ),
        ]
    )
    episode = run_episode(client, offline, q, "tools", "m")
    assert grade(q, episode.submission, episode.status, episode.retrieved).outcome == "correct"


def test_loop_nudges_once_then_gives_up(offline: Fetcher, questions: list[Question]) -> None:
    q = questions[0]
    text = StubBlock("text", text="I think it is R.")
    client = Scripted([msg(text, stop="end_turn"), msg(text, stop="end_turn")])
    episode = run_episode(client, offline, q, "tools", "m")
    assert episode.nudged and episode.submission is None and episode.turns == 2
    assert client.requests[1]["messages"][-1] == {"role": "user", "content": NUDGE}


def test_loop_records_refusals(offline: Fetcher, questions: list[Question]) -> None:
    client = Scripted([msg(stop="refusal")])
    episode = run_episode(client, offline, questions[0], "tools", "m")
    assert episode.status == "refused"


def test_invalid_submission_goes_back_as_a_tool_error(
    offline: Fetcher, questions: list[Question]
) -> None:
    client = Scripted(
        [
            msg(tool("submit_answer", answer="R")),
            msg(tool("submit_answer", premise_ok=True, answer="R", explanation="", sources=[])),
        ]
    )
    episode = run_episode(client, offline, questions[0], "tools", "m")
    assert episode.submission is not None and episode.turns == 2
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True


class SpyStub(StubMessages):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[dict[str, Any]] = []

    def create(self, **params: Any) -> StubMessage:
        self.requests.append({**params, "messages": list(params["messages"])})
        return super().create(**params)


def test_closed_book_arm_offers_only_submit(offline: Fetcher, questions: list[Question]) -> None:
    spy = SpyStub()
    episode = run_episode(spy, offline, questions[0], "closed_book", "m")
    assert [t["name"] for t in spy.requests[0]["tools"]] == ["submit_answer"]
    assert episode.submission is not None and not episode.tool_calls


def test_stub_tools_arm_drives_one_lookup(offline: Fetcher, questions: list[Question]) -> None:
    spy = SpyStub()
    episode = run_episode(spy, offline, questions[0], "tools", "m")
    assert len(episode.tool_calls) == 1 and episode.submission is not None


def test_submit_alongside_lookups_is_sent_back(offline: Fetcher, questions: list[Question]) -> None:
    q = next(q for q in questions if q.family == "length")
    acc = q.evidence[0].input["accession"]
    client = Scripted([
        msg(tool("get_protein", accession=acc),
            tool("submit_answer", premise_ok=True, answer="1", explanation="", sources=[acc])),
        msg(tool("submit_answer", premise_ok=True, answer=str(q.gold), explanation="",
                 sources=[acc])),
    ])  # fmt: skip
    episode = run_episode(client, offline, q, "tools", "m")
    assert episode.early_submits == 1 and episode.turns == 2
    assert episode.submission is not None and episode.submission.answer == str(q.gold)


@dataclass
class Iteration:
    type: str
    input_tokens: int
    output_tokens: int
    model: str | None = None
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


def test_fallback_tokens_are_priced_per_model(offline: Fetcher, questions: list[Question]) -> None:
    usage = StubUsage(input_tokens=300, output_tokens=60, iterations=[
        Iteration("message", 100, 20),
        Iteration("fallback_message", 200, 40, model="claude-opus-5"),
    ])  # fmt: skip
    submit = tool("submit_answer", premise_ok=True, answer="R", explanation="", sources=[])
    client = Scripted([StubMessage([submit], "tool_use", usage, "claude-opus-5")])
    episode = run_episode(client, offline, questions[0], "tools", "claude-opus-5-5")
    assert episode.fallback_ran
    assert episode.usage_by_model["claude-opus-5-5"].input_tokens == 100
    assert episode.usage_by_model["claude-opus-5"].output_tokens == 40


def test_stub_decoys_bracket_the_false_premise_metric(
    offline: Fetcher, questions: list[Question]
) -> None:
    for policy, caught, alarms in (("lookup", 0.0, 0.0), ("abstain", 1.0, 1.0)):
        stub = StubMessages(policy=policy)
        grades = []
        for q in questions:
            ep = run_episode(stub, offline, q, "tools", "m")
            grades.append(grade(q, ep.submission, ep.status, ep.retrieved))
        planted = [g for g in grades if not g.premise_ok_gold]
        answerable = [g for g in grades if g.premise_ok_gold]
        assert sum(g.outcome == "correct" for g in planted) / len(planted) == caught
        assert sum(g.outcome == "false_alarm" for g in answerable) / len(answerable) == alarms
        assert not any(g.outcome == "correct" for g in answerable)
