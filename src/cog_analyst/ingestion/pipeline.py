"""End-to-end ingestion pipeline: extract -> validate -> persist (raw).

The pipeline is domain-agnostic: callers pass the target schema and a ``persist``
callable, so the same engine ingests weapons, aircraft, radar, or outposts. Each
snippet flows through the same safe path and produces an ``IngestionResult`` with
an explicit status, so a batch run reports exactly what was inserted, blocked, or
failed — without crashing the whole run on one bad record.

Guarding and dedup are intentionally NOT here; they belong to the scrub process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from cog_analyst.ingestion.entity_guard import EntityGuardViolation
from cog_analyst.ingestion.interfaces import ExtractionError, StructuredExtractor

logger = logging.getLogger("cog_analyst.pipeline")

TSchema = TypeVar("TSchema", bound=BaseModel)

# A persist function takes a validated model and returns its identifier (e.g.
# the designator or reef name).
PersistFn = Callable[[BaseModel], str]


class IngestStatus(str, Enum):
    INSERTED = "inserted"
    VALIDATION_ERROR = "validation_error"
    GUARD_VIOLATION = "guard_violation"
    EXTRACTION_ERROR = "extraction_error"
    PERSISTENCE_ERROR = "persistence_error"


@dataclass
class IngestionResult:
    status: IngestStatus
    schema_name: str
    detail: str
    identifier: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status is IngestStatus.INSERTED


class IngestionPipeline:
    """Drives safe ingestion of text snippets into the structured store."""

    def __init__(self, extractor: StructuredExtractor) -> None:
        self._extractor = extractor

    def ingest(
        self,
        text: str,
        schema: Type[TSchema],
        persist: PersistFn,
    ) -> IngestionResult:
        """Extract ``text`` into ``schema``, then persist it via ``persist``.

        Flow: extract (LLM) -> validate (Pydantic) -> persist (raw row). Each
        failure mode maps to an explicit status; nothing partial is reported as
        success.
        """
        name = schema.__name__

        try:
            obj = self._extractor.extract(text, schema)
        except ValidationError as exc:
            logger.warning("%s validation failed: %s", name, exc)
            return IngestionResult(IngestStatus.VALIDATION_ERROR, name, str(exc))
        except ExtractionError as exc:
            logger.error("%s extraction error: %s", name, exc)
            return IngestionResult(IngestStatus.EXTRACTION_ERROR, name, str(exc))
        except Exception as exc:  # noqa: BLE001 - any other extractor failure
            logger.error("%s extraction error: %s", name, exc)
            return IngestionResult(IngestStatus.EXTRACTION_ERROR, name, str(exc))

        try:
            identifier = persist(obj)
        except EntityGuardViolation as exc:
            return IngestionResult(
                IngestStatus.GUARD_VIOLATION, name, str(exc), exc.value
            )
        except Exception as exc:  # noqa: BLE001 - persistence failure
            logger.error("%s persistence error: %s", name, exc)
            return IngestionResult(IngestStatus.PERSISTENCE_ERROR, name, str(exc))

        return IngestionResult(IngestStatus.INSERTED, name, "ok", identifier)
