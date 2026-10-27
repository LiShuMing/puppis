# Notion connector

`pull(since) → PullRecord[]` via Notion REST API (`httpx`), or offline fixture.

## Env (live)

| Var | Required | Notes |
|---|---|---|
| `NOTION_TOKEN` | yes | Internal integration secret — never commit / never log |
| `NOTION_DATABASE_ID` | one of | Query database for pages |
| `NOTION_PAGE_IDS` | one of | Comma-separated page UUIDs (multi-page OK) |
| `NOTION_HTTP_MAX_RETRIES` | no | Retries **after** first attempt on 429/5xx (default `4`) |
| `NOTION_HTTP_RETRY_BASE_SECONDS` | no | Exponential backoff base (default `0.5`) |
| `NOTION_HTTP_RETRY_MAX_SECONDS` | no | Backoff cap (default `8`); honors `Retry-After` when present |

Share target pages/DBs with the integration in Notion.

### Multi-page + per-page errors

`NOTION_PAGE_IDS=id1,id2,id3` pulls each page independently. A single-page HTTP failure
is recorded on `connector.last_errors` (no secrets) and does **not** abort the batch;
successful pages still return. `scripts/ingest_notion.py` writes those into raw `errors/`.

Exit policy for ingest: **0** when ≥1 record ingested (even if some pages failed);
**1** if zero records and there were pull errors; **2** for missing config.

## Offline

```bash
PYTHONPATH=. .venv/bin/python scripts/ingest_notion.py --fixture --smoke-pack
.venv/bin/python scripts/smoke_l0_quality.py   # includes multipage + 429 mock
```

Fixture: `connectors/notion/demo_pull.json` (3 pages).

## Boundaries

- Does **not** import `serve/` or call MCP.
- Does **not** write the lake directly — `lake.ingest` + `lake.raw_store` own persistence.
