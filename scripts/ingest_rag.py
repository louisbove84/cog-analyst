"""Entry point: chunk + embed the doctrinal PDFs into the RAG vector store.

Uses Parent-Child chunking: each page becomes a parent passage, split into small
child windows. Only the children are embedded (precise matching); the parents are
stored as text and returned to the LLM at query time (rich context).

Usage:
    # Embed every PDF in rag_docs/ into data/rag.db:
    python scripts/ingest_rag.py

    # Specific files only:
    python scripts/ingest_rag.py --pdf rag_docs/China_Military_Power_2019.pdf

    # Tune child windows / DB:
    python scripts/ingest_rag.py --child-words 150 --child-overlap 30 --db data/rag.db

Requires ``pip install -e '.[rag]'`` and an embedding backend configured in
``.env`` (Google by default; see config.resolve_embed_settings). The WEG/OOB
source files are skipped since those have their own deterministic pipelines.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cog_analyst import config, db  # noqa: E402
from cog_analyst.db import rag_store  # noqa: E402
from cog_analyst.rag.chunking import chunk_pdf  # noqa: E402
from cog_analyst.rag.embedder import build_embedder  # noqa: E402

DEFAULT_DB = config.DATA_DIR / "rag.db"
# Source files consumed by other (structured) pipelines, not the RAG corpus.
_SKIP = {"fullwegexportcompressed.pdf"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Chunk + embed doctrinal PDFs into the RAG vector store."
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        nargs="*",
        help="Specific PDF(s). Default: every PDF in rag_docs/ (minus sources).",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--child-words", type=int, default=150)
    parser.add_argument("--child-overlap", type=int, default=30)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    if args.pdf:
        pdfs = list(args.pdf)
    else:
        pdfs = sorted(
            p for p in config.RAG_DOCS_DIR.glob("*.pdf") if p.name not in _SKIP
        )
    if not pdfs:
        parser.error("no PDFs to ingest")

    settings = config.resolve_embed_settings()
    print(
        f"Embedding backend: {settings.backend} "
        f"({settings.model}, dim={settings.dimension or 'model-defined'})"
    )
    embedder = build_embedder()
    conn = db.connect(args.db)
    rag_store.initialize_rag_store(conn, dimension=embedder.dimension)
    try:
        total_children = 0
        for pdf in pdfs:
            if not pdf.exists():
                print(f"  skip (missing): {pdf}")
                continue
            parents, children = chunk_pdf(
                pdf,
                child_words=args.child_words,
                child_overlap=args.child_overlap,
            )
            if not children:
                print(f"  {pdf.name}: 0 chunks")
                continue
            parent_ids = rag_store.add_parents(conn, parents)
            vectors = embedder.embed([c.text for c in children])
            written = rag_store.add_children(conn, children, vectors, parent_ids)
            total_children += written
            print(f"  {pdf.name}: {len(parents)} parents / {written} children")
        print(
            f"\nDone. {rag_store.parent_count(conn)} parents, "
            f"{rag_store.chunk_count(conn)} children in store."
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
