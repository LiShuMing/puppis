#!/usr/bin/env python3
"""Ingest Calendar → raw → lake. Offline: --fixture. ICS: CALENDAR_ICS_PATH."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from connectors.calendar.adapter import (  # noqa: E402
    CalendarConfigError,
    CalendarConnector,
    default_fixture_path,
)
from lake.api import pack, search  # noqa: E402
from lake.db import default_db_path  # noqa: E402
from lake.ingest import ingest_pull_records  # noqa: E402
from lake.raw_store import default_raw_root, open_raw_store  # noqa: E402


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
        description="Evidplane: Calendar pull → raw → lake (pack-ready)"
    )
    p.add_argument(
        "--fixture",
        nargs="?",
        const=str(default_fixture_path()),
        default=None,
        help="Offline JSON fixture (default connectors/calendar/demo_pull.json)",
    )
    p.add_argument("--ics", default=None, help="Path to .ics file")
    p.add_argument(
        "--since",
        default=None,
        help="ISO timestamp or Nd (e.g. 30d)",
    )
    p.add_argument("--db", default=None, help="SQLite path")
    p.add_argument("--raw-root", default=None, help="Local raw root (ignored for S3)")
    p.add_argument(
        "--smoke-pack",
        action="store_true",
        help="After ingest, print pack(work) cites for google_calendar",
    )
    args = p.parse_args()

    try:
        if args.fixture is not None:
            connector = CalendarConnector(fixture_path=args.fixture)
            mode = "fixture"
        elif args.ics:
            connector = CalendarConnector(ics_path=args.ics)
            mode = "ics"
        else:
            connector = CalendarConnector()
            mode = connector.health().get("mode", "api")
        health = connector.health()
        print("=== health ===")
        print(json.dumps(health, ensure_ascii=False, indent=2))
        since = _parse_since(args.since)
        records = connector.pull(since=since)
    except CalendarConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
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

    if args.raw_root:
        from lake.raw_store import LocalRawStore

        store = LocalRawStore(Path(args.raw_root).expanduser())
    else:
        store = open_raw_store()
    db = args.db or str(default_db_path())
    result = ingest_pull_records(
        records,
        raw_store=store,
        source_id="src_google_calendar",
        db_path=db,
        config={"mode": mode, "since": args.since},
    )
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
        s = search(source="google_calendar", since_days=30, limit=10, db_path=db)
        pk = pack(template="work", since_days=30, budget_tokens=3000, db_path=db)
        cal_cites = [
            c
            for c in pk.get("cites") or []
            if c.get("connector_id") == "google_calendar"
        ]
        print("\n=== smoke pack ===")
        print(
            json.dumps(
                {
                    "search_calendar_count": s["count"],
                    "pack_item_count": pk.get("item_count"),
                    "calendar_cites": [
                        {"item_id": c["item_id"], "title": c["title"]}
                        for c in cal_cites
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if s["count"] < 1:
            print("SMOKE FAIL: no google_calendar items in lake", file=sys.stderr)
            return 1
        print("\nINGEST SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
