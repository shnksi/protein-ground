"""Summaries and Markdown tables from graded episode records."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_records(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "episodes.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def wilson(successes: int, n: int, z: float = 1.96) -> list[float] | None:
    """95% Wilson score interval for a proportion.

    Unlike the usual plus-or-minus, it does not collapse to a zero-width interval at 0%
    or 100%, which is where a small set like this one tends to land.
    """
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def paired(first: list[dict[str, Any]], second: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compare two arms on the answerable items both of them ran.

    The arms answer the same questions, so the evidence is in the items where they
    disagree: an exact two-sided sign test on those (McNemar's exact test).
    """

    def correct(records: list[dict[str, Any]]) -> dict[str, bool]:
        return {
            r["question_id"]: r["grade"]["outcome"] == "correct"
            for r in records
            if r["grade"]["premise_ok_gold"]
        }

    a, b = correct(first), correct(second)
    shared = sorted(a.keys() & b.keys())
    if not shared:
        return None
    first_only = sum(a[q] and not b[q] for q in shared)
    second_only = sum(b[q] and not a[q] for q in shared)
    discordant = first_only + second_only
    tail = sum(math.comb(discordant, k) for k in range(min(first_only, second_only) + 1))
    p_value = 1.0 if discordant == 0 else min(1.0, 2 * tail / 2**discordant)
    n = len(shared)
    gap = (first_only - second_only) / n
    # Wald interval for a paired difference: rough at this size, so it is labelled as such.
    half = 1.96 * math.sqrt(max(0.0, discordant - (first_only - second_only) ** 2 / n)) / n
    return {
        "items": n,
        "first_only_correct": first_only,
        "second_only_correct": second_only,
        "gap_points": round(100 * gap, 1),
        "gap_points_ci95_approx": [round(100 * (gap - half), 1), round(100 * (gap + half), 1)],
        "p_value_exact": round(p_value, 4),
    }


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in records if r["grade"]["premise_ok_gold"]]
    planted = [r for r in records if not r["grade"]["premise_ok_gold"]]
    outcomes = Counter(r["grade"]["outcome"] for r in records)
    submitted = [r for r in records if r["submission"] is not None]
    grounded = [r for r in submitted if r["grade"]["grounded"] is not None]
    by_family: dict[str, list[bool]] = defaultdict(list)
    for r in records:
        by_family[r["grade"]["family"]].append(r["grade"]["outcome"] == "correct")
    costs = [r["cost_usd"] for r in records if r.get("cost_usd") is not None]
    own = [r for r in answerable if not r.get("fallback_ran")]
    first = records[0] if records else {}
    answerable_correct = sum(r["grade"]["outcome"] == "correct" for r in answerable)
    caught = sum(r["grade"]["outcome"] == "correct" for r in planted)
    caught_rate = _rate(caught, len(planted))
    alarm_rate = _rate(outcomes["false_alarm"], len(answerable))
    return {
        "arm": first.get("arm"),
        "prompt": first.get("prompt"),
        "model": first.get("model"),
        "items": len(records),
        "answerable": len(answerable),
        "planted": len(planted),
        "accuracy_answerable": _rate(answerable_correct, len(answerable)),
        "false_premise_caught": _rate(caught, len(planted)),
        "false_premise_accepted": _rate(outcomes["accepted_false_premise"], len(planted)),
        "false_alarms": alarm_rate,
        # Caught minus false alarms: rejecting everything scores 0 here, like accepting everything.
        "premise_discrimination": None
        if caught_rate is None or alarm_rate is None
        else round(caught_rate - alarm_rate, 3),
        "ci95": {
            "accuracy_answerable": wilson(answerable_correct, len(answerable)),
            "false_premise_caught": wilson(caught, len(planted)),
            "false_alarms": wilson(outcomes["false_alarm"], len(answerable)),
        },
        "cited_rate": _rate(sum(bool(r["grade"]["cited"]) for r in submitted), len(submitted)),
        "grounded_rate": _rate(sum(bool(r["grade"]["grounded"]) for r in grounded), len(grounded))
        if grounded
        else None,
        "outcomes": dict(outcomes),
        "mean_tool_calls": round(sum(len(r["tool_calls"]) for r in records) / len(records), 2)
        if records
        else None,
        "fallbacks": sum(bool(r.get("fallback_ran")) for r in records),
        "accuracy_answerable_named_model_only": _rate(
            sum(r["grade"]["outcome"] == "correct" for r in own), len(own)
        ),
        "early_submits": sum(int(r.get("early_submits", 0)) for r in records),
        "snapshot_misses": sum(len(r.get("snapshot_misses", [])) for r in records),
        "cost_usd": round(sum(costs), 4) if costs else None,
        "cost_per_item_usd": round(sum(costs) / len(costs), 5) if costs else None,
        "mean_seconds": round(sum(r["seconds"] for r in records) / len(records), 1)
        if records
        else None,
        "by_family": {k: _rate(sum(v), len(v)) for k, v in sorted(by_family.items())},
    }


