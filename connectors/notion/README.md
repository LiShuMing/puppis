# Notion connector

`pull(since) → PullRecord[]` via Notion REST API (`httpx`), or offline fixture.

## Env (live)

| Var | Required | Notes |
|---|---|---|
| `NOTION_TOKEN` | yes | Internal integration secret — never commit / never log |
| `NOTION_DATABASE_ID` | one of | Query database for pages |
| `NOTION_PAGE_IDS` | one of | Comma-separated page UUIDs |

Share target pages/DBs with the integration in Notion.

## Offline

```bash
PYTHONPATH=. .venv/bin/python scripts/ingest_notion.py --fixture --smoke-pack
```

Fixture: `connectors/notion/demo_pull.json`.

## Boundaries

- Does **not** import `serve/` or call MCP.
- Does **not** write the lake directly — `lake.ingest` + `lake.raw_store` own persistence.
