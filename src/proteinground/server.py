"""MCP server (stdio) exposing the proteinground tools.

Run it with `proteinground-mcp`. Set PROTEINGROUND_CACHE_DIR to keep a replayable copy
of every response, and PROTEINGROUND_MODE=offline to serve only from that copy.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Annotated, ParamSpec, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic.fields import FieldInfo

from proteinground import alphafold, pdb, uniprot
from proteinground.fetch import Fetcher, InvalidInputError, OfflineMissError, UpstreamError
from proteinground.models import (
    AlphaFoldSummary,
    Cited,
    FeatureList,
    ProteinHit,
    ProteinSummary,
    ResidueMapping,
    SequenceWindow,
    StructureEntry,
    StructureRefList,
    VariantList,
)
from proteinground.tools import TOOLS
from proteinground.version import __version__

INSTRUCTIONS = (
    "Protein facts from UniProtKB, RCSB PDB and AlphaFold DB. Each result carries the "
    "source record and URL; cite them. A result with found=false means the thing asked "
    "about does not exist in that database: report that instead of inferring a value. A "
    "tool error means the lookup failed, which is not the same as not existing. Structure "
    "files often number residues differently from UniProtKB: map with map_structure_residue "
    "before equating the two."
)

P = ParamSpec("P")
R = TypeVar("R")


def _field(tool_name: str, param_name: str) -> FieldInfo:
    """Reuse each parameter's description and bounds from the shared tool schema."""
    return TOOLS[tool_name].args.model_fields[param_name]


def _reported(fn: Callable[P, R]) -> Callable[P, R]:
    """Send a failed lookup to the client with its explanation.

    The SDK masks every exception except ToolError as "Error executing tool", which
    would hide whether a database was down, the request was rejected or the arguments
    were wrong. Anything else is a bug and stays masked.
    """

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except InvalidInputError as exc:
            raise ToolError(f"invalid arguments: {exc}") from exc
        except (UpstreamError, OfflineMissError) as exc:
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc

    return wrapper


def build_server(fetcher: Fetcher | None = None) -> MCPServer:
    f = fetcher or Fetcher.from_env()
    mcp = MCPServer("proteinground", instructions=INSTRUCTIONS, version=__version__)
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=True, idempotent_hint=True)

    def describe(name: str) -> str:
        return TOOLS[name].description

    @mcp.tool(description=describe("search_proteins"), annotations=read_only)
    @_reported
    def search_proteins(
        query: Annotated[str, _field("search_proteins", "query")],
        taxon_id: Annotated[int | None, _field("search_proteins", "taxon_id")] = None,
        reviewed_only: Annotated[bool, _field("search_proteins", "reviewed_only")] = True,
        limit: Annotated[int, _field("search_proteins", "limit")] = 5,
    ) -> Cited[list[ProteinHit]]:
        return uniprot.search(f, query, taxon_id, reviewed_only, limit)

    @mcp.tool(description=describe("get_protein"), annotations=read_only)
    @_reported
    def get_protein(
        accession: Annotated[str, _field("get_protein", "accession")],
    ) -> Cited[ProteinSummary]:
        return uniprot.get_protein(f, accession)

    @mcp.tool(description=describe("get_sequence_window"), annotations=read_only)
    @_reported
    def get_sequence_window(
        accession: Annotated[str, _field("get_sequence_window", "accession")],
        start: Annotated[int, _field("get_sequence_window", "start")],
        end: Annotated[int, _field("get_sequence_window", "end")],
    ) -> Cited[SequenceWindow]:
        return uniprot.get_sequence_window(f, accession, start, end)

    @mcp.tool(description=describe("get_features"), annotations=read_only)
    @_reported
    def get_features(
        accession: Annotated[str, _field("get_features", "accession")],
        feature_type: Annotated[str | None, _field("get_features", "feature_type")] = None,
        position: Annotated[int | None, _field("get_features", "position")] = None,
    ) -> Cited[FeatureList]:
        return uniprot.get_features(f, accession, feature_type, position)

    @mcp.tool(description=describe("get_variants"), annotations=read_only)
    @_reported
    def get_variants(
        accession: Annotated[str, _field("get_variants", "accession")],
        start: Annotated[int, _field("get_variants", "start")],
        end: Annotated[int | None, _field("get_variants", "end")] = None,
    ) -> Cited[VariantList]:
        return uniprot.get_variants(f, accession, start, end)

    @mcp.tool(description=describe("list_structures"), annotations=read_only)
    @_reported
    def list_structures(
        accession: Annotated[str, _field("list_structures", "accession")],
        method: Annotated[str | None, _field("list_structures", "method")] = None,
        limit: Annotated[int, _field("list_structures", "limit")] = 20,
    ) -> Cited[StructureRefList]:
        return uniprot.list_structures(f, accession, method, limit)

    @mcp.tool(description=describe("get_structure"), annotations=read_only)
    @_reported
    def get_structure(
        pdb_id: Annotated[str, _field("get_structure", "pdb_id")],
    ) -> Cited[StructureEntry]:
        return pdb.get_structure(f, pdb_id)

    @mcp.tool(description=describe("map_structure_residue"), annotations=read_only)
    @_reported
    def map_structure_residue(
        pdb_id: Annotated[str, _field("map_structure_residue", "pdb_id")],
        chain: Annotated[str, _field("map_structure_residue", "chain")],
        residue_number: Annotated[
            int | None, _field("map_structure_residue", "residue_number")
        ] = None,
        insertion_code: Annotated[
            str | None, _field("map_structure_residue", "insertion_code")
        ] = None,
        uniprot_position: Annotated[
            int | None, _field("map_structure_residue", "uniprot_position")
        ] = None,
        uniprot_accession: Annotated[
            str | None, _field("map_structure_residue", "uniprot_accession")
        ] = None,
    ) -> Cited[ResidueMapping]:
        return pdb.map_structure_residue(
            f,
            pdb_id,
            chain,
            residue_number,
            insertion_code,
            uniprot_position,
            uniprot_accession,
        )

    @mcp.tool(description=describe("get_alphafold_summary"), annotations=read_only)
    @_reported
    def get_alphafold_summary(
        accession: Annotated[str, _field("get_alphafold_summary", "accession")],
        start: Annotated[int | None, _field("get_alphafold_summary", "start")] = None,
        end: Annotated[int | None, _field("get_alphafold_summary", "end")] = None,
        model_id: Annotated[str | None, _field("get_alphafold_summary", "model_id")] = None,
    ) -> Cited[AlphaFoldSummary]:
        return alphafold.get_alphafold_summary(f, accession, start, end, model_id)

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
