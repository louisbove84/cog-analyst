"""Entry point: initialize spratly_fleet.db from core-document text snippets.

Usage:
    # Run the bundled demo excerpts against OpenAI (requires OPENAI_API_KEY):
    python scripts/ingest_spratly.py --demo

    # Run fully local against Ollama (no API key, no cloud):
    #   ollama pull qwen2.5  &&  ollama serve
    python scripts/ingest_spratly.py --demo --local
    python scripts/ingest_spratly.py --demo --local --model llama3.1:8b

    # Point at any OpenAI-compatible server (LM Studio, vLLM, ...):
    python scripts/ingest_spratly.py --demo \\
        --base-url http://localhost:1234/v1 --model my-model

    # Ingest your own snippets from a JSON file:
    #   {"weapons": ["...passage..."], "outposts": ["...passage..."]}
    python scripts/ingest_spratly.py --snippets path/to/snippets.json --local

This script is the Spratly-domain wiring: it pairs the generic engine
(extractor + pipeline + store) with the Spratly domain pack (reef registry,
outpost model, source excerpts).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cog_analyst import config  # noqa: E402
from cog_analyst.db import CogStore  # noqa: E402
from cog_analyst.domains.spratly import (  # noqa: E402
    DEMO_OUTPOST_SNIPPETS,
    DEMO_WEAPON_SNIPPETS,
    REEF_REGISTRY,
    SPRATLY_DB_PATH,
    OutpostInfrastructure,
)
from cog_analyst.ingestion import IngestionPipeline, LangChainExtractor  # noqa: E402
from cog_analyst.models import WeaponSpecification  # noqa: E402


def _load_snippets(path: Path) -> Dict[str, List[str]]:
    data = json.loads(path.read_text())
    return {
        "weapons": list(data.get("weapons", [])),
        "outposts": list(data.get("outposts", [])),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ingest Spratly COG data into SQLite.")
    parser.add_argument("--demo", action="store_true", help="Use bundled excerpts.")
    parser.add_argument("--snippets", type=Path, help="JSON file of text snippets.")
    parser.add_argument("--db", default=None, help="Optional SQLite DB path.")
    parser.add_argument("--model", default=None, help="LLM model name.")
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use a local Ollama server (OpenAI-compatible) instead of OpenAI.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible endpoint (e.g. LM Studio/vLLM). Overrides --local.",
    )
    parser.add_argument("--api-key", default=None, help="API key (ignored by local servers).")
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

    # Resolve the LLM backend: CLI flag > env var > default.
    base_url = args.base_url or config.LLM_BASE_URL
    api_key = args.api_key or config.LLM_API_KEY
    if args.local and base_url is None:
        base_url = config.OLLAMA_BASE_URL
        api_key = api_key or "ollama"

    if args.model is not None:
        model = args.model
    elif config.LLM_MODEL:
        model = config.LLM_MODEL
    elif base_url is not None:  # any local/compat endpoint
        model = config.DEFAULT_LOCAL_MODEL
    else:
        model = config.DEFAULT_OPENAI_MODEL

    where = base_url or "OpenAI API"
    print(f"Using model '{model}' via {where}")

    if args.demo:
        snippets = {"weapons": DEMO_WEAPON_SNIPPETS, "outposts": DEMO_OUTPOST_SNIPPETS}
    elif args.snippets:
        snippets = _load_snippets(args.snippets)
    else:
        parser.error("provide --demo or --snippets PATH")
        return 2

    db_path = args.db if args.db is not None else SPRATLY_DB_PATH
    extractor = LangChainExtractor(
        model=model,
        base_url=base_url,
        api_key=api_key,
        structured_output_method=args.structured_method,
    )
    pipeline = IngestionPipeline(extractor=extractor)

    with CogStore(db_path=db_path, reef_registry=REEF_REGISTRY) as store:
        results = []
        for text in snippets["weapons"]:
            results.append(
                pipeline.ingest(text, WeaponSpecification, store.insert_weapon)
            )
        for text in snippets["outposts"]:
            results.append(
                pipeline.ingest(text, OutpostInfrastructure, store.insert_outpost)
            )

        inserted = sum(1 for r in results if r.ok)
        print(f"\nIngestion complete: {inserted}/{len(results)} records inserted.")
        for r in results:
            print(f"  [{r.status.value:16s}] {r.schema_name:22s} {r.identifier or ''}")
        print("\nRow counts:")
        for table, n in store.counts().items():
            print(f"  {table:24s} {n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
