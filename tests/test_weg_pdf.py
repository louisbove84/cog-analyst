"""Hybrid document-relational ingestion tests (synthetic WEG-style PDF)."""

import json

import pytest

fitz = pytest.importorskip("fitz", reason="PyMuPDF required for WEG PDF tests")

from cog_analyst import db
from cog_analyst.db import document_store
from cog_analyst.ingestion.weg_pdf import AssetRecord, parse_document


def _make_sample_pdf(path):
    """Build a small PDF mirroring WEG typography (content vs. page noise)."""
    doc = fitz.open()

    def page_with(lines):
        page = doc.new_page()
        y = 72
        for text, size, font in lines:
            page.insert_text((72, y), text, fontsize=size, fontname=font)
            y += size + 8

    # Asset A, page 1 (title wraps across two 16pt lines).
    page_with([
        ("Test Alpha", 16, "tiro"),
        ("Fighter Aircraft", 16, "tiro"),
        ("WEG Location: https://example.mil/asset/alpha", 8, "tiro"),
        ("Domain: Air, Fighter", 8, "tiro"),
        ("Origin: Testland", 8, "tiro"),
        ("Notes", 12, "tiro"),
        ("The Test Alpha is a prototype: it flies fast.", 8, "tiro"),
        ("System", 12, "tiro"),
        ("Ceiling (m): 16765", 8, "tiro"),
        ("Date of Introduction", 9.4, "tiro"),
        ("M: 2001", 8, "tiro"),
        ("For Training Use Only", 11.2, "tiro"),
        ("Exported (UTC) @ 6/13/26, 6:38 AM", 11.2, "tiro"),
        ("1", 12, "helv"),
    ])
    # Asset A, page 2 (section continues across the page break).
    page_with([
        ("Speed (km/h)", 9.4, "tiro"),
        ("Maximum: 2390", 8, "tiro"),
        ("Engines", 9.4, "tiro"),
        # Long, sentence-like label must still be captured as key/value.
        ("19,955 lbs. thrust SNECMA M-88-3 turbofans with afterburner: 2", 8, "tiro"),
        ("ARMAMENT", 12, "tiro"),
        ("Cannon: 1", 8, "tiro"),
        ("For Training Use Only", 11.2, "tiro"),
        ("2", 12, "helv"),
    ])
    # Asset B, page 3.
    page_with([
        ("Test Bravo Missile", 16, "tiro"),
        ("WEG Location: https://example.mil/asset/bravo", 8, "tiro"),
        ("Notes", 12, "tiro"),
        ("Bravo is a missile.", 8, "tiro"),
        ("System", 12, "tiro"),
        ("Range (km): 300", 8, "tiro"),
        ("For Training Use Only", 11.2, "tiro"),
        ("3", 12, "helv"),
    ])

    doc.save(str(path))
    doc.close()


@pytest.fixture()
def sample_pdf(tmp_path):
    path = tmp_path / "sample_weg.pdf"
    _make_sample_pdf(path)
    return path


def test_parses_two_assets(sample_pdf):
    records = list(parse_document(sample_pdf))
    assert [r.asset_title for r in records] == [
        "Test Alpha Fighter Aircraft",  # wrapped title merged
        "Test Bravo Missile",
    ]


def test_relational_core_fields(sample_pdf):
    a = list(parse_document(sample_pdf))[0]
    assert a.source_url == "https://example.mil/asset/alpha"
    assert "prototype" in a.notes  # Notes prose routed to the notes column


def test_dynamic_payload_structure_and_kv(sample_pdf):
    a = list(parse_document(sample_pdf))[0]
    payload = a.payload
    # Pre-section metadata, minus the promoted URL.
    assert payload["Metadata"]["Domain"] == "Air, Fighter"
    assert payload["Metadata"]["Origin"] == "Testland"
    assert "WEG Location" not in payload["Metadata"]
    # Section-level key/value.
    assert payload["System"]["Ceiling (m)"] == "16765"
    # Nested sub-section key/value, including one that continued onto page 2.
    assert payload["System"]["Date of Introduction"]["M"] == "2001"
    assert payload["System"]["Speed (km/h)"]["Maximum"] == "2390"
    assert payload["ARMAMENT"]["Cannon"] == "1"
    # Notes is a relational column, not duplicated into the payload.
    assert "Notes" not in payload


def test_long_label_kept_as_key_value(sample_pdf):
    a = list(parse_document(sample_pdf))[0]
    engines = a.payload["System"]["Engines"]
    assert engines == {
        "19,955 lbs. thrust SNECMA M-88-3 turbofans with afterburner": "2"
    }


def test_page_furniture_is_discarded(sample_pdf):
    blob = json.dumps([r.payload for r in parse_document(sample_pdf)])
    assert "For Training Use Only" not in blob
    assert "Exported (UTC)" not in blob


def test_limit_stops_early(sample_pdf):
    records = list(parse_document(sample_pdf, limit=1))
    assert len(records) == 1
    assert records[0].asset_title == "Test Alpha Fighter Aircraft"


def test_upsert_round_trip_and_dedupe(tmp_path, sample_pdf):
    conn = db.connect(tmp_path / "weg.db")
    document_store.initialize_document_store(conn)
    try:
        for record in parse_document(sample_pdf):
            document_store.upsert_asset(conn, record)
        assert document_store.asset_count(conn) == 2

        stored = document_store.get_asset(conn, "Test Bravo Missile")
        assert stored["source_url"] == "https://example.mil/asset/bravo"
        assert stored["payload"]["System"]["Range (km)"] == "300"

        # Re-ingesting the same titles overwrites rather than duplicating.
        for record in parse_document(sample_pdf):
            document_store.upsert_asset(conn, record)
        assert document_store.asset_count(conn) == 2

        # The UNIQUE primary key blocks duplicate titles at the DB level.
        document_store.upsert_asset(
            conn,
            AssetRecord(
                asset_title="Test Bravo Missile",
                source_url="https://example.mil/asset/bravo-v2",
                notes="updated",
                payload={"System": {"Range (km)": "350"}},
            ),
        )
        assert document_store.asset_count(conn) == 2
        updated = document_store.get_asset(conn, "Test Bravo Missile")
        assert updated["notes"] == "updated"
        assert updated["payload"]["System"]["Range (km)"] == "350"
    finally:
        conn.close()
