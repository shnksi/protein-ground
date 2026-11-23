"""The server as a client sees it: a subprocess speaking MCP over stdio, offline."""

from __future__ import annotations

import asyncio
import os
import sys

from conftest import ROOT, SNAPSHOT
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def _session_roundtrip() -> tuple[list[str], dict[str, object]]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "proteinground.server"],
        env={**os.environ, "PROTEINGROUND_CACHE_DIR": str(SNAPSHOT),
             "PROTEINGROUND_MODE": "offline"},
        cwd=ROOT,
    )  # fmt: skip
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        result = await session.call_tool("get_structure", {"pdb_id": "6VXX"})
        assert result.structured_content is not None
        return [t.name for t in listed.tools], result.structured_content


def test_stdio_server_lists_tools_and_answers_from_the_snapshot() -> None:
    names, structured = asyncio.run(_session_roundtrip())
    assert "get_structure" in names and len(names) == 7
    data = structured["data"]
    assert isinstance(data, dict) and data["methods"] == ["ELECTRON MICROSCOPY"]
