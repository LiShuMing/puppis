"""Upsert PullRecord / Evidence into the lake (raw already written or written here)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from connectors.base import PullRecord
from lake.db import connect, default_db_path, init_db
from lake.models import Evidence
from lake.raw_store import RawStore, open_raw_store

_SH_TZ = timezone(timedelta(hours=8))
_DEFAULT_SOURCE_PREFIX = "src"


class IngestError(RuntimeError):
    """Raised when raw write or upsert fails after recording to errors/ when possible."""

    def __init__(self, message: str, *, error_uri: str | None = None) -> None:
        super().__init__(message)
        self.error_uri = error_uri


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


def _safe_err_name(item_id: str) -> str:
    return item_id.replace("/", "_").replace(" ", "_")[:80]


def upsert_evidence(
    items: Iterable[Evidence],
    *,
    source_id: str | None = None,
    db_path: str | Path | None = None,
    config_json: str = "{}",
) -> dict[str, Any]:
    """Insert or replace Evidence rows + raw_objects metadata.

    Idempotent on item_id: identical re-ingest updates the same row (no duplicate
    items). raw_objects rows are unique on (source_id, item_id, content_hash).
    """
    path = Path(db_path) if db_path else default_db_path()
    conn = connect(path)
    init_db(conn)
    now_s = _now().isoformat()
    upserted = 0
    inserted = 0
    updated = 0
    unchanged = 0
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
            prev = conn.execute(
                "SELECT body, source_url, title FROM items WHERE item_id = ?",
                (ev.item_id,),
            ).fetchone()
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
            if prev is None:
                inserted += 1
            elif (
                (prev["body"] or "") == (ev.text or "")
                and (prev["source_url"] or None) == (ev.url or None)
                and (prev["title"] or None) == (ev.title or None)
            ):
                unchanged += 1
            else:
                updated += 1
        conn.commit()
        return {
            "db": str(path),
            "upserted": upserted,
            "inserted": inserted,
            "updated": updated,
            "unchanged": unchanged,
            "by_connector": by_connector,
        }
    finally:
        conn.close()


def ingest_pull_records(
    records: Iterable[PullRecord],
    *,
    raw_store: RawStore | None = None,
    source_id: str | None = None,
    db_path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write raw objects then upsert Evidence derived from PullRecords.

    Raw write failures are recorded under sources/<connector>/errors/ then raised
    as IngestError (never silent drop).
    """
    store = raw_store or open_raw_store()
    evidence: list[Evidence] = []
    raw_uris: list[str] = []
    for rec in records:
        when = _parse_captured(rec.captured_at)
        try:
            sha, uri = store.write(rec.connector_id, rec.item_id, rec.raw, when=when)
        except Exception as exc:
            err_payload = {
                "stage": "raw_write",
                "error": type(exc).__name__,
                "message": str(exc),
                "item_id": rec.item_id,
                "connector_id": rec.connector_id,
                "captured_at": rec.captured_at,
            }
            err_uri: str | None = None
            try:
                err_uri = store.write_error(
                    rec.connector_id,
                    f"write_{_safe_err_name(rec.item_id)}",
                    err_payload,
                    when=when,
                )
            except Exception:
                err_uri = None
            raise IngestError(
                f"raw write failed for {rec.item_id}: {type(exc).__name__}: {exc}",
                error_uri=err_uri,
            ) from exc
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
