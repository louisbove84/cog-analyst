"""Demo CLI for the WEG document store's JSON1 query layer.

These are the same functions an agent would call as tools; the CLI just exercises
them against ``data/weg.db`` so you can see the grounded results by hand.

Examples:
    # What countries / how many assets are in the store?
    python scripts/query_weg.py origins

    # What is the corpus made of (fine-grained categories)?
    python scripts/query_weg.py breakdown

    # "Show me all Chinese UAVs"
    python scripts/query_weg.py search --domain UAV

    # Search by title substring
    python scripts/query_weg.py search --name J-20

    # What sections does one asset have, then fetch one of them?
    python scripts/query_weg.py sections "J-20 Chinese Multirole Fighter Aircraft"
    python scripts/query_weg.py \
        section "J-20 Chinese Multirole Fighter Aircraft" ARMAMENT
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cog_analyst import config, db  # noqa: E402

DEFAULT_DB = config.DATA_DIR / "weg.db"


def _print_hits(hits) -> None:
    if not hits:
        print("(no matches)")
        return
    for hit in hits:
        print(f"- {hit.asset_title}")
        print(f"    origin: {hit.origin}")
        print(f"    domain: {hit.domain}")
        print(f"    source: {hit.source_url}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Query the WEG document store.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite DB path.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("origins", help="List origins and their asset counts.")

    p_break = sub.add_parser(
        "breakdown", help="Category breakdown (optionally by origin)."
    )
    p_break.add_argument(
        "--origin", default=None, help="Restrict to one origin substring."
    )

    p_search = sub.add_parser("search", help="Search assets by origin/domain/name.")
    p_search.add_argument(
        "--origin", default=None, help="Origin substring (e.g. China)."
    )
    p_search.add_argument(
        "--domain", default=None, help="Domain substring (e.g. UAV, Fighter)."
    )
    p_search.add_argument("--name", default=None, help="Title substring.")
    p_search.add_argument("--limit", type=int, default=50, help="Max results.")

    p_sections = sub.add_parser("sections", help="List an asset's payload sections.")
    p_sections.add_argument("title", help="Exact asset title.")

    p_section = sub.add_parser("section", help="Print one payload section of an asset.")
    p_section.add_argument("title", help="Exact asset title.")
    p_section.add_argument("section", help="Section name (see the 'sections' command).")

    args = parser.parse_args(argv)

    if not args.db.exists():
        parser.error(f"DB not found: {args.db} (run scripts/ingest_weg.py first)")
        return 2

    conn = db.connect(args.db)
    try:
        if args.command == "origins":
            for origin, n in db.list_origins(conn).items():
                print(f"   {n:4d}  {origin}")

        elif args.command == "breakdown":
            breakdown = db.category_breakdown(conn, origin=args.origin)
            total = sum(breakdown.values()) or 1
            scope = f" (origin ~ {args.origin!r})" if args.origin else ""
            print(f"Category breakdown{scope}: {total} assets")
            for category, n in breakdown.items():
                print(f"   {n:4d}  ({n / total * 100:5.1f}%)  {category}")

        elif args.command == "search":
            hits = db.search_assets(
                conn,
                origin=args.origin,
                domain=args.domain,
                name_contains=args.name,
                limit=args.limit,
            )
            print(f"{len(hits)} match(es):")
            _print_hits(hits)

        elif args.command == "sections":
            sections = db.get_asset_sections(conn, args.title)
            if not sections:
                print(f"(no asset titled {args.title!r})")
            else:
                print(f"Sections for {args.title!r}:")
                for name in sections:
                    print(f"   - {name}")

        elif args.command == "section":
            value = db.get_asset_section(conn, args.title, args.section)
            if value is None:
                print(f"(no section {args.section!r} for {args.title!r})")
            else:
                print(json.dumps(value, indent=2, ensure_ascii=False))
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
