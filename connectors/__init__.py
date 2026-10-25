"""Connectors: pull(since) → PullRecord[] (lake writes raw + upserts Evidence)."""

from connectors.base import Connector, PullRecord

__all__ = ["Connector", "PullRecord"]
