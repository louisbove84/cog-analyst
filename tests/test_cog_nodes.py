"""COG agent node tests (retrieve is offline; LLM nodes need [agent] extras)."""

from pathlib import Path

from cog_analyst.cog.nodes import (
    _capability_view,
    resolve_scenario_node,
    retrieve_context_node,
    retrieve_node,
)
from cog_analyst.db import database, rag_store
from cog_analyst.rag.chunking import ChildChunk, ParentChunk


# TLDR: Node 1 joins WEG+OOB and attaches flattened weg_specs to raw_assets.
def test_retrieve_node_populates_raw_assets(laydown_dbs):
    oob_conn, weg_conn = laydown_dbs
    oob_path = Path(oob_conn.execute("PRAGMA database_list").fetchone()["file"])
    weg_path = Path(weg_conn.execute("PRAGMA database_list").fetchone()["file"])
    oob_conn.close()
    weg_conn.close()

    state = {"designator": "J-20", "theater": None, "role": None}
    out = retrieve_node(state, oob_path=oob_path, weg_path=weg_path)
    assert out["error"] is None
    assert len(out["raw_assets"]) == 1
    asset = out["raw_assets"][0]
    assert asset["unit_name"] == "空9旅"
    assert asset["weg_specs"]["Maximum Range (km)"] == "2000"


# TLDR: The capability view exposes specs but withholds geography from CC/CR.
def test_capability_view_strips_geography(laydown_dbs):
    oob_conn, weg_conn = laydown_dbs
    oob_path = Path(oob_conn.execute("PRAGMA database_list").fetchone()["file"])
    weg_path = Path(weg_conn.execute("PRAGMA database_list").fetchone()["file"])
    oob_conn.close()
    weg_conn.close()

    out = retrieve_node({"designator": "J-20"}, oob_path=oob_path, weg_path=weg_path)
    view = _capability_view(out["raw_assets"])
    assert view[0]["designator"] == "J-20"
    assert view[0]["specs"]["Maximum Range (km)"] == "2000"
    # Geography must not leak into the capability/requirement reasoning input.
    assert "airbase" not in view[0]
    assert "location_text" not in view[0]


# TLDR: Node 1 sets error when no rows match the filters.
def test_retrieve_node_empty_sets_error(laydown_dbs):
    oob_conn, weg_conn = laydown_dbs
    oob_path = Path(oob_conn.execute("PRAGMA database_list").fetchone()["file"])
    weg_path = Path(weg_conn.execute("PRAGMA database_list").fetchone()["file"])
    oob_conn.close()
    weg_conn.close()

    out = retrieve_node(
        {"designator": "J-20", "theater": "Southern", "role": None},
        oob_path=oob_path,
        weg_path=weg_path,
    )
    assert out["raw_assets"] == []
    assert out["error"]


# TLDR: Node 0 turns a location query into deterministic theater filters.
def test_resolve_scenario_node():
    out = resolve_scenario_node({"query": "J-20 threat to Taiwan"})
    assert out["designator"] == "J-20"
    assert out["theater"] == "Eastern"
    assert out["matched_location"] == "taiwan"


# TLDR: Context node embeds the scoped query and returns cited RAG snippets.
def test_retrieve_context_node_returns_cited_snippets(tmp_path, fake_embedder):
    rag_path = tmp_path / "rag.db"
    conn = database.connect(rag_path)
    rag_store.initialize_rag_store(conn, dimension=fake_embedder.dimension)
    parents = [ParentChunk("cmpr.pdf", 7, "J-20 fighters rely on fixed Taiwan bases")]
    children = [ChildChunk("cmpr.pdf", 7, "J-20 fighters fixed Taiwan bases", 0)]
    parent_ids = rag_store.add_parents(conn, parents)
    rag_store.add_children(
        conn, children, fake_embedder.embed([c.text for c in children]), parent_ids
    )
    conn.close()

    state = {"query": "J-20 threat", "designator": "J-20", "matched_location": "taiwan"}
    out = retrieve_context_node(
        state, embedder=fake_embedder, rag_path=rag_path, max_parents=3
    )
    assert out["context_snippets"]
    assert out["context_snippets"][0]["citation"] == "cmpr.pdf p.7"
    # Parent-child returns the full parent page text, not the child window.
    assert out["context_snippets"][0]["text"].startswith("J-20 fighters rely")


# TLDR: Missing RAG store degrades gracefully to empty context.
def test_retrieve_context_node_missing_store(tmp_path, fake_embedder):
    out = retrieve_context_node(
        {"query": "x", "designator": "J-20"},
        embedder=fake_embedder,
        rag_path=tmp_path / "nope.db",
    )
    assert out["context_snippets"] == []
