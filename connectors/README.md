# connectors

Each source is a plugin: `pull(since) → PullRecord[]`.

Contract: `connectors/base.py` (`PullRecord`, `Connector`).  
Connectors **must not** import `serve/` or `lake/`.

| Source | Status |
|---|---|
| `notion/` | L0 — REST + fixture (`demo_pull.json`) |
| `calendar/` | L0 sketch — fixture + ICS; Google API stub (TODO OAuth) |
| agentsview / github / x | Phase 1.5+ |

Ingest: `scripts/ingest_notion.py` / `scripts/ingest_calendar.py` → `lake.raw_store` → `lake.ingest`.  
Env list: `docs/connector-env.md`.
