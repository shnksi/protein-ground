"""The tool surface, defined once and shared by the MCP server and the eval agent."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from proteinground import alphafold, pdb, uniprot
from proteinground.fetch import Fetcher, InvalidInputError, OfflineMissError, UpstreamError
from proteinground.models import Cited

GROUNDING = (
    " Every value comes back with its source record. found=false with a note means the "
    "record or feature does not exist; say so rather than guessing. An error result means "
    "the lookup itself failed and says nothing about whether the record exists."
)


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchArgs(_Args):
    query: str = Field(description="UniProt query, e.g. 'gene:KRAS' or 'insulin receptor'")
    taxon_id: int | None = Field(default=None, description="NCBI taxon, e.g. 9606 for human")
    reviewed_only: bool = Field(default=True, description="Swiss-Prot (reviewed) entries only")
    limit: int = Field(default=5, ge=1, le=25)


class AccessionArgs(_Args):
    accession: str = Field(description="UniProtKB accession, e.g. P04637")


class WindowArgs(_Args):
    accession: str = Field(
        description="UniProtKB accession, or an isoform ID such as P04637-2 for that isoform"
    )
    start: int = Field(description="First position, 1-based, on this sequence")
    end: int = Field(description="Last position, inclusive; at most 50 residues per call")


class FeatureArgs(_Args):
    accession: str = Field(description="UniProtKB accession")
    feature_type: str | None = Field(
        default=None,
        description=(
            "UniProt feature type, one of: " + ", ".join(uniprot.FEATURE_TYPES) + ". Omit to "
            "list all of these. Common names such as 'signal peptide' are understood."
        ),
    )
    position: int | None = Field(
        default=None, description="Only features that cover this residue position"
    )


class VariantArgs(_Args):
    accession: str = Field(description="UniProtKB accession")
    start: int = Field(description="Residue position, 1-based, on the canonical sequence")
    end: int | None = Field(
        default=None, description="Last position for a range of at most 50; omit for one residue"
    )


class AlphaFoldArgs(_Args):
    accession: str = Field(description="UniProtKB accession")
    start: int | None = Field(
        default=None, description="Also report confidence for the residues from here"
    )
    end: int | None = Field(default=None, description="to here, inclusive; needs start")
    model_id: str | None = Field(
        default=None,
        description=(
            "Specific AlphaFold model ID (e.g. AF-P11532-9-F1) for an isoform or fragment"
        ),
    )


class MapResidueArgs(_Args):
    pdb_id: str = Field(description="Four-character PDB ID, e.g. 1IEP")
    chain: str = Field(description="Chain ID as the paper or viewer shows it, e.g. A")
    residue_number: int | None = Field(
        default=None,
        description="Residue number as numbered in the structure. Give this or uniprot_position",
    )
    insertion_code: str | None = Field(
        default=None, description="Insertion code of that residue, e.g. A in 60A"
    )
    uniprot_position: int | None = Field(
        default=None,
        description="Position on the UniProtKB sequence, to find its number in the structure",
    )
    uniprot_accession: str | None = Field(
        default=None,
        description="Disambiguate a fusion chain when mapping from uniprot_position",
    )


class StructuresArgs(_Args):
    accession: str = Field(description="UniProtKB accession")
    method: str | None = Field(
        default=None,
        description="Method filter: 'X-ray', 'EM', 'NMR' (common names like 'cryo-EM' work)",
    )
    limit: int = Field(default=20, ge=1, le=100)


class PdbArgs(_Args):
    pdb_id: str = Field(description="Four-character PDB ID, e.g. 4HHB")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[_Args]
    run: Callable[[Fetcher, Any], Cited[Any]]


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            "search_proteins",
            "Find UniProtKB entries by gene, name or keyword. Returns accessions to use "
            "with the other tools." + GROUNDING,
            SearchArgs,
            lambda f, a: uniprot.search(f, a.query, a.taxon_id, a.reviewed_only, a.limit),
        ),
        ToolSpec(
            "get_protein",
            "UniProtKB summary for one accession: name, gene, organism, canonical length, "
            "function and location." + GROUNDING,
            AccessionArgs,
            lambda f, a: uniprot.get_protein(f, a.accession),
        ),
        ToolSpec(
            "get_sequence_window",
            "Residues at given positions of the canonical UniProtKB sequence (or of one "
            "isoform), one numbered entry per position, so you never count offsets by hand. "
            "Up to 50 residues." + GROUNDING,
            WindowArgs,
            lambda f, a: uniprot.get_sequence_window(f, a.accession, a.start, a.end),
        ),
        ToolSpec(
            "get_features",
            "Annotated sequence features from UniProtKB (domains, signal peptides, active "
            "and binding sites, disulfide bonds) with start and end positions. Filter by "
            "type, by a residue position, or both." + GROUNDING,
            FeatureArgs,
            lambda f, a: uniprot.get_features(f, a.accession, a.feature_type, a.position),
        ),
        ToolSpec(
            "get_variants",
            "Natural variants and mutagenesis records that UniProtKB curates at a position "
            "or short range, with the wild-type residue there. Use it to check a mutation "
            "such as G12C: is residue 12 really Gly, and is the change annotated? UniProtKB "
            "is not a complete variant catalogue, so an empty list is not proof that a "
            "variant does not occur." + GROUNDING,
            VariantArgs,
            lambda f, a: uniprot.get_variants(f, a.accession, a.start, a.end),
        ),
        ToolSpec(
            "list_structures",
            "PDB structures that UniProtKB cross-references for an accession, with method "
            "and resolution, best resolution first." + GROUNDING,
            StructuresArgs,
            lambda f, a: uniprot.list_structures(f, a.accession, a.method, a.limit),
        ),
        ToolSpec(
            "get_structure",
            "RCSB PDB entry: title, experimental method, resolution, dates, each polymer "
            "with its chain IDs, source organism and UniProtKB accession, and the bound "
            "ligands with their chemical component IDs. An obsolete entry names its "
            "replacement." + GROUNDING,
            PdbArgs,
            lambda f, a: pdb.get_structure(f, a.pdb_id),
        ),
        ToolSpec(
            "map_structure_residue",
            "Translate residue numbering between a PDB chain and UniProtKB. Structures are "
            "often numbered differently from the UniProtKB sequence, so use this before "
            "equating 'residue 315 in the structure' with a sequence position. Returns the "
            "residue in both, whether they agree (an engineered mutation shows up here), and "
            "whether the residue was actually modelled." + GROUNDING,
            MapResidueArgs,
            lambda f, a: pdb.map_structure_residue(
                f,
                a.pdb_id,
                a.chain,
                a.residue_number,
                a.insertion_code,
                a.uniprot_position,
                a.uniprot_accession,
            ),
        ),
        ToolSpec(
            "get_alphafold_summary",
            "AlphaFold DB model confidence for an accession: mean pLDDT, the share of "
            "residues in each confidence band, and long low-confidence regions. Give start "
            "and end to get the confidence of one region." + GROUNDING,
            AlphaFoldArgs,
            lambda f, a: alphafold.get_alphafold_summary(
                f, a.accession, a.start, a.end, a.model_id
            ),
        ),
    ]
}


def anthropic_tool_defs() -> list[dict[str, Any]]:
    """Tool definitions in the Messages API shape, in a stable order for prompt caching."""
    return [
        {"name": s.name, "description": s.description, "input_schema": s.args.model_json_schema()}
        for s in TOOLS.values()
    ]


def run_tool(fetcher: Fetcher, name: str, raw_input: Any) -> tuple[str, bool]:
    """Run one tool call. Returns (JSON text for the model, is_error)."""
    spec = TOOLS.get(name)
    if spec is None:
        return json.dumps({"error": f"unknown tool '{name}'"}), True
    try:
        args = spec.args.model_validate(raw_input)
    except ValidationError as exc:
        return json.dumps(
            {"error": "invalid arguments", "detail": exc.errors(include_url=False)}, default=str
        ), True
    try:
        result = spec.run(fetcher, args)
    except InvalidInputError as exc:
        return json.dumps({"error": "invalid arguments", "detail": str(exc)}), True
    except (UpstreamError, OfflineMissError) as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"}), True
    except Exception as exc:  # a malformed record must not crash an agent's session
        return json.dumps({"error": f"unexpected {type(exc).__name__}: {exc}"}), True
    return result.model_dump_json(exclude_none=True), False
