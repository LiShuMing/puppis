# Evidplane

Personal **Evidence lake + MCP** for coding agents: authorized sources → self-owned store → `search` / `get` / `pack(work)`.

- Brand: **Evidplane** · Domain: `evidplane.com` (pending) · Repo codename: `puppis`
- Spec: [docs/SPEC.md](docs/SPEC.md) · Dogfood: [docs/dogfood.md](docs/dogfood.md)
- Modules: `connectors/` · `lake/` · `serve/` (no cross-layer calls)

## Install

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
```

## Quick smoke (no MCP client)

```bash
PYTHONPATH=. .venv/bin/python scripts/smoke_pack.py   # seed → pack(work) + cites
PYTHONPATH=. .venv/bin/python scripts/smoke_lake.py   # search/get/pack asserts
PYTHONPATH=. .venv/bin/python scripts/smoke_mcp.py    # list tools + call pack in-process
```

Default DB: `data/puppis.db` (override with `EVIDPLANE_DB` / `PUPPIS_DB`).

## Cursor MCP (stdio)

Add to `~/.cursor/mcp.json` (or project `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "evidplane": {
      "command": "/ABS/PATH/TO/puppis/.venv/bin/puppis-mcp",
      "args": [],
      "env": {
        "EVIDPLANE_DB": "/ABS/PATH/TO/puppis/data/puppis.db"
      }
    }
  }
}
```

Or without install entry point:

```json
{
  "mcpServers": {
    "evidplane": {
      "command": "/ABS/PATH/TO/puppis/.venv/bin/python",
      "args": ["-m", "serve.mcp_server"],
      "cwd": "/ABS/PATH/TO/puppis",
      "env": {
        "PYTHONPATH": "/ABS/PATH/TO/puppis"
      }
    }
  }
}
```

Tools: `search`, `get`, `pack` (`template=work`), `list_connectors`.

First launch auto-seeds fake calendar/notion/github Evidence if the DB is empty.

Private until dogfood.
