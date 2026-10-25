# lake

Evidence store: SQLite + FTS5, local `file://` raw layout, pack compiler.

| Module | Role |
|---|---|
| `models.py` | `Evidence` contract |
| `raw_store.py` | Write immutable raw JSON (`content_sha256`, `file://` uri) |
| `ingest.py` | `PullRecord[]` → raw + upsert items |
| `api.py` | `search` / `get` / `pack` (serve reads only this) |
| `seed.py` | Fake dogfood data |

Does **not** call platform APIs.
