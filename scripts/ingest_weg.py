"""Entry point: ingest the WEG-style export PDF into a hybrid SQLite store.

Usage:
    # Ingest Chinese assets only (the project default) into data/weg.db:
    python scripts/ingest_weg.py

    # Keep a different country (substring match on Metadata.Origin / title):
    python scripts/ingest_weg.py --origin Russia

    # Disable origin filtering and keep everything:
    python scripts/ingest_weg.py --all-origins

    # Sample the first 25 *kept* assets (fast smoke test on a huge file):
    python scripts/ingest_weg.py --limit 25

    # Custom paths:
    python scripts/ingest_weg.py --pdf rag_docs/fullwegexportcompressed.pdf --db data/weg.db

Parsing is fully deterministic (no LLM): a stateful typography scraper turns each
asset into a relational core (title + notes + source_url) plus a dynamic JSON
payload, written via an idempotent UPSERT keyed on the unique asset title. The
corpus is filtered to a single country of origin so the store stays focused.
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
from cog_analyst.db import document_store  # noqa: E402
from cog_analyst.ingestion.weg_pdf import AssetRecord, parse_document  # noqa: E402

DEFAULT_PDF = config.RAG_DOCS_DIR / "fullwegexportcompressed.pdf"
DEFAULT_DB = config.DATA_DIR / "weg.db"
DEFAULT_ORIGIN = "China"


def _origin_text(record: AssetRecord) -> str:
    """Best-effort origin string from the payload's Metadata block."""
    origin = (record.payload.get("Metadata") or {}).get("Origin", "")
    if isinstance(origin, list):
        origin = " ".join(str(o) for o in origin)
    return str(origin)


def _origin_matches(record: AssetRecord, needle: str) -> bool:
    """True if the country needle appears in the asset's origin or title.

    Matching the title too catches records whose Metadata.Origin failed to parse
    but whose name still identifies the country (e.g. '... Chinese ...').
    """
    needle = needle.casefold()
    return needle in _origin_text(record).casefold() or needle in record.asset_title.casefold()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ingest the WEG export PDF into SQLite.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="Source PDF path.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Target SQLite DB path.")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N kept assets.")
    parser.add_argument(
        "--origin",
        default=DEFAULT_ORIGIN,
        help="Keep only assets whose Metadata.Origin/title contains this (default: China).",
    )
    parser.add_argument(
        "--all-origins",
        action="store_true",
        help="Disable origin filtering and ingest every asset.",
    )
    parser.add_argument(
        "--log-every", type=int, default=500, help="Progress log interval (assets)."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if not args.pdf.exists():
        parser.error(f"PDF not found: {args.pdf}")
        return 2

    origin_filter = None if args.all_origins else args.origin
    scope = "all origins" if origin_filter is None else f"origin ~ {origin_filter!r}"
    print(f"Ingesting {args.pdf} -> {args.db}  [{scope}]")

    conn = db.connect(args.db)
    document_store.initialize_document_store(conn)
    try:
        kept = 0
        skipped = 0
        # parse_document's own limit counts every asset; we want a limit on KEPT
        # rows, so we filter here and stop manually.
        for record in parse_document(args.pdf, log_every=args.log_every):
            if origin_filter is not None and not _origin_matches(record, origin_filter):
                skipped += 1
                continue
            document_store.upsert_asset(conn, record)
            kept += 1
            if args.limit is not None and kept >= args.limit:
                break
        total = document_store.asset_count(conn)
        print(
            f"\nDone. Kept {kept} matching asset(s), skipped {skipped}; "
            f"{total} unique asset(s) in store."
        )
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
