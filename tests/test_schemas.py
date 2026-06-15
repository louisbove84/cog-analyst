"""Schema validation tests (the first line of anti-hallucination defense)."""

import pytest
from pydantic import ValidationError

from cog_analyst.models import (
    AircraftSpecification,
    OutpostInfrastructure,
    RadarSpecification,
    WeaponSpecification,
)


def test_valid_weapon_specification():
    w = WeaponSpecification(
        designator="HQ-9B", max_range_km=300, source_citation="Dahm 2021, p.6"
    )
    assert w.designator == "HQ-9B"
    assert w.max_range_km == 300


def test_weapon_requires_citation():
    with pytest.raises(ValidationError):
        WeaponSpecification(designator="HQ-9B", max_range_km=300, source_citation="")


def test_weapon_range_must_be_numeric():
    with pytest.raises(ValidationError):
        WeaponSpecification(
            designator="HQ-9B", max_range_km="not-a-number", source_citation="Dahm"
        )


def test_weapon_range_non_negative():
    with pytest.raises(ValidationError):
        WeaponSpecification(designator="HQ-9B", max_range_km=-1, source_citation="Dahm")


def test_weapon_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        WeaponSpecification(
            designator="HQ-9B",
            max_range_km=300,
            source_citation="Dahm 2021, p.6",
            kill_probability=0.9,  # not in schema -> forbidden
        )


def test_aircraft_radius_optional():
    a = AircraftSpecification(designator="J-11", source_citation="Dahm 2021, p.12")
    assert a.combat_radius_km is None


def test_radar_detection_range_optional_and_non_negative():
    r = RadarSpecification(designator="Type 305A", source_citation="Dahm")
    assert r.max_detection_range_km is None
    with pytest.raises(ValidationError):
        RadarSpecification(
            designator="Type 305A", max_detection_range_km=-5, source_citation="Dahm"
        )


def test_outpost_optional_fields_default_none_and_empty():
    o = OutpostInfrastructure(reef_name="Cuarteron Reef")
    assert o.runway_length_meters is None
    assert o.fighter_hangar_count is None
    assert o.verified_deployed_weapons == []
    assert o.deployed_aircraft == []
    assert o.deployed_radar == []


def test_outpost_negative_runway_rejected():
    with pytest.raises(ValidationError):
        OutpostInfrastructure(reef_name="Fiery Cross Reef", runway_length_meters=-5)


def test_outpost_empty_reef_rejected():
    with pytest.raises(ValidationError):
        OutpostInfrastructure(reef_name="   ")


def test_outpost_keeps_raw_alias_links():
    """The schema does not dedupe; raw aliases survive for downstream reconciliation."""
    o = OutpostInfrastructure(
        reef_name="Fiery Cross Reef",
        verified_deployed_weapons=["HQ-9B", "HQ-9B SAMs"],
        deployed_aircraft=["J-11"],
        deployed_radar=["Type 305A"],
    )
    assert o.verified_deployed_weapons == ["HQ-9B", "HQ-9B SAMs"]
