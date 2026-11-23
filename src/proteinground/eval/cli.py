"""proteinground-eval: run arms, grade them, and report.

proteinground-eval check-gold
proteinground-eval run --arm tools --model claude-opus-5-5 --out runs/opus-tools
proteinground-eval run --arm tools --stub --out runs/dry-run      # zero cost
proteinground-eval report runs/opus-tools runs/opus-closed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

from proteinground.eval.agent import Arm, MessagesClient, run_episode
from proteinground.eval.cost import episode_cost_usd
from proteinground.eval.goldcheck import check
from proteinground.eval.grade import grade
from proteinground.eval.report import (
    comparison_line,
    load_records,
    markdown,
    paired,
    summarise,
)
from proteinground.eval.schema import load_questions
from proteinground.fetch import Fetcher, Mode

ROOT = Path.cwd()
DEFAULT_QUESTIONS = ROOT / "evals" / "questions.jsonl"
DEFAULT_SNAPSHOT = ROOT / "evals" / "snapshot"


def cmd_check_gold(args: argparse.Namespace) -> int:
    fetcher = Fetcher(cache_dir=args.snapshot, mode=Mode.OFFLINE)
    questions = load_questions(args.questions)
    failures = [(q.id, reason) for q in questions if (reason := check(fetcher, q))]
    for qid, reason in failures:
        print(f"GOLD_FAIL {qid}: {reason}")
    print(f"GOLD_CHECK: {len(questions) - len(failures)}/{len(questions)} reachable")
    return 1 if failures else 0


def cmd_run(args: argparse.Namespace) -> int:
    questions = load_questions(args.questions)
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q.id in wanted]
    if args.limit:
        questions = questions[: args.limit]
    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / "episodes.jsonl"
    done = {r["question_id"] for r in load_records(args.out)}

    client: MessagesClient
    if args.stub:
        from proteinground.eval.stub import StubMessages

        client = StubMessages(policy=args.stub_policy)
    else:
        from proteinground.eval.agent import AnthropicMessages

        client = AnthropicMessages(fallbacks=not args.no_fallbacks)
    mode = Mode.OFFLINE if args.strict_offline else Mode.REPLAY
    arm = cast(Arm, args.arm)
    previous = load_records(args.out)
    spent = sum(r.get("cost_usd") or 0.0 for r in previous)
    refusals = sum(r["status"] == "refused" for r in previous)

    for index, question in enumerate(questions, start=1):
        if question.id in done:
            continue
        if args.cap_usd is not None and spent >= args.cap_usd:
            print(f"STOP: spend cap ${args.cap_usd:.2f} reached (estimated ${spent:.4f})")
            break
        if refusals > args.max_refusals:
            print(f"STOP: {refusals} refusals exceeds --max-refusals {args.max_refusals}; review")
            break
        fetcher = Fetcher(cache_dir=args.snapshot, mode=mode)
        episode = run_episode(
            client, fetcher, question, arm, args.model,
            effort=args.effort, max_turns=args.max_turns,
        )  # fmt: skip
        result = grade(
            question,
            episode.submission,
            episode.status,
            episode.retrieved if arm == "tools" else None,
        )
        record: dict[str, Any] = episode.to_record()
        if args.stub:
            record["model"] = f"stub-{args.stub_policy} (priced as {args.model})"
        record["grade"] = result.model_dump()
        record["snapshot_misses"] = fetcher.misses
        record["estimated_cost_usd"] = episode_cost_usd(episode)
        record["cost_usd"] = None if args.stub else record["estimated_cost_usd"]
        spent += record["cost_usd"] or 0.0
        refusals += episode.status == "refused"
        with out_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        print(
            f"[{index}/{len(questions)}] {question.id}: {result.outcome}"
            f" ({len(episode.tool_calls)} tools, {episode.seconds:.1f}s)"
        )

    summary = summarise(load_records(args.out))
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.out / "report.md").write_text(markdown([summary]))
    print(json.dumps({k: v for k, v in summary.items() if k != "by_family"}, indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    runs = [records for d in args.runs if (records := load_records(Path(d)))]
    summaries = [summarise(records) for records in runs]
    comparisons = [
        comparison_line(summaries[0], summary, result)
        for records, summary in zip(runs[1:], summaries[1:], strict=True)
        if (result := paired(runs[0], records))
    ]
    text = markdown(summaries, comparisons)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="proteinground-eval")
    sub = parser.add_subparsers(dest="command", required=True)

    gold = sub.add_parser("check-gold", help="confirm every gold answer is reachable via tools")
    gold.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    gold.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    gold.set_defaults(func=cmd_check_gold)

    run = sub.add_parser("run", help="run one arm over the question set")
    run.add_argument("--arm", choices=["tools", "closed_book"], required=True)
    run.add_argument("--model", default="claude-opus-5-5")
    run.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh"])
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    run.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    run.add_argument("--limit", type=int)
    run.add_argument("--ids", help="comma-separated question IDs")
    run.add_argument("--max-turns", type=int, default=12)
    run.add_argument("--cap-usd", type=float, help="stop once estimated spend reaches this")
    run.add_argument("--stub", action="store_true", help="zero-cost stub model (dry run)")
    run.add_argument(
        "--stub-policy",
        choices=["lookup", "abstain"],
        default="lookup",
        help="lookup: answer empty with premise_ok=true; abstain: premise_ok=false",
    )
    run.add_argument(
        "--max-refusals",
        type=int,
        default=3,
        help="stop the run once refusals exceed this (preregistered: 3)",
    )
    run.add_argument(
        "--no-fallbacks",
        action="store_true",
        help="measure the named model only; refusals are not re-run elsewhere",
    )
    run.add_argument(
        "--strict-offline",
        action="store_true",
        help="fail tool calls that miss the snapshot instead of fetching live",
    )
    run.set_defaults(func=cmd_run)

    report = sub.add_parser("report", help="compare runs in one Markdown table")
    report.add_argument("runs", nargs="+")
    report.add_argument("--out", type=Path)
    report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
