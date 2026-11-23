# Changelog

## Unreleased

Eval v2 (built and preregistered, not yet run)
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
