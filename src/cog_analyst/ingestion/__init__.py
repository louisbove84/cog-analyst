"""Ingestion engine: entity guard, structured extractor, and the safe pipeline.

This package is domain-agnostic. Domain allowlists/models live under
``cog_analyst.domains``.
"""

from cog_analyst.ingestion.entity_guard import EntityGuardViolation, EntityRegistry
from cog_analyst.ingestion.extractor import LangChainExtractor, StructuredExtractor
from cog_analyst.ingestion.pipeline import (
    IngestionPipeline,
    IngestionResult,
    IngestStatus,
)

__all__ = [
    "EntityGuardViolation",
    "EntityRegistry",
    "LangChainExtractor",
    "StructuredExtractor",
    "IngestionPipeline",
    "IngestionResult",
    "IngestStatus",
]
