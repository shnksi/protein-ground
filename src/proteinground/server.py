"""MCP server (stdio) exposing the proteinground tools.

Run it with `proteinground-mcp`. Set PROTEINGROUND_CACHE_DIR to keep a replayable copy
of every response, and PROTEINGROUND_MODE=offline to serve only from that copy.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

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
        query: str, taxon_id: int | None = None, reviewed_only: bool = True, limit: int = 5
    ) -> Cited[list[ProteinHit]]:
        return uniprot.search(f, query, taxon_id, reviewed_only, limit)

    @mcp.tool(description=describe("get_protein"), annotations=read_only)
    @_reported
    def get_protein(accession: str) -> Cited[ProteinSummary]:
        return uniprot.get_protein(f, accession)

    @mcp.tool(description=describe("get_sequence_window"), annotations=read_only)
    @_reported
    def get_sequence_window(accession: str, start: int, end: int) -> Cited[SequenceWindow]:
        return uniprot.get_sequence_window(f, accession, start, end)

    @mcp.tool(description=describe("get_features"), annotations=read_only)
    @_reported
    def get_features(
        accession: str, feature_type: str | None = None, position: int | None = None
    ) -> Cited[FeatureList]:
        return uniprot.get_features(f, accession, feature_type, position)

    @mcp.tool(description=describe("get_variants"), annotations=read_only)
    @_reported
    def get_variants(accession: str, start: int, end: int | None = None) -> Cited[VariantList]:
        return uniprot.get_variants(f, accession, start, end)

    @mcp.tool(description=describe("list_structures"), annotations=read_only)
    @_reported
    def list_structures(
        accession: str, method: str | None = None, limit: int = 20
    ) -> Cited[StructureRefList]:
        return uniprot.list_structures(f, accession, method, limit)

    @mcp.tool(description=describe("get_structure"), annotations=read_only)
    @_reported
    def get_structure(pdb_id: str) -> Cited[StructureEntry]:
        return pdb.get_structure(f, pdb_id)

    @mcp.tool(description=describe("map_structure_residue"), annotations=read_only)
    @_reported
    def map_structure_residue(
        pdb_id: str,
        chain: str,
        residue_number: int | None = None,
        insertion_code: str | None = None,
        uniprot_position: int | None = None,
    ) -> Cited[ResidueMapping]:
        return pdb.map_structure_residue(
            f, pdb_id, chain, residue_number, insertion_code, uniprot_position
        )

    @mcp.tool(description=describe("get_alphafold_summary"), annotations=read_only)
    @_reported
    def get_alphafold_summary(
        accession: str, start: int | None = None, end: int | None = None
    ) -> Cited[AlphaFoldSummary]:
        return alphafold.get_alphafold_summary(f, accession, start, end)

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
