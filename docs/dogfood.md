# Evidplane dogfood — Lake + MCP + Notion ingest

Brand **Evidplane** · repo `puppis`.

## Setup

```bash
cd /path/to/puppis
python3 -m venv .venv
.venv/bin/pip install -e .
```

Optional paths:

```bash
export EVIDPLANE_DB=/path/to/puppis/data/evidplane.db
export EVIDPLANE_RAW_ROOT=~/.evidplane          # raw file:// layout
```

## 1) Fake seed + MCP smoke (no Notion)

```bash
PYTHONPATH=. .venv/bin/python -m lake.seed --force
PYTHONPATH=. .venv/bin/python scripts/smoke_lake.py
PYTHONPATH=. .venv/bin/python -m serve.mcp_server   # stdio
```

## 2) Notion connector → raw → lake (offline fixture)

No token needed:

```bash
PYTHONPATH=. .venv/bin/python scripts/ingest_notion.py --fixture --smoke-pack
```

Uses `connectors/notion/demo_pull.json`. Raw lands under
`$EVIDPLANE_RAW_ROOT/sources/notion/raw/yyyy/mm/<item_id>.json` (default `~/.evidplane`).

## 3) Notion live pull (optional)

Create a Notion internal integration, share a database or pages with it, then:

```bash
export NOTION_TOKEN=***  # integration secret          # never commit / never paste into chat logs
export NOTION_DATABASE_ID=...        # and/or:
export NOTION_PAGE_IDS=uuid1,uuid2

PYTHONPATH=. .venv/bin/python scripts/ingest_notion.py --since 30d --smoke-pack
```

If `NOTION_TOKEN` is missing, the script exits with a clear config error (use `--fixture`).

## Cursor `mcp.json`

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

After Notion ingest, in Cursor: **search** `source=notion`, **pack** `template=work`, **get** a cited `item_id`.

## Tools

| Tool | Args | Notes |
|---|---|---|
| `search` | `q?`, `source?`, `since_days?`, `limit?` | FTS5 when `q` set |
| `get` | `item_id` | Full text + `source_url` |
| `pack` | `template=work`, `budget_tokens?`, `since_days?` | Cites + token estimate |
| `list_connectors` | — | Stub listing |

## Boundaries

- **connectors** → `PullRecord[]` only (no `serve/`, no lake writes).
- **lake** owns raw (`content_sha256` + `raw_uri`) and SQLite upsert.
- **serve** reads lake only — never Notion tokens.
