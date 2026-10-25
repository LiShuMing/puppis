"""Lake read APIs: search / get / pack_work (metadata-first, FTS5)."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from lake.db import connect, default_db_path, init_db

_CHARS_PER_TOKEN = 4
_DEFAULT_PACK_DAYS = 7
_DEFAULT_PACK_BUDGET = 3000
_DEFAULT_SEARCH_LIMIT = 20
_SH_TZ = timezone(timedelta(hours=8))


def _parse_ts(value: str) -> datetime:
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_SH_TZ)
    return dt


def _now() -> datetime:
    return datetime.now(_SH_TZ)


def _since_cutoff(since_days: int | None) -> datetime | None:
    if since_days is None:
        return None
    return _now() - timedelta(days=int(since_days))


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def _ensure_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_db_path()
    conn = connect(path)
    init_db(conn)
    return conn


def _row_to_meta(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "item_id": row["item_id"],
        "connector_id": row["connector_id"],
        "kind": row["kind"],
        "title": row["title"],
        "url": row["source_url"],
        "captured_at": row["captured_at"],
        "trust_level": row["trust_level"],
        "provenance": row["provenance"],
    }


def _fts_query(q: str) -> str:
    tokens = [t for t in re.split(r"\s+", q.strip()) if t]
    if not tokens:
        return '""'
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in tokens)


def search(
    q: str | None = None,
    source: str | None = None,
    since_days: int | None = None,
    limit: int | None = None,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Metadata-first search (FTS5 when q set)."""
    conn = _ensure_db(db_path)
    try:
        lim = max(1, min(int(limit) if limit is not None else _DEFAULT_SEARCH_LIMIT, 100))
        cutoff = _since_cutoff(since_days)

        where = ["i.tombstone = 0"]
        params: list[Any] = []
        if source:
            where.append("i.connector_id = ?")
            params.append(source)

        fetch_lim = lim * 3 if cutoff else lim
        if q and q.strip():
            sql = f"""
                SELECT i.item_id, i.connector_id, i.kind, i.title, i.source_url,
                       i.captured_at, i.trust_level, i.provenance
                FROM items_fts
                JOIN items i ON i.rowid = items_fts.rowid
                WHERE {" AND ".join(where)}
                  AND items_fts MATCH ?
                ORDER BY i.captured_at DESC
                LIMIT ?
            """
            params.extend([_fts_query(q), fetch_lim])
            rows = conn.execute(sql, params).fetchall()
        else:
            sql = f"""
                SELECT i.item_id, i.connector_id, i.kind, i.title, i.source_url,
                       i.captured_at, i.trust_level, i.provenance
                FROM items i
                WHERE {" AND ".join(where)}
                ORDER BY i.captured_at DESC
                LIMIT ?
            """
            params.append(fetch_lim)
            rows = conn.execute(sql, params).fetchall()

        items = [_row_to_meta(r) for r in rows]
        if cutoff is not None:
            items = [it for it in items if _parse_ts(it["captured_at"]) >= cutoff]
        items = items[:lim]
        return {"items": items, "count": len(items)}
    finally:
        conn.close()


