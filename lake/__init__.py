"""Lake: Evidence index + pack compiler. No platform API calls."""

from lake.db import connect, default_db_path, init_db
from lake.query import get, pack, pack_work, search

__all__ = [
    "connect",
    "default_db_path",
    "get",
    "init_db",
    "pack",
    "pack_work",
    "search",
]
