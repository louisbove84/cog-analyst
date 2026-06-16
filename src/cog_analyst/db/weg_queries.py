"""Read-only, agent-facing queries over the WEG document store.

The ``dynamic_payload`` column is schema-on-read: section keys vary per asset, so
these helpers lean on SQLite's JSON1 functions (``json_extract``, ``json_each``)
to filter and introspect the JSON without ever assuming a fixed set of columns.

Design intent — these double as **agent tools**:
  * ``search_assets`` / ``list_origins`` / ``category_breakdown`` answer
    set-level "which assets match X" questions via JSON1 filtering.
  * ``get_asset_sections`` lets an agent ask the data *what it contains* before
    drilling in, and ``get_asset_section`` fetches one narrow slice — so the model
    never has to swallow a whole multi-kilobyte payload.

Everything is read-only and parameterized. The grounding contract for callers:
answer only from what these functions return, and cite the row's ``source_url``.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

__all__ = [
    "AssetHit",
    "search_assets",
    "list_origins",
    "category_breakdown",
    "get_asset_sections",
    "get_asset_section",
]

# JSON1 paths into the one consistent block every asset shares.
_ORIGIN_PATH = "$.Metadata.Origin"
_DOMAIN_PATH = "$.Metadata.Domain"


@dataclass(frozen=True)
class AssetHit:
    """A lightweight search result: identity + citation + coarse classification."""

    asset_title: str
    source_url: Optional[str]
    origin: Optional[str]
    domain: Optional[str]


def _like(value: str) -> str:
    """Build a case-insensitive ``LIKE`` argument for a substring match."""
    return f"%{value.lower()}%"


def search_assets(
    conn: sqlite3.Connection,
    *,
    origin: Optional[str] = None,
    domain: Optional[str] = None,
    name_contains: Optional[str] = None,
    limit: Optional[int] = 50,
) -> List[AssetHit]:
    """Filter assets by origin, domain, and/or title substring (all optional).

    ``origin`` and ``domain`` match anywhere inside the Metadata fields
    (e.g. ``domain="UAV"`` or ``domain="Fighter"``); ``name_contains`` matches the
    title. All matching is case-insensitive. Returns up to ``limit`` hits ordered
    by title (pass ``limit=None`` for no cap).
    """
    sql = [
        "SELECT asset_title, source_url,",
        f"       json_extract(dynamic_payload, '{_ORIGIN_PATH}') AS origin,",
        f"       json_extract(dynamic_payload, '{_DOMAIN_PATH}') AS domain",
        "FROM weg_assets",
    ]
    clauses: List[str] = []
    params: List[Any] = []
    if origin:
        clauses.append(f"LOWER(json_extract(dynamic_payload, '{_ORIGIN_PATH}')) LIKE ?")
        params.append(_like(origin))
    if domain:
        clauses.append(f"LOWER(json_extract(dynamic_payload, '{_DOMAIN_PATH}')) LIKE ?")
        params.append(_like(domain))
    if name_contains:
        clauses.append("LOWER(asset_title) LIKE ?")
        params.append(_like(name_contains))
    if clauses:
        sql.append("WHERE " + " AND ".join(clauses))
    sql.append("ORDER BY asset_title")
    if limit is not None:
        sql.append("LIMIT ?")
        params.append(int(limit))

    rows = conn.execute("\n".join(sql), params).fetchall()
    return [
        AssetHit(
            asset_title=row["asset_title"],
            source_url=row["source_url"],
            origin=row["origin"],
            domain=row["domain"],
        )
        for row in rows
    ]


def list_origins(conn: sqlite3.Connection) -> Dict[str, int]:
    """Return a ``{origin: count}`` map, most common first (discovery helper)."""
    rows = conn.execute(
        f"SELECT json_extract(dynamic_payload, '{_ORIGIN_PATH}') AS origin, "
        "COUNT(*) AS n FROM weg_assets GROUP BY origin ORDER BY n DESC"
    ).fetchall()
    return {(row["origin"] or "(unknown)"): int(row["n"]) for row in rows}


def category_breakdown(
    conn: sqlite3.Connection, *, origin: Optional[str] = None
) -> Dict[str, int]:
    """Count assets by fine-grained category (the last token of ``Domain``).

    Optionally restrict to one origin. Useful for "what is this corpus made of"
    questions (e.g. UAVs vs fighters vs missiles), ordered most common first.
    """
    sql = (
        f"SELECT json_extract(dynamic_payload, '{_DOMAIN_PATH}') AS domain "
        "FROM weg_assets"
    )
    params: List[Any] = []
    if origin:
        sql += f" WHERE LOWER(json_extract(dynamic_payload, '{_ORIGIN_PATH}')) LIKE ?"
        params.append(_like(origin))

    counter: Counter = Counter()
    for row in conn.execute(sql, params).fetchall():
        domain = (row["domain"] or "").strip()
        parts = [p.strip() for p in domain.split(",") if p.strip()]
        counter[parts[-1] if parts else "(uncategorized)"] += 1
    return dict(counter.most_common())


def get_asset_sections(conn: sqlite3.Connection, asset_title: str) -> List[str]:
    """List the top-level payload section names for one asset (in stored order).

    This is the "ask the data what it contains" call: section keys vary per asset,
    so an agent should discover them here before requesting a specific section.
    Returns ``[]`` if the asset is unknown.
    """
    rows = conn.execute(
        "SELECT je.key AS key "
        "FROM weg_assets, json_each(weg_assets.dynamic_payload) AS je "
        "WHERE weg_assets.asset_title = ?",
        (asset_title,),
    ).fetchall()
    return [row["key"] for row in rows]


def get_asset_section(
    conn: sqlite3.Connection, asset_title: str, section: str
) -> Optional[Any]:
    """Fetch a single named section of one asset's payload (narrow retrieval).

    Returns the section's value (usually a nested dict), or ``None`` if the asset
    or section does not exist. Keeping retrieval narrow avoids dumping the entire
    payload into an LLM context.
    """
    row = conn.execute(
        "SELECT dynamic_payload FROM weg_assets WHERE asset_title = ?",
        (asset_title,),
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["dynamic_payload"])
    return payload.get(section)
