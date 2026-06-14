"""Spratly-specific extraction model(s).

`OutpostInfrastructure` is island-outpost shaped (reef name, runway, hangars),
so it lives in the domain pack rather than the shared engine. The generic
`WeaponSpecification` stays in ``cog_analyst.models``.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OutpostInfrastructure(BaseModel):
    """Infrastructure for a single Spratly island-reef outpost."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    reef_name: str = Field(..., description="Reef name; validated against the registry.")
    runway_length_meters: Optional[int] = Field(
        default=None, ge=0, description="Runway length in meters, if any."
    )
    fighter_hangar_count: Optional[int] = Field(
        default=None, ge=0, description="Number of fighter-sized hangars, if any."
    )
    verified_deployed_weapons: List[str] = Field(
        default_factory=list,
        description="Designators of weapons reported deployed at this reef.",
    )

    @field_validator("reef_name")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("reef_name must not be empty")
        return value
