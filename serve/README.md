# serve

MCP tools only: `search`, `get`, `pack` (+ `list_connectors` stub).

```bash
PYTHONPATH=. python -m serve.mcp_server
PYTHONPATH=. python scripts/smoke_mcp.py   # in-process tool listing + pack call, no client
```

`pack` passes `budget_tokens` straight to lake `pack_work`, so the MCP tool inherits the
hard cap (`token_estimate <= budget_tokens`).

Reads lake; never connectors or platform tokens. See `docs/dogfood.md`.
