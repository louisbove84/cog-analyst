"""Deterministic scenario resolution: map a free-text query to structured filters.

A user asks about a weapon (``J-20``) or a location/scenario (``Taiwan``). The
structured DBs have no geography, so a location must resolve to real, grounded
filters (theaters) via a small hand-authored map — keeping entity selection
deterministic and out of the LLM's hands. Designators are detected via the same
crosswalk used at ingest, so ``歼-20`` and ``J-20`` both resolve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from cog_analyst.ingestion.designator import normalize_designator

__all__ = ["ResolvedScenario", "resolve_scenario", "SCENARIO_THEATERS"]

# Location / scenario -> PLA theater commands responsible for it. Authored, not
# inferred. Extend as the analysis scope grows.
SCENARIO_THEATERS = {
    "taiwan": ["Eastern", "Southern"],
    "taiwan strait": ["Eastern", "Southern"],
    "senkaku": ["Eastern"],
    "east china sea": ["Eastern"],
    "south china sea": ["Southern"],
    "spratly": ["Southern"],
    "korea": ["Northern"],
    "india": ["Western"],
    "ladakh": ["Western"],
}

# Free-text role hints -> the OOB role value.
_ROLE_HINTS = {
    "fighter": "fighter",
    "bomber": "bomber",
    "uav": "uav",
    "drone": "uav",
    "transport": "transport",
    "tanker": "transport",
}

_DESIGNATOR_RE = re.compile(r"\b([A-Za-z]{1,3}-\d{1,3}[A-Za-z]?)\b")


@dataclass(frozen=True)
class ResolvedScenario:
    """Structured retrieval filters derived from the user query."""

    designator: Optional[str]
    theaters: List[str]
    role: Optional[str]
    matched_location: Optional[str]

    @property
    def theater(self) -> Optional[str]:
        """Primary theater (the structured retrieve takes a single theater)."""
        return self.theaters[0] if self.theaters else None


def _detect_designator(query: str) -> Optional[str]:
    # Chinese designator (e.g. 歼-20) anywhere in the text.
    cn = re.search(r"[\u4e00-\u9fff]+[-\uff0d]?\d+[A-Za-z]?", query)
    if cn:
        parts = normalize_designator(cn.group(0))
        if parts.en_base:
            return parts.en_base
    # Latin designator (e.g. J-20, H-6).
    latin = _DESIGNATOR_RE.search(query)
    if latin:
        return latin.group(1).upper()
    return None


def _detect_location(query: str) -> Optional[str]:
    lowered = query.lower()
    # Longest key first so "taiwan strait" beats "taiwan".
    for key in sorted(SCENARIO_THEATERS, key=len, reverse=True):
        if key in lowered:
            return key
    return None


def _detect_role(query: str) -> Optional[str]:
    lowered = query.lower()
    for hint, role in _ROLE_HINTS.items():
        if hint in lowered:
            return role
    return None


def resolve_scenario(
    query: str,
    *,
    designator: Optional[str] = None,
    theater: Optional[str] = None,
    role: Optional[str] = None,
) -> ResolvedScenario:
    """Resolve a query (plus optional explicit overrides) into retrieval filters.

    Explicit arguments always win over text detection. A location in the query
    expands to its responsible theater(s) via :data:`SCENARIO_THEATERS`.
    """
    resolved_designator = designator or _detect_designator(query)
    resolved_role = role or _detect_role(query)

    matched_location = None
    theaters: List[str] = []
    if theater:
        theaters = [theater]
    else:
        matched_location = _detect_location(query)
        if matched_location:
            theaters = list(SCENARIO_THEATERS[matched_location])

    return ResolvedScenario(
        designator=resolved_designator,
        theaters=theaters,
        role=resolved_role,
        matched_location=matched_location,
    )
