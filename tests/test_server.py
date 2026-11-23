from __future__ import annotations

import asyncio

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
