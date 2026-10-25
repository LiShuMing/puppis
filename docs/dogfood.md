# Evidplane dogfood — fake Lake + MCP

Brand **Evidplane** · repo `puppis`. This doc covers the D1–2 gate: seeded Evidence → MCP `search` / `get` / `pack` in Cursor.

## Setup

```bash
cd /path/to/puppis
python3 -m venv .venv
.venv/bin/pip install -e .   # or: pip install 'mcp>=1.0' pydantic
```

Optional DB path (default `data/evidplane.db`):

```bash
export EVIDPLANE_DB=/path/to/puppis/data/evidplane.db
```

## Seed + smoke (no Cursor)

```bash
cd /path/to/puppis
PYTHONPATH=. .venv/bin/python -m lake.seed --force
PYTHONPATH=. .venv/bin/python scripts/smoke_lake.py
```

Smoke prints `item_id`s from `search` / `get` / `pack(work)`.

## Run MCP (stdio)

```bash
cd /path/to/puppis
PYTHONPATH=. .venv/bin/python -m serve.mcp_server
```

Or after editable install: `puppis-mcp`.

Empty DB auto-seeds fake calendar/notion items on first tool call.

## Cursor `mcp.json` snippet

User-level `~/.cursor/mcp.json` or project `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "evidplane": {
      "command": "/ABSOLUTE/PATH/to/puppis/.venv/bin/python",
      "args": ["-m", "serve.mcp_server"],
      "cwd": "/ABSOLUTE/PATH/to/puppis",
      "env": {
        "PYTHONPATH": "/ABSOLUTE/PATH/to/puppis",
        "EVIDPLANE_DB": "/ABSOLUTE/PATH/to/puppis/data/evidplane.db"
      }
    }
  }
}
```

Then in Cursor Agent chat: call **pack** with `template=work`, or **search** with `q=standup`.

## Tools

| Tool | Args | Notes |
|---|---|---|
| `search` | `q?`, `source?`, `since_days?`, `limit?` | FTS5 when `q` set |
| `get` | `item_id` | Full text + `source_url` |
| `pack` | `template=work`, `budget_tokens?`, `since_days?` | Cites + token estimate |
| `list_connectors` | — | Stub listing fake seeds |

## Boundaries

- Serve reads **lake only** — never connectors or platform tokens.
- Fake seed ≠ production connector; real Notion/Calendar is the next milestone.
