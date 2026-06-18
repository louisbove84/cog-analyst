"""OOB query-layer tests: the agent-facing laydown tools over a seeded store."""

import pytest

from cog_analyst.db import database, oob_queries, oob_store
from cog_analyst.ingestion.designator import normalize_designator
from cog_analyst.ingestion.oob_markdown import UnitRecord


def _record(unit_name, aircraft, **overrides):
    fields = dict(
        unit_name=unit_name,
        service="PLAAF",
        branch=None,
        role="fighter",
        theater_command="Eastern",
        location_text="江苏南京",
        province=None,
        airbase="南京机场",
        tactical_code=None,
        remarks=None,
        source_url="https://example.org/oob",
        aircraft=[normalize_designator(a) for a in aircraft],
    )
    fields.update(overrides)
    return UnitRecord(**fields)


@pytest.fixture()
def conn(tmp_path):
    connection = database.connect(tmp_path / "oob.db")
    oob_store.initialize_oob_store(connection)
    seed = [
        _record("空9旅", ["歼-20A"], theater_command="Eastern"),
        _record("空41旅", ["歼-20A"], theater_command="Eastern"),
        _record("空131旅", ["歼-10C", "歼-20A"], theater_command="Southern"),
        _record("空106旅", ["轰-6N"], role="bomber", theater_command="Central"),
        _record(
            "海航1师",
            ["运-8特种机"],
            service="PLANAF",
            role="land_based",
            theater_command=None,
        ),
    ]
    for rec in seed:
        oob_store.upsert_unit(connection, rec)
    yield connection
    connection.close()


# TLDR: units_for_aircraft matches Latin, Chinese, or raw forms (the COG join).
def test_units_for_aircraft_matches_any_form(conn):
    by_en = {h.unit_name for h in oob_queries.units_for_aircraft(conn, "J-20")}
    by_cn = {h.unit_name for h in oob_queries.units_for_aircraft(conn, "歼-20")}
    by_raw = {h.unit_name for h in oob_queries.units_for_aircraft(conn, "歼-20A")}
    expected = {"空9旅", "空41旅", "空131旅"}
    assert by_en == by_cn == by_raw == expected


# TLDR: Inventory counts distinct fielding units and collapses variants by Latin base.
def test_aircraft_inventory_collapses_variants(conn):
    inv = oob_queries.aircraft_inventory(conn)
    assert inv["J-20"] == 3  # three units field a J-20 variant
    assert inv["J-10"] == 1
    assert inv["H-6"] == 1


# TLDR: search_units filters by service/role/theater (case-insensitive).
def test_search_units_filters(conn):
    south = oob_queries.search_units(conn, theater="southern")
    assert [h.unit_name for h in south] == ["空131旅"]
    naval = oob_queries.search_units(conn, service="PLANAF")
    assert [h.unit_name for h in naval] == ["海航1师"]


# TLDR: Breakdown helpers summarize the corpus by role and theater.
def test_role_and_theater_breakdowns(conn):
    roles = oob_queries.role_breakdown(conn)
    assert roles["fighter"] == 3
    assert roles["bomber"] == 1
    theaters = oob_queries.list_theaters(conn)
    assert theaters["Eastern"] == 2
    assert theaters["(none)"] == 1
