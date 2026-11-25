"""Intervals and the paired comparison in the eval report."""

from __future__ import annotations

from typing import Any

from proteinground.eval.report import comparison_line, markdown, paired, summarise, wilson


def record(qid: str, outcome: str, answerable: bool = True, arm: str = "tools") -> dict[str, Any]:
    return {
        "question_id": qid,
        "arm": arm,
        "model": "m",
        "submission": {"premise_ok": True},
        "tool_calls": [],
        "seconds": 1.0,
        "cost_usd": 0.01,
        "grade": {
            "premise_ok_gold": answerable,
            "outcome": outcome,
            "family": "residue_at" if answerable else "false_premise",
            "cited": True,
            "grounded": True,
        },
    }


def test_wilson_interval_keeps_width_at_the_extremes() -> None:
    assert wilson(0, 0) is None
    assert wilson(55, 55) == [0.935, 1.0]  # a perfect score on 55 items is not "exactly 100%"
    assert wilson(0, 13) == [0.0, 0.228]
    low, high = wilson(43, 55) or [0.0, 0.0]
    assert 0.65 < low < 0.782 < high < 0.88


def test_paired_test_counts_only_the_items_the_arms_disagree_on() -> None:
    first = [record(f"q{i}", "correct") for i in range(55)]
    second = [
        record(f"q{i}", "wrong" if i < 12 else "correct", arm="closed_book") for i in range(55)
    ]
    result = paired(first, second)
    assert result is not None
    assert (result["first_only_correct"], result["second_only_correct"]) == (12, 0)
    assert result["gap_points"] == 21.8 and result["p_value_exact"] == 0.0005
    low, high = result["gap_points_ci95_approx"]
    assert low < 21.8 < high < 35

    same = paired(first, first)
    assert same is not None and same["p_value_exact"] == 1.0 and same["gap_points"] == 0.0
    assert paired(first, [record("other", "correct")]) is None  # no shared items

    huge_a = [record(f"q{i}", "correct") for i in range(40)]
    huge_b = [record(f"q{i}", "wrong", arm="closed_book") for i in range(40)]
    tiny = paired(huge_a, huge_b)
    assert tiny is not None and 0.0 < tiny["p_value_exact"] < 1e-10


def test_paired_test_ignores_planted_items() -> None:
    first = [record("a", "correct"), record("trap", "correct", answerable=False)]
    second = [record("a", "wrong"), record("trap", "accepted_false_premise", answerable=False)]
    result = paired(first, second)
    assert result is not None and result["items"] == 1


def test_report_shows_intervals_and_the_comparison() -> None:
    first = [record(f"q{i}", "correct") for i in range(10)]
    first.append(record("trap", "correct", answerable=False))
    second = [
        record(f"q{i}", "wrong" if i < 4 else "correct", arm="closed_book") for i in range(10)
    ]
    summaries = [summarise(first), summarise(second)]
    assert summaries[0]["ci95"]["accuracy_answerable"] == wilson(10, 10)
    result = paired(first, second)
    assert result is not None
    text = markdown(summaries, [comparison_line(summaries[0], summaries[1], result)])
    assert "100% (72–100)" in text and "60% (31–83)" in text
    assert "4 items only the first got right, 0 only the second" in text


def test_repeated_runs_are_summarised_by_median_and_range() -> None:
    def run(wrong: int, prompt: str) -> dict[str, Any]:
        records = [record(f"q{i}", "wrong" if i < wrong else "correct") for i in range(10)]
        records.append(record("trap", "correct", answerable=False))
        return {**summarise(records), "prompt": prompt}

    runs = [run(1, "unprimed"), run(3, "unprimed"), run(2, "unprimed"), run(0, "primed")]
    text = markdown(runs)
    # One decimal, so a bar at 90% is decided by the table and not hidden by rounding.
    assert (
        "| tools, unprimed | m | 3 | 80.0% [70.0–90.0] | 100.0% [100.0–100.0] | 0.0% [0.0–0.0] "
        "| 100.0% [100.0–100.0] |"
    ) in text
    assert "| tools, primed | m | 1 | 100.0% [100.0–100.0] |" in text
    assert runs[0]["premise_discrimination"] == 1.0
    assert "Repeated runs" not in markdown([run(1, "unprimed"), run(0, "primed")])
