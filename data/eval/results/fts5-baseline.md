# FTS5 recall baseline

- Generated: `2026-10-25T22:01:28.581896+08:00` (Asia/Shanghai)
- Backend: `sqlite-fts5`
- Corpus: `data/eval/corpus/notion_demo_pull.json`
- Queries: `data/eval/queries.json` (15 total)
- DB: `/workspace/puppis/data/eval/workdir/fts5-baseline.db`

## Summary

| Metric | Value |
|---|---|
| search latency p50 (ms) | 0.298 |
| search latency p95 (ms) | 0.647 |
| search latency mean (ms) | 0.354 |
| hit@1 (labeled) | 1.0 |
| hit@3 (labeled) | 1.0 |
| hit@5 (labeled) | 1.0 |
| provenance rate (item_id+source_url) | 1.0 |
| all queries provenance ok | True |
| negatives empty-ok | 1/1 |

## Adapter plug-in (one line)

Adapter plug-in: implement `search(q)->[{item_id,source_url,...}]` over the same `data/eval/corpus/` + `data/eval/queries.json`, then drop results beside `data/eval/results/<name>-baseline.{json,md}` (Noa/技术 own Mem0/Letta/LightRAG).

## Per-query

| id | q | hit@1 | hit@3 | ranked | provenance |
|---|---|---|---|---|---|
| q01 | Evidplane checklist | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee1` | True |
| q02 | Topic Plane OSS buckets | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee1` | True |
| q03 | Calendar connector | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee1` | True |
| q04 | pack budget tokens | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee2` | True |
| q05 | source_url item_id | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee2` | True |
| q06 | human_reviewed agent_derived | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee2` | True |
| q07 | 4000 tokens | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee2` | True |
| q08 | MVP non-goals | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee3` | True |
| q09 | vector search AgentsView | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee3` | True |
| q10 | GitHub multi-tenant SaaS | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee3` | True |
| q11 | Connector pull lake upsert | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee1` | True |
| q12 | Truncate older items | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee2` | True |
| q13 | polished console UI | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee3` | True |
| q14 | dbradar | 1.0 | 1.0 | `notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee1` | True |
| q15 | quantum cryptography blockchain | None | None | `(none)` | True |

