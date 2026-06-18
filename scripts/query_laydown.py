"""CLI: query the WEG × OOB capability laydown join.

Usage:
    python scripts/query_laydown.py --designator J-20
    python scripts/query_laydown.py --designator J-20 --theater Eastern
    python scripts/query_laydown.py --designator H-6 --role bomber
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
from cog_analyst.db import join_queries, oob_store  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Query WEG capability × OOB laydown join."
    )
    parser.add_argument("--designator", help="Aircraft type (J-20, 歼-20, ...).")
    parser.add_argument("--theater", help="Theater filter (Eastern, Southern, ...).")
    parser.add_argument("--role", help="Role filter (fighter, bomber, ...).")
    parser.add_argument("--service", help="Service filter (PLAAF, PLANAF).")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--weg", type=Path, default=config.WEG_DB_PATH)
    parser.add_argument("--oob", type=Path, default=config.OOB_DB_PATH)
    args = parser.parse_args(argv)

    if not args.weg.exists():
        parser.error(f"WEG DB not found: {args.weg}")
    if not args.oob.exists():
        parser.error(f"OOB DB not found: {args.oob}")

    conn = db.connect(args.oob)
    oob_store.initialize_oob_store(conn)
    join_queries.attach_weg(conn, args.weg)
    try:
        hits = join_queries.capability_laydown(
            conn,
            designator=args.designator,
            theater=args.theater,
            role=args.role,
            service=args.service,
            limit=args.limit,
        )
        rows = join_queries.laydown_as_dicts(hits)
        for row in rows:
            if row.get("weg_asset_title"):
                system = join_queries.laydown_payload_slice(
                    conn, row["weg_asset_title"], section="System"
                )
                if system is not None:
                    row["weg_system"] = system
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
