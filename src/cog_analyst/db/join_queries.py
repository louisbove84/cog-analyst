"""Cross-database joins: WEG capabilities × OOB force laydown.

``data/weg.db`` and ``data/oob.db`` are separate files. These helpers open an
OOB connection and ``ATTACH`` the WEG store as ``weg_db``, then join
``unit_aircraft.en_designator`` to ``weg_assets.asset_title`` so an agent (or
CLI) gets one grounded row per unit/aircraft/WEG-spec triple — the artifact
Node 1 of the COG workflow needs.

Grounding contract: answer only from returned rows; cite ``weg_source_url`` and
``oob_source_url``.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from cog_analyst.ingestion.designator import normalize_designator

__all__ = [
    "LaydownHit",
    "attach_weg",
    "capability_laydown",
    "laydown_payload_slice",
    "laydown_specs",
    "laydown_as_dicts",
    "SPEC_SECTIONS",
]

_WEG_ALIAS = "weg_db"


@dataclass(frozen=True)
class LaydownHit:
    """One unit fielding one aircraft type, optionally linked to a WEG catalog row."""

    unit_key: str
    unit_name: Optional[str]
    service: Optional[str]
    role: Optional[str]
    theater_command: Optional[str]
    location_text: Optional[str]
    airbase: Optional[str]
    raw_designator: str
    cn_designator: Optional[str]
    en_designator: Optional[str]
    weg_asset_title: Optional[str]
    weg_source_url: Optional[str]
    oob_source_url: Optional[str]


def attach_weg(conn: sqlite3.Connection, weg_path: Union[str, Path]) -> None:
    """Attach ``weg_path`` as ``weg_db`` on an existing OOB connection."""
    resolved = str(Path(weg_path).resolve())
    try:
        conn.execute(f"DETACH DATABASE {_WEG_ALIAS}")
    except sqlite3.OperationalError:
        pass
    conn.execute(f"ATTACH DATABASE ? AS {_WEG_ALIAS}", (resolved,))


def _resolve_designator(designator: str) -> Tuple[str, Optional[str]]:
    """Return (needle_for_like, en_base) from Latin, Chinese, or raw input."""
    parts = normalize_designator(designator)
    if parts.en_base:
        return parts.en_base.lower(), parts.en_base
    return designator.lower(), None


def capability_laydown(
    conn: sqlite3.Connection,
    *,
    designator: Optional[str] = None,
    theater: Optional[str] = None,
    role: Optional[str] = None,
    service: Optional[str] = None,
    limit: Optional[int] = 100,
) -> List[LaydownHit]:
    """Join OOB units to WEG specs by aircraft designator.

    ``designator`` accepts Latin (``J-20``), Chinese (``歼-20``), or raw variant
    strings. Filters on theater/role/service are case-insensitive substrings.
    """
    sql = [
        "SELECT",
        "  u.unit_key, u.unit_name, u.service, u.role, u.theater_command,",
        "  u.location_text, u.airbase, u.source_url AS oob_source_url,",
        "  ua.raw_designator, ua.cn_designator, ua.en_designator,",
        "  w.asset_title AS weg_asset_title,",
        "  w.source_url AS weg_source_url",
        "FROM unit_aircraft AS ua",
        "JOIN units AS u ON u.unit_key = ua.unit_key",
        "LEFT JOIN weg_db.weg_assets AS w ON ua.en_designator IS NOT NULL",
        "  AND (",
        "    LOWER(w.asset_title) LIKE LOWER(ua.en_designator) || ' %'",
        "    OR LOWER(w.asset_title) LIKE LOWER(ua.en_designator) || '(%'",
        "    OR LOWER(w.asset_title) = LOWER(ua.en_designator)",
        "  )",
    ]
    clauses: List[str] = []
    params: List[Any] = []

    if designator:
        needle, en_base = _resolve_designator(designator)
        if en_base:
            clauses.append(
                "(LOWER(ua.en_designator) = ? OR LOWER(ua.cn_designator) LIKE ? "
                "OR LOWER(ua.raw_designator) LIKE ?)"
            )
            params.extend([en_base.lower(), f"%{needle}%", f"%{needle}%"])
        else:
            clauses.append(
                "(LOWER(ua.raw_designator) LIKE ? OR LOWER(ua.cn_designator) LIKE ? "
                "OR LOWER(ua.en_designator) LIKE ?)"
            )
            params.extend([f"%{needle}%", f"%{needle}%", f"%{needle}%"])

    if theater:
        clauses.append("LOWER(u.theater_command) LIKE ?")
        params.append(f"%{theater.lower()}%")
    if role:
        clauses.append("LOWER(u.role) LIKE ?")
        params.append(f"%{role.lower()}%")
    if service:
        clauses.append("LOWER(u.service) LIKE ?")
        params.append(f"%{service.lower()}%")

    if clauses:
        sql.append("WHERE " + " AND ".join(clauses))
    sql.append("ORDER BY u.unit_name, ua.raw_designator, w.asset_title")
    if limit is not None:
        sql.append("LIMIT ?")
        params.append(int(limit))

    rows = conn.execute("\n".join(sql), params).fetchall()
    return [
        LaydownHit(
            unit_key=row["unit_key"],
            unit_name=row["unit_name"],
            service=row["service"],
            role=row["role"],
            theater_command=row["theater_command"],
            location_text=row["location_text"],
            airbase=row["airbase"],
            raw_designator=row["raw_designator"],
            cn_designator=row["cn_designator"],
            en_designator=row["en_designator"],
            weg_asset_title=row["weg_asset_title"],
            weg_source_url=row["weg_source_url"],
            oob_source_url=row["oob_source_url"],
        )
        for row in rows
    ]


def laydown_payload_slice(
    conn: sqlite3.Connection, asset_title: str, section: str = "System"
) -> Optional[Any]:
    """Fetch one WEG payload section for a laydown hit (narrow retrieval)."""
    row = conn.execute(
        f"SELECT dynamic_payload FROM {_WEG_ALIAS}.weg_assets WHERE asset_title = ?",
        (asset_title,),
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["dynamic_payload"])
    return payload.get(section)


# WEG sections that carry capability-relevant facts. Performance metrics
# (Maximum Range, Combat Range, Service Ceiling, ...) live under "Automotive",
# identity/armament under "System", size/weight under "Dimensions".
SPEC_SECTIONS = (
    "System",
    "Automotive",
    "Dimensions",
    "Armament",
    "Main Missile Systems",
    "Missile Weapon Systems",
    "Bomb Weapon Systems",
)

# Identity-only keys we drop so the spec block is metrics/armament, not prose.
_SPEC_SKIP_KEYS = {"image sources", "manufacturer", "alternate designation(s)"}


def _flatten_scalars(obj: Any, out: Dict[str, str]) -> None:
    """Collect scalar key/value pairs from a (possibly nested) section."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, (dict, list)):
                _flatten_scalars(value, out)
            elif key.lower().strip() not in _SPEC_SKIP_KEYS:
                out.setdefault(key.strip(), str(value).strip())
    elif isinstance(obj, list):
        for item in obj:
            _flatten_scalars(item, out)


