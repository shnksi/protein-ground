from __future__ import annotations

import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from proteinground.fetch import Fetcher
from proteinground.server import build_server
from proteinground.tools import TOOLS


def test_server_exposes_the_shared_tools_read_only(offline: Fetcher) -> None:
    server = build_server(offline)
    listed = asyncio.run(server.list_tools())
    assert [t.name for t in listed] == list(TOOLS)
    for tool in listed:
        spec = TOOLS[tool.name]
        assert tool.description == spec.description
        assert set(tool.input_schema["properties"]) == set(spec.args.model_fields)
        assert tool.annotations is not None and tool.annotations.read_only_hint
        assert tool.output_schema is not None


def test_server_call_returns_structured_cited_result(offline: Fetcher) -> None:
    server = build_server(offline)
    result = asyncio.run(
        server.call_tool("get_sequence_window", {"accession": "P04637", "start": 175, "end": 175})
    )
    structured = result.structured_content  # type: ignore[union-attr]
    assert structured is not None
    assert structured["data"]["residues"] == [
        {"position": 175, "one_letter": "R", "three_letter": "Arg"}
    ]
    assert structured["sources"][0]["database"] == "UniProtKB"


def test_failed_lookup_reaches_the_client_with_its_reason(offline: Fetcher) -> None:
    """The SDK masks unknown exceptions; a lookup failure must keep its explanation."""
    server = build_server(offline)
    with pytest.raises(ToolError, match="exactly one of residue_number or uniprot_position"):
        asyncio.run(server.call_tool("map_structure_residue", {"pdb_id": "1IEP", "chain": "A"}))
    with pytest.raises(ToolError, match="OfflineMissError: not in the frozen snapshot"):
        asyncio.run(server.call_tool("get_protein", {"accession": "P12345"}))


def test_not_found_is_a_result_not_an_error(offline: Fetcher) -> None:
    server = build_server(offline)
    result = asyncio.run(server.call_tool("get_structure", {"pdb_id": "1HHB"}))
    structured = result.structured_content  # type: ignore[union-attr]
    assert structured is not None and structured["found"] is False
    assert "superseded by 4HHB" in structured["note"]
