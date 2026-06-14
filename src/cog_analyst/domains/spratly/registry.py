"""Spratly domain entity registry (the deterministic allowlist)."""

from __future__ import annotations

from typing import List

from cog_analyst.ingestion.entity_guard import EntityRegistry

# The seven Chinese-occupied Spratly outposts covered by the core source doc.
MASTER_REEFS: List[str] = [
    "Fiery Cross Reef",
    "Subi Reef",
    "Mischief Reef",
    "Cuarteron Reef",
    "Gaven Reef",
    "Hughes Reef",
    "Johnson Reef",
]

# Guard for the OutpostInfrastructure.reef_name field.
REEF_REGISTRY = EntityRegistry(field="reef_name", allowed=MASTER_REEFS)
