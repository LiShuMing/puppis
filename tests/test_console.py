import dataclasses
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from connectors.base import PullRecord
from console.server import create_app
from console.service import Service
from lake.db import connect, init_db
from lake.ingest import ingest_pull_records
from lake.query import get
from lake.raw_store import LocalRawStore

ORIGIN = {"Origin": "http://localhost"}


@pytest.fixture
def workspace(tmp_path):
    service = Service(tmp_path / "evidence.db", LocalRawStore(tmp_path / "raw"))
    with TestClient(create_app(service), base_url="http://localhost") as client:
        yield client, service


def post(client, action, payload):
    return client.post(f"/api/{action}", json=payload, headers=ORIGIN)


def test_empty_library_never_seeds_and_persists_after_restart(workspace):
    client, service = workspace
    assert client.get("/api/status").json()["total"] == 0
    assert client.get("/api/search").json()["items"] == []
    assert client.get("/api/pack").json()["cites"] == []
    note = {
        "title": "交付记录",
        "text": "Milestone: deliver local evidence workspace",
        "url": "https://example.com/record",
    }
    first = post(client, "import-text", note).json()
    assert first["inserted"] == 1
    assert post(client, "import-text", note).json()["unchanged"] == 1
    found = client.get("/api/search?q=Milestone&source=manual").json()
    assert found["total"] == 1
    item = client.get("/api/item", params={"id": first["item_id"]}).json()
    assert item["text"] == note["text"]
    assert item["source_url"] == note["url"]
    assert item["provenance"] == {"source": "export", "human_reviewed": False}
    assert (
        hashlib.sha256(
            Path(item["raw_uri"].removeprefix("file://")).read_bytes()
        ).hexdigest()
        == item["content_sha256"]
    )
    with TestClient(
        create_app(Service(service.db_path, service.store)), base_url="http://localhost"
    ) as restarted:
        assert restarted.get("/api/status").json()["total"] == 1
        pack = restarted.get("/api/pack?budget=200").json()
        assert pack["token_estimate"] <= 200
        assert pack["cites"][0]["item_id"] == first["item_id"]
        assert (
            restarted.get(
                "/api/item", params={"id": pack["cites"][0]["item_id"]}
            ).status_code
            == 200
        )


def test_mcp_uses_same_db_without_automatic_demo(workspace, monkeypatch):
    client, service = workspace
    monkeypatch.setenv("EVIDPLANE_DB", service.db_path)
    from serve.mcp_server import get as mcp_get
    from serve.mcp_server import pack as mcp_pack
    from serve.mcp_server import search as mcp_search

    assert json.loads(mcp_search())["count"] == 0
    created = post(
        client, "import-text", {"title": "MCP shared", "text": "shared evidence"}
    ).json()
    assert json.loads(mcp_get(created["item_id"]))["text"] == "shared evidence"
    assert json.loads(mcp_pack())["item_count"] == 1


def test_demo_is_explicit_labeled_and_idempotent(workspace):
    client, _ = workspace
    assert post(client, "import-demo", {}).json()["inserted"] == 3
    assert post(client, "import-demo", {}).json()["unchanged"] == 3
    assert client.get("/api/status").json()["demo_count"] == 3
    items = client.get("/api/search").json()["items"]
    assert all(item["demo"] for item in items)
    assert all(cite["demo"] for cite in client.get("/api/pack").json()["cites"])


def test_partial_notion_sync_reports_failure_without_losing_success(workspace, monkeypatch):
    client, service = workspace
    from console import service as service_module

    record = PullRecord(
        item_id="notion_success", connector_id="notion", kind="page", title="Successful page",
        text="success", url="https://www.notion.so/success", captured_at="2026-10-28T00:00:00Z", raw={"id": "success"},
    )

    class PartialConnector:
        last_errors = [{"stage": "list_blocks", "status": 403, "error": "HTTPStatusError", "page_id_last4": "abcd", "message": "private upstream detail"}]

        def health(self):
            return {"ok": True}

        def pull(self):
            return [record]

    monkeypatch.setattr(service_module, "NotionConnector", PartialConnector)
    result = post(client, "sync-notion", {}).json()
    assert result["partial"] and result["failed"] == 1 and result["inserted"] == 1
    assert service.get(record.item_id)["text"] == "success"
    errors = list(Path(service.store.root).rglob("errors/**/*.json"))
    assert len(errors) == 1
    assert "private upstream detail" not in errors[0].read_text()


