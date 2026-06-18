"""Relational store for PLA air order-of-battle (OOB) units.

Unlike the WEG catalog (whose per-asset layout varies, hence a JSON payload),
order-of-battle rows are uniform: a unit has a garrison, a tactical code, and a
set of aircraft. So this is a plain normalized schema — a ``units`` hub and a
``unit_aircraft`` spoke — with the aircraft's ``en_designator`` acting as the
join key back into ``data/weg.db``.

Writes are idempotent: :func:`upsert_unit` UPSERTs the unit row and fully
rebuilds that unit's aircraft links, so re-ingesting the source snapshot
converges instead of duplicating.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from cog_analyst.ingestion.oob_markdown import UnitRecord

__all__ = [
    "OOB_SCHEMA",
    "initialize_oob_store",
    "upsert_unit",
    "get_unit",
    "unit_count",
]

OOB_SCHEMA = """
CREATE TABLE IF NOT EXISTS units (
    unit_key        TEXT PRIMARY KEY,
    unit_name       TEXT,
    service         TEXT,
    branch          TEXT,
    role            TEXT,
    theater_command TEXT,
    location_text   TEXT,
    province        TEXT,
    airbase         TEXT,
    tactical_code   TEXT,
    remarks         TEXT,
    source_url      TEXT
);

CREATE TABLE IF NOT EXISTS unit_aircraft (
    unit_key      TEXT NOT NULL,
    raw_designator TEXT NOT NULL,
    cn_designator TEXT,
    en_designator TEXT,
    PRIMARY KEY (unit_key, raw_designator),
    FOREIGN KEY (unit_key) REFERENCES units(unit_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_unit_aircraft_en
    ON unit_aircraft (en_designator);
"""


def initialize_oob_store(conn: sqlite3.Connection) -> None:
    """Create the ``units`` and ``unit_aircraft`` tables idempotently."""
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(OOB_SCHEMA)
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise


def upsert_unit(conn: sqlite3.Connection, record: UnitRecord) -> str:
    """Insert or update one unit and rebuild its aircraft links atomically.

    The unit row is keyed on ``unit_key``; its aircraft links are deleted and
    re-inserted so a re-ingest reflects the current snapshot exactly. Returns the
    ``unit_key``.
    """
    try:
        conn.execute(
            """
            INSERT INTO units (
                unit_key, unit_name, service, branch, role, theater_command,
                location_text, province, airbase, tactical_code, remarks,
                source_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(unit_key) DO UPDATE SET
                unit_name = excluded.unit_name,
                service = excluded.service,
                branch = excluded.branch,
                role = excluded.role,
                theater_command = excluded.theater_command,
                location_text = excluded.location_text,
                province = excluded.province,
                airbase = excluded.airbase,
                tactical_code = excluded.tactical_code,
                remarks = excluded.remarks,
                source_url = excluded.source_url
            """,
            (
                record.unit_key,
                record.unit_name,
                record.service,
                record.branch,
                record.role,
                record.theater_command,
                record.location_text,
                record.province,
                record.airbase,
                record.tactical_code,
                record.remarks,
                record.source_url,
            ),
        )
        conn.execute("DELETE FROM unit_aircraft WHERE unit_key = ?", (record.unit_key,))
        for aircraft in record.aircraft:
            conn.execute(
                """
                INSERT OR IGNORE INTO unit_aircraft
                    (unit_key, raw_designator, cn_designator, en_designator)
                VALUES (?, ?, ?, ?)
                """,
                (
                    record.unit_key,
                    aircraft.raw,
                    aircraft.cn_base,
                    aircraft.en_base,
                ),
            )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return record.unit_key


def get_unit(conn: sqlite3.Connection, unit_key: str) -> Optional[Dict[str, Any]]:
    """Fetch one unit with its aircraft list, or ``None`` if unknown."""
    row = conn.execute("SELECT * FROM units WHERE unit_key = ?", (unit_key,)).fetchone()
    if row is None:
        return None
    aircraft = conn.execute(
        "SELECT raw_designator, cn_designator, en_designator "
        "FROM unit_aircraft WHERE unit_key = ? ORDER BY raw_designator",
        (unit_key,),
    ).fetchall()
    result = dict(row)
    result["aircraft"] = [dict(a) for a in aircraft]
    return result


def unit_count(conn: sqlite3.Connection) -> int:
    """Return the number of stored units."""
    row = conn.execute("SELECT COUNT(*) AS n FROM units").fetchone()
    return int(row["n"] if isinstance(row, sqlite3.Row) else row[0])
