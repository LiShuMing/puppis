"""Evidplane MCP server: search / get / pack over the local lake (stdio)."""
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

from lake import api as lake_api
from lake.db import default_db_path, item_count
from lake.seed import seed_fake

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


def _ensure_seeded() -> None:
    """Auto-seed fake Evidence once so Cursor dogfood works out of the box."""
    path = default_db_path()
    from lake.db import connect, init_db

    conn = connect(path)
    try:
        init_db(conn)
        if item_count(conn) == 0:
            seed_fake(path)
    finally:
        conn.close()


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
    _ensure_seeded()
    return _json(
        lake_api.search(q=q, source=source, since_days=since_days, limit=limit)
    )


@server.tool(
    name="get",
    description="Fetch one Evidence item by item_id (full text + source_url + provenance).",
)
def get(item_id: str) -> str:
    _ensure_seeded()
    return _json(lake_api.get(item_id))


@server.tool(
    name="pack",
    description=(
        "Compile a context Pack for agents. template='work' returns recent "
        "high-signal items with cites and a token_estimate. Optional budget_tokens, since_days."
    ),
)
def pack(
    template: str = "work",
    budget_tokens: int | None = 4000,
    since_days: int | None = 7,
) -> str:
    _ensure_seeded()
    return _json(
        lake_api.pack(
            template=template,
            budget_tokens=budget_tokens,
            since_days=since_days,
        )
    )


@server.tool(
    name="list_connectors",
    description="List configured connectors (stub until real OAuth sources land).",
)
def list_connectors() -> str:
    _ensure_seeded()
    return _json(
        {
            "connectors": [
                {
                    "connector_id": "google_calendar",
                    "status": "fake_seed",
                    "note": "L0 dogfood seed only",
                },
                {
                    "connector_id": "notion",
                    "status": "ingest_ready",
                    "note": "scripts/ingest_notion.py (--fixture or NOTION_TOKEN)",
                },
            ]
        }
    )


def main() -> None:
    _ensure_seeded()
    # mcp 2.x: run(transport='stdio') blocks on stdin.
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
