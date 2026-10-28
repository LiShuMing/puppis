#!/usr/bin/env python3
"""L0 quality smoke: idempotent fixture ingest, error paths, pack budget, MCP tools.

Does not require live Notion / OSS credentials. Uses an isolated temp DB + raw root.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from connectors.notion.adapter import NotionConnector, default_fixture_path  # noqa: E402
from lake.db import connect, init_db  # noqa: E402
from lake.ingest import IngestError, ingest_pull_records  # noqa: E402
from lake.query import get, pack, search  # noqa: E402
from lake.raw_store import LocalRawStore  # noqa: E402
from lake.seed import seed_fake  # noqa: E402


def _count_items(db: Path, *, connector_id: str | None = None) -> int:
    conn = connect(db)
    try:
        init_db(conn)
        if connector_id:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM items WHERE tombstone=0 AND connector_id=?",
                (connector_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM items WHERE tombstone=0"
            ).fetchone()
        return int(row["n"])
    finally:
        conn.close()


def _count_raw_objects(db: Path, *, item_id: str | None = None) -> int:
    conn = connect(db)
    try:
        init_db(conn)
        if item_id:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM raw_objects WHERE item_id=?",
                (item_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS n FROM raw_objects").fetchone()
        return int(row["n"])
    finally:
        conn.close()


class _FailingRawStore(LocalRawStore):
    """Local store that fails write() once errors/ still works."""

    def write(self, connector_id, item_id, payload, *, when=None):  # type: ignore[override]
        raise OSError("simulated raw write failure")


def test_idempotent_fixture(tmp: Path) -> dict:
    db = tmp / "idem.db"
    raw = tmp / "raw_idem"
    store = LocalRawStore(raw)
    connector = NotionConnector(fixture_path=default_fixture_path())
    records = connector.pull()
    assert records, "fixture must yield records"
    r1 = ingest_pull_records(
        records, raw_store=store, source_id="src_notion", db_path=db, config={"mode": "fixture"}
    )
    n1 = _count_items(db, connector_id="notion")
    raw_n1 = _count_raw_objects(db)
    r2 = ingest_pull_records(
        records, raw_store=store, source_id="src_notion", db_path=db, config={"mode": "fixture"}
    )
    n2 = _count_items(db, connector_id="notion")
    raw_n2 = _count_raw_objects(db)
    assert n1 == n2 == len(records), f"idempotent items: {n1=} {n2=} expected {len(records)}"
    assert raw_n1 == raw_n2, f"identical content must not add raw_objects rows: {raw_n1=} {raw_n2=}"
    assert r2.get("unchanged", 0) == len(records), f"second pass should be unchanged: {r2}"

    # Changed content → update same item_id, new content_hash row, still 1 items row.
    # PullRecord is a plain dataclass (not pydantic) — rebuild it with replace().
    first = records[0]
    new_raw = dict(first.raw) if isinstance(first.raw, dict) else {"text": first.text}
    new_raw = {**new_raw, "_smoke_mutate": True}
    changed = dataclasses.replace(
        first,
        text=first.text + "\n# changed for idempotency test",
        raw=new_raw,
    )
    r3 = ingest_pull_records(
        [changed], raw_store=store, source_id="src_notion", db_path=db, config={"mode": "mutate"}
    )
    n3 = _count_items(db, connector_id="notion")
    raw_for_item = _count_raw_objects(db, item_id=first.item_id)
    assert n3 == len(records), f"update must not duplicate item rows: {n3}"
    assert raw_for_item >= 2, "changed content should add a new raw_objects hash row"
    assert r3.get("updated", 0) >= 1

    # Every recorded hash still resolves to its original, independently stored bytes.
    conn = connect(db)
    try:
        rows = conn.execute("SELECT content_hash, uri FROM raw_objects WHERE item_id=?", (first.item_id,)).fetchall()
        assert len({row["uri"] for row in rows}) == len(rows)
        for row in rows:
            assert hashlib.sha256(Path(row["uri"].removeprefix("file://")).read_bytes()).hexdigest() == row["content_hash"]
    finally:
        conn.close()

    return {
        "fixture_records": len(records),
        "items_after_double": n2,
        "raw_objects_after_double": raw_n2,
        "items_after_mutate": n3,
        "raw_objects_for_changed_item": raw_for_item,
        "second_pass_unchanged": r2.get("unchanged"),
        "mutate_updated": r3.get("updated"),
    }


def test_error_paths(tmp: Path) -> dict:
    out: dict = {}

    # 1) missing NOTION_TOKEN → exit 2 + stderr
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT)
    env.pop("NOTION_TOKEN", None)
    env["EVIDPLANE_RAW_ROOT"] = str(tmp / "raw_err_cfg")
    env["EVIDPLANE_DB"] = str(tmp / "err_cfg.db")
    cp = subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "ingest_notion.py")],
        cwd=str(_ROOT),
        env=env,
        text=True,
        capture_output=True,
    )
    assert cp.returncode == 2, f"missing token expected exit 2, got {cp.returncode}: {cp.stderr}"
    assert "NOTION_TOKEN" in cp.stderr
    out["missing_token_exit"] = cp.returncode

    # 2) corrupt fixture → config/pull error + errors/ file + non-zero
    bad = tmp / "bad_fixture.json"
    bad.write_text("{not json", encoding="utf-8")
    raw_root = tmp / "raw_err_fix"
    env2 = os.environ.copy()
    env2["PYTHONPATH"] = str(_ROOT)
    env2["EVIDPLANE_RAW_ROOT"] = str(raw_root)
    env2["EVIDPLANE_DB"] = str(tmp / "err_fix.db")
    cp2 = subprocess.run(
        [
            sys.executable,
            str(_ROOT / "scripts" / "ingest_notion.py"),
            "--fixture",
            str(bad),
        ],
        cwd=str(_ROOT),
        env=env2,
        text=True,
        capture_output=True,
    )
    assert cp2.returncode != 0, "corrupt fixture must fail"
    err_files = list((raw_root / "sources" / "notion" / "errors").rglob("*.json")) if (raw_root / "sources").exists() else []
    assert err_files, f"expected errors/ json, stderr={cp2.stderr!r}"
    out["corrupt_fixture_exit"] = cp2.returncode
    out["corrupt_error_files"] = len(err_files)

    # 3) raw write failure → IngestError + errors/
    db = tmp / "fail_write.db"
    fail_root = tmp / "raw_fail_write"
    store = _FailingRawStore(fail_root)
    connector = NotionConnector(fixture_path=default_fixture_path())
    records = connector.pull()[:1]
    raised = False
    err_uri = None
    try:
        ingest_pull_records(records, raw_store=store, source_id="src_notion", db_path=db)
    except IngestError as e:
        raised = True
        err_uri = e.error_uri
    assert raised, "raw write failure must raise IngestError"
    assert err_uri, "raw write failure must land in errors/"
    assert _count_items(db, connector_id="notion") == 0
    out["raw_write_error_uri_present"] = bool(err_uri)
    return out


def test_pack_budget(tmp: Path) -> dict:
    db = tmp / "pack.db"
    seed_fake(db, force=True)
    results = {}
    for budget in (50, 100, 200, 500, 3000):
        p = pack(template="work", budget_tokens=budget, since_days=30, db_path=str(db))
        est = int(p["token_estimate"])
        assert est <= budget, f"budget {budget} overshot: estimate={est}"
        results[str(budget)] = {"estimate": est, "items": p["item_count"]}
    # Tight budget still returns structured pack
    p50 = pack(template="work", budget_tokens=50, since_days=30, db_path=str(db))
    assert p50["budget_tokens"] == 50
    assert "token_estimate" in p50
    return results


def test_search_get_pack_mcp(tmp: Path) -> dict:
    db = tmp / "flow.db"
    raw = tmp / "raw_flow"
    os.environ["EVIDPLANE_DB"] = str(db)
    os.environ["EVIDPLANE_RAW_ROOT"] = str(raw)
    store = LocalRawStore(raw)
    records = NotionConnector(fixture_path=default_fixture_path()).pull()
    ingest_pull_records(records, raw_store=store, source_id="src_notion", db_path=db)
    s = search(source="notion", since_days=30, limit=10, db_path=str(db))
    assert s["count"] >= 1
    item_id = s["items"][0]["item_id"]
    g = get(item_id, db_path=str(db))
    assert "error" not in g
    assert g.get("source_url") or g.get("url")
    pk = pack(template="work", budget_tokens=800, since_days=30, db_path=str(db))
    assert pk["token_estimate"] <= 800
    assert pk["item_count"] >= 1
    assert all(c.get("item_id") for c in pk["cites"])

    # MCP tools in-process
    import asyncio
    from serve.mcp_server import server

    async def _mcp():
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert {"search", "get", "pack", "list_connectors"} <= names
        result = await server.call_tool(
            "pack", {"template": "work", "budget_tokens": 500, "since_days": 30}
        )
        text = ""
        if hasattr(result, "content"):
            text = "\n".join(getattr(c, "text", None) or str(c) for c in result.content)
        else:
            text = str(result)
        assert "token_estimate" in text or "cites" in text or "Evidplane" in text
        return sorted(names)

    names = asyncio.run(_mcp())
    return {
        "search_count": s["count"],
        "get_item_id": item_id,
        "pack_estimate": pk["token_estimate"],
        "mcp_tools": names,
    }


def test_local_raw_idempotent_put(tmp: Path) -> dict:
    store = LocalRawStore(tmp / "raw_put")
    payload = {"hello": "world", "n": 1}
    sha1, uri1 = store.write("notion", "item_smoke_1", payload)
    sha2, uri2 = store.write("notion", "item_smoke_1", payload)
    assert sha1 == sha2
    assert uri1 == uri2
    # Changed payload is a new version; previous bytes remain available.
    sha3, uri3 = store.write("notion", "item_smoke_1", {**payload, "n": 2})
    assert sha3 != sha1
    assert uri3 != uri1
    assert hashlib.sha256(Path(uri1.removeprefix("file://")).read_bytes()).hexdigest() == sha1
    return {"sha_stable_on_identical": True, "sha_changes_on_update": True}



def _minimal_page_json(page_id: str, title: str = "Smoke page") -> dict:
    return {
        "object": "page",
        "id": page_id,
        "created_time": "2026-10-20T02:00:00.000Z",
        "last_edited_time": "2026-10-25T08:30:00.000Z",
        "url": f"https://www.notion.so/{page_id.replace('-', '')}",
        "properties": {
            "Name": {
                "id": "title",
                "type": "title",
                "title": [
                    {
                        "type": "text",
                        "plain_text": title,
                        "text": {"content": title},
                    }
                ],
            }
        },
    }


def _empty_blocks_json() -> dict:
    return {"object": "list", "results": [], "has_more": False, "next_cursor": None}


def test_multipage_fixture() -> dict:
    connector = NotionConnector(fixture_path=default_fixture_path())
    records = connector.pull()
    assert len(records) == 3, f"demo_pull fixture must yield 3 pages, got {len(records)}"
    assert not connector.last_errors
    ids = {r.item_id for r in records}
    assert len(ids) == 3
    return {"fixture_pages": len(records), "item_ids": sorted(ids)}


def test_per_page_isolation_mock() -> dict:
    """One page 200, one page hard 403 — successes returned, errors in last_errors."""
    import httpx

    page_ok = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeee1"
    page_bad = "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeee2"
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        path = request.url.path
        if path.endswith(f"/pages/{page_ok}"):
            return httpx.Response(200, json=_minimal_page_json(page_ok, "OK page"))
        if path.endswith(f"/pages/{page_bad}"):
            return httpx.Response(403, json={"message": "forbidden"})
        if "/blocks/" in path and path.endswith("/children"):
            return httpx.Response(200, json=_empty_blocks_json())
        return httpx.Response(404, json={"message": "unexpected"})

    sleeps: list[float] = []
    connector = NotionConnector(
        token="secret_test_token_not_real",
        page_ids=[page_ok, page_bad],
        max_retries=0,  # no retry on 403
        sleep=lambda d: sleeps.append(d),
        transport=httpx.MockTransport(handler),
    )
    records = connector.pull()
    assert len(records) == 1, f"expected 1 success, got {len(records)}: {records}"
    assert records[0].item_id == "notion_pg_aaaaaaaabbbbccccddddeeeeeeeeeee1"
    assert len(connector.last_errors) == 1
    err = connector.last_errors[0]
    assert err.get("status") == 403
    assert err.get("page_id_last4") == "eee2"
    # 403 must not burn retries / sleep
    assert sleeps == []
    return {
        "records": len(records),
        "errors": len(connector.last_errors),
        "error_status": err.get("status"),
        "http_calls": len(calls),
    }


def test_retry_on_429_mock() -> dict:
    """First get_page returns 429 (+ Retry-After), then 200 — pull succeeds after retry."""
    import httpx

    page_id = "cccccccc-bbbb-cccc-dddd-eeeeeeeeeee3"
    hits = {"pages": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith(f"/pages/{page_id}"):
            hits["pages"] += 1
            if hits["pages"] == 1:
                return httpx.Response(
                    429,
                    headers={"Retry-After": "0"},
                    json={"message": "rate limited"},
                )
            return httpx.Response(200, json=_minimal_page_json(page_id, "After retry"))
        if "/blocks/" in path and path.endswith("/children"):
            return httpx.Response(200, json=_empty_blocks_json())
        return httpx.Response(404, json={"message": "unexpected"})

    sleeps: list[float] = []
    connector = NotionConnector(
        token="secret_test_token_not_real",
        page_ids=[page_id],
        max_retries=3,
        retry_base_seconds=0.5,
        retry_max_seconds=8.0,
        sleep=lambda d: sleeps.append(d),
        transport=httpx.MockTransport(handler),
    )
    records = connector.pull()
    assert len(records) == 1, f"expected success after 429 retry, got {records}"
    assert not connector.last_errors
    assert hits["pages"] >= 2, f"expected retry, page hits={hits['pages']}"
    assert connector.last_http_attempts >= 2
    assert sleeps, "expected sleep on 429 retry"
    assert sleeps[0] == 0.0, f"Retry-After:0 should yield 0 delay, got {sleeps[0]}"
    return {
        "records": len(records),
        "page_hits": hits["pages"],
        "http_attempts": connector.last_http_attempts,
        "sleeps": sleeps,
    }


def test_retry_exhausted_5xx_then_isolate() -> dict:
    """Page A always 503 → error after retries; page B 200 → still returned."""
    import httpx

    page_a = "dddddddd-bbbb-cccc-dddd-eeeeeeeeeee4"
    page_b = "eeeeeeee-bbbb-cccc-dddd-eeeeeeeeeee5"
    hits_a = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith(f"/pages/{page_a}"):
            hits_a["n"] += 1
            return httpx.Response(503, json={"message": "unavailable"})
        if path.endswith(f"/pages/{page_b}"):
            return httpx.Response(200, json=_minimal_page_json(page_b, "Survivor"))
        if "/blocks/" in path and path.endswith("/children"):
            return httpx.Response(200, json=_empty_blocks_json())
        return httpx.Response(404, json={"message": "unexpected"})

    sleeps: list[float] = []
    connector = NotionConnector(
        token="secret_test_token_not_real",
        page_ids=[page_a, page_b],
        max_retries=2,  # 3 total attempts on A
        retry_base_seconds=0.01,
        retry_max_seconds=0.05,
        sleep=lambda d: sleeps.append(d),
        transport=httpx.MockTransport(handler),
    )
    records = connector.pull()
    assert len(records) == 1
    assert "Survivor" in (records[0].title or "")
    assert len(connector.last_errors) == 1
    assert connector.last_errors[0].get("status") == 503
    assert hits_a["n"] == 3, f"expected 1+2 retries, got {hits_a['n']}"
    assert len(sleeps) == 2
    return {
        "records": len(records),
        "errors": len(connector.last_errors),
        "page_a_hits": hits_a["n"],
        "sleeps": len(sleeps),
    }



def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="evidplane_l0q_"))
    report: dict = {"tmp": str(tmp)}
    try:
        print("=== 1) LocalRawStore idempotent put ===")
        report["raw_put"] = test_local_raw_idempotent_put(tmp)
        print(json.dumps(report["raw_put"], indent=2))

        print("\n=== 2) Idempotent fixture ingest ===")
        report["idempotent"] = test_idempotent_fixture(tmp)
        print(json.dumps(report["idempotent"], indent=2))

        print("\n=== 3) Error paths ===")
        report["errors"] = test_error_paths(tmp)
        print(json.dumps(report["errors"], indent=2))

        print("\n=== 4) pack budget hard cap ===")
        report["pack_budget"] = test_pack_budget(tmp)
        print(json.dumps(report["pack_budget"], indent=2))

        print("\n=== 5) search/get/pack + MCP ===")
        report["flow"] = test_search_get_pack_mcp(tmp)
        print(json.dumps(report["flow"], indent=2))

        print("\n=== 6) multipage fixture (3 pages) ===")
        report["multipage_fixture"] = test_multipage_fixture()
        print(json.dumps(report["multipage_fixture"], indent=2))

        print("\n=== 7) per-page isolation (mock) ===")
        report["per_page_isolation"] = test_per_page_isolation_mock()
        print(json.dumps(report["per_page_isolation"], indent=2))

        print("\n=== 8) retry on 429 (mock) ===")
        report["retry_429"] = test_retry_on_429_mock()
        print(json.dumps(report["retry_429"], indent=2))

        print("\n=== 9) 5xx retries then isolate (mock) ===")
        report["retry_5xx_isolate"] = test_retry_exhausted_5xx_then_isolate()
        print(json.dumps(report["retry_5xx_isolate"], indent=2))

        print("\nSMOKE_L0_QUALITY OK")
        return 0
    except Exception as exc:
        print(f"SMOKE_L0_QUALITY FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
    finally:
        # Keep tmp on failure for debug; wipe on success
        if report.get("flow"):
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
