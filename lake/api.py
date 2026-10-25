"""Compatibility re-exports — prefer lake.query for new code."""
from lake.query import get, pack, pack_work, search

__all__ = ["get", "pack", "pack_work", "search"]
