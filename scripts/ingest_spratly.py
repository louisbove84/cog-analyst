"""Entry point: build spratly_fleet.db from core-document text snippets.

Usage:
    # Bundled demo excerpts using whatever backend your .env selects:
    python scripts/ingest_spratly.py --demo

    # Force a local Ollama server (no API key, no cloud):
    #   ollama pull qwen2.5  &&  ollama serve
    python scripts/ingest_spratly.py --demo --backend ollama
    python scripts/ingest_spratly.py --demo --backend ollama --model llama3.1:8b

    # Point at any OpenAI-compatible server (LM Studio, vLLM, xAI, ...):
    python scripts/ingest_spratly.py --demo \\
        --base-url http://localhost:1234/v1 --model my-model

    # Ingest your own snippets from a JSON file with any of these keys:
    #   {"weapons": [...], "aircraft": [...], "radar": [...], "outposts": [...]}
    python scripts/ingest_spratly.py --snippets path/to/snippets.json

This script wires the generic engine (extractor + pipeline + db) to the Spratly
domain pack (source excerpts). Records are written raw; ground-truth
reconciliation is handled against the WEG document store (see scripts/ingest_weg.py).
"""

from __future__ import annotations

import argparse
import functools
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Type

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cog_analyst import config, db  # noqa: E402
from cog_analyst.domains.spratly import (  # noqa: E402
    DEMO_AIRCRAFT_SNIPPETS,
    DEMO_OUTPOST_SNIPPETS,
    DEMO_RADAR_SNIPPETS,
    DEMO_WEAPON_SNIPPETS,
    SPRATLY_DB_PATH,
    OutpostInfrastructure,
)
from cog_analyst.ingestion import IngestionPipeline, LangChainExtractor  # noqa: E402
from cog_analyst.ingestion.pipeline import PersistFn  # noqa: E402
from cog_analyst.models import (  # noqa: E402
    AircraftSpecification,
    RadarSpecification,
    WeaponSpecification,
)
from cog_analyst.models.schemas import CogBaseModel  # noqa: E402


def _load_snippets(path: Path) -> Dict[str, List[str]]:
    data = json.loads(path.read_text())
    return {
        "weapons": list(data.get("weapons", [])),
        "aircraft": list(data.get("aircraft", [])),
        "radar": list(data.get("radar", [])),
        "outposts": list(data.get("outposts", [])),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ingest Spratly COG data into SQLite.")
    parser.add_argument("--demo", action="store_true", help="Use bundled excerpts.")
    parser.add_argument("--snippets", type=Path, help="JSON file of text snippets.")
    parser.add_argument("--db", default=None, help="Optional SQLite DB path.")
    parser.add_argument("--model", default=None, help="LLM model name.")
    parser.add_argument(
        "--backend",
        default=None,
        choices=["openai", "ollama", "lmstudio"],
        help="LLM backend preset (overrides COG_LLM_BACKEND).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible endpoint (e.g. LM Studio/vLLM). Overrides --backend.",
    )
    parser.add_argument(
        "--api-key", default=None, help="API key (ignored by local servers)."
    )
    parser.add_argument(
        "--structured-method",
        default=None,
        choices=["function_calling", "json_schema", "json_mode"],
        help="Structured-output strategy; try 'function_calling' for local models.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    settings = config.resolve_llm_settings(
        backend=args.backend,
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        structured_output_method=args.structured_method,
    )
    print(f"Using model '{settings.model}' via {settings.where}")

    if args.demo:
        snippets = {
            "weapons": DEMO_WEAPON_SNIPPETS,
            "aircraft": DEMO_AIRCRAFT_SNIPPETS,
            "radar": DEMO_RADAR_SNIPPETS,
            "outposts": DEMO_OUTPOST_SNIPPETS,
        }
    elif args.snippets:
        snippets = _load_snippets(args.snippets)
    else:
        parser.error("provide --demo or --snippets PATH")
        return 2

    db_path = Path(args.db) if args.db is not None else SPRATLY_DB_PATH

    extractor = LangChainExtractor(
        model=settings.model,
        base_url=settings.base_url,
        api_key=settings.api_key,
        structured_output_method=settings.structured_output_method,
    )
    pipeline = IngestionPipeline(extractor=extractor)

    conn = db.connect(db_path)
    db.initialize_database(conn)
    try:
        jobs: List[Tuple[str, Type[CogBaseModel], PersistFn]] = [
            ("weapons", WeaponSpecification, functools.partial(db.insert_weapon, conn)),
            (
                "aircraft",
                AircraftSpecification,
                functools.partial(db.insert_aircraft, conn),
            ),
            ("radar", RadarSpecification, functools.partial(db.insert_radar, conn)),
            (
                "outposts",
                OutpostInfrastructure,
                functools.partial(db.insert_outpost, conn),
            ),
        ]
        results = []
        for key, schema, persist in jobs:
            for text in snippets.get(key, []):
                results.append(pipeline.ingest(text, schema, persist))

        inserted = sum(1 for r in results if r.ok)
        print(f"\nIngestion complete: {inserted}/{len(results)} records inserted.")
        for r in results:
            print(f"  [{r.status.value:16s}] {r.schema_name:22s} {r.identifier or ''}")

        print("\nRow counts:")
        for table, n in db.counts(conn).items():
            print(f"  {table:24s} {n}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
