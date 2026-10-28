"""Evidplane MCP server: search / get / pack over the local lake (stdio).

Uses mcp>=2 MCPServer (FastMCP rename). Serve talks only to lake — never
platform APIs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Allow `python -m serve.mcp_server` from repo root without install.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp.server.mcpserver import MCPServer

from lake.query import get as lake_get
from lake.query import pack as lake_pack
from lake.query import search as lake_search
from lake.query import overview

server = MCPServer(
    name="evidplane",
    title="Evidplane",
    instructions=(
        "Personal Evidence lake for work context. "
        "Use pack(work) for a citeable recent-work bundle; "
        "search to find candidates; get(item_id) to pull full text + source_url. "
        "Do not invent item_ids — only cite ids returned by these tools."
    ),
)


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@server.tool(
    name="search",
    description=(
        "Search Evidence metadata (title/body FTS). "
        "Optional filters: source=connector_id, since_days, limit."
    ),
)
def search(
    q: str | None = None,
    source: str | None = None,
    since_days: int | None = None,
    limit: int | None = 20,
) -> str:
    return _json(
        lake_search(q=q, source=source, since_days=since_days, limit=limit)
    )


@server.tool(
    name="get",
    description="Fetch one Evidence item by item_id (full text + source_url + provenance).",
)
def get(item_id: str) -> str:
    return _json(lake_get(item_id))


@server.tool(
    name="pack",
    description=(
        "Compile a context Pack for agents. template='work' returns recent "
        "high-signal items with cites and a token_estimate. Optional budget_tokens, since_days."
    ),
)
def pack(
    template: str = "work",
    budget_tokens: int | None = 3000,
    since_days: int | None = 7,
) -> str:
    return _json(
        lake_pack(
            template=template,
            budget_tokens=budget_tokens,
            since_days=since_days,
        )
    )


@server.tool(
    name="list_connectors",
    description="List sources actually ingested into the local Evidence library.",
)
def list_connectors() -> str:
    return _json({"connectors": overview()["sources"]})


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
