# Results: eval v2, claude-opus-5-5, 23 to 24 Nov 2026

Harness at commit `7c5d635`, tools v0.2.0 (commit `981db33`, nine lookup tools). Preregistration: [`evals/v2/PREREG.md`](../../PREREG.md), unchanged since that commit, which was made before the pilot.

175 questions on 43 long-tail proteins: 140 answerable and 35 planted false premises. Two arms (tools, closed_book) under two prompts, three runs each: 12 runs, 2,100 episodes. The primed prompt is the one v1 ran with: it warns that some questions hide a false premise and, in the tools arm, says to look every value up. The unprimed prompt gives neither. All runs: effort medium, max 12 turns, snapshot replay, server-side refusal fallback on. Every run finished, no stop rule fired and no episode errored.

## Headline: no warning in the prompt

The unprimed pair, median of three runs with the lowest and highest run in brackets.

| Arm | Answerable correct (140 items) | False premise caught (35 items) | False alarms | Grounded |
|---|---|---|---|---|
| tools | **100.0%** [100.0–100.0] | **91.4%** [91.4–91.4] | 0.0% [0.0–0.0] | 100.0% |
| closed_book | 32.9% [30.0–35.7] | 60.0% [51.4–65.7] | 7.9% [7.9–10.7] | – |

Compared item by item on the 140 answerable questions, 94, 98 and 90 were right only in the tools arm in runs 1, 2 and 3, and none only in the closed-book arm. The gaps are 67.1, 70.0 and 64.3 points (approximate 95% intervals 59.4 to 74.9, 62.4 to 77.6 and 56.3 to 72.2). The exact paired test gives p = 1.0e-28, 6.3e-30 and 1.6e-27; `reports/` prints these as "p = 0.0" because it rounds.

## All four arm and prompt pairs

Median of three runs, lowest and highest in brackets.

| Arm, prompt | Answerable correct | False premise caught | False alarms | Caught minus false alarms | Grounded | Tool calls / item | Cost / item |
|---|---|---|---|---|---|---|---|
| tools, unprimed | 100.0% [100.0–100.0] | 91.4% [91.4–91.4] | 0.0% [0.0–0.0] | 91.4% [91.4–91.4] | 100.0% | 1.11 | $0.0106 |
| closed_book, unprimed | 32.9% [30.0–35.7] | 60.0% [51.4–65.7] | 7.9% [7.9–10.7] | 52.1% [43.5–55.0] | – | 0 | $0.0144 |
| tools, primed | 100.0% [100.0–100.0] | 100.0% [100.0–100.0] | 0.0% [0.0–0.0] | 100.0% [100.0–100.0] | 100.0% | 1.09 | $0.0104 |
| closed_book, primed | 32.9% [30.0–33.6] | 48.6% [45.7–54.3] | 2.1% [1.4–2.1] | 46.5% [44.3–52.2] | – | 0 | $0.0132 |

Each run, as counts:

| Run | Answerable correct | False premise caught | False alarms |
|---|---|---|---|
| tools, primed, runs 1 to 3 | 140, 140, 140 of 140 | 35, 35, 35 of 35 | 0, 0, 0 of 140 |
| tools, unprimed, runs 1 to 3 | 140, 140, 140 of 140 | 32, 32, 32 of 35 | 0, 0, 0 of 140 |
| closed_book, primed, runs 1 to 3 | 42, 46, 47 of 140 | 19, 16, 17 of 35 | 3, 2, 3 of 140 |
| closed_book, unprimed, runs 1 to 3 | 46, 42, 50 of 140 | 23, 21, 18 of 35 | 15, 11, 11 of 140 |

95% Wilson intervals for one run: tools answerable 97 to 100; tools caught 90 to 100 primed and 78 to 97 unprimed; closed_book answerable between 23 to 38 and 28 to 44 depending on the run. `reports/` has every run's intervals.

## Against the preregistered bars

Bars are decided on the `summary.json` rates. A bar on one arm is read on the median of its three runs, and a bar on a difference on the median of the three per-pair differences (run k against run k).

