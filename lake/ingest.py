"""Upsert PullRecord / Evidence into the lake (raw already written or written here)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from connectors.base import PullRecord
from lake.db import connect, default_db_path, init_db
from lake.models import Evidence
from lake.raw_store import LocalRawStore

_SH_TZ = timezone(timedelta(hours=8))
_DEFAULT_SOURCE_PREFIX = "src"


def _now() -> datetime:
    return datetime.now(_SH_TZ)


def _parse_captured(value: str) -> datetime:
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def upsert_evidence(
    items: Iterable[Evidence],
    *,
    source_id: str | None = None,
    db_path: str | Path | None = None,
    config_json: str = "{}",
) -> dict[str, Any]:
    """Insert or replace Evidence rows + raw_objects metadata."""
    path = Path(db_path) if db_path else default_db_path()
    conn = connect(path)
    init_db(conn)
    now_s = _now().isoformat()
    upserted = 0
    by_connector: dict[str, int] = {}
    try:
        for ev in items:
            sid = source_id or f"{_DEFAULT_SOURCE_PREFIX}_{ev.connector_id}"
            conn.execute(
                """
                INSERT INTO sources
                  (source_id, connector_id, config_json, status, cursor_json, updated_at)
                VALUES (?, ?, ?, 'connected', '{}', ?)
                ON CONFLICT(source_id) DO UPDATE SET
                  connector_id=excluded.connector_id,
                  status='connected',
                  updated_at=excluded.updated_at
                """,
                (sid, ev.connector_id, config_json, now_s),
            )
            raw_id = f"raw_{ev.item_id}_{ev.content_sha256[:12]}"
            conn.execute(
                """
                INSERT OR IGNORE INTO raw_objects
                  (raw_id, source_id, item_id, content_hash, uri, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    raw_id,
                    sid,
                    ev.item_id,
                    ev.content_sha256,
                    ev.raw_uri or "",
                    ev.captured_at,
                ),
            )
            prov = ev.provenance.get("source", "platform")
            if not isinstance(prov, str):
                prov = "platform"
            conn.execute(
                """
                INSERT INTO items
                  (item_id, source_id, connector_id, kind, title, body, source_url,
                   captured_at, ingested_at, trust_level, provenance, tombstone)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?, 0)
                ON CONFLICT(item_id) DO UPDATE SET
                  source_id=excluded.source_id,
                  connector_id=excluded.connector_id,
                  kind=excluded.kind,
                  title=excluded.title,
                  body=excluded.body,
                  source_url=excluded.source_url,
                  captured_at=excluded.captured_at,
                  ingested_at=excluded.ingested_at,
                  provenance=excluded.provenance,
                  tombstone=0
                """,
                (
                    ev.item_id,
                    sid,
                    ev.connector_id,
                    ev.kind,
                    ev.title,
                    ev.text or "",
                    ev.url,
                    ev.captured_at,
                    now_s,
                    prov,
                ),
            )
            upserted += 1
            by_connector[ev.connector_id] = by_connector.get(ev.connector_id, 0) + 1
        conn.commit()
        return {
            "db": str(path),
            "upserted": upserted,
            "by_connector": by_connector,
        }
    finally:
        conn.close()


def ingest_pull_records(
    records: Iterable[PullRecord],
    *,
    raw_store: LocalRawStore | None = None,
    source_id: str | None = None,
    db_path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write raw objects then upsert Evidence derived from PullRecords."""
    store = raw_store or LocalRawStore()
    evidence: list[Evidence] = []
    raw_uris: list[str] = []
    for rec in records:
        when = _parse_captured(rec.captured_at)
        sha, uri = store.write(rec.connector_id, rec.item_id, rec.raw, when=when)
        raw_uris.append(uri)
        evidence.append(
            Evidence(
                item_id=rec.item_id,
                connector_id=rec.connector_id,
                kind=rec.kind,
                title=rec.title,
                url=rec.url,
                captured_at=rec.captured_at,
                valid_from=rec.valid_from,
                valid_to=rec.valid_to,
                content_sha256=sha,
                raw_uri=uri,
                text=rec.text,
                provenance=rec.provenance,
            )
        )
    cfg = json.dumps(config or {"mode": "pull"}, ensure_ascii=False)
    result = upsert_evidence(
        evidence,
        source_id=source_id,
        db_path=db_path,
        config_json=cfg,
    )
    result["raw_root"] = str(store.root)
    result["raw_uris"] = raw_uris
    return result
