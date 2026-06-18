"""Entry point: run the grounded COG analysis graph.

Usage:
    python scripts/run_cog_agent.py \\
        --query "Assess J-20 threat laydown" --designator J-20

    python scripts/run_cog_agent.py \\
        --query "Southern theater bombers" --role bomber --theater Southern

Requires ``pip install -e '.[agent]'`` and a configured ``.env`` LLM backend.
Node 1 (retrieve) is deterministic; nodes 2–4 call the LLM with structured output.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cog_analyst import config  # noqa: E402
from cog_analyst.cog.graph import run_analysis  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the COG analysis agent.")
    parser.add_argument("--query", required=True, help="Analyst question (context).")
    parser.add_argument(
        "--designator", help="Override the aircraft type filter (else inferred)."
    )
    parser.add_argument(
        "--theater", help="Override the theater filter (else inferred from query)."
    )
    parser.add_argument("--role", help="Override the role filter (else inferred).")
    parser.add_argument("--weg", type=Path, default=config.WEG_DB_PATH)
    parser.add_argument("--oob", type=Path, default=config.OOB_DB_PATH)
    parser.add_argument("--rag", type=Path, default=config.RAG_DB_PATH)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    if not args.weg.exists():
        parser.error(f"WEG DB not found: {args.weg}")
    if not args.oob.exists():
        parser.error(f"OOB DB not found: {args.oob}")

    result = run_analysis(
        args.query,
        designator=args.designator,
        theater=args.theater,
        role=args.role,
        oob_path=args.oob,
        weg_path=args.weg,
        rag_path=args.rag,
    )
    print(json.dumps(dict(result), ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
