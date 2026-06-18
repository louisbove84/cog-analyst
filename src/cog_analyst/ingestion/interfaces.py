"""Abstract contracts for the ingestion layer.

The extractor boundary is expressed as an ABC (nominal, explicit inheritance)
rather than a Protocol, so implementations must subclass and ``isinstance``
checks are reliable. A universal ``TSchema`` TypeVar lets a single extractor
serve every Pydantic schema passed to :meth:`StructuredExtractor.extract`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Type, TypeVar

from pydantic import BaseModel

__all__ = ["TSchema", "StructuredExtractor", "ExtractionError"]

TSchema = TypeVar("TSchema", bound=BaseModel)


class ExtractionError(RuntimeError):
    """Raised on extractor transport/client failures.

    Distinct from Pydantic ``ValidationError`` so callers can tell a broken
    connection or malformed LLM response apart from data that failed validation.
    """


class StructuredExtractor(ABC):
    """Contract for components that turn source text into a validated schema."""

    @abstractmethod
    def extract(self, text: str, schema: Type[TSchema]) -> TSchema:
        """Extract ``text`` into an instance of exactly ``schema``.

        Implementations must return an instance of ``schema`` (not a coerced or
        substitute type) or raise. They must never silently downgrade the type
        or swallow validation/transport errors.
        """
        raise NotImplementedError
