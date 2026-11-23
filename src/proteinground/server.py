"""MCP server (stdio) exposing the proteinground tools.

Run it with `proteinground-mcp`. Set PROTEINGROUND_CACHE_DIR to keep a replayable copy
of every response, and PROTEINGROUND_MODE=offline to serve only from that copy.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from proteinground import alphafold, pdb, uniprot
from proteinground.fetch import Fetcher
from proteinground.models import (
    AlphaFoldSummary,
    Cited,
    FeatureList,
    ProteinHit,
    ProteinSummary,
    SequenceWindow,
    StructureEntry,
    StructureRefList,
)
from proteinground.tools import TOOLS

INSTRUCTIONS = (
    "Protein facts from UniProtKB, RCSB PDB and AlphaFold DB. Each result carries the "
    "source record and URL; cite them. A result with found=false means the thing asked "
    "about does not exist in that database: report that instead of inferring a value."
)


def build_server(fetcher: Fetcher | None = None) -> MCPServer:
    f = fetcher or Fetcher.from_env()
    mcp = MCPServer("proteinground", instructions=INSTRUCTIONS, version="0.1.0")
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=True, idempotent_hint=True)

    def describe(name: str) -> str:
        return TOOLS[name].description

    @mcp.tool(description=describe("search_proteins"), annotations=read_only)
    def search_proteins(
        query: str, taxon_id: int | None = None, reviewed_only: bool = True, limit: int = 5
    ) -> Cited[list[ProteinHit]]:
        return uniprot.search(f, query, taxon_id, reviewed_only, limit)

    @mcp.tool(description=describe("get_protein"), annotations=read_only)
    def get_protein(accession: str) -> Cited[ProteinSummary]:
        return uniprot.get_protein(f, accession)

    @mcp.tool(description=describe("get_sequence_window"), annotations=read_only)
    def get_sequence_window(accession: str, start: int, end: int) -> Cited[SequenceWindow]:
        return uniprot.get_sequence_window(f, accession, start, end)

    @mcp.tool(description=describe("get_features"), annotations=read_only)
    def get_features(accession: str, feature_type: str | None = None) -> Cited[FeatureList]:
        return uniprot.get_features(f, accession, feature_type)

    @mcp.tool(description=describe("list_structures"), annotations=read_only)
    def list_structures(
        accession: str, method: str | None = None, limit: int = 20
    ) -> Cited[StructureRefList]:
        return uniprot.list_structures(f, accession, method, limit)

    @mcp.tool(description=describe("get_structure"), annotations=read_only)
    def get_structure(pdb_id: str) -> Cited[StructureEntry]:
        return pdb.get_structure(f, pdb_id)

    @mcp.tool(description=describe("get_alphafold_summary"), annotations=read_only)
    def get_alphafold_summary(accession: str) -> Cited[AlphaFoldSummary]:
        return alphafold.get_alphafold_summary(f, accession)

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
