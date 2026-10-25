"""Local file:// raw object store (S3-compatible layout, L0)."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_raw_root() -> Path:
    override = os.environ.get("EVIDPLANE_RAW_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    home = Path.home() / ".evidplane"
    return home.resolve()


class LocalRawStore:
    """Write immutable raw JSON under sources/<connector>/raw/yyyy/mm/<item_id>.json."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else default_raw_root()

    def path_for(
        self,
        connector_id: str,
        item_id: str,
        *,
        when: datetime | None = None,
    ) -> Path:
        when = when or datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        yyyy = f"{when.year:04d}"
        mm = f"{when.month:02d}"
        safe_id = item_id.replace("/", "_")
        return (
            self.root
            / "sources"
            / connector_id
            / "raw"
            / yyyy
            / mm
            / f"{safe_id}.json"
        )

    def write(
        self,
        connector_id: str,
        item_id: str,
        payload: dict[str, Any] | bytes | str,
        *,
        when: datetime | None = None,
    ) -> tuple[str, str]:
        """Serialize payload, write once, return (content_sha256, file:// uri)."""
        if isinstance(payload, bytes):
            data = payload
        elif isinstance(payload, str):
            data = payload.encode("utf-8")
        else:
            data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode(
                "utf-8"
            )
        digest = hashlib.sha256(data).hexdigest()
        path = self.path_for(connector_id, item_id, when=when)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Immutable: skip rewrite if identical hash already on disk.
        if path.is_file():
            existing = path.read_bytes()
            if hashlib.sha256(existing).hexdigest() == digest:
                return digest, path.as_uri()
        path.write_bytes(data)
        return digest, path.as_uri()

    def write_error(
        self,
        connector_id: str,
        name: str,
        payload: dict[str, Any],
        *,
        when: datetime | None = None,
    ) -> str:
        when = when or datetime.now(timezone.utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        path = (
            self.root
            / "sources"
            / connector_id
            / "errors"
            / f"{when.year:04d}"
            / f"{when.month:02d}"
            / f"{name}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path.as_uri()
