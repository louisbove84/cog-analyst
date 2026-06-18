"""SQLite-backed vector store for the RAG corpus (Parent-Child retrieval).

Two tables implement hierarchical retrieval:

  * ``rag_parents`` — one full page of text, NOT embedded. This is what the LLM
    actually reads, so it gets a complete idea rather than a fragment.
  * ``rag_chunks``  — small child windows WITH embeddings, each pointing at its
    parent. These are what we match against (precise), then resolve up to the
    parent (rich context).

Retrieval ranks children by exact cosine similarity (vectors are pre-normalized,
so cosine == dot product), then **de-duplicates onto distinct parents** and caps
the result at ``max_parents`` to bound the LLM context. Brute force over a few
thousand children is sub-millisecond; swap in FAISS/Chroma if the corpus grows.

Every hit carries ``source`` + ``page`` so retrieved context is always citable.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Sequence

if TYPE_CHECKING:
    import numpy as np

    from cog_analyst.rag.chunking import ChildChunk, ParentChunk

__all__ = [
    "RAG_SCHEMA",
    "ContextHit",
    "initialize_rag_store",
    "add_parents",
    "add_children",
    "search",
    "chunk_count",
    "parent_count",
]

RAG_SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_parents (
    parent_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source    TEXT    NOT NULL,
    page      INTEGER NOT NULL,
    text      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id INTEGER NOT NULL REFERENCES rag_parents (parent_id),
    source    TEXT    NOT NULL,
    page      INTEGER NOT NULL,
    text      TEXT    NOT NULL,
    embedding BLOB    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_parent ON rag_chunks (parent_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_source ON rag_chunks (source);
CREATE INDEX IF NOT EXISTS idx_rag_parents_source ON rag_parents (source);
"""


@dataclass(frozen=True)
class ContextHit:
    """One retrieved parent page with provenance and its best child score."""

    source: str
    page: int
    text: str
    score: float

    def citation(self) -> str:
        """Human-readable citation, e.g. ``China_Military_Power_2019.pdf p.42``."""
        return f"{self.source} p.{self.page}"


def initialize_rag_store(conn: sqlite3.Connection, *, dimension: int) -> None:
    """Create the RAG tables and record the embedding dimension idempotently."""
    try:
        conn.executescript(RAG_SCHEMA)
        conn.execute(
            "INSERT INTO rag_meta (key, value) VALUES ('dimension', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(dimension),),
        )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise


def add_parents(
    conn: sqlite3.Connection, parents: Sequence["ParentChunk"]
) -> List[int]:
    """Insert parent pages and return their assigned ``parent_id``s, in order."""
    ids: List[int] = []
    try:
        for parent in parents:
            cursor = conn.execute(
                "INSERT INTO rag_parents (source, page, text) VALUES (?, ?, ?)",
                (parent.source, parent.page, parent.text),
            )
            if cursor.lastrowid is None:  # pragma: no cover - sqlite always sets it
                raise sqlite3.Error("INSERT did not return a rowid")
            ids.append(int(cursor.lastrowid))
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return ids


def add_children(
    conn: sqlite3.Connection,
    children: Sequence["ChildChunk"],
    vectors: "np.ndarray",
    parent_ids: Sequence[int],
) -> int:
    """Insert embedded children, resolving each ``parent_index`` to a parent_id.

    ``parent_ids`` is the list returned by :func:`add_parents` for the same
    document, so ``parent_ids[child.parent_index]`` is the child's real FK.
    """
    if len(children) != len(vectors):
        raise ValueError("children and vectors length mismatch")
    rows = []
    for i, child in enumerate(children):
        if not 0 <= child.parent_index < len(parent_ids):
            raise ValueError(f"parent_index {child.parent_index} out of range")
        rows.append(
            (
                parent_ids[child.parent_index],
                child.source,
                child.page,
                child.text,
                vectors[i].astype("float32").tobytes(),
            )
        )
    try:
        conn.executemany(
            "INSERT INTO rag_chunks (parent_id, source, page, text, embedding) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return len(children)


def search(
    conn: sqlite3.Connection,
    query_vector: "np.ndarray",
    *,
    child_pool: int = 15,
    max_parents: int = 4,
    sources: Optional[Sequence[str]] = None,
) -> List[ContextHit]:
    """Parent-child search: rank children, de-dup to distinct parent pages.

    Ranks the top ``child_pool`` children by cosine similarity, then walks them
    in descending score order collecting distinct parents until ``max_parents``
    are gathered. Each returned :class:`ContextHit` is a full parent page scored
    by its best-matching child. ``sources`` optionally restricts the search to
    specific document filenames. Returns ``[]`` if the store is empty.
    """
    import numpy as np

    sql = "SELECT parent_id, embedding FROM rag_chunks"
    params: List[object] = []
    if sources:
        placeholders = ",".join("?" for _ in sources)
        sql += f" WHERE source IN ({placeholders})"
        params.extend(sources)
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return []

    matrix = np.frombuffer(
        b"".join(row["embedding"] for row in rows), dtype=np.float32
    ).reshape(len(rows), -1)
    query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
    scores = matrix @ query

    pool = np.argsort(scores)[::-1][: max(child_pool, max_parents)]
    # Children are walked best-first, so the first time a parent appears carries
    # its highest-scoring child — exactly the score we want to attribute to it.
    best_by_parent: dict[int, float] = {}
    order: List[int] = []
    for i in pool:
        parent_id = int(rows[i]["parent_id"])
        if parent_id not in best_by_parent:
            best_by_parent[parent_id] = float(scores[i])
            order.append(parent_id)
        if len(order) >= max_parents:
            break

    hits: List[ContextHit] = []
    for parent_id in order:
        parent = conn.execute(
            "SELECT source, page, text FROM rag_parents WHERE parent_id = ?",
            (parent_id,),
        ).fetchone()
        if parent is None:
            continue
        hits.append(
            ContextHit(
                source=parent["source"],
                page=int(parent["page"]),
                text=parent["text"],
                score=best_by_parent[parent_id],
            )
        )
    return hits


def chunk_count(conn: sqlite3.Connection) -> int:
    """Return the number of embedded child chunks."""
    row = conn.execute("SELECT COUNT(*) AS n FROM rag_chunks").fetchone()
    return int(row["n"] if isinstance(row, sqlite3.Row) else row[0])


def parent_count(conn: sqlite3.Connection) -> int:
    """Return the number of parent pages."""
    row = conn.execute("SELECT COUNT(*) AS n FROM rag_parents").fetchone()
    return int(row["n"] if isinstance(row, sqlite3.Row) else row[0])
