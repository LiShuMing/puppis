# serve

MCP tools only: `search`, `get`, `pack`, `list_connectors` (actual ingested sources).
Empty databases stay empty; demo import is explicit in the local Console.

```bash
PYTHONPATH=. python -m serve.mcp_server
PYTHONPATH=. python scripts/smoke_mcp.py   # in-process tool listing + pack call, no client
```

`pack` passes `budget_tokens` straight to lake `pack_work`, so the MCP tool inherits the
hard cap (`token_estimate <= budget_tokens`).

Reads lake; never connectors or platform tokens. See `docs/dogfood.md`.
