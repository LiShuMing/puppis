#!/usr/bin/env python3
"""Ingest Notion → raw (file:// or S3) → lake. Offline: --fixture. Live: NOTION_* env."""
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
from lake.ingest import IngestError, ingest_pull_records  # noqa: E402
from lake.raw_store import LocalRawStore, open_raw_store  # noqa: E402


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


def _open_store(raw_root: str | None):
    if raw_root:
        return LocalRawStore(Path(raw_root).expanduser())
    return open_raw_store()


def _record_error(store, name: str, payload: dict) -> str | None:
    try:
        return store.write_error("notion", name, payload)
    except Exception as exc:
        print(f"warning: could not write errors/: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def _write_pull_errors(store, errors: list[dict]) -> list[str]:
    """Persist per-page pull errors to raw errors/. Returns uris written."""
    uris: list[str] = []
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for i, err in enumerate(errors):
        last4 = err.get("page_id_last4") or "unk"
        name = f"pull_page_{last4}_{ts}_{i}"
        payload = {
            "stage": err.get("stage") or "pull_page",
            "mode": "api",
            "error": err.get("error"),
            "message": err.get("message"),
            "page_id_last4": err.get("page_id_last4"),
            "page_id_len": err.get("page_id_len"),
            "status": err.get("status"),
        }
        uri = _record_error(store, name, payload)
        if uri:
            uris.append(uri)
    return uris


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
    p.add_argument("--db", default=None, help="SQLite path (default data/puppis.db or EVIDPLANE_DB)")
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

    store = _open_store(args.raw_root)
    mode = "fixture" if fixture is not None else "api"

    try:
        if fixture is not None:
            connector = NotionConnector(fixture_path=fixture)
        else:
            connector = NotionConnector()
        health = connector.health()
        # health never includes token
        print("=== health ===")
        print(json.dumps(health, ensure_ascii=False, indent=2))
        since = _parse_since(args.since)
        records = connector.pull(since=since)
    except NotionConfigError as e:
        err_uri = _record_error(
            store,
            f"config_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            {
                "stage": "config",
                "mode": mode,
                "error": "NotionConfigError",
                "message": str(e),
            },
        )
        print(f"config error: {e}", file=sys.stderr)
        if err_uri:
            print(f"error_uri: {err_uri}", file=sys.stderr)
        return 2
    except Exception as e:
        # Avoid dumping request headers / token on HTTP errors.
        err_uri = _record_error(
            store,
            f"pull_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            {
                "stage": "pull",
                "mode": mode,
                "error": type(e).__name__,
                "message": str(e),
            },
        )
        print(f"pull failed: {type(e).__name__}: {e}", file=sys.stderr)
        if err_uri:
            print(f"error_uri: {err_uri}", file=sys.stderr)
        return 1

    pull_errors = list(getattr(connector, "last_errors", None) or [])
    error_uris: list[str] = []
    if pull_errors:
        error_uris = _write_pull_errors(store, pull_errors)
        print(
            f"warning: {len(pull_errors)} page-level pull error(s); "
            f"wrote {len(error_uris)} errors/ object(s)",
            file=sys.stderr,
        )

    print(f"\n=== pull ({mode}) ===")
    print(
        json.dumps(
            {
                "count": len(records),
                "ids": [r.item_id for r in records],
                "titles": [r.title for r in records],
                "pull_errors": len(pull_errors),
                "pull_error_last4s": [e.get("page_id_last4") for e in pull_errors],
                "error_uri_count": len(error_uris),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if not records:
        if pull_errors:
            print("pull produced 0 records with page errors", file=sys.stderr)
            return 1
        print("pull produced 0 records", file=sys.stderr)
        # Empty success is allowed (e.g. since filter); still exit 0 unless smoke-pack.
        if args.smoke_pack:
            print("SMOKE FAIL: no notion items pulled", file=sys.stderr)
            return 1
        return 0

    db = args.db or str(default_db_path())
    try:
        result = ingest_pull_records(
            records,
            raw_store=store,
            source_id="src_notion",
            db_path=db,
            config={"mode": mode, "since": args.since, "pull_errors": len(pull_errors)},
        )
    except IngestError as e:
        print(f"ingest failed: {e}", file=sys.stderr)
        if e.error_uri:
            print(f"error_uri: {e.error_uri}", file=sys.stderr)
        return 1

    # Do not print raw body; uris are local paths only.
    print("\n=== ingest ===")
    print(
        json.dumps(
            {
                "db": result["db"],
                "upserted": result["upserted"],
                "inserted": result.get("inserted"),
                "updated": result.get("updated"),
                "unchanged": result.get("unchanged"),
                "by_connector": result["by_connector"],
                "raw_root": result["raw_root"],
                "raw_uri_count": len(result.get("raw_uris") or []),
                "pull_errors": len(pull_errors),
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
                    "pack_token_estimate": pk.get("token_estimate"),
                    "pack_budget_tokens": pk.get("budget_tokens"),
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
        if int(pk.get("token_estimate") or 0) > int(pk.get("budget_tokens") or 0):
            print("SMOKE FAIL: pack exceeds budget_tokens", file=sys.stderr)
            return 1
        print("\nINGEST SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
