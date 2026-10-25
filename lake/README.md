# lake

Raw immutable store + rebuildable derived + FTS5 index + `pack(template)`.

- `schema.sql` — sources / raw_objects / items / items_fts
- `db.py` — SQLite connect + init (`EVIDPLANE_DB` or `data/evidplane.db`)
- `api.py` — `search` / `get` / `pack` (Serve calls these only)
- `seed.py` — fake calendar/notion Evidence for dogfood
- `models.py` — Evidence pydantic contract (connectors → lake)

Does not call platform APIs.
