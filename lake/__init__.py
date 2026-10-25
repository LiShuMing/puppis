"""Lake: Evidence index + pack compiler. No platform API calls."""

from lake.api import get, pack, search
from lake.db import connect, default_db_path, init_db

__all__ = ["connect", "default_db_path", "get", "init_db", "pack", "search"]
