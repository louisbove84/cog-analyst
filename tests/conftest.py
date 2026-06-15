"""Shared test fixtures: offline DB and a fake extractor (no network needed)."""

from __future__ import annotations

from typing import Dict, Tuple, Type, TypeVar

import pytest
from pydantic import BaseModel

from cog_analyst import db
from cog_analyst.ingestion import StructuredExtractor

TSchema = TypeVar("TSchema", bound=BaseModel)


class FakeExtractor(StructuredExtractor):
    """Returns pre-seeded schema instances keyed by (schema, trigger substring).

    Stands in for the LLM so pipeline tests are deterministic and offline while
    honoring the real ABC contract: return an instance of the requested schema,
    or raise to simulate an extraction failure.
    """

    def __init__(self) -> None:
        self._responses: Dict[Tuple[str, str], BaseModel] = {}
        self._errors: Dict[Tuple[str, str], Exception] = {}

    def register(self, schema: Type[BaseModel], trigger: str, value: BaseModel) -> None:
        self._responses[(schema.__name__, trigger)] = value

    def register_error(self, schema: Type[BaseModel], trigger: str, exc: Exception) -> None:
        self._errors[(schema.__name__, trigger)] = exc

    def extract(self, text: str, schema: Type[TSchema]) -> TSchema:
        for (schema_name, trigger), exc in self._errors.items():
            if schema_name == schema.__name__ and trigger in text:
                raise exc
        for (schema_name, trigger), value in self._responses.items():
            if schema_name == schema.__name__ and trigger in text:
                return value  # type: ignore[return-value]
        raise AssertionError(
            f"FakeExtractor: no response registered for {schema.__name__} / {text!r}"
        )


@pytest.fixture()
def conn(tmp_path):
    connection = db.connect(tmp_path / "test_spratly.db")
    db.initialize_database(connection)
    yield connection
    connection.close()


@pytest.fixture()
def fake_extractor() -> FakeExtractor:
    return FakeExtractor()
