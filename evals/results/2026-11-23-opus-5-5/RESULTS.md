# Results: claude-opus-5-5, 23 Nov 2026

Preregistration: [`evals/PREREG.md`](../../PREREG.md), unchanged since before the pilot. Both arms: effort medium, max 12 turns, snapshot replay (0 snapshot misses), server-side refusal fallback on (0 fallbacks, 0 refusals).

| Arm | Answerable correct | False premise caught | False alarms | Grounded | Tool calls / item | Cost / item |
|---|---|---|---|---|---|---|
| tools | 55/55 (100%) | 13/13 (100%) | 0/55 | 68/68 (100%) | 1.03 | $0.0087 |
| closed_book | 43/55 (78%) | 13/13 (100%) | 1/55 | – | 0 | $0.0103 |

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

The gap bar missed. As preregistered, this means the set is too easy to answer from memory, so the result is not a claim of a large lift from tools.

## What the numbers say

- **With the tools, every item was right and every answer was grounded** in a record the tools returned during that episode. Each of the 13 planted premises was rejected for the right reason (for example, "1IEP … maps to mouse ABL1 (UniProtKB P00520), not human"). That ceiling means the set no longer separates one tool-using agent from another; the next version needs harder, less famous items.
- **From memory, Opus 5.5 knew more than expected.** It got every residue-at-position item right on these well-known proteins (it recalled TP53 residues 161 to 170 verbatim), along with every length, ligand ID, method and resolution, and every planted premise. Famous proteins are the wrong test set for a closed-book baseline.
- **The closed-book misses are values that can't be memorised reliably:** all six AlphaFold confidence fractions, two of three mean pLDDT values, three of four "best-resolution X-ray structure" items (the record has moved on since training), and one signal-peptide boundary (1-12 for 1-13).
- **Closed-book was calibrated, not careless.** Every miss was labelled in its explanation as an estimate from memory. Its one false alarm was a confident wrong "fact": it said AlphaFold DB has no model for the SARS-CoV-2 spike (P0DTC2), but one exists under a newer-style model ID.
- **Tools were also slightly cheaper** per item ($0.0087 against $0.0103): one cached lookup cost less than the extra thinking spent recalling.

## Files

- `tools-episodes.jsonl`, `closed-episodes.jsonl`: every episode with its submission, tool calls, grade, tokens and transcript.
- `tools-summary.json`, `closed-summary.json`, `report.md`: the summaries and the per-family table.
- `pilot-spend.json`: the pilot's spend ledger.
