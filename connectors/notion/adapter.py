"""Notion adapter: pull(since) → PullRecord[] via REST or offline fixture."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from connectors.base import PullRecord

NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"
CONNECTOR_ID = "notion"
_FIXTURE_PATH = Path(__file__).with_name("demo_pull.json")


class NotionConfigError(RuntimeError):
    """Raised when required Notion env/config is missing or invalid."""


def _parse_since(since: datetime | None) -> datetime | None:
    if since is None:
        return None
    if since.tzinfo is None:
        return since.replace(tzinfo=timezone.utc)
    return since.astimezone(timezone.utc)


def _rich_text_plain(rich: list[dict[str, Any]] | None) -> str:
    if not rich:
        return ""
    parts: list[str] = []
    for span in rich:
        if not isinstance(span, dict):
            continue
        plain = span.get("plain_text")
        if plain is None and isinstance(span.get("text"), dict):
            plain = span["text"].get("content")
        if plain:
            parts.append(str(plain))
    return "".join(parts)


def _title_from_properties(props: dict[str, Any]) -> str | None:
    for prop in props.values():
        if not isinstance(prop, dict):
            continue
        if prop.get("type") == "title":
            t = _rich_text_plain(prop.get("title"))
            return t or None
    return None


def _page_title(page: dict[str, Any]) -> str:
    props = page.get("properties") or {}
    title = _title_from_properties(props) if isinstance(props, dict) else None
    if title:
        return title
    # Standalone pages sometimes expose title via child title property only;
    # fall back to id short form.
    pid = page.get("id") or "unknown"
    return f"Notion page {str(pid).replace('-', '')[:8]}"


def _page_url(page: dict[str, Any]) -> str | None:
    url = page.get("url")
    return str(url) if url else None


def _page_edited_at(page: dict[str, Any]) -> str:
    raw = page.get("last_edited_time") or page.get("created_time")
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    s = str(raw)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return s


def _blocks_to_text(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for b in blocks:
        btype = b.get("type")
        if not btype or not isinstance(b.get(btype), dict):
            continue
        node = b[btype]
        rich = node.get("rich_text") or node.get("text")
        if isinstance(rich, list):
            line = _rich_text_plain(rich).strip()
            if line:
                if btype == "heading_1":
                    lines.append(f"# {line}")
                elif btype == "heading_2":
                    lines.append(f"## {line}")
                elif btype == "heading_3":
                    lines.append(f"### {line}")
                elif btype == "bulleted_list_item":
                    lines.append(f"- {line}")
                elif btype == "numbered_list_item":
                    lines.append(f"1. {line}")
                elif btype == "to_do":
                    mark = "x" if node.get("checked") else " "
                    lines.append(f"- [{mark}] {line}")
                else:
                    lines.append(line)
        elif btype == "code":
            line = _rich_text_plain(node.get("rich_text")).rstrip()
            lang = node.get("language") or ""
            lines.append(f"```{lang}\n{line}\n```")
        elif btype == "divider":
            lines.append("---")
    return "\n".join(lines).strip()


def _item_id_for_page(page_id: str) -> str:
    clean = str(page_id).replace("-", "").lower()
    return f"notion_pg_{clean}"


def _records_from_payload(
    pages: list[dict[str, Any]],
    *,
    since: datetime | None,
) -> list[PullRecord]:
    cutoff = _parse_since(since)
    out: list[PullRecord] = []
    for page in pages:
        if page.get("object") and page.get("object") != "page":
            continue
        edited = _page_edited_at(page)
        if cutoff is not None:
            try:
                edited_dt = datetime.fromisoformat(
                    edited[:-1] + "+00:00" if edited.endswith("Z") else edited
                )
                if edited_dt.tzinfo is None:
                    edited_dt = edited_dt.replace(tzinfo=timezone.utc)
                if edited_dt < cutoff:
                    continue
            except ValueError:
                pass
        blocks = page.get("_blocks") or page.get("blocks") or []
        if not isinstance(blocks, list):
            blocks = []
        text = _blocks_to_text(blocks)
        title = _page_title(page)
        if not text:
            text = title
        # Strip helper keys from stored raw.
        raw = {k: v for k, v in page.items() if not k.startswith("_")}
        if blocks and "blocks" not in raw:
            raw = {**raw, "blocks": blocks}
        pid = str(page.get("id") or "")
        out.append(
            PullRecord(
                item_id=_item_id_for_page(pid),
                connector_id=CONNECTOR_ID,
                kind="page",
                title=title,
                url=_page_url(page),
                captured_at=edited,
                text=text,
                raw=raw,
                provenance={"source": "platform", "human_reviewed": False},
            )
        )
    return out


class NotionConnector:
    """pull(since) from Notion API or a local fixture JSON."""

    connector_id = CONNECTOR_ID

    def __init__(
        self,
        *,
        token: str | None = None,
        database_id: str | None = None,
        page_ids: list[str] | None = None,
        fixture_path: str | Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._fixture_path = Path(fixture_path) if fixture_path else None
        self._token = token if token is not None else os.environ.get("NOTION_TOKEN")
        self._database_id = (
            database_id
            if database_id is not None
            else os.environ.get("NOTION_DATABASE_ID")
        )
        if page_ids is not None:
            self._page_ids = list(page_ids)
        else:
            raw_ids = os.environ.get("NOTION_PAGE_IDS", "").strip()
            self._page_ids = [p.strip() for p in raw_ids.split(",") if p.strip()]
        self._timeout = timeout

    def health(self) -> dict[str, Any]:
        if self._fixture_path is not None:
            return {
                "connector_id": self.connector_id,
                "mode": "fixture",
                "ok": self._fixture_path.is_file(),
                "fixture": str(self._fixture_path),
            }
        has_token = bool(self._token)
        has_target = bool(self._database_id or self._page_ids)
        return {
            "connector_id": self.connector_id,
            "mode": "api",
            "ok": has_token and has_target,
            "has_token": has_token,
            "has_database_id": bool(self._database_id),
            "page_id_count": len(self._page_ids),
        }

    def pull(self, since: datetime | None = None) -> list[PullRecord]:
        if self._fixture_path is not None:
            return self._pull_fixture(since)
        self._require_api_config()
        return self._pull_api(since)

    def _require_api_config(self) -> None:
        missing: list[str] = []
        if not self._token:
            missing.append("NOTION_TOKEN")
        if not self._database_id and not self._page_ids:
            missing.append("NOTION_DATABASE_ID or NOTION_PAGE_IDS")
        if missing:
            raise NotionConfigError(
                "Notion connector missing config: "
                + ", ".join(missing)
                + ". Set env vars, or pass fixture_path=/…/demo_pull.json for offline smoke."
            )

    def _pull_fixture(self, since: datetime | None) -> list[PullRecord]:
        path = self._fixture_path or _FIXTURE_PATH
        if not path.is_file():
            raise NotionConfigError(f"Notion fixture not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        pages = data.get("pages") if isinstance(data, dict) else data
        if not isinstance(pages, list):
            raise NotionConfigError("Fixture must be {pages:[…]} or a list of pages")
        return _records_from_payload(pages, since=since)

    def _headers(self) -> dict[str, str]:
        # Never log this dict.
        assert self._token
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _pull_api(self, since: datetime | None) -> list[PullRecord]:
        pages: list[dict[str, Any]] = []
        with httpx.Client(timeout=self._timeout, headers=self._headers()) as client:
            if self._database_id:
                pages.extend(self._query_database(client, self._database_id, since))
            for pid in self._page_ids:
                page = self._get_page(client, pid)
                if page:
                    pages.append(page)
            # Dedupe by id
            by_id: dict[str, dict[str, Any]] = {}
            for p in pages:
                pid = str(p.get("id") or "")
                if pid:
                    by_id[pid] = p
            enriched: list[dict[str, Any]] = []
            for p in by_id.values():
                pid = str(p["id"])
                blocks = self._list_blocks(client, pid)
                p = {**p, "_blocks": blocks}
                enriched.append(p)
        return _records_from_payload(enriched, since=since)

    def _query_database(
        self,
        client: httpx.Client,
        database_id: str,
        since: datetime | None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"page_size": 50}
        cutoff = _parse_since(since)
        if cutoff is not None:
            body["filter"] = {
                "timestamp": "last_edited_time",
                "last_edited_time": {
                    "on_or_after": cutoff.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                },
            }
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            payload = dict(body)
            if cursor:
                payload["start_cursor"] = cursor
            r = client.post(f"{NOTION_API}/databases/{database_id}/query", json=payload)
            r.raise_for_status()
            data = r.json()
            for row in data.get("results") or []:
                if isinstance(row, dict):
                    results.append(row)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return results

    def _get_page(self, client: httpx.Client, page_id: str) -> dict[str, Any] | None:
        pid = re.sub(r"[^0-9a-fA-F-]", "", page_id)
        r = client.get(f"{NOTION_API}/pages/{pid}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else None

    def _list_blocks(self, client: httpx.Client, block_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            r = client.get(f"{NOTION_API}/blocks/{block_id}/children", params=params)
            r.raise_for_status()
            data = r.json()
            for row in data.get("results") or []:
                if isinstance(row, dict):
                    results.append(row)
                    # One level of children for nested blocks (lightweight L0).
                    if row.get("has_children") and row.get("id"):
                        try:
                            results.extend(self._list_blocks(client, str(row["id"])))
                        except httpx.HTTPError:
                            pass
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return results


def default_fixture_path() -> Path:
    return _FIXTURE_PATH