def get(item_id: str, *, db_path: str | None = None) -> dict[str, Any]:
    """Fetch one Evidence item with body + source_url + provenance."""
    conn = _ensure_db(db_path)
    try:
        row = conn.execute(
            """
            SELECT item_id, connector_id, kind, title, body, source_url,
                   captured_at, ingested_at, trust_level, provenance, tombstone
            FROM items WHERE item_id = ?
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            return {"error": "not_found", "item_id": item_id}
        if row["tombstone"]:
            return {"error": "tombstoned", "item_id": item_id}
        return {
            "item_id": row["item_id"],
            "connector_id": row["connector_id"],
            "kind": row["kind"],
            "title": row["title"],
            "text": row["body"],
            "url": row["source_url"],
            "source_url": row["source_url"],
            "captured_at": row["captured_at"],
            "ingested_at": row["ingested_at"],
            "trust_level": row["trust_level"],
            "provenance": {
                "source": row["provenance"],
                "human_reviewed": False,
            },
        }
    finally:
        conn.close()


def _trim_to_budget(text: str, budget: int) -> str:
    """Hard-trim text so _estimate_tokens(text) <= budget."""
    if budget <= 0:
        return ""
    if _estimate_tokens(text) <= budget:
        return text
    # Ceil estimate uses 4 chars/token; keep a little headroom via byte trim loop.
    max_chars = max(0, budget * _CHARS_PER_TOKEN)
    trimmed = text[:max_chars]
    while trimmed and _estimate_tokens(trimmed) > budget:
        trimmed = trimmed[: max(0, len(trimmed) - _CHARS_PER_TOKEN)]
    return trimmed


def pack_work(
    budget_tokens: int = 3000,
    since_days: int = 7,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Assemble recent high-signal items into a work Pack with cites.

    Hard contract: token_estimate <= budget_tokens. Items/cites are selected
    greedily (newest first); the first oversize block may be truncated to fit
    remaining budget; further items are skipped.
    """
    budget = max(1, int(budget_tokens))
    days = int(since_days)
    conn = _ensure_db(db_path)
    try:
        cutoff = _since_cutoff(days)
        rows = conn.execute(
            """
            SELECT item_id, connector_id, kind, title, body, source_url,
                   captured_at, trust_level, provenance
            FROM items
            WHERE tombstone = 0
            ORDER BY captured_at DESC
            LIMIT 50
            """
        ).fetchall()

        selected: list[dict[str, Any]] = []
        cites: list[dict[str, Any]] = []
        header = (
            f"# Evidplane pack(work)\n"
            f"Window: last {days} day(s) · budget ≤ {budget} tokens\n"
            f"Generated: {_now().isoformat()}\n\n"
        )
        header = _trim_to_budget(header, budget)
        used = _estimate_tokens(header)
        body_parts = [header]

        for row in rows:
            if cutoff is not None and _parse_ts(row["captured_at"]) < cutoff:
                continue
            remain = budget - used
            if remain <= 0:
                break
            title = row["title"] or row["item_id"]
            excerpt = (row["body"] or "").strip()
            if len(excerpt) > 600:
                excerpt = excerpt[:597] + "..."
            block = (
                f"## [{row['item_id']}] {title}\n"
                f"- source: `{row['connector_id']}` · kind: `{row['kind']}` · "
                f"at: {row['captured_at']}\n"
                f"- url: {row['source_url'] or '(none)'}\n\n"
                f"{excerpt}\n\n"
            )
            cost = _estimate_tokens(block)
            if cost > remain:
                if selected:
                    break
                # First item: truncate to remaining budget (may omit if too tight).
                block = _trim_to_budget(block, remain)
                cost = _estimate_tokens(block)
                if cost == 0 or cost > remain:
                    break
            body_parts.append(block)
            used += cost
            selected.append(_row_to_meta(row))
            cites.append(
                {
                    "item_id": row["item_id"],
                    "title": title,
                    "url": row["source_url"],
                    "connector_id": row["connector_id"],
                    "captured_at": row["captured_at"],
                }
            )

        text = "".join(body_parts)
        if not selected:
            empty_note = "_No evidence in window. Seed or sync a connector._\n"
            remain = budget - _estimate_tokens(text)
            if remain > 0:
                text += _trim_to_budget(empty_note, remain)

        text = _trim_to_budget(text, budget)
        # Drop cites whose item_id no longer appears after hard trim.
        if selected:
            kept_ids = {c["item_id"] for c in cites if f"[{c['item_id']}]" in text}
            if len(kept_ids) < len(cites):
                cites = [c for c in cites if c["item_id"] in kept_ids]
                selected = [i for i in selected if i["item_id"] in kept_ids]

        return {
            "template": "work",
            "text": text,
            "items": selected,
            "cites": cites,
            "token_estimate": _estimate_tokens(text),
            "budget_tokens": budget,
            "since_days": days,
            "item_count": len(selected),
        }
    finally:
        conn.close()


def pack(
    template: str = "work",
    budget_tokens: int | None = None,
    since_days: int | None = None,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Compile a Pack; L0 only supports template='work'."""
    if template != "work":
        return {
            "error": "unknown_template",
            "template": template,
            "supported": ["work"],
        }
    return pack_work(
        budget_tokens=int(budget_tokens) if budget_tokens else _DEFAULT_PACK_BUDGET,
        since_days=int(since_days) if since_days is not None else _DEFAULT_PACK_DAYS,
        db_path=db_path,
    )