def test_file_import_cannot_replace_live_source(workspace):
    client, service = workspace
    payload = {"pages": [{"id": "p1", "properties": {}, "blocks": []}]}
    assert post(client, "import-file", payload).json()["inserted"] == 1
    item = service.search()["items"][0]
    assert item["item_id"] == "import_notion_pg_p1"
    assert service.get(item["item_id"])["provenance"]["source"] == "export"


def test_input_failures_and_no_secret_exposure(workspace, monkeypatch):
    client, _ = workspace
    monkeypatch.setenv("NOTION_TOKEN", "DO-NOT-LEAK-THIS-TOKEN")
    monkeypatch.delenv("NOTION_DATABASE_ID", raising=False)
    monkeypatch.delenv("NOTION_PAGE_IDS", raising=False)
    assert "DO-NOT-LEAK" not in client.get("/api/status").text
    response = post(client, "sync-notion", {})
    assert response.status_code == 400
    assert "NOTION_TOKEN" in response.json()["error"]
    assert "DO-NOT-LEAK" not in response.text
    for endpoint in [
        "pack?budget=0",
        "pack?budget=-1",
        "pack?days=no",
        "pack?days=-7",
        "search?offset=-1",
    ]:
        assert client.get("/api/" + endpoint).status_code == 400
    assert client.get("/api/item?id=missing").status_code == 404
    assert (
        post(client, "import-text", {"title": "empty", "text": "   "}).status_code
        == 400
    )
    assert (
        post(
            client,
            "import-text",
            {"title": "x", "text": "x", "url": "javascript:alert(1)"},
        ).status_code
        == 400
    )
    assert post(client, "import-file", {"pages": [{"blocks": []}]}).status_code == 400
    assert post(client, "import-file", {"pages": [{}] * 101}).status_code == 400
    assert (
        client.post(
            "/api/import-file",
            content=b"x" * (2 * 1024 * 1024 + 1),
            headers={**ORIGIN, "Content-Type": "application/json"},
        ).status_code
        == 413
    )


def test_local_write_boundary_and_html_are_not_executable(workspace):
    client, _ = workspace
    note = {"title": "<script>title</script>", "text": "<img src=x onerror=alert(1)>"}
    assert client.post("/api/import-text", json=note).status_code == 403
    assert (
        client.post(
            "/api/import-text", json=note, headers={"Origin": "https://other.example"}
        ).status_code
        == 403
    )
    assert (
        client.post("/api/import-text", content="{}", headers=ORIGIN).status_code == 415
    )
    assert (
        client.get("/api/status", headers={"Host": "attacker.example"}).status_code
        == 400
    )
    created = post(client, "import-text", note)
    assert created.status_code == 200
    assert (
        client.get("/")
        .headers["content-security-policy"]
        .startswith("default-src 'self'")
    )
    assert "<script>title" not in client.get("/").text
    assert (
        client.get("/api/item", params={"id": created.json()["item_id"]}).json()["text"]
        == note["text"]
    )


def test_provenance_effective_dates_and_version_history(tmp_path):
    db = tmp_path / "library.db"
    store = LocalRawStore(tmp_path / "raw")
    rec = PullRecord(
        item_id="a/b",
        connector_id="manual",
        kind="note",
        title="hello",
        url=None,
        captured_at="2026-10-28T08:00:00+00:00",
        text="old",
        raw={"v": 1},
        provenance={"source": "agent", "human_reviewed": True, "reviewer": "owner"},
        valid_from="2026-10-20T00:00:00+00:00",
        valid_to="2026-10-30T00:00:00+00:00",
    )
    ingest_pull_records([rec], raw_store=store, db_path=db)
    ingest_pull_records(
        [dataclasses.replace(rec, text="new", raw={"v": 2})],
        raw_store=store,
        db_path=db,
    )
    item = get(rec.item_id, db_path=str(db))
    assert item["provenance"] == rec.provenance
    assert item["valid_from"] == rec.valid_from
    assert item["valid_to"] == rec.valid_to
    assert item["trust_level"] == 1
    with connect(db) as conn:
        rows = conn.execute("SELECT content_hash, uri FROM raw_objects").fetchall()
    assert len(rows) == len({row["uri"] for row in rows}) == 2
    for row in rows:
        assert (
            hashlib.sha256(
                Path(row["uri"].removeprefix("file://")).read_bytes()
            ).hexdigest()
            == row["content_hash"]
        )


