#!/usr/bin/env python3
"""Ingest Notion → raw (file://) → lake. Offline: --fixture. Live: NOTION_* env."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from connectors.notion.adapter import (  # noqa: E402
    NotionConfigError,
    NotionConnector,
    default_fixture_path,
)
from lake.api import pack, search  # noqa: E402
from lake.db import default_db_path  # noqa: E402
from lake.ingest import ingest_pull_records  # noqa: E402
from lake.raw_store import LocalRawStore, default_raw_root  # noqa: E402


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.endswith("d") and value[:-1].isdigit():
        days = int(value[:-1])
        return datetime.now(timezone.utc) - timedelta(days=days)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main() -> int:
    p = argparse.ArgumentParser(
        description="Evidplane: Notion pull → raw → lake (pack-ready)"
    )
    p.add_argument(
        "--fixture",
        nargs="?",
        const=str(default_fixture_path()),
        default=None,
        help="Offline JSON fixture (default connectors/notion/demo_pull.json if flag set)",
    )
    p.add_argument(
        "--since",
        default=None,
        help="ISO timestamp or Nd (e.g. 30d). Default: all / API filter none",
    )
    p.add_argument("--db", default=None, help="SQLite path (default data/puppis.db)")
    p.add_argument(
        "--raw-root",
        default=None,
        help="Raw store root (default ~/.evidplane or EVIDPLANE_RAW_ROOT)",
    )
    p.add_argument(
        "--smoke-pack",
        action="store_true",
        help="After ingest, print pack(work) cite count for source=notion",
    )
    args = p.parse_args()

    fixture = args.fixture
    use_api = fixture is None
    if use_api and not os.environ.get("NOTION_TOKEN"):
        print(
            "NOTION_TOKEN not set. Use --fixture for offline smoke, or export "
            "NOTION_TOKEN plus NOTION_DATABASE_ID and/or NOTION_PAGE_IDS.",
            file=sys.stderr,
        )
        return 2

    try:
        if fixture is not None:
            connector = NotionConnector(fixture_path=fixture)
            mode = "fixture"
        else:
            connector = NotionConnector()
            mode = "api"
        health = connector.health()
        # health never includes token
        print("=== health ===")
        print(json.dumps(health, ensure_ascii=False, indent=2))
        since = _parse_since(args.since)
        records = connector.pull(since=since)
    except NotionConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        # Avoid dumping request headers / token on HTTP errors.
        print(f"pull failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"\n=== pull ({mode}) ===")
    print(
        json.dumps(
            {
                "count": len(records),
                "ids": [r.item_id for r in records],
                "titles": [r.title for r in records],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    raw_root = Path(args.raw_root).expanduser() if args.raw_root else default_raw_root()
    store = LocalRawStore(raw_root)
    db = args.db or str(default_db_path())
    result = ingest_pull_records(
        records,
        raw_store=store,
        source_id="src_notion",
        db_path=db,
        config={"mode": mode, "since": args.since},
    )
    # Do not print raw body; uris are local paths only.
    print("\n=== ingest ===")
    print(
        json.dumps(
            {
                "db": result["db"],
                "upserted": result["upserted"],
                "by_connector": result["by_connector"],
                "raw_root": result["raw_root"],
                "raw_uri_count": len(result.get("raw_uris") or []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if args.smoke_pack:
        s = search(source="notion", since_days=30, limit=10, db_path=db)
        pk = pack(template="work", since_days=30, budget_tokens=3000, db_path=db)
        notion_cites = [
            c for c in pk.get("cites") or [] if c.get("connector_id") == "notion"
        ]
        print("\n=== smoke pack ===")
        print(
            json.dumps(
                {
                    "search_notion_count": s["count"],
                    "pack_item_count": pk.get("item_count"),
                    "notion_cites": [
                        {"item_id": c["item_id"], "title": c["title"]}
                        for c in notion_cites
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if s["count"] < 1:
            print("SMOKE FAIL: no notion items in lake", file=sys.stderr)
            return 1
        print("\nINGEST SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
