# proteinground

Cited protein facts for AI agents. An MCP server over UniProtKB, RCSB PDB and AlphaFold DB that returns every value with the record it came from, and says "not found" when something doesn't exist, so the model doesn't guess. It comes with a preregistered eval that plants false premises, to measure whether an agent checks before it answers.

```
> In UniProtKB entry P01308 (human insulin), which amino acid is at position 450?

get_sequence_window(accession="P01308", start=450, end=450)
→ found: false
  note: "position 450 is beyond the end of P01308, which has 110 residues"
  sources: [UniProtKB P01308, release 2026_04, https://www.uniprot.org/uniprotkb/P01308/entry]

> The sickle-cell mutation is Glu6Val in haemoglobin beta. Which UniProtKB position is that?

map_structure_residue(pdb_id="4HHB", chain="B", residue_number=6)
→ found: true
  author_residue: "6"   structure_residue: "E"   observed: true
  uniprot_accession: "P68871"   uniprot_position: 7   uniprot_residue: "E"   matches_uniprot: true
  sources: [RCSB PDB 4HHB, UniProtKB P68871]
```

## Why

Language models answer protein questions fluently, and often wrongly: a residue number off by one, a structure's method misremembered, a mouse structure cited as human. A scientist acting on that pays more for a confident wrong answer than for "I don't know". These tools make the checked answer the easy one, and the eval measures whether the agent takes it.

## What to use it for

- **Check a mutation before you write it down.** `get_variants("P01116", 12)` returns the wild-type residue (Gly) and the curated changes at that position (G12C, G12D, G12V), so "KRAS G12C" is confirmed against the sequence, not recalled.
- **Translate residue numbers between a structure and the sequence.** Papers, viewers and PDB files use the authors' numbering, which often differs from UniProtKB: haemoglobin beta's Glu6 is position 7, thrombin's catalytic Ser195 is position 568. `map_structure_residue` converts in either direction, handles insertion codes (`60A`), and reports when the structure carries a different residue (6OIM has Cys at KRAS position 12) or when the residue was never modelled.
- **Verify a structure citation.** `get_structure` gives the method, resolution, the source organism and chain IDs of each polymer, and the real ligand apart from the additives. That is how "human ABL1 bound to imatinib (1IEP)" turns out to be mouse Abl.
- **Decide whether an AlphaFold model can be trusted where you need it.** `get_alphafold_summary("P04637", start=100, end=290)` gives the confidence of that region (mean pLDDT 95.6) next to the whole model (75.1) and its disordered stretches.
- **Pick a structure.** `list_structures` ranks the cross-referenced entries by resolution and shows which residues each one covers.

## The tools

| Tool | Source | Returns |
|---|---|---|
| `search_proteins` | UniProtKB | accessions for a gene, name or keyword |
| `get_protein` | UniProtKB | name, gene, organism, canonical length, function, location |
| `get_sequence_window` | UniProtKB | up to 50 residues, one numbered entry per position; accepts an isoform ID such as `P04637-2` |
| `get_features` | UniProtKB | domains, signal peptides, active and binding sites, disulfides, with positions; filter by type or by residue position |
| `get_variants` | UniProtKB | the wild-type residue and the curated natural variants and mutagenesis records at a position or short range |
| `list_structures` | UniProtKB → PDB | cross-referenced structures, best resolution first |
| `get_structure` | RCSB PDB | method, resolution, R-free/R-work, dates, each polymer's chain IDs, organism and UniProtKB accession, bound ligands |
| `map_structure_residue` | RCSB PDB + UniProtKB | a residue's number in a chain ↔ its UniProtKB position, the residue in both, whether they agree, whether it was modelled |
| `get_alphafold_summary` | AlphaFold DB | mean pLDDT, the share of residues in each confidence band, long low-confidence regions, and the confidence of a region (or specific isoform/fragment model) |

Design choices, each aimed at a known way agents go wrong:

