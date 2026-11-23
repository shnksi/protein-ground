# proteinground

Cited protein facts for AI agents. An MCP server over UniProtKB, RCSB PDB and AlphaFold DB that returns every value with the record it came from, and says "not found" when something doesn't exist, so the model doesn't guess. It comes with a preregistered eval that plants false premises, to measure whether an agent checks before it answers.

```
> In UniProtKB entry P01308 (human insulin), which amino acid is at position 450?

get_sequence_window(accession="P01308", start=450, end=450)
→ found: false
  note: "position 450 is beyond the end of P01308, which has 110 residues"
  sources: [UniProtKB P01308, release 2026_04, https://www.uniprot.org/uniprotkb/P01308/entry]
```

## Why

Language models answer protein questions fluently, and often wrongly: a residue number off by one, a structure's method misremembered, a mouse structure cited as human. A scientist acting on that pays more for a confident wrong answer than for "I don't know". These tools make the checked answer the easy one, and the eval measures whether the agent takes it.

## The tools

| Tool | Source | Returns |
|---|---|---|
| `search_proteins` | UniProtKB | accessions for a gene, name or keyword |
| `get_protein` | UniProtKB | name, gene, organism, canonical length, function, location |
| `get_sequence_window` | UniProtKB | up to 50 residues, one numbered entry per position |
| `get_features` | UniProtKB | domains, signal peptides, active and binding sites, disulfides, with positions |
| `list_structures` | UniProtKB → PDB | cross-referenced structures, best resolution first |
| `get_structure` | RCSB PDB | method, resolution, dates, the UniProtKB accession of each chain, bound ligands |
| `get_alphafold_summary` | AlphaFold DB | mean pLDDT, the share of residues in each confidence band, long low-confidence regions |

Design choices, each aimed at a known way agents go wrong:

- **Every result is `Cited[T]`**: `found`, `data`, `note`, and `sources` (database, record ID, a URL a person can open, retrieval time, release). The citation travels with the value, so the agent never has to reconstruct where a number came from.
- **"Doesn't exist" is a first-class answer.** A missing record, a position past the end of a sequence or an absent feature comes back as `found: false` with a reason, plus the feature types that *are* annotated. The usual failure is a tool that returns an empty list and leaves the model to fill the silence. The reverse matters too: asking for a feature type the tool doesn't retrieve (natural variants, say) says so, rather than claiming the entry has none.
- **Residues are numbered for the model.** Sequence windows return `{position, one_letter, three_letter}` per residue, because models miscount offsets into long strings.
- **Ligands carry context.** Crystallisation additives and ions (glycerol, sulfate, chloride) are flagged, so the agent doesn't report glycerol as the bound drug.
- **Read-only and replayable.** Tools are annotated read-only and idempotent. Every response can be written to a cache and replayed offline, which is how the eval stays reproducible.

The tool surface is defined once (`src/proteinground/tools.py`) and shared by the MCP server and the eval agent, so what gets measured is what ships.

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

- PDB IDs that have not been assigned (`9ZYZ`, `9ZZX`)
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

Claude Opus 5.5, 23 Nov 2026, all 68 items per arm. Full write-up and records: [`evals/results/2026-11-23-opus-5-5/`](evals/results/2026-11-23-opus-5-5/RESULTS.md).

| Arm | Answerable correct | False premise caught | False alarms | Grounded | Cost / item |
|---|---|---|---|---|---|
| tools | **100%** (55/55) | **100%** (13/13) | 0% | 100% | $0.0087 |
| closed_book | 78% (43/55) | 100% (13/13) | 2% (1/55) | – | $0.0103 |
| stub, always "fine" (decoy) | 0% | 0% | 0% | – | $0 |
| stub, always "doesn't exist" (decoy) | 0% | 100% | 100% | – | $0 |

The whole run cost $1.38. With the tools, every answer was right and grounded in a record fetched during that episode, with about one lookup per question. The closed-book misses are values that can't be memorised: all six AlphaFold confidence fractions, most best-resolution structures (the record has moved on since training), and a signal-peptide boundary off by one.

Five of the six preregistered bars passed. The one that missed: the tools-minus-memory gap was 22 points against a preregistered 30. Opus 5.5 recalled residues, lengths, ligand IDs and every planted premise for these famous proteins from memory. So this set shows the tools are reliable and grounded; it does not show a large lift over a strong model's memory. That needs a harder set of less-studied proteins, which is the next version.

### Run it

```bash
uv sync --extra eval
uv run proteinground-eval check-gold
uv run proteinground-eval run --arm tools --stub --out runs/dry-run      # free

export ANTHROPIC_API_KEY=...
uv run proteinground-eval run --arm tools --model claude-opus-5-5 --cap-usd 12 --out runs/opus-tools
uv run proteinground-eval run --arm closed_book --model claude-opus-5-5 --cap-usd 3 --out runs/opus-closed
uv run proteinground-eval report runs/opus-tools runs/opus-closed
```

Runs resume where they stopped. `--ids` runs chosen items, `--no-fallbacks` measures the named model only, and `--strict-offline` fails any tool call that misses the snapshot. Rebuild the set with fresh residue positions with `uv run python evals/build_questions.py --seed 8 --refresh`.

## Development

```bash
uv sync --extra eval
uv run pytest            # 65 tests, offline against the snapshot
uv run mypy              # strict
uv run ruff check . && uv run ruff format --check .
```

## Limits

- 68 items is small. One answerable item is 1.8 points, so treat differences under about 10 points as noise.
- The questions are public, so later models may have trained on them. Rebuild with a new seed before reusing the numbers.
- Live mode drifts: new PDB entries change "best resolution", and the two unassigned PDB IDs may be assigned one day. The snapshot keeps them fixed.
- The set is saturated for a tool-using agent (100%) and mostly memorisable for closed-book Opus 5.5 (78%). It checks that the tools work and that answers are grounded; it can't rank strong agents against each other.
- Data licences: UniProtKB and AlphaFold DB under CC BY 4.0, RCSB PDB under CC0 (see `evals/snapshot/README.md`).

Built with Claude Code. MIT licence.