| Bar | Target | Result | |
|---|---|---|---|
| accuracy_answerable, tools, primed | >= 90% | 1.000, 1.000, 1.000 | pass |
| accuracy_answerable, tools, unprimed | >= 85% | 1.000, 1.000, 1.000 | pass |
| accuracy gap, tools minus closed_book, each prompt | >= 50 points, p < 0.01 in each pair | primed +70.0, +67.1, +66.4 (median 67.1); unprimed +67.1, +70.0, +64.3 (median 67.1); largest p = 1.6e-27 | pass |
| false_premise_caught, tools, primed | >= 85% | 35 of 35 in each run | pass |
| false_premise_caught, tools, unprimed | >= 70% | 32 of 35 in each run (0.914) | pass |
| false_alarms, tools | <= 5% | 0 of 140 in all six runs | pass |
| premise discrimination gap, tools minus closed_book | >= 30 points | primed +47.8, +55.7, +53.5 (median 53.5); unprimed +36.4, +39.3, +47.9 (median 39.3) | pass |
| grounded_rate, tools | >= 90% | 1.000 in all six runs | pass |
| run-to-run range of accuracy_answerable, every arm and prompt | <= 5 points | tools 0.0 and 0.0; closed_book primed 3.6; closed_book unprimed 5.7 (42, 46 and 50 of 140) | **miss** |
| scorer controls | `uv run pytest` passes before any run | 178 tests pass | pass |
| pilot (3 items in each arm and prompt) | no errors or refusals, cache reads, tools primed >= 2 of 3, projection under $4 a run | 0 errors, 0 refusals, 3 of 3, largest projection $2.58 | pass |

The spread bar missed: the closed-book arm under the unprimed prompt ranged over 5.7 points. As preregistered, differences smaller than that range cannot be read from these runs. That rules out reading closed_book primed against closed_book unprimed on answerable accuracy (both medians are 32.9%). It does not touch the headline: the smallest gap between the arms is 64.3 points.

## What the numbers say

- **Memory fails on these proteins and the tools do not.** Closed-book Opus 5.5 answered about a third of the answerable questions; with the tools it answered all 140 in all six runs, each grounded in a record fetched during that episode, with about 1.1 lookups per question. On v1's famous proteins the same model scored 78% from memory.
- **Without the warning, the tools arm still caught 32 of 35 planted premises**, in every run, with no false alarms. Removing the warning and the lookup instruction cost nothing on answerable items.
- **The three misses are the same three items every time**: an author residue number said to be the same UniProtKB position (`trap-samenumber-1A5I-A-34`, `-1PFX-C-103`, `-5SGA-E-156`). The model looked the mapping up, gave the residue at the author number, left the flag at "answerable", and wrote the correction in its explanation ("it corresponds to UniProtKB P98119 position 244, not 34"). The grader reads the flag, so these count as accepted, as preregistered. Under the primed prompt the same model set the flag on all three. These items have a literal answer under one reading, so what they measure is whether the model sets the flag, not whether it notices.
- **The tools arm is at the ceiling.** 140 of 140 in six runs means this set cannot rank one tool surface against a better one.
- **What closed book can and cannot recall.** It got every ligand component ID (6 of 6 in all six runs) and most best-resolution structures and variant lookups. It got no AlphaFold confidence fraction (0 of 10) and no obsolete entry's replacement (0 of 6) in any run, and a fifth to a quarter of lengths, structure numberings and feature ranges.
- **Closed book catches the easy planted kinds and few of the subtle ones.** A position past the end and an absent feature were caught in every run. A wrong wild-type residue was caught in 0 to 2 of 5, an author number given as the UniProtKB position in 0 or 1 of 3, and under the primed prompt a claimed difference that is not there in 0 of 3.
- **Closed book's higher caught rate without the warning is mostly "I don't know".** It caught 60.0% unprimed against 48.6% primed, and raised false alarms from 2.1% to 7.9%: it sets the flag when it cannot recall. The hand count below shows the same thing, which is why the bar is on caught minus false alarms.

