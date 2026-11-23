# Results: claude-opus-5-5, 23 Nov 2026

Tools as of v0.1.0 (commit `737b8f8`, seven lookup tools); check that commit out to rerun these arms as they were. Preregistration: [`evals/PREREG.md`](../../PREREG.md), unchanged since before the pilot. Both arms: effort medium, max 12 turns, snapshot replay (0 snapshot misses), server-side refusal fallback on (0 fallbacks, 0 refusals).

| Arm | Answerable correct | False premise caught | False alarms | Grounded | Tool calls / item | Cost / item |
|---|---|---|---|---|---|---|
| tools | 55/55 (100%) | 13/13 (100%) | 0/55 | 68/68 (100%) | 1.03 | $0.0087 |
| closed_book | 43/55 (78%) | 13/13 (100%) | 1/55 | – | 0 | $0.0103 |

95% Wilson intervals: answerable correct 94–100% (tools) and 66–87% (closed_book); false premise caught 77–100% in both arms. Compared item by item on the 55 answerable questions, 12 were right only in the tools arm and none only in the closed-book arm (exact paired test, p = 0.0005); the gap is 21.8 points with an approximate 95% interval of 10.9 to 32.7. `report.md` was regenerated with these figures; the episode records and summaries are as first written.

Total spend, estimated from token usage: $1.38 ($0.08 pilot, $0.59 tools, $0.70 closed_book).

## Against the preregistered bars

| Bar | Target | Result | |
|---|---|---|---|
| accuracy_answerable, tools | >= 90% | 100% | pass |
| false_premise_caught, tools | >= 85% | 100% | pass |
| false_alarms, tools | <= 5% | 0% | pass |
| grounded_rate, tools | >= 90% | 100% | pass |
| accuracy gap, tools minus closed_book | >= 30 points | 22 points | **miss** |
| scorer controls | all pass | 65 tests pass | pass |
| pilot (3 per arm) | >= 2/3 tools correct, no errors, projection under $15 | 3/3, 0 errors, $1.92 projected | pass |

The gap bar missed. As preregistered, this means the set is too easy to answer from memory, so the result is not a claim of a large lift from tools. The interval on the gap includes 30, so a larger set could land on either side of the bar; with one run of 55 items it is scored as a miss.

## What the numbers say

- **With the tools, every item was right and every answer was grounded** in a record the tools returned during that episode. Each of the 13 planted premises was rejected for the right reason (for example, "1IEP … maps to mouse ABL1 (UniProtKB P00520), not human"). That ceiling means the set no longer separates one tool-using agent from another; the next version needs harder, less famous items.
- **From memory, Opus 5.5 knew more than expected.** It got every residue-at-position item right on these well-known proteins (it recalled TP53 residues 161 to 170 verbatim), along with every length, ligand ID, method and resolution, and every planted premise. Famous proteins are the wrong test set for a closed-book baseline.
- **The closed-book misses are values that can't be memorised reliably:** all six AlphaFold confidence fractions, two of three mean pLDDT values, three of four "best-resolution X-ray structure" items (the record has moved on since training), and one signal-peptide boundary (1-12 for 1-13).
- **Closed-book was calibrated, not careless.** Every miss was labelled in its explanation as an estimate from memory. Its one false alarm was a confident wrong "fact": it said AlphaFold DB has no model for the SARS-CoV-2 spike (P0DTC2), but one exists under a newer-style model ID.
- **The planted explanations were audited by hand afterwards (v0.2.0).** All 26 (13 per arm) reject the premise for the stated reason; the grader only checks that it was rejected. One label in the set is imprecise: 9ZYZ and 9ZZX are described as "does not exist", but the archive lists both as deposited and unreleased. Both arms answered that no released entry exists, which is correct either way.
- **Tools were also slightly cheaper** per item ($0.0087 against $0.0103): one cached lookup cost less than the extra thinking spent recalling.

## Files

- `tools-episodes.jsonl`, `closed-episodes.jsonl`: every episode with its submission, tool calls, grade, tokens and transcript.
- `tools-summary.json`, `closed-summary.json`, `report.md`: the summaries and the per-family table.
- `pilot-spend.json`: the pilot's spend ledger.
