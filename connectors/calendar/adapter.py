"""Calendar adapter: pull(since) → PullRecord[] via fixture, ICS, or Google API stub."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from connectors.base import PullRecord

CONNECTOR_ID = "google_calendar"
_FIXTURE_PATH = Path(__file__).with_name("demo_pull.json")


class CalendarConfigError(RuntimeError):
    """Raised when required calendar config is missing or invalid."""


def _parse_since(since: datetime | None) -> datetime | None:
    if since is None:
        return None
    if since.tzinfo is None:
        return since.replace(tzinfo=timezone.utc)
    return since.astimezone(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # All-day dates: YYYY-MM-DD
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        s = s + "T00:00:00+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _item_id_for(event_id: str) -> str:
    clean = re.sub(r"[^0-9a-zA-Z_-]", "_", str(event_id)).lower()
    return f"cal_evt_{clean}"


def _event_start_iso(event: dict[str, Any]) -> str | None:
    start = event.get("start")
    if isinstance(start, dict):
        return start.get("dateTime") or start.get("date")
    if isinstance(start, str):
        return start
    return event.get("dtstart") or event.get("DTSTART")


def _event_end_iso(event: dict[str, Any]) -> str | None:
    end = event.get("end")
    if isinstance(end, dict):
        return end.get("dateTime") or end.get("date")
    if isinstance(end, str):
        return end
    return event.get("dtend") or event.get("DTEND")


def _event_updated_iso(event: dict[str, Any]) -> str:
    for key in ("updated", "last_edited_time", "created", "created_time"):
        if event.get(key):
            return str(event[key])
    start = _event_start_iso(event)
    if start:
        return str(start)
    return datetime.now(timezone.utc).isoformat()


def _event_to_record(event: dict[str, Any]) -> PullRecord:
    eid = str(event.get("id") or event.get("uid") or event.get("UID") or "unknown")
    title = (
        event.get("summary")
        or event.get("SUMMARY")
        or event.get("title")
        or f"Event {eid[:12]}"
    )
    desc = event.get("description") or event.get("DESCRIPTION") or ""
    url = event.get("htmlLink") or event.get("url") or event.get("URL")
    start = _event_start_iso(event)
    end = _event_end_iso(event)
    text_parts = [str(title)]
    if start:
        text_parts.append(f"start: {start}")
    if end:
        text_parts.append(f"end: {end}")
    if desc:
        text_parts.append(str(desc).strip())
    text = "\n".join(text_parts)
    return PullRecord(
        item_id=_item_id_for(eid),
        connector_id=CONNECTOR_ID,
        kind="event",
        title=str(title),
        url=str(url) if url else None,
        captured_at=_event_updated_iso(event),
        text=text,
        raw=event,
        provenance={"source": "platform", "human_reviewed": False},
        valid_from=str(start) if start else None,
        valid_to=str(end) if end else None,
    )


def _records_from_events(
    events: list[dict[str, Any]],
    *,
    since: datetime | None,
) -> list[PullRecord]:
    cutoff = _parse_since(since)
    out: list[PullRecord] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        rec = _event_to_record(event)
        if cutoff is not None:
            # Prefer updated; fall back to start
            stamp = _parse_iso(rec.captured_at) or _parse_iso(rec.valid_from)
            if stamp is not None and stamp < cutoff:
                continue
        out.append(rec)
    return out


# --- minimal ICS parser (VEVENT only) ---

def _unfold_ics(text: str) -> str:
    # RFC 5545 line folding: CRLF + space/tab continuation
    return re.sub(r"\r?\n[ \t]", "", text)


def _parse_ics_vevents(text: str) -> list[dict[str, Any]]:
    text = _unfold_ics(text)
    events: list[dict[str, Any]] = []
    blocks = re.split(r"(?i)BEGIN:VEVENT", text)
    for block in blocks[1:]:
        end = re.search(r"(?i)END:VEVENT", block)
        body = block[: end.start()] if end else block
        fields: dict[str, str] = {}
        for line in body.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            name, _, value = line.partition(":")
            name = name.split(";", 1)[0].upper()
            fields[name] = value.strip()
        if not fields:
            continue
        uid = fields.get("UID") or fields.get("SUMMARY") or f"ics_{len(events)}"
        start_raw = fields.get("DTSTART")
        end_raw = fields.get("DTEND")
        event: dict[str, Any] = {
            "id": uid,
            "uid": uid,
            "summary": fields.get("SUMMARY"),
            "description": fields.get("DESCRIPTION", "").replace("\\n", "\n"),
            "url": fields.get("URL"),
            "status": (fields.get("STATUS") or "confirmed").lower(),
            "updated": fields.get("LAST-MODIFIED") or fields.get("DTSTAMP") or start_raw,
            "start": _ics_dt_to_google_shape(start_raw),
            "end": _ics_dt_to_google_shape(end_raw),
            "_source": "ics",
        }
        events.append(event)
    return events


def _ics_dt_to_google_shape(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    v = value.strip()
    # date only YYYYMMDD
    if re.fullmatch(r"\d{8}", v):
        return {"date": f"{v[0:4]}-{v[4:6]}-{v[6:8]}"}
    # YYYYMMDDTHHMMSSZ or with TZID already stripped
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z?", v)
    if m:
        y, mo, d, h, mi, s = m.groups()
        suffix = "Z" if v.endswith("Z") else ""
        iso = f"{y}-{mo}-{d}T{h}:{mi}:{s}"
        if suffix:
            iso += "+00:00"
        return {"dateTime": iso}
    # already ISO-ish
    if "T" in v or "-" in v:
        return {"dateTime": v}
    return {"dateTime": v}


class CalendarConnector:
    """pull(since) from fixture JSON, ICS file/URL, or Google Calendar API (stub)."""

    connector_id = CONNECTOR_ID

    def __init__(
        self,
        *,
        fixture_path: str | Path | None = None,
        ics_path: str | Path | None = None,
        ics_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._fixture_path = Path(fixture_path) if fixture_path else None
        env_ics = os.environ.get("CALENDAR_ICS_PATH") or os.environ.get(
            "GOOGLE_CALENDAR_ICS_PATH"
        )
        self._ics_path = Path(ics_path) if ics_path else (
            Path(env_ics) if env_ics else None
        )
        self._ics_url = ics_url or os.environ.get("CALENDAR_ICS_URL")
        self._timeout = timeout
        # API stub markers (never load secrets into health)
        self._has_api_creds = bool(
            os.environ.get("GOOGLE_CALENDAR_CREDENTIALS")
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            or os.environ.get("GOOGLE_CALENDAR_TOKEN")
        )

    def health(self) -> dict[str, Any]:
        if self._fixture_path is not None:
            return {
                "connector_id": self.connector_id,
                "mode": "fixture",
                "ok": self._fixture_path.is_file(),
                "fixture": str(self._fixture_path),
            }
        if self._ics_path is not None or self._ics_url:
            ok = True
            if self._ics_path is not None:
                ok = self._ics_path.is_file()
            return {
                "connector_id": self.connector_id,
                "mode": "ics",
                "ok": ok,
                "has_ics_path": self._ics_path is not None,
                "has_ics_url": bool(self._ics_url),
            }
        return {
            "connector_id": self.connector_id,
            "mode": "api",
            "ok": False,
            "has_credentials": self._has_api_creds,
            "todo": (
                "Google Calendar OAuth not implemented in L0. "
                "Use fixture_path=…/demo_pull.json or CALENDAR_ICS_PATH / "
                "CALENDAR_ICS_URL. API needs GOOGLE_CALENDAR_CREDENTIALS "
                "(OAuth client JSON) + calendar id — see docs/connector-env.md."
            ),
        }

    def pull(self, since: datetime | None = None) -> list[PullRecord]:
        if self._fixture_path is not None:
            return self._pull_fixture(since)
        if self._ics_path is not None or self._ics_url:
            return self._pull_ics(since)
        raise CalendarConfigError(
            "Calendar connector: Google Calendar API not implemented yet (TODO). "
            "Pass fixture_path for offline smoke, or set CALENDAR_ICS_PATH / "
            "CALENDAR_ICS_URL. For live API later: GOOGLE_CALENDAR_CREDENTIALS "
            "+ GOOGLE_CALENDAR_ID (see docs/connector-env.md)."
        )

    def _pull_fixture(self, since: datetime | None) -> list[PullRecord]:
        path = self._fixture_path or _FIXTURE_PATH
        if not path.is_file():
            raise CalendarConfigError(f"Calendar fixture not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        events = data.get("events") if isinstance(data, dict) else data
        if not isinstance(events, list):
            raise CalendarConfigError("Fixture must be {events:[…]} or a list")
        return _records_from_events(events, since=since)

    def _pull_ics(self, since: datetime | None) -> list[PullRecord]:
        if self._ics_path is not None:
            if not self._ics_path.is_file():
                raise CalendarConfigError(f"ICS file not found: {self._ics_path}")
            text = self._ics_path.read_text(encoding="utf-8", errors="replace")
        else:
            assert self._ics_url
            with urlopen(self._ics_url, timeout=self._timeout) as resp:  # noqa: S310
                text = resp.read().decode("utf-8", errors="replace")
        events = _parse_ics_vevents(text)
        return _records_from_events(events, since=since)


def default_fixture_path() -> Path:
    return _FIXTURE_PATH
