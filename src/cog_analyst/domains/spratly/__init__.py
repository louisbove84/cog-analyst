"""Spratly Islands domain pack.

``OutpostInfrastructure`` is the engine's hub node (it lives in core
``cog_analyst.models.schemas``); it is re-exported here for ergonomic
domain-scoped imports.
"""

from cog_analyst.domains.spratly.registry import MASTER_REEFS, REEF_REGISTRY
from cog_analyst.domains.spratly.source import (
    CORE_SOURCE_CITATION,
    CORE_SOURCE_PDF,
    DEMO_AIRCRAFT_SNIPPETS,
    DEMO_OUTPOST_SNIPPETS,
    DEMO_RADAR_SNIPPETS,
    DEMO_WEAPON_SNIPPETS,
    SPRATLY_DB_PATH,
)
from cog_analyst.models.schemas import OutpostInfrastructure

__all__ = [
    "OutpostInfrastructure",
    "MASTER_REEFS",
    "REEF_REGISTRY",
    "CORE_SOURCE_CITATION",
    "CORE_SOURCE_PDF",
    "DEMO_WEAPON_SNIPPETS",
    "DEMO_AIRCRAFT_SNIPPETS",
    "DEMO_RADAR_SNIPPETS",
    "DEMO_OUTPOST_SNIPPETS",
    "SPRATLY_DB_PATH",
]