def test_local_atomic_concurrent_writes_aliases_and_corruption(tmp_path):
    store = LocalRawStore(tmp_path)
    when = datetime(2026, 10, 28, tzinfo=UTC)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: store.write("manual", "a/b", {"value": 1}, when=when),
                range(30),
            )
        )
    assert len(set(results)) == 1
    _, alias = store.write("manual", "a_b", {"value": 1}, when=when)
    assert alias != results[0][1]
    _, long_id = store.write("manual", "中文" * 1000, {"v": 1}, when=when)
    assert Path(long_id.removeprefix("file://")).is_file()
    path = Path(results[0][1].removeprefix("file://"))
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="verification"):
        store.write("manual", "a/b", {"value": 1}, when=when)
    assert path.read_bytes() == b"corrupt"


def test_existing_schema_migrates_without_losing_evidence(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(Path("lake/schema.sql").read_text())
        conn.execute(
            "INSERT INTO items(item_id,source_id,connector_id,kind,title,body,captured_at,ingested_at) VALUES('old','src_old','notion','page','Old','keep me','2026-10-20T00:00:00Z','2026-10-20T00:00:00Z')"
        )
    conn = connect(path)
    init_db(conn)
    init_db(conn)
    conn.close()
    assert get("old", db_path=str(path))["text"] == "keep me"
    assert get("old", db_path=str(path))["raw_uri"] is None


def test_timezones_pagination_and_cjk_literal_matching(tmp_path, monkeypatch):
    from lake import query

    service = Service(tmp_path / "search.db", LocalRawStore(tmp_path / "raw"))
    base = PullRecord(
        item_id="utc-newer",
        connector_id="manual",
        kind="note",
        title="项目计划",
        text="中文记录 100% ready",
        url=None,
        raw={"v": 1},
        captured_at="2026-10-28T01:00:00+00:00",
    )
    other = dataclasses.replace(
        base,
        item_id="local-older",
        raw={"v": 2},
        captured_at="2026-10-28T08:30:00+08:00",
        text="中文记录 1000 ready",
    )
    ingest_pull_records([base, other], raw_store=service.store, db_path=service.db_path)
    monkeypatch.setattr(query, "_now", lambda: datetime(2026, 10, 28, 2, tzinfo=UTC))
    page = service.search(q="项目", since_days=1, limit=1)
    assert page["items"][0]["item_id"] == "utc-newer"
    assert page["total"] == 2 and page["has_more"]
    assert (
        service.search(q="项目", since_days=1, limit=1, offset=1)["items"][0]["item_id"]
        == "local-older"
    )
    assert service.search(q="中文 100%", since_days=1)["count"] == 1
    assert (
        query.pack_work(budget_tokens=3000, since_days=1, db_path=service.db_path)[
            "cites"
        ][0]["item_id"]
        == "utc-newer"
    )


def test_existing_raw_uri_stays_valid_after_upgrade_and_new_version(tmp_path):
    db = tmp_path / "legacy.db"
    legacy = tmp_path / "raw/sources/manual/raw/2026/10/legacy.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'{"v":1}')
    digest = hashlib.sha256(legacy.read_bytes()).hexdigest()
    with sqlite3.connect(db) as conn:
        conn.executescript(Path("lake/schema.sql").read_text())
        conn.execute(
            "INSERT INTO sources VALUES('src_manual','manual','{}','connected','{}','2026-10-28')"
        )
        conn.execute(
            "INSERT INTO raw_objects VALUES('legacy','src_manual','legacy',?,?,?)",
            (digest, legacy.as_uri(), "2026-10-28T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO items(item_id,source_id,connector_id,kind,title,body,captured_at,ingested_at) VALUES('legacy','src_manual','manual','note','Legacy','old','2026-10-28T00:00:00Z','2026-10-28T00:00:00Z')"
        )
    rec = PullRecord(
        item_id="legacy",
        connector_id="manual",
        kind="note",
        title="Legacy",
        text="new",
        url=None,
        raw={"v": 2},
        captured_at="2026-10-28T01:00:00Z",
    )
    ingest_pull_records([rec], raw_store=LocalRawStore(tmp_path / "raw"), db_path=db)
    assert legacy.read_bytes() == b'{"v":1}'
    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT uri FROM raw_objects WHERE raw_id='legacy'"
            ).fetchone()[0]
            == legacy.as_uri()
        )
        # Legacy readers can still select the original columns after additive migration.
        assert (
            conn.execute("SELECT body FROM items WHERE item_id='legacy'").fetchone()[0]
            == "new"
        )
    assert get("legacy", db_path=str(db))["raw_uri"] != legacy.as_uri()
