"""RAG vector store tests (Parent-Child) with a deterministic fake embedder."""

import numpy as np
import pytest

from cog_analyst.db import database, rag_store
from cog_analyst.rag.chunking import ChildChunk, ParentChunk
from cog_analyst.rag.embedder import GoogleEmbedder


def _seed(conn, embedder, parents, children):
    """Insert parents + embedded children into a fresh store."""
    parent_ids = rag_store.add_parents(conn, parents)
    vectors = embedder.embed([c.text for c in children])
    rag_store.add_children(conn, children, vectors, parent_ids)


@pytest.fixture()
def rag_conn(tmp_path, fake_embedder):
    conn = database.connect(tmp_path / "rag.db")
    rag_store.initialize_rag_store(conn, dimension=fake_embedder.dimension)
    parents = [
        ParentChunk("cmpr.pdf", 10, "PLA air power depends on fixed airbases and fuel"),
        ParentChunk("dahm.pdf", 4, "Naval shipbuilding capacity and dry docks"),
    ]
    # Two children on parent 0 (page 10), one on parent 1 (page 4).
    children = [
        ChildChunk("cmpr.pdf", 10, "fixed airbases and fuel for air power", 0),
        ChildChunk("cmpr.pdf", 10, "PLA air power depends on bases", 0),
        ChildChunk("dahm.pdf", 4, "naval shipbuilding capacity dry docks", 1),
    ]
    _seed(conn, fake_embedder, parents, children)
    yield conn, fake_embedder
    conn.close()


# TLDR: Search returns the best-matching PARENT page first, with a citation.
def test_search_returns_parent_pages(rag_conn):
    conn, embedder = rag_conn
    q = embedder.embed_one("airbases and fuel supply for air power")
    hits = rag_store.search(conn, q, max_parents=2)
    assert hits[0].source == "cmpr.pdf"
    assert hits[0].page == 10
    # The returned text is the full parent page, not the matched child window.
    assert hits[0].text == "PLA air power depends on fixed airbases and fuel"
    assert hits[0].citation() == "cmpr.pdf p.10"
    assert hits[0].score >= hits[-1].score


# TLDR: Two children on the same page collapse to ONE parent hit (de-dup).
def test_children_dedup_to_single_parent(rag_conn):
    conn, embedder = rag_conn
    q = embedder.embed_one("PLA air power bases fuel airbases")
    hits = rag_store.search(conn, q, child_pool=10, max_parents=5)
    cmpr_hits = [h for h in hits if h.source == "cmpr.pdf"]
    assert len(cmpr_hits) == 1  # page 10 appears once despite two matching children


# TLDR: max_parents caps how many distinct pages reach the LLM (context bound).
def test_max_parents_caps_results(rag_conn):
    conn, embedder = rag_conn
    q = embedder.embed_one("air power shipbuilding")
    hits = rag_store.search(conn, q, child_pool=10, max_parents=1)
    assert len(hits) == 1


# TLDR: The sources filter restricts retrieval to specific documents.
def test_search_source_filter(rag_conn):
    conn, embedder = rag_conn
    q = embedder.embed_one("shipbuilding")
    hits = rag_store.search(conn, q, max_parents=5, sources=["dahm.pdf"])
    assert {h.source for h in hits} == {"dahm.pdf"}


# TLDR: counts reflect what was ingested; empty store returns no hits.
def test_counts_and_empty(rag_conn, tmp_path, fake_embedder):
    conn, _ = rag_conn
    assert rag_store.parent_count(conn) == 2
    assert rag_store.chunk_count(conn) == 3

    empty = database.connect(tmp_path / "empty.db")
    rag_store.initialize_rag_store(empty, dimension=fake_embedder.dimension)
    try:
        assert rag_store.chunk_count(empty) == 0
        assert rag_store.search(empty, fake_embedder.embed_one("anything")) == []
    finally:
        empty.close()


# TLDR: Length mismatch between children and vectors is rejected loudly.
def test_add_children_length_mismatch(rag_conn):
    conn, embedder = rag_conn
    parent_ids = rag_store.add_parents(conn, [ParentChunk("x.pdf", 1, "p")])
    with pytest.raises(ValueError):
        rag_store.add_children(
            conn,
            [ChildChunk("x.pdf", 1, "a", 0)],
            embedder.embed(["a", "b"]),
            parent_ids,
        )


class _FakeGenAIClient:
    """Stand-in for google-genai: records the task_type and returns unit-ish vecs."""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self.calls = []

    class _Resp:
        def __init__(self, embeddings):
            self.embeddings = embeddings

    class _Emb:
        def __init__(self, values):
            self.values = values

    @property
    def models(self):
        return self

    def embed_content(self, *, model, contents, config):
        task = config["task_type"] if isinstance(config, dict) else config.task_type
        self.calls.append(task)
        embs = [
            self._Emb([float(i + 1)] * self.dimension) for i, _ in enumerate(contents)
        ]
        return self._Resp(embs)


# TLDR: GoogleEmbedder normalizes vectors and uses asymmetric task types.
def test_google_embedder_normalizes_and_sets_task_types():
    client = _FakeGenAIClient(dimension=8)
    embedder = GoogleEmbedder(dimension=8, client=client)

    docs = embedder.embed(["alpha", "beta"])
    assert docs.shape == (2, 8)
    # L2-normalized: each row has unit norm.
    np.testing.assert_allclose(np.linalg.norm(docs, axis=1), [1.0, 1.0], rtol=1e-6)

    query = embedder.embed_one("alpha")
    assert query.shape == (8,)
    # Documents use RETRIEVAL_DOCUMENT; the query uses RETRIEVAL_QUERY.
    assert client.calls == ["RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY"]
