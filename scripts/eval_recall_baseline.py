#!/usr/bin/env python3
"""FTS5 recall baseline over frozen dogfood Notion fixture (offline, no token).

Shared interface for later adapters (Noa/技术):
  same `data/eval/queries.json` + `data/eval/corpus/` → ranked item_ids;
  write sibling results under `data/eval/results/<backend>-baseline.{json,md}`.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from connectors.notion.adapter import NotionConnector  # noqa: E402
from lake.api import get, search  # noqa: E402
from lake.ingest import ingest_pull_records  # noqa: E402
from lake.raw_store import LocalRawStore  # noqa: E402

_SH_TZ = timezone(timedelta(hours=8))
_DEFAULT_QUERIES = _ROOT / "data" / "eval" / "queries.json"
_DEFAULT_CORPUS = _ROOT / "data" / "eval" / "corpus" / "notion_demo_pull.json"
_DEFAULT_RESULTS_DIR = _ROOT / "data" / "eval" / "results"
_DEFAULT_WORK = _ROOT / "data" / "eval" / "workdir"


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def _hit_at_k(ranked: list[str], expected: list[str], k: int) -> float | None:
    """1.0 if any expected id appears in top-k; None if expected is empty (negatives)."""
    if not expected:
        return None
    top = set(ranked[:k])
    return 1.0 if top.intersection(expected) else 0.0


def _ensure_ingest(
    *,
    fixture: Path,
    db_path: Path,
    raw_root: Path,
    force: bool,
) -> dict[str, Any]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    if db_path.exists() and not force:
        # Cheap freshness: skip re-ingest if db already has notion rows.
        from lake.db import connect, init_db

        conn = connect(db_path)
        try:
            init_db(conn)
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM items WHERE connector_id='notion' AND tombstone=0"
            ).fetchone()["c"]
        finally:
            conn.close()
        if n > 0:
            return {"skipped": True, "db": str(db_path), "notion_items": n}

    connector = NotionConnector(fixture_path=str(fixture))
    records = connector.pull()
    store = LocalRawStore(raw_root)
    result = ingest_pull_records(
        records,
        raw_store=store,
        source_id="src_notion_eval",
        db_path=str(db_path),
        config={"mode": "eval_fixture", "fixture": str(fixture)},
    )
    result["skipped"] = False
    return result


def _run_queries(
    queries: list[dict[str, Any]],
    *,
    db_path: str,
    k_values: list[int],
    repeats: int,
    limit: int,
) -> dict[str, Any]:
    per_query: list[dict[str, Any]] = []
    all_lat_ms: list[float] = []
    hit_sums: dict[int, list[float]] = {k: [] for k in k_values}
    provenance_ok_total = 0
    provenance_checked = 0
    negative_empty_ok = 0
    negative_total = 0

    for qspec in queries:
        qid = qspec["id"]
        q = qspec["q"]
        expected = list(qspec.get("expected_item_ids") or [])
        latencies: list[float] = []
        last_items: list[dict[str, Any]] = []
        for _ in range(max(1, repeats)):
            t0 = time.perf_counter()
            out = search(q=q, source="notion", limit=limit, db_path=db_path)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            latencies.append(dt_ms)
            all_lat_ms.append(dt_ms)
            last_items = list(out.get("items") or [])

        ranked_ids = [it.get("item_id") for it in last_items if it.get("item_id")]
        # Provenance: every hit must have item_id + source_url (search returns url field).
        prov_ok = True
        for it in last_items:
            provenance_checked += 1
            has_id = bool(it.get("item_id"))
            # lake.api.search exposes source_url as "url"
            src = it.get("source_url") or it.get("url")
            has_url = bool(src)
            if has_id and has_url:
                provenance_ok_total += 1
            else:
                prov_ok = False
            # Cross-check get() also returns source_url when item_id present.
            if has_id:
                detail = get(str(it["item_id"]), db_path=db_path)
                if detail.get("error") or not detail.get("source_url"):
                    prov_ok = False

        hits: dict[str, float | None] = {}
        for k in k_values:
            h = _hit_at_k([str(x) for x in ranked_ids], expected, k)
            hits[f"hit@{k}"] = h
            if h is not None:
                hit_sums[k].append(h)

        if not expected:
            negative_total += 1
            if len(ranked_ids) == 0:
                negative_empty_ok += 1

        lat_sorted = sorted(latencies)
        per_query.append(
            {
                "id": qid,
                "q": q,
                "expected_item_ids": expected,
                "ranked_item_ids": ranked_ids,
                "latency_ms": {
                    "p50": round(_percentile(lat_sorted, 50), 3),
                    "p95": round(_percentile(lat_sorted, 95), 3),
                    "mean": round(statistics.fmean(latencies), 3),
                    "n": len(latencies),
                },
                "hits": hits,
                "provenance_ok": prov_ok,
                "notes": qspec.get("notes"),
            }
        )

    all_sorted = sorted(all_lat_ms)
    summary = {
        "backend": "sqlite-fts5",
        "query_count": len(queries),
        "labeled_query_count": sum(1 for q in queries if q.get("expected_item_ids")),
        "negative_query_count": negative_total,
        "latency_ms": {
            "p50": round(_percentile(all_sorted, 50), 3),
            "p95": round(_percentile(all_sorted, 95), 3),
            "mean": round(statistics.fmean(all_lat_ms), 3) if all_lat_ms else 0.0,
            "n": len(all_lat_ms),
        },
        "hit_at_k": {
            f"hit@{k}": round(statistics.fmean(vals), 4) if vals else None
            for k, vals in sorted(hit_sums.items())
        },
        "provenance": {
            "hits_with_item_id_and_source_url": provenance_ok_total,
            "hits_checked": provenance_checked,
            "rate": (
                round(provenance_ok_total / provenance_checked, 4)
                if provenance_checked
                else None
            ),
            "all_queries_provenance_ok": all(r["provenance_ok"] for r in per_query),
        },
        "negatives": {
            "empty_result_ok": negative_empty_ok,
            "total": negative_total,
        },
    }
    return {"summary": summary, "queries": per_query}


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    s = payload["summary"]
    lines = [
        "# FTS5 recall baseline",
        "",
        f"- Generated: `{payload['generated_at']}` (Asia/Shanghai)",
        f"- Backend: `{s['backend']}`",
        f"- Corpus: `{payload['corpus']}`",
        f"- Queries: `{payload['queries_path']}` ({s['query_count']} total)",
        f"- DB: `{payload['db']}`",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| search latency p50 (ms) | {s['latency_ms']['p50']} |",
        f"| search latency p95 (ms) | {s['latency_ms']['p95']} |",
        f"| search latency mean (ms) | {s['latency_ms']['mean']} |",
    ]
    for k, v in s["hit_at_k"].items():
        lines.append(f"| {k} (labeled) | {v if v is not None else 'n/a'} |")
    prov = s["provenance"]
    lines.extend(
        [
            f"| provenance rate (item_id+source_url) | {prov['rate']} |",
            f"| all queries provenance ok | {prov['all_queries_provenance_ok']} |",
            f"| negatives empty-ok | {s['negatives']['empty_result_ok']}/{s['negatives']['total']} |",
            "",
            "## Adapter plug-in (one line)",
            "",
            payload["adapter_oneline"],
            "",
            "## Per-query",
            "",
            "| id | q | hit@1 | hit@3 | ranked | provenance |",
            "|---|---|---|---|---|---|",
        ]
    )
    for r in payload["queries"]:
        h = r["hits"]
        ranked = ", ".join(r["ranked_item_ids"][:3]) or "(none)"
        lines.append(
            f"| {r['id']} | {r['q']} | {h.get('hit@1')} | {h.get('hit@3')} | "
            f"`{ranked}` | {r['provenance_ok']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Evidplane FTS5 recall baseline (offline)")
    p.add_argument("--queries", type=Path, default=_DEFAULT_QUERIES)
    p.add_argument("--fixture", type=Path, default=_DEFAULT_CORPUS)
    p.add_argument(
        "--db",
        type=Path,
        default=_DEFAULT_WORK / "fts5-baseline.db",
        help="Eval SQLite path (isolated from dogfood db)",
    )
    p.add_argument(
        "--raw-root",
        type=Path,
        default=_DEFAULT_WORK / "raw",
        help="Eval raw store root",
    )
    p.add_argument("--results-dir", type=Path, default=_DEFAULT_RESULTS_DIR)
    p.add_argument("--repeats", type=int, default=5, help="Timed search repeats per query")
    p.add_argument("--limit", type=int, default=10, help="search limit / max rank depth")
    p.add_argument("--force-ingest", action="store_true")
    args = p.parse_args()

    if not args.fixture.is_file():
        print(f"missing corpus fixture: {args.fixture}", file=sys.stderr)
        return 2
    if not args.queries.is_file():
        print(f"missing queries: {args.queries}", file=sys.stderr)
        return 2

    qdoc = json.loads(args.queries.read_text(encoding="utf-8"))
    queries = list(qdoc.get("queries") or [])
    k_values = [int(x) for x in (qdoc.get("k_values") or [1, 3, 5])]

    ingest_info = _ensure_ingest(
        fixture=args.fixture,
        db_path=args.db,
        raw_root=args.raw_root,
        force=args.force_ingest,
    )

    run = _run_queries(
        queries,
        db_path=str(args.db),
        k_values=k_values,
        repeats=args.repeats,
        limit=args.limit,
    )

    adapter_oneline = (
        "Adapter plug-in: implement `search(q)->[{item_id,source_url,...}]` over the same "
        "`data/eval/corpus/` + `data/eval/queries.json`, then drop results beside "
        "`data/eval/results/<name>-baseline.{json,md}` (Noa/技术 own Mem0/Letta/LightRAG)."
    )

    generated_at = datetime.now(_SH_TZ).isoformat()
    payload: dict[str, Any] = {
        "generated_at": generated_at,
        "backend": "sqlite-fts5",
        "repo_commit": _git_head(),
        "corpus": str(args.fixture.relative_to(_ROOT))
        if args.fixture.is_relative_to(_ROOT)
        else str(args.fixture),
        "queries_path": str(args.queries.relative_to(_ROOT))
        if args.queries.is_relative_to(_ROOT)
        else str(args.queries),
        "db": str(args.db),
        "ingest": {
            "skipped": ingest_info.get("skipped"),
            "upserted": ingest_info.get("upserted"),
            "notion_items": ingest_info.get("notion_items"),
        },
        "adapter_oneline": adapter_oneline,
        "summary": run["summary"],
        "queries": run["queries"],
    }

    args.results_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.results_dir / "fts5-baseline.json"
    md_path = args.results_dir / "fts5-baseline.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_markdown(md_path, payload)

    s = payload["summary"]
    print("=== FTS5 baseline summary ===")
    print(
        json.dumps(
            {
                "latency_ms_p50": s["latency_ms"]["p50"],
                "latency_ms_p95": s["latency_ms"]["p95"],
                "hit_at_k": s["hit_at_k"],
                "provenance_rate": s["provenance"]["rate"],
                "json": str(json_path),
                "md": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _git_head() -> str | None:
    try:
        import subprocess

        out = subprocess.check_output(
            ["git", "-C", str(_ROOT), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
