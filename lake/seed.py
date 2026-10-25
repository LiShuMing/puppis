"""Seed fake calendar/notion Evidence for MVP dogfood."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from lake.db import connect, default_db_path, init_db, item_count

_SH_TZ = timezone(timedelta(hours=8))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fake_items(now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(_SH_TZ)
    # Mix of recent work signals (calendar events + notion pages).
    specs = [
        {
            "item_id": "cal_evt_20261024_standup",
            "source_id": "src_calendar_dogfood",
            "connector_id": "google_calendar",
            "kind": "event",
            "title": "Evidplane standup",
            "body": (
                "Daily standup: ship fake Lake + MCP pack(work) to Cursor. "
                "Owner: 阿里云 lane. Blocker: none. Next: Notion connector."
            ),
            "source_url": "https://calendar.google.com/calendar/event?eid=fake_standup",
            "captured_at": (now - timedelta(hours=6)).isoformat(),
        },
        {
            "item_id": "cal_evt_20261023_design",
            "source_id": "src_calendar_dogfood",
            "connector_id": "google_calendar",
            "kind": "event",
            "title": "Context Plane design review",
            "body": (
                "Agreed three-module split: connectors / lake / serve. "
                "No cross-layer calls. Pack template work = last 7 days + cites."
            ),
            "source_url": "https://calendar.google.com/calendar/event?eid=fake_design",
            "captured_at": (now - timedelta(days=2, hours=3)).isoformat(),
        },
        {
            "item_id": "cal_evt_20261020_1on1",
            "source_id": "src_calendar_dogfood",
            "connector_id": "google_calendar",
            "kind": "event",
            "title": "1:1 Kevin / 技术",
            "body": (
                "Prioritize agentic gate: Cursor must call pack(work) before "
                "real connectors. Domain evidplane.com can wait."
            ),
            "source_url": "https://calendar.google.com/calendar/event?eid=fake_1on1",
            "captured_at": (now - timedelta(days=5)).isoformat(),
        },
        {
            "item_id": "notion_pg_evidplane_spec",
            "source_id": "src_notion_dogfood",
            "connector_id": "notion",
            "kind": "page",
            "title": "Evidplane L0 checklist",
            "body": (
                "Acceptance: seed → search/get/pack via MCP → Cursor dogfood. "
                "OSS raw layout later. Do not share buckets with Topic Plane."
            ),
            "source_url": "https://www.notion.so/fake/evidplane-l0-checklist",
            "captured_at": (now - timedelta(days=1, hours=2)).isoformat(),
        },
        {
            "item_id": "notion_pg_open_questions",
            "source_id": "src_notion_dogfood",
            "connector_id": "notion",
            "kind": "page",
            "title": "Open questions — pack budget",
            "body": (
                "Default pack(work) budget 4000 tokens. Truncate older items first. "
                "Every cite must carry item_id + source_url for get()."
            ),
            "source_url": "https://www.notion.so/fake/open-questions-pack-budget",
            "captured_at": (now - timedelta(days=1, hours=8)).isoformat(),
        },
        {
            "item_id": "notion_pg_mvp_scope",
            "source_id": "src_notion_dogfood",
            "connector_id": "notion",
            "kind": "page",
            "title": "MVP non-goals",
            "body": (
                "Out of L0: vector search, AgentsView connector, GitHub second source, "
                "polished console UI, public multi-tenant SaaS."
            ),
            "source_url": "https://www.notion.so/fake/mvp-non-goals",
            "captured_at": (now - timedelta(days=3)).isoformat(),
        },
        {
            "item_id": "cal_evt_20261018_oss",
            "source_id": "src_calendar_dogfood",
            "connector_id": "google_calendar",
            "kind": "event",
            "title": "OSS layout walkthrough",
            "body": (
                "s3://bucket/evidplane/sources/<connector>/raw/yyyy/mm/<item_id>.json. "
                "errors/ sibling. derived/ rebuildable."
            ),
            "source_url": "https://calendar.google.com/calendar/event?eid=fake_oss",
            "captured_at": (now - timedelta(days=7, hours=1)).isoformat(),
        },
        {
            "item_id": "notion_pg_kill_signals",
            "source_id": "src_notion_dogfood",
            "connector_id": "notion",
            "kind": "page",
            "title": "Kill signals",
            "body": (
                "Kill if pack cites cannot round-trip get(item_id), or if agents "
                "need platform tokens. Success = Cursor session answers "
                "'what am I working on' from pack alone."
            ),
            "source_url": "https://www.notion.so/fake/kill-signals",
            "captured_at": (now - timedelta(hours=20)).isoformat(),
        },
    ]
    return specs


def seed_fake(db_path: str | Path | None = None, *, force: bool = False) -> dict[str, Any]:
    """Insert fake Evidence. Skips if items already exist unless force=True."""
    path = Path(db_path) if db_path else default_db_path()
    conn = connect(path)
    init_db(conn)
    try:
        existing = item_count(conn)
        if existing and not force:
            return {"db": str(path), "seeded": 0, "existing": existing, "skipped": True}

        if force:
            conn.execute("DELETE FROM items")
            conn.execute("DELETE FROM raw_objects")
            conn.execute("DELETE FROM sources")
            # Rebuild empty FTS content table
            conn.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
            conn.commit()

        now = datetime.now(_SH_TZ)
        now_s = now.isoformat()
        sources = {
            "src_calendar_dogfood": ("google_calendar", '{"mode":"fake"}'),
            "src_notion_dogfood": ("notion", '{"mode":"fake"}'),
        }
        for sid, (cid, cfg) in sources.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO sources
                  (source_id, connector_id, config_json, status, cursor_json, updated_at)
                VALUES (?, ?, ?, 'connected', '{}', ?)
                """,
                (sid, cid, cfg, now_s),
            )

        n = 0
        for it in _fake_items(now):
            body = it["body"]
            content_hash = _sha(body)
            raw_id = f"raw_{it['item_id']}"
            uri = f"file://fake/{it['connector_id']}/raw/{it['item_id']}.json"
            conn.execute(
                """
                INSERT OR REPLACE INTO raw_objects
                  (raw_id, source_id, item_id, content_hash, uri, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (raw_id, it["source_id"], it["item_id"], content_hash, uri, it["captured_at"]),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO items
                  (item_id, source_id, connector_id, kind, title, body, source_url,
                   captured_at, ingested_at, trust_level, provenance, tombstone)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, 'platform', 0)
                """,
                (
                    it["item_id"],
                    it["source_id"],
                    it["connector_id"],
                    it["kind"],
                    it["title"],
                    body,
                    it["source_url"],
                    it["captured_at"],
                    now_s,
                ),
            )
            n += 1
        conn.commit()
        return {"db": str(path), "seeded": n, "existing": existing, "skipped": False}
    finally:
        conn.close()


def main() -> None:
    import argparse
    import json

    p = argparse.ArgumentParser(description="Seed fake Evidplane lake data")
    p.add_argument("--db", default=None, help="SQLite path (default data/evidplane.db)")
    p.add_argument("--force", action="store_true", help="Wipe items and reseed")
    args = p.parse_args()
    print(json.dumps(seed_fake(args.db, force=args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
