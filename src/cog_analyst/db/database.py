"""SQLite connection helper shared by all stores."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

__all__ = ["connect"]


def connect(db_path: Union[str, Path]) -> sqlite3.Connection:
    """Open a configured SQLite connection, creating the parent dir if needed.

    Uses ``sqlite3.Row`` so callers can read columns by name. Enables foreign
    keys for this connection (SQLite defaults them off per-connection).
    """
    path = Path(db_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn
