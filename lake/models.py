"""Shared Evidence contract (connectors → lake)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    item_id: str
    connector_id: str
    kind: str
    title: str | None = None
    url: str | None = None
    captured_at: str
    valid_from: str | None = None
    valid_to: str | None = None
    content_sha256: str
    raw_uri: str | None = None
    text: str = ""
    provenance: dict[str, Any] = Field(
        default_factory=lambda: {"source": "platform", "human_reviewed": False}
    )


ProvenanceSource = Literal["platform", "agent", "export"]
