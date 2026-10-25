# connectors

Each source is a plugin: `pull(since) → PullRecord[]`.

Contract: `connectors/base.py` (`PullRecord`, `Connector`).  
Connectors **must not** import `serve/` or `lake/`.

| Source | Status |
|---|---|
| `notion/` | L0 — REST + fixture (`demo_pull.json`) |
| `calendar/` | stub (next) |
| agentsview / github / x | Phase 1.5+ |

Ingest path: `scripts/ingest_notion.py` → `lake.raw_store` → `lake.ingest`.
