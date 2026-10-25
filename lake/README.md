# lake

Evidence store: SQLite + FTS5, local `file://` or S3-compatible raw, pack compiler.

| Module | Role |
|---|---|
| `models.py` | `Evidence` contract |
| `raw_store.py` | `LocalRawStore` (default) / `S3RawStore` (`EVIDPLANE_RAW_BACKEND=s3`) |
| `ingest.py` | `PullRecord[]` → raw + upsert items |
| `api.py` | `search` / `get` / `pack` (serve reads only this) |
| `seed.py` | Fake dogfood data |

Does **not** call platform APIs. OSS layout + ECS path: `docs/deploy-ecs-oss.md`.
