# Evidplane dogfood — Lake + MCP + Notion ingest

S3/OSS raw storage uses Apache OpenDAL Python (`S3RawStore`, alias `OpenDalRawStore`); the existing `EVIDPLANE_S3_*` / `AWS_*` environment variables remain unchanged.

Brand **Evidplane** · repo `puppis`.

## Setup

```bash
cd /path/to/puppis
python3 -m venv .venv
.venv/bin/pip install -e .
```

Optional paths (defaults shown):

```bash
export EVIDPLANE_DB=/path/to/data.db           # default: data/puppis.db
export EVIDPLANE_RAW_ROOT=~/.evidplane         # raw file:// layout (default ~/.evidplane)
export EVIDPLANE_RAW_BACKEND=local             # local | s3 (S3-compatible, incl. OSS/MinIO)
```

## 1) Fake seed + MCP smoke (no Notion)

```bash
PYTHONPATH=. .venv/bin/python -m lake.seed --force
PYTHONPATH=. .venv/bin/python scripts/smoke_lake.py
PYTHONPATH=. .venv/bin/python scripts/smoke_pack.py
PYTHONPATH=. .venv/bin/python scripts/smoke_mcp.py
PYTHONPATH=. .venv/bin/python -m serve.mcp_server   # stdio
```

Full L0 quality gate (idempotent double ingest, error paths → `errors/`, pack budget, MCP):

```bash
PYTHONPATH=. .venv/bin/python scripts/smoke_l0_quality.py
```

## 2) Notion connector → raw → lake (offline fixture)

No token needed:

```bash
PYTHONPATH=. .venv/bin/python scripts/ingest_notion.py --fixture --smoke-pack
```

Uses `connectors/notion/demo_pull.json`. Raw lands under
`$EVIDPLANE_RAW_ROOT/sources/notion/raw/yyyy/mm/<sha256(item_id)>/<content_sha256>.json` (default `~/.evidplane`).
Ingest is idempotent by `item_id` (re-pull → `inserted/updated/unchanged` stats, no duplicate
rows). On a raw-write failure the error record goes to `sources/<connector>/errors/yyyy/mm/*.json`
and the run fails loudly (`IngestError`), never silently.

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
        "EVIDPLANE_DB": "/ABSOLUTE/PATH/to/puppis/data/puppis.db"
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
| `pack` | `template=work`, `budget_tokens?`, `since_days?` | Cites + token estimate; hard cap: `token_estimate <= budget_tokens` |
| `list_connectors` | — | Actual ingested sources; empty on a fresh library |

## Boundaries

- **connectors** → `PullRecord[]` only (no `serve/`, no lake writes).
- **lake** owns raw (`content_sha256` + `raw_uri`) and SQLite upsert (idempotent by `item_id`;
  write failures recorded under `sources/<connector>/errors/`).
- **pack budget is a hard contract**: `pack_work` trims output so `token_estimate <= budget_tokens`.
- **serve** reads lake only — never Notion tokens.
