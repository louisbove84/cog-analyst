"""OOB relational store tests: schema, UPSERT, and aircraft-link rebuild."""

import pytest

from cog_analyst.db import database, oob_store
from cog_analyst.ingestion.designator import normalize_designator
from cog_analyst.ingestion.oob_markdown import UnitRecord


def _record(unit_name, aircraft, **overrides):
    fields = dict(
        unit_name=unit_name,
        service="PLAAF",
        branch="空軍航空兵部隊",
        role="fighter",
        theater_command="Eastern",
        location_text="安徽芜湖市湾里机场",
        province=None,
        airbase="湾里机场",
        tactical_code="62X0X",
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
    yield connection
    connection.close()


# TLDR: A unit and its aircraft links round-trip through the hub/spoke schema.
def test_upsert_and_get(conn):
    oob_store.upsert_unit(conn, _record("空9旅", ["歼-20A"]))
    stored = oob_store.get_unit(conn, "空9旅")
    assert stored["service"] == "PLAAF"
    assert stored["airbase"] == "湾里机场"
    assert [a["en_designator"] for a in stored["aircraft"]] == ["J-20"]
    assert oob_store.unit_count(conn) == 1


# TLDR: Re-ingesting a unit updates it in place and rebuilds aircraft (no dupes).
def test_upsert_is_idempotent_and_rebuilds_links(conn):
    oob_store.upsert_unit(conn, _record("空9旅", ["歼-20A", "歼-16"]))
    # Re-ingest with a shorter aircraft list: links must be replaced, not appended.
    oob_store.upsert_unit(conn, _record("空9旅", ["歼-20A"], theater_command="Central"))
    stored = oob_store.get_unit(conn, "空9旅")
    assert oob_store.unit_count(conn) == 1
    assert stored["theater_command"] == "Central"
    assert [a["raw_designator"] for a in stored["aircraft"]] == ["歼-20A"]


# TLDR: A row with no unit name gets a synthesized, stable key from role+location.
def test_synthesized_key_for_nameless_row(conn):
    rec = _record("", ["歼-15"], role="carrier_based", location_text="辽宁兴城")
    key = oob_store.upsert_unit(conn, rec)
    assert key == "carrier_based|辽宁兴城"
    assert oob_store.get_unit(conn, key) is not None


# TLDR: Unknown units return None rather than raising.
def test_missing_unit_returns_none(conn):
    assert oob_store.get_unit(conn, "does-not-exist") is None
