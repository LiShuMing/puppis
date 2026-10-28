"""Notion adapter: pull(since) → PullRecord[] via REST or offline fixture."""
from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from connectors.base import PullRecord

NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"
CONNECTOR_ID = "notion"
_FIXTURE_PATH = Path(__file__).with_name("demo_pull.json")

# Retries after the first attempt. Total attempts = 1 + max_retries.
_DEFAULT_MAX_RETRIES = 4
_DEFAULT_RETRY_BASE = 0.5
_DEFAULT_RETRY_MAX = 8.0


class NotionConfigError(RuntimeError):
    """Raised when required Notion env/config is missing or invalid."""


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


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


def records_from_payload(
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


def _sanitize_page_id(page_id: str) -> str:
    return re.sub(r"[^0-9a-fA-F-]", "", page_id)


def _page_id_last4(page_id: str) -> str:
    clean = str(page_id).replace("-", "")
    return clean[-4:] if len(clean) >= 4 else clean


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
        max_retries: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        sleep: Callable[[float], None] | None = None,
        transport: httpx.BaseTransport | None = None,
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
        self._max_retries = (
            max_retries
            if max_retries is not None
            else _env_int("NOTION_HTTP_MAX_RETRIES", _DEFAULT_MAX_RETRIES)
        )
        self._retry_base = (
            retry_base_seconds
            if retry_base_seconds is not None
            else _env_float("NOTION_HTTP_RETRY_BASE_SECONDS", _DEFAULT_RETRY_BASE)
        )
        self._retry_max = (
            retry_max_seconds
            if retry_max_seconds is not None
            else _env_float("NOTION_HTTP_RETRY_MAX_SECONDS", _DEFAULT_RETRY_MAX)
        )
        self._sleep: Callable[[float], None] = sleep if sleep is not None else time.sleep
        self._transport = transport
        # Cleared at the start of each pull(); structured, no secrets.
        self.last_errors: list[dict[str, Any]] = []
        # Observability for smoke (does not include secrets).
        self.last_http_attempts: int = 0
        self.last_retry_sleeps: list[float] = []

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
            "http_max_retries": self._max_retries,
            "http_retry_base_seconds": self._retry_base,
            "http_retry_max_seconds": self._retry_max,
        }

    def pull(self, since: datetime | None = None) -> list[PullRecord]:
        self.last_errors = []
        self.last_http_attempts = 0
        self.last_retry_sleeps = []
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
        return records_from_payload(pages, since=since)

    def _headers(self) -> dict[str, str]:
        # Never log this dict.
        assert self._token
        return {
            "Authorization": f"Bearer {self._token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _client_kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "timeout": self._timeout,
            "headers": self._headers(),
        }
        if self._transport is not None:
            kw["transport"] = self._transport
        return kw

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        """Backoff seconds before the next attempt (attempt is 0-indexed failed try)."""
        if response is not None:
            ra = response.headers.get("Retry-After")
            if ra is not None:
                try:
                    return max(0.0, float(ra))
                except ValueError:
                    pass
        # Exponential: base * 2^attempt, capped, light jitter.
        delay = min(self._retry_max, self._retry_base * (2**attempt))
        jitter = delay * 0.1 * random.random()
        return min(self._retry_max, delay + jitter)

    def _request(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """HTTP with retries on 429 / 5xx and transport errors.

        ``NOTION_HTTP_MAX_RETRIES`` = retries *after* the first attempt
        (total attempts = 1 + max_retries). Never logs headers/token.
        """
        last_exc: Exception | None = None
        last_resp: httpx.Response | None = None
        attempts = self._max_retries + 1
        for attempt in range(attempts):
            self.last_http_attempts += 1
            try:
                resp = client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    break
                delay = self._retry_delay(attempt, None)
                self.last_retry_sleeps.append(delay)
                self._sleep(delay)
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                last_resp = resp
                if attempt >= self._max_retries:
                    resp.raise_for_status()
                    return resp  # pragma: no cover — raise_for_status always raises
                delay = self._retry_delay(attempt, resp)
                self.last_retry_sleeps.append(delay)
                self._sleep(delay)
                continue

            return resp

        if last_resp is not None:
            last_resp.raise_for_status()
        assert last_exc is not None
        raise last_exc

    def _record_page_error(
        self,
        *,
        page_id: str,
        stage: str,
        error: str,
        message: str,
        status: int | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "stage": stage,
            "page_id_last4": _page_id_last4(page_id),
            "page_id_len": len(str(page_id).replace("-", "")),
            "error": error,
            "message": message[:500],
        }
        # Keep a sanitized id form for smoke asserts (no token).
        entry["page_id"] = _sanitize_page_id(page_id)
        if status is not None:
            entry["status"] = status
        self.last_errors.append(entry)

    def _pull_api(self, since: datetime | None) -> list[PullRecord]:
        pages: list[dict[str, Any]] = []
        with httpx.Client(**self._client_kwargs()) as client:
            if self._database_id:
                try:
                    pages.extend(self._query_database(client, self._database_id, since))
                except Exception as exc:
                    # DB query is a hard failure for that source; record + re-raise
                    # so callers without page_ids still see a failed pull.
                    self._record_page_error(
                        page_id=self._database_id,
                        stage="database_query",
                        error=type(exc).__name__,
                        message=str(exc),
                    )
                    if not self._page_ids:
                        raise
                    # With page_ids present, continue pages; DB miss is in last_errors.

            for pid in self._page_ids:
                stage = "get_page"
                try:
                    page = self._get_page(client, pid)
                    if page is None:
                        self._record_page_error(
                            page_id=pid,
                            stage="get_page",
                            error="NotFound",
                            message="page not found (404)",
                            status=404,
                        )
                        continue
                    block_id = str(page.get("id") or pid)
                    stage = "list_blocks"
                    blocks = self._list_blocks(client, block_id)
                    pages.append({**page, "_blocks": blocks})
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code if exc.response is not None else None
                    self._record_page_error(
                        page_id=pid,
                        stage=stage,
                        error="HTTPStatusError",
                        message=str(exc),
                        status=status,
                    )
                except Exception as exc:
                    self._record_page_error(
                        page_id=pid,
                        stage=stage,
                        error=type(exc).__name__,
                        message=str(exc),
                    )

            # Dedupe by id; enrich blocks for database rows that lack _blocks.
            by_id: dict[str, dict[str, Any]] = {}
            for p in pages:
                pid = str(p.get("id") or "")
                if pid:
                    by_id[pid] = p
            enriched: list[dict[str, Any]] = []
            for p in by_id.values():
                if "_blocks" in p:
                    enriched.append(p)
                    continue
                pid = str(p["id"])
                try:
                    blocks = self._list_blocks(client, pid)
                    enriched.append({**p, "_blocks": blocks})
                except Exception as exc:
                    self._record_page_error(
                        page_id=pid,
                        stage="list_blocks",
                        error=type(exc).__name__,
                        message=str(exc),
                    )
        return records_from_payload(enriched, since=since)

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
            r = self._request(
                client, "POST", f"{NOTION_API}/databases/{database_id}/query", json=payload
            )
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
        pid = _sanitize_page_id(page_id)
        r = self._request(client, "GET", f"{NOTION_API}/pages/{pid}")
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
            r = self._request(
                client, "GET", f"{NOTION_API}/blocks/{block_id}/children", params=params
            )
            r.raise_for_status()
            data = r.json()
            for row in data.get("results") or []:
                if isinstance(row, dict):
                    results.append(row)
                    # Capture nested children; a failed subtree fails this page.
                    if row.get("has_children") and row.get("id"):
                        results.extend(self._list_blocks(client, str(row["id"])))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return results


def default_fixture_path() -> Path:
    return _FIXTURE_PATH