def laydown_specs(conn: sqlite3.Connection, asset_title: str) -> Dict[str, str]:
    """Return a flat ``{spec: value}`` block from the quantitative WEG sections.

    Merges :data:`SPEC_SECTIONS` (performance, dimensions, armament) into one
    flat dict so the agent sees metrics like ``Maximum Range`` / ``Service
    Ceiling`` — which live under ``Automotive``, not ``System``. Location and
    identity prose are excluded so downstream reasoning is not polluted.
    """
    row = conn.execute(
        f"SELECT dynamic_payload FROM {_WEG_ALIAS}.weg_assets WHERE asset_title = ?",
        (asset_title,),
    ).fetchone()
    if row is None:
        return {}
    payload = json.loads(row["dynamic_payload"])
    specs: Dict[str, str] = {}
    for section in SPEC_SECTIONS:
        if section in payload:
            _flatten_scalars(payload[section], specs)
    return specs


def laydown_as_dicts(hits: List[LaydownHit]) -> List[Dict[str, Any]]:
    """Serialize laydown hits for agent state / JSON tool output."""
    return [
        {
            "unit_key": h.unit_key,
            "unit_name": h.unit_name,
            "service": h.service,
            "role": h.role,
            "theater_command": h.theater_command,
            "location_text": h.location_text,
            "airbase": h.airbase,
            "raw_designator": h.raw_designator,
            "cn_designator": h.cn_designator,
            "en_designator": h.en_designator,
            "weg_asset_title": h.weg_asset_title,
            "weg_source_url": h.weg_source_url,
            "oob_source_url": h.oob_source_url,
        }
        for h in hits
    ]
