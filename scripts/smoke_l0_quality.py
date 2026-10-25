#!/usr/bin/env python3
"""L0 quality smoke: idempotent fixture ingest, error paths, pack budget, MCP tools.

Does not require live Notion / OSS credentials. Uses an isolated temp DB + raw root.
"""
from __future__ import annotations

import dataclasses
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

    # Local raw path stable (same item_id path) with new digest written.
    # item_id may contain '/' — the store sanitizes it for the filename.
    safe = first.item_id.replace("/", "_")
    raw_files = list((raw / "sources" / "notion" / "raw").rglob(f"{safe}.json"))
    assert len(raw_files) == 1, f"raw file should stay single path per item_id, got {raw_files}"

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
    # changed payload overwrites same path, new sha
    sha3, uri3 = store.write("notion", "item_smoke_1", {**payload, "n": 2})
    assert sha3 != sha1
    assert uri3 == uri1
    return {"sha_stable_on_identical": True, "sha_changes_on_update": True}


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
