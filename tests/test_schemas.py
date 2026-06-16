"""Schema validation tests (the first line of anti-hallucination defense)."""

import pytest
from pydantic import ValidationError

from cog_analyst.models import (
    AircraftSpecification,
    OutpostInfrastructure,
    RadarSpecification,
    WeaponSpecification,
)


# TLDR: A well-formed weapon spec validates and exposes its fields.
def test_valid_weapon_specification():
    w = WeaponSpecification(
        designator="HQ-9B", max_range_km=300, source_citation="Dahm 2021, p.6"
    )
    assert w.designator == "HQ-9B"
    assert w.max_range_km == 300


# TLDR: An empty source_citation is rejected (every fact must be sourced).
def test_weapon_requires_citation():
    with pytest.raises(ValidationError):
        WeaponSpecification(designator="HQ-9B", max_range_km=300, source_citation="")


# TLDR: A non-numeric range is rejected (no string smuggled into a number field).
def test_weapon_range_must_be_numeric():
    with pytest.raises(ValidationError):
        WeaponSpecification(
            designator="HQ-9B", max_range_km="not-a-number", source_citation="Dahm"
        )


# TLDR: A negative range is rejected (ranges can't be below zero).
def test_weapon_range_non_negative():
    with pytest.raises(ValidationError):
        WeaponSpecification(designator="HQ-9B", max_range_km=-1, source_citation="Dahm")


# TLDR: Unknown fields are forbidden (extra="forbid" blocks LLM-invented keys).
def test_weapon_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        WeaponSpecification(
            designator="HQ-9B",
            max_range_km=300,
            source_citation="Dahm 2021, p.6",
            kill_probability=0.9,  # not in schema -> forbidden
        )


# TLDR: Aircraft combat radius is optional and defaults to None when omitted.
def test_aircraft_radius_optional():
    a = AircraftSpecification(designator="J-11", source_citation="Dahm 2021, p.12")
    assert a.combat_radius_km is None


# TLDR: Radar detection range is optional but, when given, must be non-negative.
def test_radar_detection_range_optional_and_non_negative():
    r = RadarSpecification(designator="Type 305A", source_citation="Dahm")
    assert r.max_detection_range_km is None
    with pytest.raises(ValidationError):
        RadarSpecification(
            designator="Type 305A", max_detection_range_km=-5, source_citation="Dahm"
        )


# TLDR: A bare outpost defaults its numeric fields to None and its link lists to empty.
def test_outpost_optional_fields_default_none_and_empty():
    o = OutpostInfrastructure(reef_name="Cuarteron Reef")
    assert o.runway_length_meters is None
    assert o.fighter_hangar_count is None
    assert o.verified_deployed_weapons == []
    assert o.deployed_aircraft == []
    assert o.deployed_radar == []


# TLDR: A negative runway length is rejected.
def test_outpost_negative_runway_rejected():
    with pytest.raises(ValidationError):
        OutpostInfrastructure(reef_name="Fiery Cross Reef", runway_length_meters=-5)


# TLDR: A blank/whitespace-only reef name is rejected.
def test_outpost_empty_reef_rejected():
    with pytest.raises(ValidationError):
        OutpostInfrastructure(reef_name="   ")


# TLDR: The schema preserves raw alias links as-is (it validates, it doesn't dedupe).
def test_outpost_keeps_raw_alias_links():
    """The schema does not dedupe; raw aliases survive for downstream reconciliation."""
    o = OutpostInfrastructure(
        reef_name="Fiery Cross Reef",
        verified_deployed_weapons=["HQ-9B", "HQ-9B SAMs"],
        deployed_aircraft=["J-11"],
        deployed_radar=["Type 305A"],
    )
    assert o.verified_deployed_weapons == ["HQ-9B", "HQ-9B SAMs"]
