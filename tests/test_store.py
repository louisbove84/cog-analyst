"""SQLite store tests: schema types, relations, and guard enforcement."""

import pytest

from cog_analyst.db import CogStore
from cog_analyst.domains.spratly import OutpostInfrastructure
from cog_analyst.ingestion.entity_guard import EntityGuardViolation
from cog_analyst.models import WeaponSpecification


def test_init_is_idempotent(store):
    before = store.counts()
    store.init_db()
    store.init_db()
    assert store.counts() == before


def test_strict_integer_columns(store):
    assert store.get_column_type("weapon_specifications", "max_range_km") == "INTEGER"
    assert store.get_column_type("outpost_infrastructure", "runway_length_meters") == "INTEGER"
    assert store.get_column_type("outpost_infrastructure", "fighter_hangar_count") == "INTEGER"


def test_insert_and_read_weapon(store):
    w = WeaponSpecification(
        designator="YJ-12",
        export_variant="CM-302",
        platform="Ship, aircraft, or ground TEL",
        max_range_km=290,
        flight_profile="Low-low or high-low, supersonic",
        source_citation="Dahm 2021, p.18",
    )
    store.insert_weapon(w)
    got = store.get_weapon("YJ-12")
    assert got is not None
    assert got.export_variant == "CM-302"
    assert got.max_range_km == 290


def test_insert_outpost_with_weapon_relations(store):
    o = OutpostInfrastructure(
        reef_name="Fiery Cross Reef",
        runway_length_meters=3000,
        fighter_hangar_count=24,
        verified_deployed_weapons=["HQ-9B", "YJ-12"],
    )
    store.insert_outpost(o)
    assert store.counts()["outpost_infrastructure"] == 1
    assert store.get_outpost_weapons("Fiery Cross Reef") == ["HQ-9B", "YJ-12"]


def test_hallucinated_reef_writes_nothing(store):
    o = OutpostInfrastructure(
        reef_name="Atlantis Reef",
        runway_length_meters=5000,
        fighter_hangar_count=99,
        verified_deployed_weapons=["DEATH-RAY-1"],
    )
    with pytest.raises(EntityGuardViolation):
        store.insert_outpost(o)
    counts = store.counts()
    assert counts["outpost_infrastructure"] == 0
    assert counts["outpost_weapons"] == 0


def test_outpost_insert_without_registry_refuses(tmp_path):
    """A store with no registry must refuse outpost writes (no unguarded data)."""
    s = CogStore(db_path=tmp_path / "noreg.db")
    try:
        o = OutpostInfrastructure(reef_name="Fiery Cross Reef")
        with pytest.raises(ValueError):
            s.insert_outpost(o)
        assert s.counts()["outpost_infrastructure"] == 0
    finally:
        s.close()


def test_weapon_upsert_updates_in_place(store):
    w1 = WeaponSpecification(
        designator="HQ-9B", platform="TEL", max_range_km=200,
        flight_profile="vertical launch", source_citation="old",
    )
    w2 = WeaponSpecification(
        designator="HQ-9B", platform="Road-mobile TEL", max_range_km=300,
        flight_profile="vertical launch", source_citation="Dahm 2021, p.6",
    )
    store.insert_weapon(w1)
    store.insert_weapon(w2)
    assert store.counts()["weapon_specifications"] == 1
    assert store.get_weapon("HQ-9B").max_range_km == 300
