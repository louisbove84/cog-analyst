"""Pydantic schemas for the COG agent graph (structured LLM outputs)."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field


class CapabilityList(BaseModel):
    """Node 2 output: capabilities supported by metrics in raw_assets."""

    model_config = ConfigDict(extra="forbid")
    critical_capabilities: List[str] = Field(
        description="Combat capabilities explicitly supported by cited metrics."
    )


class RequirementList(BaseModel):
    """Node 3 output: dependencies that sustain the listed capabilities."""

    model_config = ConfigDict(extra="forbid")
    critical_requirements: List[str] = Field(
        description="Physical, logistical, or spectrum bounds required."
    )


class VulnerabilitySynthesis(BaseModel):
    """Node 4 output: disruptable requirements and a grounded CoG name."""

    model_config = ConfigDict(extra="forbid")
    critical_vulnerabilities: List[str] = Field(
        description=(
            "Requirements that can be disrupted or are single points of failure."
        )
    )
    cog_statement: str = Field(
        description=(
            "Center of Gravity: must name a unit, base, theater, or requirement "
            "that appears in the supplied evidence — never invent a new entity."
        )
    )
