"""Read-only, agent-facing queries over the PLA air OOB store.

These double as **agent tools** and complete the capability-to-laydown join the
COG workflow needs:

  * ``units_for_aircraft`` answers "who fields type X, and from where" — the
    bridge from a WEG capability (combat radius, payload) to real units/bases.
  * ``search_units`` / ``role_breakdown`` / ``aircraft_inventory`` answer
    set-level laydown questions (by service, theater, role, or type).

Everything is read-only and parameterized. Grounding contract for callers:
answer only from what these return, and cite the row's ``source_url``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

__all__ = [
    "UnitHit",
    "search_units",
    "units_for_aircraft",
    "aircraft_inventory",
    "role_breakdown",
    "list_theaters",
]


@dataclass(frozen=True)
class UnitHit:
    """A laydown search result: unit identity, location, and its aircraft."""

    unit_key: str
    unit_name: Optional[str]
    service: Optional[str]
    role: Optional[str]
    theater_command: Optional[str]
    location_text: Optional[str]
    airbase: Optional[str]
    tactical_code: Optional[str]
    source_url: Optional[str]
    aircraft: List[str]


def _like(value: str) -> str:
    return f"%{value.lower()}%"


def _hits_from_rows(conn: sqlite3.Connection, rows: List[sqlite3.Row]) -> List[UnitHit]:
    """Attach each unit's aircraft list and build :class:`UnitHit` objects."""
    hits: List[UnitHit] = []
    for row in rows:
        aircraft = conn.execute(
            "SELECT raw_designator FROM unit_aircraft "
            "WHERE unit_key = ? ORDER BY raw_designator",
            (row["unit_key"],),
        ).fetchall()
        hits.append(
            UnitHit(
                unit_key=row["unit_key"],
                unit_name=row["unit_name"],
                service=row["service"],
                role=row["role"],
                theater_command=row["theater_command"],
                location_text=row["location_text"],
                airbase=row["airbase"],
                tactical_code=row["tactical_code"],
                source_url=row["source_url"],
                aircraft=[a["raw_designator"] for a in aircraft],
            )
        )
    return hits


def search_units(
    conn: sqlite3.Connection,
    *,
    service: Optional[str] = None,
    role: Optional[str] = None,
    theater: Optional[str] = None,
    location_contains: Optional[str] = None,
    limit: Optional[int] = 50,
) -> List[UnitHit]:
    """Filter units by service, role, theater, and/or garrison substring.

    All filters are optional and case-insensitive; results are ordered by unit
    name. Pass ``limit=None`` to remove the cap.
    """
    sql = ["SELECT * FROM units"]
    clauses: List[str] = []
    params: List[Any] = []
    if service:
        clauses.append("LOWER(service) LIKE ?")
        params.append(_like(service))
    if role:
        clauses.append("LOWER(role) LIKE ?")
        params.append(_like(role))
    if theater:
        clauses.append("LOWER(theater_command) LIKE ?")
        params.append(_like(theater))
    if location_contains:
        clauses.append("LOWER(location_text) LIKE ?")
        params.append(_like(location_contains))
    if clauses:
        sql.append("WHERE " + " AND ".join(clauses))
    sql.append("ORDER BY unit_name")
    if limit is not None:
        sql.append("LIMIT ?")
        params.append(int(limit))

    rows = conn.execute("\n".join(sql), params).fetchall()
    return _hits_from_rows(conn, rows)


def units_for_aircraft(
    conn: sqlite3.Connection, designator: str, *, limit: Optional[int] = 100
) -> List[UnitHit]:
    """Return units that field a given aircraft type (the key COG join).

    ``designator`` matches the Latin (``J-20``), Chinese (``歼-20``), or raw
    (``歼-20A``) form, case-insensitively, so an agent can pass whatever a WEG
    lookup yielded. Results are deduplicated by unit and ordered by name.
    """
    needle = _like(designator)
    rows = conn.execute(
        """
        SELECT DISTINCT u.*
        FROM units AS u
        JOIN unit_aircraft AS ua ON ua.unit_key = u.unit_key
        WHERE LOWER(ua.en_designator) LIKE ?
           OR LOWER(ua.cn_designator) LIKE ?
           OR LOWER(ua.raw_designator) LIKE ?
        ORDER BY u.unit_name
        """
        + ("\nLIMIT ?" if limit is not None else ""),
        ([needle, needle, needle] + ([int(limit)] if limit is not None else [])),
    ).fetchall()
    return _hits_from_rows(conn, rows)


def aircraft_inventory(
    conn: sqlite3.Connection, *, service: Optional[str] = None
) -> Dict[str, int]:
    """Count fielding units per aircraft (``{en_designator: unit_count}``).

    Uses the Latin base designator so variants collapse together (``歼-10A`` and
    ``歼-10C`` both count under ``J-10``). Optionally restrict to one service.
    Ordered most common first — a quick "what is most widely fielded" view.
    """
    sql = [
        "SELECT COALESCE(ua.en_designator, ua.cn_designator) AS designator,",
        "       COUNT(DISTINCT ua.unit_key) AS n",
        "FROM unit_aircraft AS ua",
        "JOIN units AS u ON u.unit_key = ua.unit_key",
    ]
    params: List[Any] = []
    if service:
        sql.append("WHERE LOWER(u.service) LIKE ?")
        params.append(_like(service))
    sql.append("GROUP BY designator ORDER BY n DESC")
    rows = conn.execute("\n".join(sql), params).fetchall()
    return {(row["designator"] or "(unknown)"): int(row["n"]) for row in rows}


def role_breakdown(
    conn: sqlite3.Connection, *, service: Optional[str] = None
) -> Dict[str, int]:
    """Count units by role (fighter/bomber/uav/...), most common first."""
    sql = ["SELECT role, COUNT(*) AS n FROM units"]
    params: List[Any] = []
    if service:
        sql.append("WHERE LOWER(service) LIKE ?")
        params.append(_like(service))
    sql.append("GROUP BY role ORDER BY n DESC")
    rows = conn.execute("\n".join(sql), params).fetchall()
    return {(row["role"] or "(unknown)"): int(row["n"]) for row in rows}


def list_theaters(conn: sqlite3.Connection) -> Dict[str, int]:
    """Return a ``{theater_command: unit_count}`` map, most common first."""
    rows = conn.execute(
        "SELECT theater_command, COUNT(*) AS n FROM units "
        "GROUP BY theater_command ORDER BY n DESC"
    ).fetchall()
    return {(row["theater_command"] or "(none)"): int(row["n"]) for row in rows}
