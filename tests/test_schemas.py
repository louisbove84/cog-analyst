"""Schema validation tests (the first line of anti-hallucination defense)."""

import pytest
from pydantic import ValidationError

from cog_analyst.domains.spratly import OutpostInfrastructure
from cog_analyst.models import WeaponSpecification


def test_valid_weapon_specification():
    w = WeaponSpecification(
        designator="HQ-9B",
        export_variant=None,
        platform="Road-mobile TEL",
        max_range_km=300,
        flight_profile="Semi-active radar homing; vertical launch",
        source_citation="Dahm 2021, p.6",
    )
    assert w.max_range_km == 300
    assert w.export_variant is None


def test_weapon_export_variant_optional():
    w = WeaponSpecification(
        designator="YJ-12",
        export_variant="CM-302",
        platform="Ship, aircraft, or ground TEL",
        max_range_km=290,
        flight_profile="Low-low or high-low, supersonic",
        source_citation="Dahm 2021, p.18",
    )
    assert w.export_variant == "CM-302"


def test_weapon_requires_citation():
    with pytest.raises(ValidationError):
        WeaponSpecification(
            designator="HQ-9B",
            platform="Road-mobile TEL",
            max_range_km=300,
            flight_profile="vertical launch",
            source_citation="",
        )


def test_weapon_range_must_be_numeric():
    with pytest.raises(ValidationError):
        WeaponSpecification(
            designator="HQ-9B",
            platform="Road-mobile TEL",
            max_range_km="not-a-number",
            flight_profile="vertical launch",
            source_citation="Dahm 2021, p.6",
        )


def test_weapon_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        WeaponSpecification(
            designator="HQ-9B",
            platform="TEL",
            max_range_km=300,
            flight_profile="vertical launch",
            source_citation="Dahm 2021, p.6",
            kill_probability=0.9,  # not in schema -> forbidden
        )


def test_outpost_optional_fields_default_none_and_empty():
    o = OutpostInfrastructure(reef_name="Cuarteron Reef")
    assert o.runway_length_meters is None
    assert o.fighter_hangar_count is None
    assert o.verified_deployed_weapons == []


def test_outpost_negative_runway_rejected():
    with pytest.raises(ValidationError):
        OutpostInfrastructure(reef_name="Fiery Cross Reef", runway_length_meters=-5)