def _pct(value: Any) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


def _pct_ci(value: Any, interval: list[float] | None) -> str:
    """A rate with its 95% interval, e.g. '78% (66–87)'."""
    if value is None or interval is None:
        return _pct(value)
    return f"{value * 100:.0f}% ({interval[0] * 100:.0f}–{interval[1] * 100:.0f})"


def _usd(value: Any) -> str:
    return "–" if value is None else f"${value:.4f}"


def _arm(summary: dict[str, Any]) -> str:
    """The arm, with its prompt when the run recorded one (runs before v2 did not)."""
    prompt = summary.get("prompt")
    return f"{summary['arm']}, {prompt}" if prompt else str(summary["arm"])


def comparison_line(first: dict[str, Any], second: dict[str, Any], result: dict[str, Any]) -> str:
    low, high = result["gap_points_ci95_approx"]
    return (
        f"{_arm(first)} / {first['model']} vs {_arm(second)} / {second['model']}, on the "
        f"{result['items']} answerable items both ran: {result['first_only_correct']} items "
        f"only the first got right, {result['second_only_correct']} only the second. Gap "
        f"{result['gap_points']:+.1f} points (approximate 95% interval {low:+.1f} to "
        f"{high:+.1f}); exact paired test p = {result['p_value_exact']}."
    )


REPLICATED = (
    "accuracy_answerable",
    "false_premise_caught",
    "false_alarms",
    "premise_discrimination",
    "grounded_rate",
)


def _spread(values: list[Any]) -> str:
    """The median of several runs with the lowest and highest, e.g. '91% [89–93]'."""
    known = sorted(v for v in values if v is not None)
    if not known:
        return "–"
    median = statistics.median(known)
    return f"{median * 100:.1f}% [{known[0] * 100:.1f}–{known[-1] * 100:.1f}]"


def replicate_rows(summaries: list[dict[str, Any]]) -> list[str]:
    """One line per arm, prompt and model that was run more than once; else nothing."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for s in summaries:
        groups.setdefault((_arm(s), str(s["model"])), []).append(s)
    if all(len(group) < 2 for group in groups.values()):
        return []
    rows = [
        "",
        "| Arm | Model | Runs | Answerable correct | False premise caught | False alarms "
        "| Caught minus false alarms | Grounded |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for (arm, model), group in groups.items():
        cells = " | ".join(_spread([s.get(metric) for s in group]) for metric in REPLICATED)
        rows.append(f"| {arm} | {model} | {len(group)} | {cells} |")
    rows.append("\nRepeated runs: the median run, with the lowest and highest in brackets.")
    return rows


def markdown(summaries: list[dict[str, Any]], comparisons: list[str] | None = None) -> str:
    head = "| Arm | Model | Items | Answerable correct | False premise caught | False premise accepted | False alarms | Cited a source record | Grounded | Tool calls / item | Cost / item |"  # noqa: E501
    rows = [head, "|" + "---|" * 11]
    for s in summaries:
        ci = s.get("ci95") or {}
        rows.append(
            f"| {_arm(s)} | {s['model']} | {s['items']} | "
            f"{_pct_ci(s['accuracy_answerable'], ci.get('accuracy_answerable'))} | "
            f"{_pct_ci(s['false_premise_caught'], ci.get('false_premise_caught'))} | "
            f"{_pct(s['false_premise_accepted'])} | "
            f"{_pct_ci(s['false_alarms'], ci.get('false_alarms'))} | {_pct(s['cited_rate'])} | "
            f"{_pct(s['grounded_rate'])} | {s['mean_tool_calls']} | "
            f"{_usd(s['cost_per_item_usd'])} |"
        )
    rows.append("\nRates are followed by their 95% Wilson interval, in percent.")
    rows += replicate_rows(summaries)
    for line in comparisons or []:
        rows.append(f"\n{line}")
    for s in summaries:
        if s["fallbacks"]:
            rows.append(
                f"\n{_arm(s)} / {s['model']}: {s['fallbacks']} items were served by a fallback "
                f"model; answerable accuracy without them: "
                f"{_pct(s['accuracy_answerable_named_model_only'])}."
            )
    families = sorted({f for s in summaries for f in s["by_family"]})
    rows += [
        "",
        "| Family | " + " | ".join(f"{_arm(s)} / {s['model']}" for s in summaries) + " |",
        "|---|" + "---|" * len(summaries),
    ]
    for fam in families:
        rows.append(
            f"| {fam} | " + " | ".join(_pct(s["by_family"].get(fam)) for s in summaries) + " |"
        )
    return "\n".join(rows) + "\n"
