"""Pydantic data schemas for the cog-analyst extraction layer.

These models are the *only* shape the LLM is allowed to emit. The extractor is
treated as untrusted: every field is explicitly typed, range-constrained, and
text fields are rejected when empty. Resolving alias strings to canonical
catalog designators is deliberately deferred to the scrub process and is not a
schema concern.

Design: the outpost is the hub node. Weapons, aircraft, and radar are reusable
capability catalogs keyed by ``designator``; the outpost references them by raw
designator strings so the relational layer can link them after scrubbing.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = [
    "CogBaseModel",
    "non_empty_text",
    "WeaponSpecification",
    "AircraftSpecification",
    "RadarSpecification",
    "OutpostInfrastructure",
]


def non_empty_text(value: str) -> str:
    """Reject empty or whitespace-only strings.

    With ``str_strip_whitespace=True`` Pydantic strips surrounding whitespace
    before validators run, so a stripped-empty string indicates the source field
    carried no real content.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("value must be a non-empty string")
    return value


class CogBaseModel(BaseModel):
    """Shared base enforcing strict, hallucination-resistant parsing.

    - ``str_strip_whitespace``: trims incidental whitespace from every string.
    - ``extra="forbid"``: rejects any field the LLM invents outside the schema.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        frozen=False,
    )


class WeaponSpecification(CogBaseModel):
    """A reusable weapon-system catalog entry (e.g. ``HQ-9B``)."""

    designator: str
    max_range_km: int
    source_citation: str

    @field_validator("designator", "source_citation")
    @classmethod
    def _check_text(cls, value: str) -> str:
        return non_empty_text(value)

    @field_validator("max_range_km")
    @classmethod
    def _check_range(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_range_km must be >= 0")
        return value


class AircraftSpecification(CogBaseModel):
    """A reusable aircraft-type catalog entry (e.g. ``J-11``)."""

    designator: str
    combat_radius_km: Optional[int] = None
    source_citation: str

    @field_validator("designator", "source_citation")
    @classmethod
    def _check_text(cls, value: str) -> str:
        return non_empty_text(value)

    @field_validator("combat_radius_km")
    @classmethod
    def _check_radius(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("combat_radius_km must be >= 0")
        return value


class RadarSpecification(CogBaseModel):
    """A reusable radar/sensor catalog entry (e.g. ``Type 305A``)."""

    designator: str
    max_detection_range_km: Optional[int] = None
    source_citation: str

    @field_validator("designator", "source_citation")
    @classmethod
    def _check_text(cls, value: str) -> str:
        return non_empty_text(value)

    @field_validator("max_detection_range_km")
    @classmethod
    def _check_detection_range(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("max_detection_range_km must be >= 0")
        return value


class OutpostInfrastructure(CogBaseModel):
    """The hub node: an outpost plus links to capability catalogs.

    ``runway_length_meters`` and ``fighter_hangar_count`` are intrinsic to the
    outpost. The three link lists hold raw designator strings that the scrub
    process later reconciles against the catalog tables; the schema intentionally
    does not deduplicate or canonicalize them.
    """

    reef_name: str
    runway_length_meters: Optional[int] = None
    fighter_hangar_count: Optional[int] = None
    verified_deployed_weapons: List[str] = []
    deployed_aircraft: List[str] = []
    deployed_radar: List[str] = []

    @field_validator("reef_name")
    @classmethod
    def _check_reef_name(cls, value: str) -> str:
        return non_empty_text(value)

    @field_validator("runway_length_meters", "fighter_hangar_count")
    @classmethod
    def _check_non_negative(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value < 0:
            raise ValueError("value must be >= 0")
        return value
