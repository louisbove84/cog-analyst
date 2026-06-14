"""Shared test fixtures, including a fake extractor (no live LLM needed)."""

from pathlib import Path
from typing import Dict, Tuple, Type, TypeVar

import pytest
from pydantic import BaseModel

from cog_analyst.db import CogStore
from cog_analyst.domains.spratly import REEF_REGISTRY
from cog_analyst.ingestion import StructuredExtractor

TSchema = TypeVar("TSchema", bound=BaseModel)


class FakeExtractor(StructuredExtractor):
    """Returns pre-seeded schema instances keyed by (schema, trigger substring).

    This stands in for the LLM so pipeline/store tests are deterministic and
    offline. It mimics the real extractor's contract: return an instance of the
    requested schema, or raise to simulate an extraction/validation failure.
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
        raise AssertionError(f"FakeExtractor: no response registered for {schema.__name__} / {text!r}")


@pytest.fixture()
def store(tmp_path: Path) -> CogStore:
    s = CogStore(db_path=tmp_path / "test_spratly.db", reef_registry=REEF_REGISTRY)
    yield s
    s.close()


@pytest.fixture()
def fake_extractor() -> FakeExtractor:
    return FakeExtractor()
