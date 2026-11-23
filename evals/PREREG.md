# proteinground: tools vs closed-book on cited protein facts

Frozen before any paid call. A bar, arm, decoy or stop rule changed after the pilot starts makes a new eval with a new preregistration.

## Bars
- accuracy_answerable, tools arm: pass at >= 90% of the 55 answerable items (higher is better). A miss means the tool surface fails agents on routine lookups; fix the tools before publishing any result.
- false_premise_caught, tools arm: pass at >= 85% (11 of 13 planted items; higher is better). A miss means found=false and the notes do not steer the model to say "this does not exist"; revisit the notes and the prompt.
- false_alarms, tools arm: pass at <= 5% of answerable items (at most 2 of 55; lower is better). A miss means the abstention instruction over-triggers.
- grounded_rate, tools arm: pass at >= 90% of submissions naming a record the tools actually returned during that episode (higher is better). A miss means citations are decoration.
- accuracy gap, tools minus closed_book: expect >= 30 points (tools higher). A smaller gap means the set is too easy to answer from memory, and the README must say so instead of claiming a lift.
- Scorer controls, before any run: the positive controls and decoys in tests/test_grade.py all behave as written (exit 0). A failure blocks every run.

## Arms
- A1 tools: claude-opus-5-5, effort medium, adaptive thinking (model default), 7 lookup tools plus submit_answer, max 12 turns, max_tokens 16000, server-side refusal fallback on (items a fallback model served are reported separately), snapshot replay. Per item about $0.088 at 14,000 input and 1,600 output tokens (`gstack-eval-plan arms`).
- A2 closed_book: claude-opus-5-5, same settings, submit_answer only. Per item about $0.018 at roughly 400 input and 800 output tokens (own estimate; the gstack line prices per model at the tools-arm token estimate, which overstates this arm).
- Not in this run: a claude-haiku-5-5 tools arm. It has no row in gstack's lib/pricing.ts, so its admission cannot be priced; add the row first.

## Decoys
- Grader decoys on the real items (tests/test_grade.py): for every answerable question, natural phrasings of the gold must pass and hedged versions must fail ("X or Y" for residues, ranges, PDB IDs and accessions; "X-ray or cryo-EM"; another ligand in the same entry). Plus fixed cases: an off-by-one range (713-979 for 712-979), 1.8 Å for 1.74 Å, the pronoun "I" read as isoleucine, the "90" in "pLDDT above 90" read as the answer, a year read as a PDB ID. Passing them shows the scorer cannot be gamed by answer format; it says nothing about models.
- Stub decoy runs (zero cost): an always-"fine" stub (looks up one record, submits an empty answer with premise_ok=true) must score 0% answerable and 0% caught; an always-"doesn't exist" stub must score 100% caught and 100% false alarms. Together they show "false premise caught" means nothing without "false alarms" beside it.
- 13 planted false-premise items (19% of 68), each checked against the snapshot when the set is built: 2 unassigned PDB IDs, a wrong subunit (P69905 called beta), a position past the end of insulin, an absent kinase domain, a nonexistent accession, 2 wrong methods (4HHB, 6VXX), 2 wrong species (1IEP is mouse Abl, GFP called human), and 3 absent features (signal peptide, active site, transmembrane helix). An arm that answers everything without checking scores 0% on them.

## Stop rules
- Spend cap: $15 across both arms (`--cap-usd 12` for tools, `--cap-usd 3` for closed_book). The runner stops before the next item once estimated spend reaches its cap.
- Pilot (3 items per arm: one residue_at, one method_resolution, one false_premise): stop and report, without asking for the full run, if any pilot item errors, if the pilot's per-item cost projects the full run above $15, or if the tools arm gets fewer than 2 of 3 right.
- A scorer below its bar (tests/test_grade.py failing) stops everything before a call.
- budget_exhausted from the spend ledger ends the run.
- More than 3 refusals in the tools arm stops the run for review (protein questions can trip bio safety classifiers); `--max-refusals 3` enforces it.
- Items served by a server-side fallback model are reported separately (`accuracy_answerable_named_model_only` in summary.json); the headline names the model that was asked.

## Held-out exposure
| set | prior exposure (which runs, which models) | reservation (what this run may read) |
|---|---|---|
| none | No held-out set exists. All 68 questions are in evals/questions.jsonl and ship with the public repo. | The run reads the full public set. Because it is public, later models may have seen it; rebuild with a new `--seed` for fresh residue positions before reusing these numbers as evidence. |
