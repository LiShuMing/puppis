# Evidplane

Personal **Evidence lake + MCP** for coding agents: authorized sources → self-owned store → `search` / `get` / `pack(work)`.

- Brand: **Evidplane** · Domain: `evidplane.com` (pending) · Repo codename: `puppis`
- Spec: [docs/SPEC.md](docs/SPEC.md) · Dogfood: [docs/dogfood.md](docs/dogfood.md)
- Modules: `connectors/` · `lake/` · `serve/` (no cross-layer calls)

## Quick smoke

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
PYTHONPATH=. .venv/bin/python scripts/smoke_lake.py
PYTHONPATH=. .venv/bin/python scripts/ingest_notion.py --fixture --smoke-pack
PYTHONPATH=. .venv/bin/python -m serve.mcp_server   # stdio MCP for Cursor
```

Private until dogfood.
