# lake

Evidence store: SQLite + FTS5, local `file://` or S3-compatible raw, pack compiler.

| Module | Role |
|---|---|
| `models.py` | `Evidence` contract |
| `raw_store.py` | `LocalRawStore` (default) / `S3RawStore` (`EVIDPLANE_RAW_BACKEND=s3`) |
| `ingest.py` | `PullRecord[]` → raw + upsert items |
| `query.py` | Public `search` / `get` / `pack` APIs used by Serve |
| `api.py` | Compatibility re-exports for older callers |
| `seed.py` | Fake dogfood data |

S3/OSS raw storage uses Apache OpenDAL Python (`S3RawStore`, alias `OpenDalRawStore`); the existing `EVIDPLANE_S3_*` / `AWS_*` environment variables remain unchanged.

Does **not** call platform APIs. OSS layout + ECS path: `docs/deploy-ecs-oss.md`.

Contracts:

Current implementation and known integrity gaps are documented in
[architecture](../docs/ARCHITECTURE.md) and the [project review](../docs/reviews/2026-10-28-project-review.md).
New raw versions use item/content hashes and never overwrite an existing version.
DB + raw backup/restore is available; raw-only index replay remains unimplemented.

- **Idempotent ingest** — upsert by `item_id`; repeated pulls report `inserted` / `updated` /
  `unchanged` and never duplicate item rows. Identical content adds no `raw_objects` rows.
- **No silent drops** — a raw-write failure is recorded under
  `sources/<connector>/errors/yyyy/mm/*.json` and raises `IngestError` (with `error_uri`).
- **Pack budget is a hard cap** — `pack_work` trims output so
  `token_estimate <= budget_tokens` (default budget 3000 when unset, see `_DEFAULT_PACK_BUDGET`).
