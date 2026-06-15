"""Hybrid document-relational store for high-variance asset documents.

Core identity is relational and strict: ``asset_title`` is a UNIQUE primary key
that blocks duplicate records at the database level. The unpredictable,
per-domain layout sections are not modeled as columns; they live in a single
``dynamic_payload`` TEXT column as a stringified JSON object. Writes use an
idempotent UPSERT so re-ingesting a document cleanly overwrites its record.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from cog_analyst.ingestion.weg_pdf import AssetRecord

__all__ = [
    "WEG_SCHEMA",
    "initialize_document_store",
    "upsert_asset",
    "get_asset",
    "asset_count",
]

WEG_SCHEMA = """
CREATE TABLE IF NOT EXISTS weg_assets (
    asset_title     TEXT PRIMARY KEY,
    source_url      TEXT,
    notes           TEXT,
    dynamic_payload TEXT NOT NULL
);
"""


def initialize_document_store(conn: sqlite3.Connection) -> None:
    """Create the ``weg_assets`` table idempotently."""
    try:
        conn.executescript(WEG_SCHEMA)
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise


def upsert_asset(conn: sqlite3.Connection, record: "AssetRecord") -> str:
    """Insert or update one asset by title; returns the asset title.

    The UNIQUE primary key on ``asset_title`` means a re-ingest overwrites the
    prior record (and its JSON payload) instead of duplicating it.
    """
    title, source_url, notes, payload_json = record.to_row()
    try:
        conn.execute(
            """
            INSERT INTO weg_assets (asset_title, source_url, notes, dynamic_payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(asset_title) DO UPDATE SET
                source_url = excluded.source_url,
                notes = excluded.notes,
                dynamic_payload = excluded.dynamic_payload
            """,
            (title, source_url, notes, payload_json),
        )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return title


def get_asset(conn: sqlite3.Connection, asset_title: str) -> Optional[Dict[str, Any]]:
    """Fetch one asset, parsing its JSON payload back into a dict."""
    row = conn.execute(
        "SELECT asset_title, source_url, notes, dynamic_payload "
        "FROM weg_assets WHERE asset_title = ?",
        (asset_title,),
    ).fetchone()
    if row is None:
        return None
    return {
        "asset_title": row["asset_title"],
        "source_url": row["source_url"],
        "notes": row["notes"],
        "payload": json.loads(row["dynamic_payload"]),
    }


def asset_count(conn: sqlite3.Connection) -> int:
    """Return the number of stored assets."""
    row = conn.execute("SELECT COUNT(*) AS n FROM weg_assets").fetchone()
    return int(row["n"] if isinstance(row, sqlite3.Row) else row[0])
