#!/usr/bin/env python3
"""Smoke: list MCP tools via in-process MCPServer (no Cursor needed)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


async def _run() -> int:
    # Import after path fix so serve can resolve lake.*
    from serve.mcp_server import server

    tools = await server.list_tools()
    names = sorted(t.name for t in tools)
    print("=== MCP tools ===")
    print(json.dumps(names, indent=2))
    expected = {"search", "get", "pack", "list_connectors"}
    missing = expected - set(names)
    assert not missing, f"missing tools: {missing}"

    # Call pack through the server tool registry
    result = await server.call_tool("pack", {"template": "work", "budget_tokens": 3000})
    # call_tool may return CallToolResult or similar — stringify content
    text = ""
    if hasattr(result, "content"):
        parts = []
        for c in result.content:
            parts.append(getattr(c, "text", None) or str(c))
        text = "\n".join(parts)
    else:
        text = str(result)
    print("\n=== pack via MCPServer.call_tool (excerpt) ===")
    print(text[:1200])
    assert "item_id" in text or "cites" in text or "Evidplane" in text
    print("\nSMOKE_MCP OK")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
