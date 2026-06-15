"""Ingestion layer: extractor contracts and the extract-validate-persist pipeline."""

from cog_analyst.ingestion.entity_guard import EntityGuardViolation, EntityRegistry
from cog_analyst.ingestion.extractor import LangChainExtractor
from cog_analyst.ingestion.interfaces import (
    ExtractionError,
    StructuredExtractor,
    TSchema,
)
from cog_analyst.ingestion.pipeline import (
    IngestionPipeline,
    IngestionResult,
    IngestStatus,
)

__all__ = [
    "EntityGuardViolation",
    "EntityRegistry",
    "StructuredExtractor",
    "ExtractionError",
    "TSchema",
    "LangChainExtractor",
    "IngestionPipeline",
    "IngestionResult",
    "IngestStatus",
]
