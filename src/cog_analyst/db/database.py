"""SQLite persistence: connection setup, schema init, and insert functions.

These are pure functions over a ``sqlite3.Connection`` rather than a god-object
store, so the write path stays small and auditable. Persistence writes validated
rows *as-is*: no dedup, no canonicalization, no entity guarding. Those belong to
the separate scrub process. All SQL is parameterized; values are never
string-formatted into statements.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

from cog_analyst.models.schemas import (
    AircraftSpecification,
    OutpostInfrastructure,
    RadarSpecification,
    WeaponSpecification,
)

__all__ = [
    "connect",
    "initialize_database",
    "insert_weapon",
    "insert_aircraft",
    "insert_radar",
    "insert_outpost",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS weapon_specifications (
    designator      TEXT    PRIMARY KEY,
    max_range_km    INTEGER NOT NULL,
    source_citation TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS aircraft_specifications (
    designator       TEXT    PRIMARY KEY,
    combat_radius_km INTEGER,
    source_citation  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS radar_specifications (
    designator             TEXT    PRIMARY KEY,
    max_detection_range_km INTEGER,
    source_citation        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS outpost_infrastructure (
    reef_name            TEXT    PRIMARY KEY,
    runway_length_meters INTEGER,
    fighter_hangar_count INTEGER
);

CREATE TABLE IF NOT EXISTS outpost_weapons (
    reef_name         TEXT NOT NULL,
    weapon_designator TEXT NOT NULL,
    PRIMARY KEY (reef_name, weapon_designator),
    FOREIGN KEY (reef_name) REFERENCES outpost_infrastructure (reef_name)
);

CREATE TABLE IF NOT EXISTS outpost_aircraft (
    reef_name           TEXT NOT NULL,
    aircraft_designator TEXT NOT NULL,
    PRIMARY KEY (reef_name, aircraft_designator),
    FOREIGN KEY (reef_name) REFERENCES outpost_infrastructure (reef_name)
);

CREATE TABLE IF NOT EXISTS outpost_radar (
    reef_name        TEXT NOT NULL,
    radar_designator TEXT NOT NULL,
    PRIMARY KEY (reef_name, radar_designator),
    FOREIGN KEY (reef_name) REFERENCES outpost_infrastructure (reef_name)
);
"""


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


def initialize_database(conn: sqlite3.Connection) -> None:
    """Create all tables idempotently. Safe to call repeatedly."""
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(_SCHEMA)
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise


def insert_weapon(conn: sqlite3.Connection, weapon: WeaponSpecification) -> str:
    """Upsert a weapon catalog row keyed on ``designator``. Returns designator."""
    try:
        conn.execute(
            """
            INSERT INTO weapon_specifications (designator, max_range_km, source_citation)
            VALUES (?, ?, ?)
            ON CONFLICT(designator) DO UPDATE SET
                max_range_km = excluded.max_range_km,
                source_citation = excluded.source_citation
            """,
            (weapon.designator, weapon.max_range_km, weapon.source_citation),
        )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return weapon.designator


def insert_aircraft(conn: sqlite3.Connection, aircraft: AircraftSpecification) -> str:
    """Upsert an aircraft catalog row keyed on ``designator``. Returns designator."""
    try:
        conn.execute(
            """
            INSERT INTO aircraft_specifications (designator, combat_radius_km, source_citation)
            VALUES (?, ?, ?)
            ON CONFLICT(designator) DO UPDATE SET
                combat_radius_km = excluded.combat_radius_km,
                source_citation = excluded.source_citation
            """,
            (aircraft.designator, aircraft.combat_radius_km, aircraft.source_citation),
        )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return aircraft.designator


def insert_radar(conn: sqlite3.Connection, radar: RadarSpecification) -> str:
    """Upsert a radar catalog row keyed on ``designator``. Returns designator."""
    try:
        conn.execute(
            """
            INSERT INTO radar_specifications (designator, max_detection_range_km, source_citation)
            VALUES (?, ?, ?)
            ON CONFLICT(designator) DO UPDATE SET
                max_detection_range_km = excluded.max_detection_range_km,
                source_citation = excluded.source_citation
            """,
            (radar.designator, radar.max_detection_range_km, radar.source_citation),
        )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return radar.designator


def insert_outpost(conn: sqlite3.Connection, outpost: OutpostInfrastructure) -> str:
    """Upsert the hub row and its raw capability links in one transaction.

    Link rows are written verbatim (``INSERT OR IGNORE``) from the schema's three
    designator lists; reconciliation to canonical catalog rows happens downstream
    against the WEG ground-truth store. Returns the reef name.
    """
    try:
        conn.execute(
            """
            INSERT INTO outpost_infrastructure (reef_name, runway_length_meters, fighter_hangar_count)
            VALUES (?, ?, ?)
            ON CONFLICT(reef_name) DO UPDATE SET
                runway_length_meters = excluded.runway_length_meters,
                fighter_hangar_count = excluded.fighter_hangar_count
            """,
            (
                outpost.reef_name,
                outpost.runway_length_meters,
                outpost.fighter_hangar_count,
            ),
        )

        for designator in outpost.verified_deployed_weapons:
            conn.execute(
                """
                INSERT OR IGNORE INTO outpost_weapons (reef_name, weapon_designator)
                VALUES (?, ?)
                """,
                (outpost.reef_name, designator),
            )
        for designator in outpost.deployed_aircraft:
            conn.execute(
                """
                INSERT OR IGNORE INTO outpost_aircraft (reef_name, aircraft_designator)
                VALUES (?, ?)
                """,
                (outpost.reef_name, designator),
            )
        for designator in outpost.deployed_radar:
            conn.execute(
                """
                INSERT OR IGNORE INTO outpost_radar (reef_name, radar_designator)
                VALUES (?, ?)
                """,
                (outpost.reef_name, designator),
            )

        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return outpost.reef_name
