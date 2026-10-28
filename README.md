# Evidplane

Personal **Evidence lake + MCP** for coding agents: authorized sources → self-owned store → `search` / `get` / `pack(work)`.

- Brand: **Evidplane** · Domain: `evidplane.com` (pending) · Repo codename: `puppis`
- Spec: [docs/SPEC.md](docs/SPEC.md) · Dogfood: [docs/dogfood.md](docs/dogfood.md)
- Modules: `connectors/` · `lake/` · `serve/` (explicit dependency boundaries)

## Local workspace

```bash
.venv/bin/python scripts/workspace.py start
```

Open [Evidplane](http://127.0.0.1:8765): import notes or JSON, search evidence,
inspect sources, and build context packs with citations. MCP shares the same library.
See [local setup, backup and usage](docs/LOCAL_PLATFORM.md).

## Development

Start with [AGENTS.md](AGENTS.md), [architecture](docs/ARCHITECTURE.md), and the
[development workflow](docs/DEVELOPMENT.md). Changes follow **spec → owner confirmation
→ implementation → acceptance checks**; use the [spec index and template](docs/specs/README.md).
The [project review](docs/reviews/2026-10-28-project-review.md) records current gaps.
The [technical roadmap](docs/TECHNICAL_ROADMAP.md) proposes versioned evidence,
context compilation, and bounded Agent workflows; [SPEC-0004](docs/specs/0004-evidence-intelligence-roadmap.md)
is a design draft pending implementation approval.
Run smoke scripts with isolated DB/raw paths as described in the workflow: some seed
scripts replace existing database contents.

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

An empty database stays empty. Import explicitly marked demo data from the local
workspace, or use `python -m lake.seed` with an isolated database for development.

Private until dogfood.
