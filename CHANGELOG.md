# Changelog

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
