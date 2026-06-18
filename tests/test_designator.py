"""Crosswalk tests: Chinese PLA designators -> Latin join keys."""

from cog_analyst.ingestion.designator import (
    is_designator,
    normalize_designator,
    split_aircraft_cell,
)


# TLDR: Single-character role prefixes map and variant suffixes collapse to a base.
def test_simple_prefix_and_variant_stripping():
    parts = normalize_designator("歼-20A")
    assert parts.cn_base == "歼-20"
    assert parts.en_base == "J-20"
    assert parts.raw == "歼-20A"


# TLDR: Multi-character prefixes win over their single-char substrings (歼轰 not 歼).
def test_compound_prefix_precedence():
    assert normalize_designator("歼轰-7A").en_base == "JH-7"
    assert normalize_designator("运油-20").en_base == "YY-20"
    assert normalize_designator("空警-500").en_base == "KJ-500"


# TLDR: Attack-UAV and trainer prefixes resolve, including foreign (Su) origins.
def test_attack_trainer_and_foreign():
    assert normalize_designator("攻击-1").en_base == "GJ-1"
    assert normalize_designator("教练-10").en_base == "JL-10"
    assert normalize_designator("苏-30MK2").en_base == "Su-30"


# TLDR: Named systems with no number map to their English name.
def test_named_systems():
    assert normalize_designator("云影").en_base == "Cloud Shadow"
    assert normalize_designator("翔龙").en_base == "Soaring Dragon"


# TLDR: Division/unit names that merely contain a role char are NOT designators.
def test_division_names_are_not_designators():
    assert not is_designator("第34运输机师")
    assert not is_designator("强军先锋飞行大队")
    assert is_designator("歼-16")
    # Unrecognized tokens round-trip with en_base=None instead of being dropped.
    assert normalize_designator("第34运输机师").en_base is None


# TLDR: A 机型 cell splits on ideographic commas; slash variants stay together.
def test_split_aircraft_cell():
    parts = split_aircraft_cell("歼-11B、歼-10A/B/C/S")
    assert [p.raw for p in parts] == ["歼-11B", "歼-10A/B/C/S"]
    assert [p.en_base for p in parts] == ["J-11", "J-10"]
