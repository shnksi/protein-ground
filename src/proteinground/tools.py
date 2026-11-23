"""The tool surface, defined once and shared by the MCP server and the eval agent."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from proteinground import alphafold, pdb, uniprot
from proteinground.fetch import Fetcher, OfflineMissError, UpstreamError
from proteinground.models import Cited

GROUNDING = (
    " Every value comes back with its source record. found=false with a note means the "
    "record or feature does not exist; say so rather than guessing."
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
    accession: str = Field(description="UniProtKB accession")
    start: int = Field(description="First position, 1-based, on the canonical sequence")
    end: int = Field(description="Last position, inclusive; at most 50 residues per call")


class FeatureArgs(_Args):
    accession: str = Field(description="UniProtKB accession")
    feature_type: str | None = Field(
        default=None,
        description=(
            "UniProt feature type, one of: " + ", ".join(uniprot.FEATURE_TYPES) + ". Omit to "
            "list all of these."
        ),
    )


class StructuresArgs(_Args):
    accession: str = Field(description="UniProtKB accession")
    method: str | None = Field(default=None, description="'X-ray', 'EM' or 'NMR'")
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
            "Residues at given positions of the canonical UniProtKB sequence, one numbered "
            "entry per position, so you never count offsets by hand. Up to 50 residues."
            + GROUNDING,
            WindowArgs,
            lambda f, a: uniprot.get_sequence_window(f, a.accession, a.start, a.end),
        ),
        ToolSpec(
            "get_features",
            "Annotated sequence features from UniProtKB (domains, signal peptides, active "
            "and binding sites, disulfide bonds) with start and end positions." + GROUNDING,
            FeatureArgs,
            lambda f, a: uniprot.get_features(f, a.accession, a.feature_type),
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
            "RCSB PDB entry: title, experimental method, resolution, dates, the UniProtKB "
            "accession of each polymer and the bound ligands with their chemical component "
            "IDs." + GROUNDING,
            PdbArgs,
            lambda f, a: pdb.get_structure(f, a.pdb_id),
        ),
        ToolSpec(
            "get_alphafold_summary",
            "AlphaFold DB model confidence for an accession: mean pLDDT, the share of "
            "residues in each confidence band, and long low-confidence regions." + GROUNDING,
            AccessionArgs,
            lambda f, a: alphafold.get_alphafold_summary(f, a.accession),
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
    except (UpstreamError, OfflineMissError) as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"}), True
    except Exception as exc:  # a malformed record must not crash an agent's session
        return json.dumps({"error": f"unexpected {type(exc).__name__}: {exc}"}), True
    return result.model_dump_json(exclude_none=True), False