- **Every result is `Cited[T]`**: `found`, `data`, `note`, and `sources` (database, record ID, a URL a person can open, retrieval time, release). The citation travels with the value, so the agent never has to reconstruct where a number came from.
- **"Doesn't exist" is a first-class answer.** A missing record, a position past the end of a sequence or an absent feature comes back as `found: false` with a reason, plus the feature types that *are* annotated. The usual failure is a tool that returns an empty list and leaves the model to fill the silence. The reverse matters too: asking for a feature type the tool doesn't retrieve says so, rather than claiming the entry has none, and common names ("signal peptide", "disulfide bonds", `ACT_SITE`) resolve to UniProt's own.
- **A failed lookup is an error, never "not found".** Only a real 404 means a record is missing. A request the database rejects (HTTP 400, or a GraphQL error after an upstream schema change) comes back as a tool error that says it is not evidence of absence, and is not cached. Before this rule, one renamed UniProt field would have made every lookup answer "no such entry", with a citation.
- **A missing value is null, never zero.** If AlphaFold DB omits a confidence field the result leaves it out and says which, and a record without a sequence is an error. Nothing defaults to `0.0` or a length of 0.
- **"Missing" says why.** An obsolete PDB entry names its replacement (1HHB → 4HHB), a deposited-but-unreleased entry is reported as on hold, and an isoform ID or entry name gets the call that will work.
- **Numbering is translated, not assumed.** Structure and sequence numbering are mapped through the deposited alignment, and a residue that differs between the two is flagged.
- **Residues are numbered for the model.** Sequence windows return `{position, one_letter, three_letter}` per residue, because models miscount offsets into long strings.
- **Ligands carry context.** Crystallisation additives and ions (glycerol, sulfate, chloride) are flagged, so the agent doesn't report glycerol as the bound drug.
- **Read-only and replayable.** Tools are annotated read-only and idempotent. Every response can be written to a cache and replayed offline, which is how the eval stays reproducible.

The tool surface is defined once (`src/proteinground/tools.py`) and shared by the MCP server and the eval agent, so what gets measured is what ships. Lookup failures reach an MCP client with their explanation instead of a bare "error executing tool".

## Install

```bash
git clone https://github.com/shnksi/protein-ground && cd protein-ground
uv sync
uv run proteinground-mcp        # MCP over stdio
```

Add it to Claude Code:

```bash
claude mcp add proteinground -- uvx --from git+https://github.com/shnksi/protein-ground proteinground-mcp
```

Or to an MCP client config:

```json
{
  "mcpServers": {
    "proteinground": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/shnksi/protein-ground", "proteinground-mcp"],
      "env": { "PROTEINGROUND_CACHE_DIR": "~/.cache/proteinground" }
    }
  }
}
```

`PROTEINGROUND_CACHE_DIR` keeps a replayable copy of every response. `PROTEINGROUND_MODE` is `cache-first` (default), `live`, `replay` or `offline`.

## The eval

68 questions over 14 well-studied proteins, in 11 families: the residue at a position, sequence length, feature spans, experimental method and resolution, ligand component IDs, which UniProtKB entry a PDB chain maps to, best-resolution X-ray structure, AlphaFold confidence, and accession lookup.

**13 of them (19%) are planted false premises**, each checked against the data when the set is built:

- PDB IDs with no released entry (`9ZYZ`, `9ZZX`). The set calls these "does not exist"; they are in fact deposited and on hold, which the tools now report. The right answer is unchanged: there is no resolution to give.
- "UniProtKB entry P69905 is human hemoglobin subunit beta…" (it is alpha)
- "PDB entry 1IEP shows human ABL1 bound to imatinib…" (the chain is mouse Abl, P00520)
- "PDB entry 4HHB is a cryo-EM structure…" (X-ray, 1984)
- a position past the end of insulin, insulin's "kinase domain", Cas9's "signal peptide", myoglobin's "active site"

The right answer to a planted item is to say what is wrong. An agent that answers everything confidently scores 0% on them.

How it is kept honest:

- **Gold answers come from raw records, by separate code.** `evals/build_questions.py` computes each answer straight from the API JSON and shares only URL builders with the tools. `proteinground-eval check-gold` then confirms every answer is reachable through the tools, so a tool bug fails the check instead of grading itself correct. Currently 68/68.
- **A frozen snapshot.** The responses behind every gold answer (UniProtKB 2026_04, AlphaFold DB v6, RCSB PDB as of 23 Nov 2026) are in `evals/snapshot/`, 1 MB gzipped. Runs replay it, so the agent sees the records the answers came from. A call the snapshot doesn't hold (say, a search phrased differently) is fetched live and counted as a snapshot miss; `--strict-offline` makes the run fully hermetic instead.
- **No model grades a model.** Graders are parsers plus rules (residue codes, ranges, numeric tolerance, method plus resolution, ID sets). Each parser pulls out every candidate value, so a hedge like "P00520 or P00519" fails. `tests/test_grade.py` builds natural phrasings of every real gold answer (which must pass) and hedged or near-miss versions (which must fail): off-by-one ranges, 1.8 Å for 1.74 Å, "X-ray or cryo-EM", the pronoun "I" read as isoleucine, and the "90" in "pLDDT above 90" read as the answer.
- **Grounded, not just cited.** An answer counts as grounded only if the record it cites was actually returned by a tool during that episode. A `submit_answer` sent in the same turn as lookups is sent back, since it was written before their results arrived.
- **Two decoys bracket the false-premise score.** "Caught" only checks that the agent said the premise is false, so it is always read next to false alarms. A stub that always says "fine" scores 0% caught; a stub that always says "doesn't exist" scores 100% caught and 100% false alarms.
- **Preregistered.** Bars, arms, decoys and stop rules are frozen in [`evals/PREREG.md`](evals/PREREG.md) before any paid call.

