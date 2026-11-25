# proteinground eval v2: long-tail proteins, with and without a warning

Frozen before any paid call. A bar, arm, decoy, stop rule or run count changed after the pilot starts makes a new eval with a new preregistration.

## Why a second eval

Eval v1 (68 questions on 14 famous proteins) could not show that the tools matter. Closed-book Claude Opus 5.5 answered 78% from memory and rejected 13 of 13 planted false premises, and the prompt told both arms that false premises exist and told the tools arm to look every value up. v2 changes the two things that made v1 easy: the proteins are ones a model is unlikely to have memorised, and each arm is also run with a prompt that gives no warning.

## Question set

- 175 questions: 140 answerable, 35 planted false premises (20.0%). One answerable item is 0.71 points.
- 43 proteins from 37 organisms, 32 reviewed and 11 unreviewed, drawn by seed 11 from seven UniProtKB searches (`STRATA` in `evals/v2/build_questions.py`; the queries, the accessions drawn and the accessions passed over with the reason are in `evals/v2/MANIFEST.json`). Every stratum leaves out twelve model organisms (human, mouse, rat, baker's and fission yeast, E. coli K-12, B. subtilis 168, Arabidopsis, fruit fly, C. elegans, zebrafish, cattle) and keeps sequences of 80 to 800 residues. No protein was picked or dropped by hand.
- Strata: reviewed with a PDB structure and annotation score 3 or lower (12); reviewed, annotation score 1, one AlphaFold model and no structure (7); unreviewed with a PDB structure (7); unreviewed with one AlphaFold model and no structure (4); reviewed with described isoforms (4); reviewed with mutagenesis records and a structure (5); reviewed peptidase S1 family with a structure (4), the family where structures carry insertion codes.
- How the draw works: a pool small enough to list is listed whole and shuffled. A large pool is drawn in two stages: a seeded random sequence length, then a seeded random entry among the pool's entries of that length. That samples lengths evenly, not entries evenly. The search pages the draw read are kept in `evals/v2/pools/`.
- Removed PDB entries (the obsolete-entry items) are drawn by the same seed from the archive's own list of removed entries, keeping those the archive marks obsolete.
- Families kept from v1: residue_at (20), length (8), feature_range (10), method_resolution (12), ligand_comp_id (6), polymer_uniprot (8), best_xray (6), af_fraction (10), af_mean (6), accession_lookup (5).
- Families for the v0.2.0 tools: structure_numbering (8; author number to UniProtKB position where the two differ), structure_residue (6; chains numbered as UniProtKB), modelled_residue (6; the residue with coordinates at an author number), insertion_code (6), engineered_mutation (6; the structure differs from the canonical sequence), variant_lookup (6; a substitution checked with `get_variants`), isoform_residue (5; a position where the isoform and the canonical sequence differ), obsolete_replacement (6).
- Gold answers are computed in `build_questions.py` from raw records (UniProtKB JSON, RCSB REST records for entries, polymer entities, chain instances and removed entries, the AlphaFold DB prediction record) by code that shares only URL builders with the tools. The tools read chains and entities through RCSB GraphQL. `proteinground-eval check-gold --questions evals/v2/questions.jsonl --snapshot evals/v2/snapshot` reports 175/175 reachable. The structure-numbering, insertion-code, modelled-residue and difference items were also checked against PDBe's SIFTS and residue-listing API, a separate route to the same mapping.

## Bars

Each bar is decided on the rates in the runs' `summary.json` (three decimals), not on rounded percentages. A bar on one arm is read on the median of its three runs. A bar on a difference between arms is read on the median of the three per-pair differences, run k of one arm against run k of the other.

- accuracy_answerable, tools arm, primed prompt: pass at >= 90% (126 of 140; higher is better). A miss means the tool surface fails agents on routine lookups of little-known records; fix the tools before publishing any result.
- accuracy_answerable, tools arm, unprimed prompt: pass at >= 85% (119 of 140; higher is better). A miss means that without a prompt telling it to look values up the model answers from memory or stops short; the tool descriptions are not doing the work and the README must say so.
- accuracy gap, tools minus closed_book, same prompt: pass at >= 50 points in both prompts (tools higher), with the exact paired test at p < 0.01 in each of the three run pairs. A miss means the draw is still answerable from memory, or the tools arm is weak; no claim that the tools matter.
- false_premise_caught, tools arm, primed prompt: pass at >= 85% (30 of 35; higher is better). A miss means found=false, the mapping fields and the notes do not steer a warned model to reject the premise.
- false_premise_caught, tools arm, unprimed prompt: pass at >= 70% (25 of 35; higher is better). A miss means the tool surface, with no warning in the prompt, does not make the model reject a false premise; the README must then say the tools catch false premises when the agent is told to check.
- false_alarms, tools arm: pass at <= 5% of answerable items in both prompts (at most 7 of 140; lower is better). A miss means the model rejects true premises; the true-premise twins (below) are where to look.
- premise discrimination (false_premise_caught minus false_alarms, `premise_discrimination` in summary.json), tools minus closed_book, same prompt: pass at >= 30 points in both prompts (tools higher). A miss means a model without tools tells planted premises from true ones nearly as well, so the planted items can be spotted from plausibility.
- grounded_rate, tools arm: pass at >= 90% in both prompts (higher is better). A miss means citations are decoration.
- Run-to-run spread: the range (highest minus lowest run) of accuracy_answerable is at most 5 points in every arm and prompt (lower is better). A miss means differences smaller than the range cannot be read from these runs; report medians and ranges only.
- Scorer controls, before any run: `uv run pytest` exits 0, including the pass and must-fail cases for every answer type and the regrade of the published v1 episodes. A failure blocks every run.

Reported without a bar: false_premise_caught for each planted kind (the family table lists them as `false_premise.<kind>`), and the closed_book arm's own rates.

## Arms

Two arms, each under two prompts, each run three times: 12 runs of 175 items.

- A1 tools, primed: claude-opus-5-5, effort medium, adaptive thinking (model default), nine lookup tools plus submit_answer, max 12 turns, max_tokens 16000, server-side refusal fallback on (items a fallback model served are reported separately), snapshot replay. `--prompt primed` is the prompt and answer form v1 ran with, byte for byte (a test pins their hashes). Expected about $0.012 per item: v1 measured $0.0087 with seven tools and 2.0 turns, and v2 adds two tool definitions and some second lookups. Without prompt caching the same item would cost $0.046 (`gstack-eval-plan arms`, 9,700 input and 350 output tokens).
- A2 tools, unprimed: the same, with `--prompt unprimed`. The system prompt names the databases, says tools are available, and asks for the answer format; it does not mention false premises and does not say to look values up. The answer form's flag is named `answerable` ("false if the question as asked has no correct answer") instead of `premise_ok`. The tool definitions are the same as under the primed prompt, because they are the product under test: every description ends by saying that found=false means the record or feature does not exist and to say so, and the descriptions of `get_variants` and `map_structure_residue` say what those tools are for. An MCP client shows an agent exactly that text. So "unprimed" means no warning from the prompt or the answer form; it does not mean the model reads nothing about checking. Expected about $0.012 per item.
- A3 closed_book, primed: claude-opus-5-5, same settings, submit_answer only. Expected about $0.011 per item (v1 measured $0.0103; nearly all of it is thinking output).
- A4 closed_book, unprimed: the same, with `--prompt unprimed`. Expected about $0.011 per item.
- Three runs per arm and prompt because one run cannot separate a real difference from sampling noise: this model takes no temperature or seed, and adaptive thinking varies from call to call. Three is the least that gives a median and a range; at these prices more would cost little, but the bars above are written for three.
- Not in this eval: other models. A cheaper model in the tools arm is a separate question with its own preregistration.

## Decoys

- Grader decoys (tests/test_grade.py, tests/test_eval_v2.py): for every answerable question, natural phrasings of the gold must pass and at least one near miss must fail. For the two new answer types: a substitution with the wrong wild-type residue, the wrong position, the wrong replacement, the two residues reversed, a hedge between two substitutions, or no replacement at all must fail (`mutation`); the author number handed back as the UniProtKB position, an off-by-one position, a range, and a hedge between the answer and the number the question gave must fail (`position`). A ligand answer that also names another item's component ID must fail. The v1 decoys still apply to the families v1 had. Passing them shows the scorer cannot be gamed by answer format; it says nothing about models.
- Stub decoy runs (zero cost), under both prompts: an always-"fine" stub (one lookup, an empty answer, flag true) must score 0% answerable and 0% caught; an always-"cannot be answered" stub must score 100% caught and 100% false alarms. Together they show "false premise caught" means nothing without "false alarms" beside it.
- 35 planted false premises, each checked against the snapshot when the set is built. Every one asks for something that is not there, so "this cannot be answered" is the literally correct reply and no value can be both right and an acceptance of the premise:
  - 23 subtle: a mutagenesis record named with the wrong wild-type residue (5); an author residue number stated to be the same UniProtKB position when it is not, where the two residues differ (3); the amino acid modelled at a residue that has no coordinates (6); a difference from the canonical sequence claimed where there is none (3); an isoform that does not exist, or a position past the end of a shorter isoform (4); an obsolete entry that nothing superseded (2).
  - 12 of the kinds v1 used: two PDB IDs the archive never issued, two accessions that do not exist, four positions past the end of the sequence, four absent features.
  - Left out on purpose: v1's wrong-method, wrong-organism and wrong-name kinds. The question they ask ("at what resolution…", "how long…") has a literal answer, so an unwarned model that answers and corrects the premise in passing cannot be told from one that accepted it.
- How a planted item is scored: caught when the flag says it cannot be answered. For the wrong-wild-type items only, giving exactly the true substitution (T10A where the question said Val10) is also a catch, because that answer is itself the correction; the substitution with the wrong residue, a hedge between the two, or anything else is an acceptance.
- Each planted item is written from the same template as an answerable family, so the wording does not give it away: variant_lookup, structure_residue, modelled_residue, engineered_mutation, isoform_residue, obsolete_replacement, method_resolution, residue_at and feature_range. The two nonexistent accessions are the exception: they cannot carry the "(name, organism)" their answerable twins do.
- True-premise twins: the 35 answerable items in the first six of those families state or assume, in the same words, something that is true ("is also position N", "is modelled at", "differs from", "annotates a mutagenesis record at Lys45"). An arm that rejects every question written that way scores false alarms on them.

## Stop rules

- Spend cap: $61 in all. `--cap-usd 5` on each of the 12 runs ($60), plus $1 for the pilot. The runner stops before the next item once a run's estimated spend reaches its cap. The cap is deliberately below what a tools run would cost without prompt caching ($8.00), so a run whose cache has silently stopped working is cut short instead of finishing at four times the price.
- Pilot: 3 items in each arm and prompt, 12 episodes, `--cap-usd 0.25` each: `numbering-6F55-A-40` (structure_numbering), `lookup-Q87043` (accession_lookup, the family where an agent's search is least predictable) and `trap-variant-Q9AFC7-V10` (planted, wrong wild-type residue). Stop and report, without asking for the full run, if any pilot episode errors or is refused; if the second and third items of an arm read nothing from the prompt cache (`cache_read_tokens` of 0); if the mean cost of the second and third items of any arm and prompt, times 175, is above $4 (80% of that run's cap); or if the tools arm under the primed prompt gets fewer than 2 of 3 right. Snapshot misses in the pilot are reported, not a stop.
- A scorer below its bar (`uv run pytest` failing) stops everything before a call.
- budget_exhausted from the spend ledger ends the run.
- More than 3 refusals in a run stops that run for review (`--max-refusals 3`). The draw includes venom, viral and bacterial proteins, which can trip the biology safety classifier even for database lookups.
- More than 17 episodes (10%) with a snapshot miss in one tools run stops that run (`--max-miss-episodes 17`): the agent is then reading live records the gold answers were not computed from. Below that, every wrong answer in an episode with a miss is listed in the results.
- Items served by a server-side fallback model are reported separately (`accuracy_answerable_named_model_only` in summary.json); the headline names the model that was asked. Fallback tokens are priced at the fallback model's rate (`cost.py` has rows for Claude Opus 5 and Opus 4.8); an episode served by a model with no price row is not counted toward the cap, so each run's records are checked for a null cost before the next run starts.
- The three runs of an arm are run to completion or not counted. A run stopped by a rule above is reported as stopped, and its arm is reported on the runs that finished, with the number stated.

## Runs and reporting

- Run directories: `runs/v2/<arm>-<prompt>-<k>` for k = 1, 2, 3, each from `proteinground-eval run --arm <arm> --prompt <prompt> --questions evals/v2/questions.jsonl --snapshot evals/v2/snapshot --cap-usd 5 --max-miss-episodes 17 --out <dir>`.
- Results are reported with what `proteinground-eval report` prints: each rate with its 95% Wilson interval, the exact paired test (McNemar's exact test on the answerable items both runs answered) with the gap and its approximate interval, the family table, and, for repeated runs, the median with the lowest and highest run to one decimal.
- For each k: `proteinground-eval report runs/v2/tools-unprimed-k runs/v2/closed_book-unprimed-k runs/v2/tools-primed-k` gives tools against closed_book and unprimed against primed for the tools arm; `proteinground-eval report runs/v2/tools-primed-k runs/v2/closed_book-primed-k` gives the primed pair. One call over all 12 directories gives the medians and ranges.
- The headline is the unprimed pair: answerable accuracy and false premises caught, tools against closed_book, median of three runs with the range.
- After the runs, every planted item's explanation in all four arms is read by hand and counted as rejected for the stated reason, rejected for another reason, or accepted. The grader's count stays the headline; the hand count is reported beside it.
- The tools are v0.2.0 (commit `981db33`); the eval harness changes for v2 are committed before the pilot and the results name that commit.

## Known limits

- Under the unprimed prompt the answer form still has a flag, and the tool descriptions still say what found=false means. The form's wording avoids "premise" and "does not exist", but a flag at all tells the model that some questions cannot be answered. Both unprimed arms get the same form, so the comparison between them is fair on that; the tools arm alone reads the tool descriptions, which is the difference being measured. The comparison with the primed prompt measures the prompt's warning and its lookup instruction together.
- A model can notice a false premise, say so in its explanation, and still set the flag to true with a value. The planted items are written so that no such value is right, but a model may give one anyway; the grader counts that as accepted and the hand count shows how often it happened.
- A closed-book model can set the flag to false because it does not know the answer. That raises its caught rate and its false alarms together, which is why the bar is on their difference.
- Answers are read strictly. A hedge fails, and so does a right answer padded with a second candidate: a position given beside the author number outside parentheses, or a one-letter residue beside another capital letter that reads as a residue. The same rule applies to every arm.
- The two-stage draw is even over sequence lengths, not over entries, and peptidase S1 is a stratum chosen for a property (insertion codes), not at random. Results describe this draw, not UniProtKB as a whole.
- "engineered_mutation" covers any difference between a deposited chain and the canonical sequence: engineered changes, cloning artefacts and sequence conflicts alike. The questions say "differs from".
- Gold answers and tool answers come from the same upstream databases by different routes. Agreement shows the tools parse correctly; it cannot show the databases are right.
- Under replay, a tool call the snapshot does not hold is fetched live and counted. Live records can differ from the snapshot once the databases update.

## Held-out exposure

| set | prior exposure (which runs, which models) | reservation (what this run may read) |
|---|---|---|
| none | No held-out set exists. The 175 questions were built on 23 Nov 2026 and no model has been run on them; they ship with the public repo once pushed. | The run reads the full set. Because it is public, later models may have seen it; rebuild with a new `--seed` for a fresh draw before reusing these numbers as evidence. |
