"""Entry point: ingest the PLA air OOB Markdown export into SQLite.

Usage:
    # Ingest into data/oob.db (default paths):
    python scripts/ingest_oob.py --md rag_docs/pla_air_oob.md

    # Keep staff/HQ rows that have no aircraft (default drops them):
    python scripts/ingest_oob.py --md rag_docs/pla_air_oob.md --keep-empty

    # Custom DB path:
    python scripts/ingest_oob.py --md rag_docs/pla_air_oob.md --db data/oob.db

Parsing is fully deterministic (no LLM): a stateful Markdown table scraper turns
each unit row into a relational record plus normalized aircraft links, written
via an idempotent UPSERT keyed on the unit. Aircraft designators are crosswalked
from Chinese to Latin so they join ``data/weg.db`` by ``en_designator``.
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
from cog_analyst.db import oob_store  # noqa: E402
from cog_analyst.ingestion.oob_markdown import parse_markdown  # noqa: E402

DEFAULT_MD = config.RAG_DOCS_DIR / "pla_air_oob.md"
DEFAULT_DB = config.DATA_DIR / "oob.db"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest the PLA air OOB Markdown export into SQLite."
    )
    parser.add_argument(
        "--md", type=Path, default=DEFAULT_MD, help="Source Markdown path."
    )
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help="Target SQLite DB path."
    )
    parser.add_argument(
        "--keep-empty",
        action="store_true",
        help="Keep rows with no recognized aircraft (default: drop them).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    if not args.md.exists():
        parser.error(f"Markdown file not found: {args.md}")
        return 2

    print(f"Ingesting {args.md} -> {args.db}")
    conn = db.connect(args.db)
    oob_store.initialize_oob_store(conn)
    try:
        ingested = 0
        for record in parse_markdown(args.md, require_aircraft=not args.keep_empty):
            oob_store.upsert_unit(conn, record)
            ingested += 1
        total = oob_store.unit_count(conn)
        print(f"\nDone. Ingested {ingested} unit row(s); {total} unit(s) in store.")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
