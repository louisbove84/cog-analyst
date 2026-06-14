"""Deterministic entity guard tests (generic registry + Spratly registry)."""

import logging

import pytest

from cog_analyst.domains.spratly import MASTER_REEFS, REEF_REGISTRY
from cog_analyst.ingestion.entity_guard import EntityGuardViolation, EntityRegistry


@pytest.mark.parametrize("reef", MASTER_REEFS)
def test_all_master_reefs_pass(reef):
    assert REEF_REGISTRY.is_known(reef) is True
    assert REEF_REGISTRY.enforce(reef) == reef


def test_whitespace_tolerated():
    assert REEF_REGISTRY.enforce("  Subi Reef  ") == "Subi Reef"


@pytest.mark.parametrize(
    "bad",
    [
        "Woody Island",          # real place, but not a Spratly master reef
        "Scarborough Shoal",     # not in registry
        "fiery cross reef",      # wrong casing -> blocked by design
        "Fiery Cross",           # missing 'Reef'
        "Atlantis Reef",         # hallucinated
        "",                      # empty
    ],
)
def test_unknown_names_blocked(bad):
    assert REEF_REGISTRY.is_known(bad) is False
    with pytest.raises(EntityGuardViolation):
        REEF_REGISTRY.enforce(bad)


def test_violation_carries_field_and_value():
    with pytest.raises(EntityGuardViolation) as excinfo:
        REEF_REGISTRY.enforce("Atlantis Reef")
    assert excinfo.value.field == "reef_name"
    assert excinfo.value.value == "Atlantis Reef"


def test_violation_is_logged(caplog):
    with caplog.at_level(logging.ERROR, logger="cog_analyst.entity_guard"):
        with pytest.raises(EntityGuardViolation):
            REEF_REGISTRY.enforce("Hallucinated Reef")
    assert any("Blocked hallucinated/unknown reef_name" in r.message for r in caplog.records)


def test_registry_is_reusable_for_other_domains():
    """The mechanism is generic: a fresh registry guards any field/allowlist."""
    ships = EntityRegistry(field="shipyard", allowed=["Jiangnan", "Dalian"])
    assert ships.is_known("Jiangnan") is True
    assert ships.is_known("Atlantis Yard") is False
    with pytest.raises(EntityGuardViolation):
        ships.enforce("Atlantis Yard")