Metrics per arm: accuracy on answerable items, false premises caught and accepted, false alarms (saying "doesn't exist" when it does), cited and grounded rates, tool calls and cost per item.

### Results

Claude Opus 5.5, 23 Nov 2026, all 68 items per arm, one run each. Measured on v0.1.0 (commit `737b8f8`) with its seven tools; the tools added in v0.2.0 were first run in eval v2, below. Full write-up and records: [`evals/results/2026-11-23-opus-5-5/`](evals/results/2026-11-23-opus-5-5/RESULTS.md).

| Arm | Answerable correct (95% interval) | False premise caught (95% interval) | False alarms | Grounded | Cost / item |
|---|---|---|---|---|---|
| tools | **100%** (55/55; 94–100) | **100%** (13/13; 77–100) | 0% | 100% | $0.0087 |
| closed_book | 78% (43/55; 66–87) | 100% (13/13; 77–100) | 2% (1/55) | – | $0.0103 |
| stub, always "fine" (decoy) | 0% | 0% | 0% | – | $0 |
| stub, always "doesn't exist" (decoy) | 0% | 100% | 100% | – | $0 |

The arms answer the same questions, so they are compared item by item: 12 items only the tools arm got right, none the other way (exact paired test, p = 0.0005). The gap is 22 points, with an approximate 95% interval of 11 to 33.

The whole run cost $1.38. With the tools, every answer was right and grounded in a record fetched during that episode, with about one lookup per question. The closed-book misses are values that can't be memorised: all six AlphaFold confidence fractions, most best-resolution structures (the record has moved on since training), and a signal-peptide boundary off by one.

Five of the six preregistered bars passed. The one that missed: the tools-minus-memory gap was 22 points against a preregistered 30 (the interval reaches 30, so the set cannot rule the bar in or out; it was scored as a miss, as preregistered). Opus 5.5 recalled residues, lengths, ligand IDs and every planted premise for these famous proteins from memory. So this set shows the tools are reliable and grounded; it does not show a large lift over a strong model's memory. That needs a harder set of less-studied proteins, which is eval v2.

### Eval v2: long-tail proteins, with and without the warning

v1 left two questions open: do the tools help where memory fails, and does an agent check when nothing tells it to? v2 asks both.

- **175 questions on 43 little-studied proteins**, drawn by seed from UniProtKB searches that leave out twelve model organisms (reviewed entries with low annotation scores, and unreviewed entries). No protein was picked by hand.
- **Families for the v0.2.0 tools**, next to v1's: structure-to-sequence numbering, insertion codes, modelled residues, differences from the canonical sequence, substitutions, isoform numbering and obsolete PDB entries.
- **35 planted false premises (20%)**, 23 of them subtle: a mutagenesis record named with the wrong wild-type residue, an author residue number passed off as the UniProtKB position, a residue with no coordinates, an isoform that does not exist. Each shares its wording with an answerable twin.
- **Two prompts.** `primed` is the prompt v1 ran with. `unprimed` gives no warning about false premises and no instruction to look values up.
- **Three runs** of each arm under each prompt, because one run cannot separate a real difference from sampling noise.

Bars, arms and stop rules were frozen in [`evals/v2/PREREG.md`](evals/v2/PREREG.md) before the pilot.

Claude Opus 5.5, 23 to 24 Nov 2026, tools v0.2.0, harness at commit `7c5d635`. Median of three runs, with the lowest and highest run in brackets. Full write-up and records: [`evals/v2/results/2026-11-24-opus-5-5/`](evals/v2/results/2026-11-24-opus-5-5/RESULTS.md).

| Arm, prompt | Answerable correct (140) | False premise caught (35) | False alarms | Grounded | Cost / item |
|---|---|---|---|---|---|
| tools, unprimed | **100.0%** [100.0–100.0] | **91.4%** [91.4–91.4] | 0.0% | 100% | $0.0106 |
| closed_book, unprimed | 32.9% [30.0–35.7] | 60.0% [51.4–65.7] | 7.9% [7.9–10.7] | – | $0.0144 |
| tools, primed | 100.0% [100.0–100.0] | 100.0% [100.0–100.0] | 0.0% | 100% | $0.0104 |
| closed_book, primed | 32.9% [30.0–33.6] | 48.6% [45.7–54.3] | 2.1% [1.4–2.1] | – | $0.0132 |

