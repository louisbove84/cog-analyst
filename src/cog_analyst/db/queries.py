"""Read-only queries over the cog-analyst SQLite schema.

Kept separate from ``database.py`` (which only writes) so the read and write
surfaces stay decoupled. All functions take a ``sqlite3.Connection`` and never
mutate. Table identifiers used in PRAGMA/SELECT are validated against a fixed
allowlist so no caller can inject arbitrary identifiers.
"""

from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional

from cog_analyst.models.schemas import (
    AircraftSpecification,
    RadarSpecification,
    WeaponSpecification,
)

__all__ = [
    "ALL_TABLES",
    "counts",
    "get_column_type",
    "get_weapon",
    "get_aircraft",
    "get_radar",
    "get_outpost_weapons",
    "get_outpost_aircraft",
    "get_outpost_radar",
]

ALL_TABLES = (
    "weapon_specifications",
    "aircraft_specifications",
    "radar_specifications",
    "outpost_infrastructure",
    "outpost_weapons",
    "outpost_aircraft",
    "outpost_radar",
)

# Maps the three outpost link tables to their designator column.
_LINK_COLUMNS = {
    "outpost_weapons": "weapon_designator",
    "outpost_aircraft": "aircraft_designator",
    "outpost_radar": "radar_designator",
}


def _require_known_table(table: str) -> str:
    if table not in ALL_TABLES:
        raise ValueError(f"unknown table: {table!r}")
    return table


def counts(conn: sqlite3.Connection) -> Dict[str, int]:
    """Return row counts for every table, keyed by table name."""
    result: Dict[str, int] = {}
    for table in ALL_TABLES:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        result[table] = int(row["n"] if isinstance(row, sqlite3.Row) else row[0])
    return result


def get_column_type(conn: sqlite3.Connection, table: str, column: str) -> Optional[str]:
    """Return the declared SQL type of ``column`` in ``table`` (or None)."""
    _require_known_table(table)
    for row in conn.execute(f"PRAGMA table_info({table})").fetchall():
        if row["name"] == column:
            return row["type"]
    return None


def get_weapon(conn: sqlite3.Connection, designator: str) -> Optional[WeaponSpecification]:
    row = conn.execute(
        "SELECT designator, max_range_km, source_citation "
        "FROM weapon_specifications WHERE designator = ?",
        (designator,),
    ).fetchone()
    if row is None:
        return None
    return WeaponSpecification(
        designator=row["designator"],
        max_range_km=row["max_range_km"],
        source_citation=row["source_citation"],
    )


def get_aircraft(conn: sqlite3.Connection, designator: str) -> Optional[AircraftSpecification]:
    row = conn.execute(
        "SELECT designator, combat_radius_km, source_citation "
        "FROM aircraft_specifications WHERE designator = ?",
        (designator,),
    ).fetchone()
    if row is None:
        return None
    return AircraftSpecification(
        designator=row["designator"],
        combat_radius_km=row["combat_radius_km"],
        source_citation=row["source_citation"],
    )


def get_radar(conn: sqlite3.Connection, designator: str) -> Optional[RadarSpecification]:
    row = conn.execute(
        "SELECT designator, max_detection_range_km, source_citation "
        "FROM radar_specifications WHERE designator = ?",
        (designator,),
    ).fetchone()
    if row is None:
        return None
    return RadarSpecification(
        designator=row["designator"],
        max_detection_range_km=row["max_detection_range_km"],
        source_citation=row["source_citation"],
    )


def _linked_designators(conn: sqlite3.Connection, table: str, reef_name: str) -> List[str]:
    column = _LINK_COLUMNS[table]
    rows = conn.execute(
        f"SELECT {column} AS designator FROM {table} "
        "WHERE reef_name = ? ORDER BY designator",
        (reef_name,),
    ).fetchall()
    return [row["designator"] for row in rows]


def get_outpost_weapons(conn: sqlite3.Connection, reef_name: str) -> List[str]:
    return _linked_designators(conn, "outpost_weapons", reef_name)


def get_outpost_aircraft(conn: sqlite3.Connection, reef_name: str) -> List[str]:
    return _linked_designators(conn, "outpost_aircraft", reef_name)


def get_outpost_radar(conn: sqlite3.Connection, reef_name: str) -> List[str]:
    return _linked_designators(conn, "outpost_radar", reef_name)
