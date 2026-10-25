"""Shared connector contract. Connectors must not import serve/ or lake/."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class PullRecord:
    """One unit pulled from a platform before raw write + lake upsert.

    `raw` is the JSON-serializable platform payload stored under raw_uri.
    Connectors do not compute content_sha256 / raw_uri — lake raw_store does.
    """

    item_id: str
    connector_id: str
    kind: str
    title: str | None
    url: str | None
    captured_at: str
    text: str
    raw: dict[str, Any]
    provenance: dict[str, Any] = field(
        default_factory=lambda: {"source": "platform", "human_reviewed": False}
    )
    valid_from: str | None = None
    valid_to: str | None = None


@runtime_checkable
class Connector(Protocol):
    connector_id: str

    def pull(self, since: datetime | None = None) -> list[PullRecord]:
        """Fetch records changed at/after `since` (inclusive). None = full pull."""
        ...

    def health(self) -> dict[str, Any]:
        """Lightweight readiness check (no secrets in return value)."""
        ...
