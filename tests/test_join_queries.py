"""Cross-DB join tests: WEG capabilities × OOB laydown."""

from cog_analyst.db import join_queries


# TLDR: Join matches en_designator J-20 to a WEG asset title and returns both URLs.
def test_capability_laydown_joins_weg_and_oob(laydown_dbs):
    oob_conn, _ = laydown_dbs
    hits = join_queries.capability_laydown(oob_conn, designator="J-20")
    assert len(hits) == 1
    hit = hits[0]
    assert hit.unit_name == "空9旅"
    assert hit.en_designator == "J-20"
    assert hit.weg_asset_title.startswith("J-20")
    assert hit.weg_source_url == "https://example.mil/weg/j-20"
    assert hit.oob_source_url == "https://example.org/oob"


# TLDR: Theater filter narrows laydown rows without touching unrelated units.
def test_capability_laydown_theater_filter(laydown_dbs):
    oob_conn, _ = laydown_dbs
    assert join_queries.capability_laydown(oob_conn, theater="Southern") == []
    assert len(join_queries.capability_laydown(oob_conn, theater="Eastern")) == 1


# TLDR: laydown_payload_slice fetches one WEG section through the attached DB.
def test_laydown_payload_slice(laydown_dbs):
    oob_conn, _ = laydown_dbs
    hits = join_queries.capability_laydown(oob_conn, designator="J-20")
    system = join_queries.laydown_payload_slice(
        oob_conn, hits[0].weg_asset_title, section="System"
    )
    assert system["Maximum Range (km)"] == "2000"


# TLDR: laydown_as_dicts produces JSON-serializable rows for agent state.
def test_laydown_as_dicts(laydown_dbs):
    oob_conn, _ = laydown_dbs
    hits = join_queries.capability_laydown(oob_conn, designator="歼-20")
    rows = join_queries.laydown_as_dicts(hits)
    assert rows[0]["unit_name"] == "空9旅"
    assert rows[0]["en_designator"] == "J-20"
