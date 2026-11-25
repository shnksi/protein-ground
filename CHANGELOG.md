# Changelog

## 0.2.1

Fixes
- The MCP server now forwards every parameter description and numeric bound from `tools.py` into its advertised `inputSchema`, matching what the eval agent sees.
- `PROTEINGROUND_CACHE_DIR` expands `~` (`~/.cache/proteinground` now writes to the user's home directory instead of a literal `./~/` folder).
- `list_structures(method=...)` understands common method names (`cryo-EM`, `X-RAY DIFFRACTION`, `electron microscopy`) instead of returning `found: false`, and reports unknown method filters without claiming no structures exist.
- Isoform-numbered variants and features no longer collide with canonical position lookups in `get_variants` and `get_features`.
- `get_alphafold_summary` selects the covering fragment when a long protein has multiple fragments, reports available isoform models when AlphaFold DB has no canonical model (e.g. dystrophin `P11532`), and accepts `model_id` to inspect a specific isoform or fragment.
- `get_structure` includes `r_free` and `r_work` for refined X-ray structures, distinguishes metal ions (`ZN`, `MG`, `CA`, etc.) from crystallisation additives, and keeps all source organisms on chimeric polymers.
- `map_structure_residue` accepts lowercase insertion codes and an optional `uniprot_accession` to disambiguate fusion chains.
- `search_proteins` rejects empty queries as invalid input and suggests `reviewed_only=False` when a Swiss-Prot-only search returns no hits.
- `Fetcher` stops accumulating `urls_seen` unboundedly in long-lived MCP servers, uses thread-safe temp paths for atomic cache writes, and respects `Retry-After` on HTTP 429.
- `proteinground-eval report` preserves scientific notation for small exact p-values (`< 0.0001`) instead of rounding them to `0.0`.

Eval v2
- Results, Claude Opus 5.5, 23 to 24 Nov 2026 (`evals/v2/results/2026-11-24-opus-5-5/`): three runs of each arm under each prompt. With no warning in the prompt the tools arm answered 100.0% of the 140 answerable questions and caught 91.4% of the 35 planted premises, against 32.9% and 60.0% closed book (medians). Nine of ten preregistered bars passed; the closed-book arm's run-to-run spread (5.7 points against 5) missed.
- `evals/v2/`: 175 questions on 43 long-tail proteins drawn from UniProtKB searches by seed (reviewed entries with low annotation scores, unreviewed entries, no model organisms), with families for the 0.2.0 tools: structure-to-sequence numbering, insertion codes, modelled residues, differences between a structure and the canonical sequence, substitutions checked with `get_variants`, isoform numbering and obsolete PDB entries. A fifth are planted false premises; each asks for something that is not there and shares its wording with an answerable twin.
- `proteinground-eval run --prompt primed|unprimed`: `primed` is the prompt v1 ran with; `unprimed` gives no warning about false premises and no instruction to look values up. `--max-miss-episodes` stops a run that keeps reading records outside its snapshot.
- Two answer types with their own graders and decoys: `mutation` (K123A, Lys123Ala) and `position` (a residue position, read strictly).
- `proteinground-eval report` summarises repeated runs of one arm by their median and range, and summaries carry `premise_discrimination` (false premises caught minus false alarms).
- Fallback models have price rows, so tokens a fallback served count toward a run's spend cap.
- The v1 questions, snapshot, preregistration and results are untouched; the published episodes regrade to the same outcomes.

## 0.2.0

Fixes
- An HTTP 400 from UniProtKB, RCSB PDB or AlphaFold DB is a tool error, not `found: false`. One renamed upstream field used to make every lookup report "no such entry", with a citation, and cache that for a day. GraphQL errors are treated the same way. Neither is cached.
- A value the database omits is left out of the result with a note. AlphaFold confidence fields no longer default to `0.0`, and a record without a sequence is an error instead of a length of 0.
- The MCP server passes lookup failures to the client with their reason. The SDK was masking them as "Error executing tool".
- An unparseable search query is an error, not "no matches".
- `get_features` understands common names ("signal peptide", "disulfide bonds", `ACT_SITE`). It used to reject the name its own description advertised.
- An obsolete PDB entry names its replacement, and a deposited-but-unreleased entry is reported as on hold.
- `get_structure` reads all entities in one request (was one request per entity, capped at 12 of each kind) and returns each polymer's chain IDs, source organism and length.

New
- `map_structure_residue`: residue numbering between a PDB chain and UniProtKB, in either direction, with insertion codes, mismatches and unmodelled residues reported.
- `get_variants`: the wild-type residue and curated natural variants and mutagenesis records at a position.
- `get_sequence_window` accepts isoform IDs; `get_features` filters by residue position; `get_alphafold_summary` reports the confidence of a region.
- `proteinground-eval report` prints 95% Wilson intervals and an exact paired test between arms.

Eval
- Questions, gold answers and the preregistration are unchanged; the published results were measured on 0.1.0. The snapshot gained 36 records for the new request paths and tests.

## 0.1.0

First version: seven lookup tools, the 68-question eval and its preregistered run.
