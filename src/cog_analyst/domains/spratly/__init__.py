"""Spratly Islands domain pack."""

from cog_analyst.domains.spratly.models import OutpostInfrastructure
from cog_analyst.domains.spratly.registry import MASTER_REEFS, REEF_REGISTRY
from cog_analyst.domains.spratly.source import (
    CORE_SOURCE_CITATION,
    CORE_SOURCE_PDF,
    DEMO_OUTPOST_SNIPPETS,
    DEMO_WEAPON_SNIPPETS,
    SPRATLY_DB_PATH,
)

__all__ = [
    "OutpostInfrastructure",
    "MASTER_REEFS",
    "REEF_REGISTRY",
    "CORE_SOURCE_CITATION",
    "CORE_SOURCE_PDF",
    "DEMO_OUTPOST_SNIPPETS",
    "DEMO_WEAPON_SNIPPETS",
    "SPRATLY_DB_PATH",
]
