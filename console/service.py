"""Application operations: console routes never talk to connectors or SQL directly."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from connectors.base import PullRecord
from connectors.calendar.adapter import records_from_events
from connectors.notion.adapter import (
    NotionConnector,
    default_fixture_path,
    records_from_payload,
)
from lake.db import default_db_path
from lake.ingest import ingest_pull_records
from lake.query import get, overview, pack, search
from lake.raw_store import RawStore, open_raw_store


class UserError(ValueError):
    """A safe, actionable message intended for the local user."""


class Service:
    def __init__(
        self, db_path: str | Path | None = None, raw_store: RawStore | None = None
    ):
        self.db_path = str(db_path or default_db_path())
        self.store = raw_store or open_raw_store()
        overview(db_path=self.db_path)

    def status(self):
        result = overview(db_path=self.db_path)
        result["notion"] = NotionConnector().health()
        result["storage"] = "local" if isinstance(self.store.root, Path) else "s3"
        result["database"] = self.db_path
        return result

    def search(self, **kwargs):
        return search(db_path=self.db_path, **kwargs)

    def get(self, item_id):
        return get(item_id, db_path=self.db_path)

    def pack(self, **kwargs):
        return pack(db_path=self.db_path, **kwargs)

    def _ingest(self, records, *, mode, source_id=None):
        result = ingest_pull_records(
            records,
            raw_store=self.store,
            db_path=self.db_path,
            source_id=source_id,
            config={"mode": mode},
        )
        return {
            key: result[key] for key in ("upserted", "inserted", "updated", "unchanged")
        }

    def import_text(self, title: str, text: str, url: str | None = None):
        title, text = title.strip(), text.strip()
        if not title or not text:
            raise UserError("请填写标题和正文")
        if url and urlparse(url).scheme not in {"http", "https"}:
            raise UserError("来源链接仅支持 http/https")
        payload = {"title": title, "text": text, "url": url or None}
        identity = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        record = PullRecord(
            item_id=f"manual_{identity}",
            connector_id="manual",
            kind="note",
            title=title,
            text=text,
            url=url or None,
            captured_at=datetime.now(UTC).isoformat(),
            raw=payload,
            provenance={"source": "export", "human_reviewed": False},
        )
        return {**self._ingest([record], mode="manual"), "item_id": record.item_id}

    def import_fixture(self, payload):
        if not isinstance(payload, dict):
            raise UserError("JSON 须为 {pages: [...]} 或 {events: [...]} 格式")
        key = "pages" if "pages" in payload else "events"
        rows = payload.get(key)
        if not isinstance(rows, list) or not rows or len(rows) > 100:
            raise UserError("每次导入需要 1–100 条 pages 或 events")
        if any(
            not isinstance(row, dict) or not (row.get("id") or row.get("uid"))
            for row in rows
        ):
            raise UserError("每条资料需要稳定的 id")
        records = (
            records_from_payload(rows, since=None)
            if key == "pages"
            else records_from_events(rows, since=None)
        )
        if not records:
            raise UserError("文件没有可导入的资料")
        # Uploaded files are exports, not a live API capture. Separate namespaces
        # prevent overwriting a live connector's evidence with an uploaded file.
        records = [
            dataclasses.replace(
                rec,
                item_id="import_" + rec.item_id,
                provenance={"source": "export", "human_reviewed": False},
            )
            for rec in records
        ]
        return self._ingest(
            records, mode="file", source_id=f"import_{records[0].connector_id}"
        )

    def import_demo(self):
        now = datetime.now(UTC).isoformat()
        records = NotionConnector(fixture_path=default_fixture_path()).pull()
        records = [
            dataclasses.replace(
                rec,
                item_id="demo_" + rec.item_id,
                captured_at=now,
                provenance={"source": "export", "human_reviewed": False, "demo": True},
            )
            for rec in records
        ]
        return self._ingest(records, mode="demo", source_id="demo_notion")

    def sync_notion(self):
        connector = NotionConnector()
        if not connector.health()["ok"]:
            raise UserError(
                "请在启动服务的环境配置 NOTION_TOKEN 和 NOTION_PAGE_IDS 或 NOTION_DATABASE_ID"
            )
        records = connector.pull()
        errors = connector.last_errors
        # Do not include provider messages/URLs in the browser or error objects.
        for index, error in enumerate(errors):
            self.store.write_error(
                "notion",
                f"console_sync_{os.urandom(8).hex()}_{index}",
                {
                    "stage": error.get("stage"),
                    "error": error.get("error"),
                    "status": error.get("status"),
                    "page_id_last4": error.get("page_id_last4"),
                },
            )
        if not records and errors:
            raise UserError("Notion 同步失败；请检查目标页面权限与服务端配置")
        result = (
            self._ingest(records, mode="api", source_id="src_notion")
            if records
            else {
                "upserted": 0,
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
            }
        )
        return {**result, "failed": len(errors), "partial": bool(errors)}
