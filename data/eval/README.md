# Evidplane eval corpus + baselines

Frozen dogfood Notion fixture for SPEC §6.2 recall comparisons.

## Layout

- `corpus/` — frozen pages + `manifest.json` (stable `item_id` + `source_url`)
- `queries.json` — shared labeled query set
- `results/` — per-backend baseline JSON/MD
- `workdir/` — local SQLite/raw for runs (gitignored)

## FTS5 baseline (阿里云)

```bash
PYTHONPATH=. .venv/bin/python scripts/eval_recall_baseline.py
```

Offline; no `NOTION_TOKEN`.

## Adapter plug-in (Noa / 技术)

Implement `search(q)->[{item_id,source_url,...}]` over the same `data/eval/corpus/` + `data/eval/queries.json`, then write `data/eval/results/<name>-baseline.{json,md}`. Do not change query IDs or expected `item_id`s when comparing.
