"""Summaries and Markdown tables from graded episode records."""

from __future__ import annotations

import json
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
    return {
        "arm": first.get("arm"),
        "model": first.get("model"),
        "items": len(records),
        "answerable": len(answerable),
        "planted": len(planted),
        "accuracy_answerable": _rate(
            sum(r["grade"]["outcome"] == "correct" for r in answerable), len(answerable)
        ),
        "false_premise_caught": _rate(
            sum(r["grade"]["outcome"] == "correct" for r in planted), len(planted)
        ),
        "false_premise_accepted": _rate(outcomes["accepted_false_premise"], len(planted)),
        "false_alarms": _rate(outcomes["false_alarm"], len(answerable)),
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


def _usd(value: Any) -> str:
    return "–" if value is None else f"${value:.4f}"


def markdown(summaries: list[dict[str, Any]]) -> str:
    head = "| Arm | Model | Items | Answerable correct | False premise caught | False premise accepted | False alarms | Cited a source record | Grounded | Tool calls / item | Cost / item |"  # noqa: E501
    rows = [head, "|" + "---|" * 11]
    for s in summaries:
        rows.append(
            f"| {s['arm']} | {s['model']} | {s['items']} | {_pct(s['accuracy_answerable'])} | "
            f"{_pct(s['false_premise_caught'])} | {_pct(s['false_premise_accepted'])} | "
            f"{_pct(s['false_alarms'])} | {_pct(s['cited_rate'])} | {_pct(s['grounded_rate'])} | "
            f"{s['mean_tool_calls']} | {_usd(s['cost_per_item_usd'])} |"
        )
    for s in summaries:
        if s["fallbacks"]:
            rows.append(
                f"\n{s['arm']} / {s['model']}: {s['fallbacks']} items were served by a fallback "
                f"model; answerable accuracy without them: "
                f"{_pct(s['accuracy_answerable_named_model_only'])}."
            )
    families = sorted({f for s in summaries for f in s["by_family"]})
    rows += [
        "",
        "| Family | " + " | ".join(f"{s['arm']} / {s['model']}" for s in summaries) + " |",
        "|---|" + "---|" * len(summaries),
    ]
    for fam in families:
        rows.append(
            f"| {fam} | " + " | ".join(_pct(s["by_family"].get(fam)) for s in summaries) + " |"
        )
    return "\n".join(rows) + "\n"
