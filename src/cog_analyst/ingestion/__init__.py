"""Ingestion layer: LLM extractor contracts (optional; used by agent nodes)."""

from cog_analyst.ingestion.extractor import LangChainExtractor
from cog_analyst.ingestion.interfaces import (
    ExtractionError,
    StructuredExtractor,
    TSchema,
)

__all__ = [
    "StructuredExtractor",
    "ExtractionError",
    "TSchema",
    "LangChainExtractor",
]
