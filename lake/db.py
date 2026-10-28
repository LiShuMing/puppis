"""SQLite connection + schema init for the Evidence lake."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def default_db_path() -> Path:
    override = os.environ.get("EVIDPLANE_DB") or os.environ.get("PUPPIS_DB")
    if override:
        return Path(override).expanduser().resolve()
    return (_REPO_ROOT / "data" / "puppis.db").resolve()


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Apply lake/schema.sql (items + FTS5 external-content + sync triggers)."""
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(items)")}
    for name, definition in {
        "provenance_json": "TEXT", "valid_from": "TEXT", "valid_to": "TEXT",
        "content_sha256": "TEXT", "raw_uri": "TEXT",
    }.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE items ADD COLUMN {name} {definition}")
    conn.commit()


def item_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM items WHERE tombstone = 0").fetchone()
    return int(row["n"]) if row else 0
