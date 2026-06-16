"""Tests for the WEG JSON1 query/agent-tool layer (offline, in-memory)."""

from __future__ import annotations

import pytest

from cog_analyst import db
from cog_analyst.ingestion.weg_pdf import AssetRecord


def _record(title, origin, domain, sections=None):
    payload = {"Metadata": {"Origin": origin, "Domain": domain}}
    if sections:
        payload.update(sections)
    return AssetRecord(
        asset_title=title,
        source_url=f"https://example/{title.replace(' ', '_')}",
        notes="prose",
        payload=payload,
    )


@pytest.fixture()
def weg_conn():
    conn = db.connect(":memory:")
    db.initialize_document_store(conn)
    records = [
        _record(
            "J-20 Chinese Multirole Fighter Aircraft",
            "China, People's Republic of",
            "Air, Aircraft, Fixed Wing Aircraft, Fighter Aircraft",
            {"ARMAMENT": {"_text": "PL-15"}, "System": {"Crew": "1"}},
        ),
        _record(
            "Wing Loong II Chinese Unmanned Aerial Vehicle (UAV)",
            "China, People's Republic of",
            "Air, Aircraft, Unmanned, Long-Distance UAVs (More than 300 km)",
        ),
        _record(
            "MQ-9 Reaper American Unmanned Aerial Vehicle (UAV)",
            "United States",
            "Air, Aircraft, Unmanned, Long-Distance UAVs (More than 300 km)",
        ),
    ]
    for rec in records:
        db.upsert_asset(conn, rec)
    yield conn
    conn.close()


# TLDR: Origin search is case-insensitive and returns only matching-country assets.
def test_search_by_origin_is_case_insensitive(weg_conn):
    hits = db.search_assets(weg_conn, origin="china")
    titles = {h.asset_title for h in hits}
    assert titles == {
        "J-20 Chinese Multirole Fighter Aircraft",
        "Wing Loong II Chinese Unmanned Aerial Vehicle (UAV)",
    }


# TLDR: Origin + domain filters combine ("Chinese UAVs" returns just the UAV).
def test_search_by_domain_substring(weg_conn):
    hits = db.search_assets(weg_conn, origin="china", domain="UAV")
    assert [h.asset_title for h in hits] == [
        "Wing Loong II Chinese Unmanned Aerial Vehicle (UAV)"
    ]


# TLDR: Title-substring search returns the asset with its origin and citation.
def test_search_by_name(weg_conn):
    hits = db.search_assets(weg_conn, name_contains="j-20")
    assert len(hits) == 1
    assert hits[0].origin == "China, People's Republic of"
    assert hits[0].source_url.endswith("J-20_Chinese_Multirole_Fighter_Aircraft")


# TLDR: The limit argument caps the number of search results.
def test_search_limit(weg_conn):
    assert len(db.search_assets(weg_conn, limit=1)) == 1


# TLDR: list_origins() reports each country with its asset count.
def test_list_origins_counts(weg_conn):
    origins = db.list_origins(weg_conn)
    assert origins["China, People's Republic of"] == 2
    assert origins["United States"] == 1


# TLDR: Category breakdown counts assets by type and respects the origin filter.
def test_category_breakdown_by_origin(weg_conn):
    breakdown = db.category_breakdown(weg_conn, origin="china")
    assert breakdown["Long-Distance UAVs (More than 300 km)"] == 1
    assert breakdown["Fighter Aircraft"] == 1
    # The American UAV must be excluded by the origin filter.
    assert sum(breakdown.values()) == 2


# TLDR: An asset's payload section names are listed in stored order.
def test_get_asset_sections_in_order(weg_conn):
    sections = db.get_asset_sections(
        weg_conn, "J-20 Chinese Multirole Fighter Aircraft"
    )
    assert sections == ["Metadata", "ARMAMENT", "System"]


# TLDR: Fetching one named section returns just that slice of the payload.
def test_get_asset_section_returns_subtree(weg_conn):
    section = db.get_asset_section(
        weg_conn, "J-20 Chinese Multirole Fighter Aircraft", "ARMAMENT"
    )
    assert section == {"_text": "PL-15"}


# TLDR: Unknown assets/sections return empty/None instead of raising.
def test_unknown_asset_and_section_return_empty(weg_conn):
    assert db.get_asset_sections(weg_conn, "Nope") == []
    assert db.get_asset_section(weg_conn, "Nope", "ARMAMENT") is None
    assert (
        db.get_asset_section(
            weg_conn, "J-20 Chinese Multirole Fighter Aircraft", "NoSuchSection"
        )
        is None
    )