## Hand count of the planted explanations

Every planted item's explanation was read by hand in all four arm and prompt pairs: 35 items by 3 runs, 105 per pair. "Stated reason" means the explanation gives the actual defect, even tentatively. "Another reason" means the flag was set because the model could not recall, or doubted something else. The grader's count stays the headline.

| Arm, prompt | Grader: caught | Rejected for the stated reason | Rejected for another reason | Accepted | Refused |
|---|---|---|---|---|---|
| tools, primed | 105 | 105 | 0 | 0 | 0 |
| tools, unprimed | 96 | 96 | 0 | 9 | 0 |
| closed_book, primed | 52 | 46 | 6 | 53 | 0 |
| closed_book, unprimed | 62 | 43 | 19 | 42 | 1 |

- All nine tools-arm acceptances are the three author-number items above. Each explanation names the defect.
- Under the unprimed prompt, 5 of the tools arm's 15 wrong-wild-type catches gave the true substitution (T10A where the question said Val10) with the flag left at "answerable". That is a catch by the preregistered rule for this kind, because the answer is itself the correction. The other 10 set the flag.

The labels were assigned by one reader and are not in a file; the explanations are in each run's `episodes.jsonl` under `submission.explanation`.

## Run health

- **Refusals:** 3 episodes, all closed book, all on the vesicular stomatitis virus matrix protein P08325: `variant-P08325-M48R` in primed runs 1 and 2, and `trap-variant-P08325-F51` in unprimed run 1. At most 1 in a run; the stop rule is more than 3.
- **Fallback model:** the server-side fallback (`claude-opus-5`) ran on 7 closed-book episodes, all on those two items. Three are the refusals above. The other four were answered by the fallback: `trap-variant-P08325-F51` in all three primed runs (caught each time) and `variant-P08325-M48R` in unprimed run 3 (correct). Answerable accuracy on the named model only: primed 0.302, 0.331, 0.336; unprimed 0.329, 0.300, 0.353. No tools-arm episode was refused or used the fallback.
- **Snapshot misses:** 3 to 5 episodes in each tools run read a record outside the snapshot (the stop rule is more than 17): the accession lookups `lookup-Q5SJG7`, `lookup-Q9AFC7` and `lookup-Q87043` in every run, `lookup-Q7CPI7` once, and `trap-absent-80CC` in four runs, where the model also checked the look-alike ID 8OCC. Every one of those episodes was graded correct, so there is no wrong answer with a miss to list.
- **Prompt cache:** every item after the first in every run read from the cache. No episode has a null cost.

## Spend

Estimated from token usage at $4 in, $20 out, $0.20 cache read and $5 cache write per million tokens.

| | Spend |
|---|---|
| Pilot, 12 episodes | $0.20 |
| tools, 6 runs | $11.00 ($1.80 to $1.86 a run) |
| closed_book, 6 runs | $14.58 ($2.30 to $2.59 a run) |
| Total | $25.77 of the $61 cap |

Closed book cost more per item than the tools arm ($0.0132 to $0.0148 against $0.0103 to $0.0106) and took longer (about 8 s against 5 s): the model spent more thinking on recall than one cached lookup costs.

## Files

- `<arm>-<prompt>-<k>/`: one directory per run, as the runner wrote it. `episodes.jsonl` has every episode with its submission, tool calls, grade, tokens and transcript; `summary.json` has the rates the bars are decided on; `report.md` is that run's own table.
- `reports/unprimed-pair-{1,2,3}.md`: tools unprimed, closed_book unprimed and tools primed for run k. `reports/primed-pair-{1,2,3}.md`: tools primed against closed_book primed. `reports/all-12.md`: all 12 runs with medians, ranges and the family table.
- `pilot-spend.json`: the pilot's spend ledger.

The reports regenerate from these directories, for example:

```bash
R=evals/v2/results/2026-11-24-opus-5-5
uv run proteinground-eval report $R/tools-unprimed-1 $R/closed_book-unprimed-1 $R/tools-primed-1
```
