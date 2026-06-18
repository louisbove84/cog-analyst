"""Scenario resolution tests: query -> deterministic structured filters."""

from cog_analyst.cog.scenario import resolve_scenario


# TLDR: A location expands to its responsible theater(s), primary first.
def test_location_expands_to_theaters():
    r = resolve_scenario("What threatens Taiwan?")
    assert r.matched_location == "taiwan"
    assert r.theaters == ["Eastern", "Southern"]
    assert r.theater == "Eastern"


# TLDR: A Latin designator in the query is detected and upper-cased.
def test_latin_designator_detected():
    r = resolve_scenario("Assess the J-20 threat")
    assert r.designator == "J-20"


# TLDR: A Chinese designator is crosswalked to its Latin join key.
def test_chinese_designator_crosswalked():
    r = resolve_scenario("歼-20的能力")
    assert r.designator == "J-20"


# TLDR: Role hints map to the OOB role vocabulary.
def test_role_hint_detected():
    assert resolve_scenario("bomber laydown").role == "bomber"
    assert resolve_scenario("drone units").role == "uav"


# TLDR: Explicit overrides win over text detection.
def test_explicit_overrides_win():
    r = resolve_scenario("Taiwan J-20", theater="Western", designator="H-6")
    assert r.theater == "Western"
    assert r.designator == "H-6"
    # Explicit theater suppresses location expansion.
    assert r.matched_location is None


# TLDR: "taiwan strait" matches the longer key, not just "taiwan".
def test_longest_location_key_wins():
    r = resolve_scenario("operations in the Taiwan Strait")
    assert r.matched_location == "taiwan strait"
