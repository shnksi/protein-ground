# Snapshot

Gzipped JSON responses from the public APIs, recorded on 23 Nov 2026 by
`evals/build_questions.py`. Each file holds one URL, its HTTP status, retrieval time and body.
The eval replays these so every run sees the records the gold answers came from.

The 154 files recorded for v0.1.0 are unchanged. v0.2.0 added 36 on the same day: the
GraphQL entity record of each PDB entry the questions touch (the tools now read entities
in one request; the gold answers are still computed from the REST records), the archive
status of the two unreleased PDB IDs, and the records behind the residue-mapping, variant,
isoform and obsolete-entry tests (`EXTRA_CALLS` in `build_questions.py`).

Data licences: UniProtKB release 2026_04 (CC BY 4.0, The UniProt Consortium);
RCSB PDB entries (CC0 1.0); AlphaFold DB model v6 summaries and confidence files
(CC BY 4.0, Google DeepMind and EMBL-EBI).