The headline is the unprimed pair. From memory, Opus 5.5 answered a third of these questions; with the tools it answered all 140 in all six runs, with about 1.1 lookups per question. In each of the three paired runs, 90 to 98 answerable items were right only with the tools and none only without (exact paired test, p below 1e-26 in every pair); the gap is 64 to 70 points. The twelve runs cost $25.77 with the pilot.

With no warning in the prompt, the tools arm still caught 32 of the 35 planted premises in every run, with no false alarms. The three it missed are the same every time: an author residue number said to be the same UniProtKB position. The model looked the mapping up, gave the residue at the author number, and wrote the correction in its explanation without setting the flag. The grader reads the flag, so these count as accepted. With the warning it set the flag on all three.

Closed book caught more planted premises without the warning (60.0% against 48.6%) and raised more false alarms (7.9% against 2.1%): it uses the flag to say it does not know. Read by hand, 19 of its 62 unprimed catches set the flag only because it could not recall the record, against none of the tools arm's.

Nine of the ten preregistered bars passed. The one that missed is run-to-run spread: closed book under the unprimed prompt ranged over 5.7 points of answerable accuracy (42, 46 and 50 of 140) against a bar of 5. As preregistered, differences smaller than that cannot be read from these runs. The gaps between the arms are more than ten times larger.

### Run it

```bash
uv sync --extra eval
uv run proteinground-eval check-gold
uv run proteinground-eval run --arm tools --stub --out runs/dry-run      # free

export ANTHROPIC_API_KEY=...
uv run proteinground-eval run --arm tools --model claude-opus-5-5 --cap-usd 12 --out runs/opus-tools
uv run proteinground-eval run --arm closed_book --model claude-opus-5-5 --cap-usd 3 --out runs/opus-closed
uv run proteinground-eval report runs/opus-tools runs/opus-closed

# eval v2: name its questions and snapshot, and pick a prompt
uv run proteinground-eval run --arm tools --prompt unprimed --questions evals/v2/questions.jsonl --snapshot evals/v2/snapshot --cap-usd 5 --max-miss-episodes 17 --out runs/v2/tools-unprimed-1
```

Runs resume where they stopped. `--ids` runs chosen items, `--no-fallbacks` measures the named model only, and `--strict-offline` fails any tool call that misses the snapshot. Rebuild the set with fresh residue positions with `uv run python evals/build_questions.py --seed 8 --refresh`.

## Development

```bash
uv sync --extra eval
uv run pytest            # 187 tests, offline against the snapshot
uv run mypy              # strict
uv run ruff check . && uv run ruff format --check .
```

## Limits

- v1 is 68 items, and each arm ran once. One answerable item is 1.8 points; its intervals are wide for that reason, so treat v1 differences under about 10 points as noise. v2 is 175 items run three times; its closed-book runs ranged over as much as 5.7 points, and smaller differences cannot be read. Both are one model.
- The primed prompt tells the model that some questions hide a false premise and, in the tools arm, to look every value up. v1's caught and grounded rates therefore measure behaviour when asked to be careful, not unprompted. v2's unprimed prompt drops both, but the answer form still has a flag and the tool descriptions still say what `found: false` means: "unprimed" means no warning from the prompt, not no hint at all.
- The grader only checks that the premise was rejected. Every planted item's explanation in both published runs was read by hand; the v2 results page has the count.
- v1 covers the seven v0.1.0 tools. `get_variants` and `map_structure_residue` were first run by a model in v2.
- v2's proteins are one seeded draw, even over sequence lengths and not over entries, with one stratum (peptidase S1) chosen for its insertion codes. The results describe that draw, not UniProtKB as a whole.
- `get_variants` reads UniProtKB's curated variants, which are a subset of what ClinVar and gnomAD hold. An empty result is reported as "none annotated", never as "does not occur".
- Residue mapping uses the alignment RCSB PDB publishes for each entity. A chain with no UniProtKB alignment (many antibodies, designed proteins) maps to nothing, and says so. Feature annotations are canonical-sequence only: an isoform ID works for sequence windows, not for features or variants.
- The questions are public, so later models may have trained on them. Rebuild with a new seed before reusing the numbers.
- Live mode drifts: new PDB entries change "best resolution", and the two unassigned PDB IDs may be assigned one day. The snapshot keeps them fixed.
- Both sets are saturated for a tool-using agent (100% of answerable items), and v1 is mostly memorisable for closed-book Opus 5.5 (78%). They check that the tools work, that answers are grounded and, in v2, that memory is no substitute; they can't rank strong agents or tool surfaces against each other.
- Data licences: UniProtKB and AlphaFold DB under CC BY 4.0, RCSB PDB under CC0 (see `evals/snapshot/README.md`).

Built with Claude Code. MIT licence.
