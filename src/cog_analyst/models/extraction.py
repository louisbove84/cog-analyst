"""Core (domain-agnostic) extraction schema(s).

`WeaponSpecification` describes a weapon system and is reusable across any
theater of analysis. Domain-specific entities (e.g. Spratly island outposts)
live in their domain pack under ``cog_analyst.domains``.

The LLM is treated as an untrusted extraction mechanism: it fills these typed
fields from source text, and Pydantic rejects anything that does not validate.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WeaponSpecification(BaseModel):
    """A single weapon system extracted from a source document."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    designator: str = Field(..., description="PLA designator, e.g. 'HQ-9B' or 'YJ-12'.")
    export_variant: Optional[str] = Field(
        default=None, description="Export designator if stated, e.g. 'CM-302'."
    )
    platform: str = Field(
        ..., description="Firing platform, e.g. 'Ship, aircraft, or ground TEL'."
    )
    max_range_km: int = Field(..., ge=0, description="Maximum range in kilometers.")
    flight_profile: str = Field(
        ..., description="Flight profile, e.g. 'Low-low, supersonic'."
    )
    source_citation: str = Field(
        ..., min_length=1, description="Where this fact came from (doc + page)."
    )

    @field_validator("designator", "platform", "flight_profile", "source_citation")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must not be empty")
        return value
