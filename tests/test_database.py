"""Persistence tests: schema types, upserts, and raw hub-and-spoke links."""

from cog_analyst import db
from cog_analyst.models import (
    AircraftSpecification,
    OutpostInfrastructure,
    RadarSpecification,
    WeaponSpecification,
)


def test_init_is_idempotent(conn):
    before = db.counts(conn)
    db.initialize_database(conn)
    db.initialize_database(conn)
    assert db.counts(conn) == before


def test_strict_integer_columns(conn):
    assert db.get_column_type(conn, "weapon_specifications", "max_range_km") == "INTEGER"
    assert db.get_column_type(conn, "outpost_infrastructure", "runway_length_meters") == "INTEGER"
    assert db.get_column_type(conn, "aircraft_specifications", "combat_radius_km") == "INTEGER"


def test_insert_and_read_weapon(conn):
    db.insert_weapon(
        conn,
        WeaponSpecification(designator="YJ-12", max_range_km=290, source_citation="Dahm p.18"),
    )
    got = db.get_weapon(conn, "YJ-12")
    assert got is not None
    assert got.max_range_km == 290


def test_insert_and_read_aircraft_and_radar(conn):
    db.insert_aircraft(
        conn,
        AircraftSpecification(designator="J-11", combat_radius_km=1500, source_citation="Dahm"),
    )
    db.insert_radar(
        conn,
        RadarSpecification(designator="Type 305A", max_detection_range_km=400, source_citation="Dahm"),
    )
    assert db.get_aircraft(conn, "J-11").combat_radius_km == 1500
    assert db.get_radar(conn, "Type 305A").max_detection_range_km == 400


def test_insert_outpost_links_all_capabilities(conn):
    db.insert_outpost(
        conn,
        OutpostInfrastructure(
            reef_name="Fiery Cross Reef",
            runway_length_meters=3000,
            fighter_hangar_count=24,
            verified_deployed_weapons=["HQ-9B", "YJ-12"],
            deployed_aircraft=["J-11"],
            deployed_radar=["Type 305A"],
        ),
    )
    assert db.counts(conn)["outpost_infrastructure"] == 1
    assert db.get_outpost_weapons(conn, "Fiery Cross Reef") == ["HQ-9B", "YJ-12"]
    assert db.get_outpost_aircraft(conn, "Fiery Cross Reef") == ["J-11"]
    assert db.get_outpost_radar(conn, "Fiery Cross Reef") == ["Type 305A"]


def test_outpost_keeps_raw_aliases(conn):
    """The write path is raw: no guard, no dedup (reconciliation is downstream)."""
    db.insert_outpost(
        conn,
        OutpostInfrastructure(
            reef_name="Atlantis Reef",  # unknown reef, kept raw on write
            verified_deployed_weapons=["HQ-9B", "HQ-9B SAMs"],
        ),
    )
    assert db.counts(conn)["outpost_infrastructure"] == 1
    assert db.get_outpost_weapons(conn, "Atlantis Reef") == ["HQ-9B", "HQ-9B SAMs"]


def test_weapon_upsert_updates_in_place(conn):
    db.insert_weapon(
        conn, WeaponSpecification(designator="HQ-9B", max_range_km=200, source_citation="old")
    )
    db.insert_weapon(
        conn, WeaponSpecification(designator="HQ-9B", max_range_km=300, source_citation="Dahm p.6")
    )
    assert db.counts(conn)["weapon_specifications"] == 1
    assert db.get_weapon(conn, "HQ-9B").max_range_km == 300


def test_duplicate_outpost_link_is_ignored(conn):
    o = OutpostInfrastructure(
        reef_name="Subi Reef", verified_deployed_weapons=["HQ-9B", "HQ-9B"]
    )
    db.insert_outpost(conn, o)
    assert db.get_outpost_weapons(conn, "Subi Reef") == ["HQ-9B"]
