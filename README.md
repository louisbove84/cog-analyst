# cog-analyst — Spratly COG Ingestion Engine (v1)

A grounded ingestion engine for the Spratly Islands Center-of-Gravity (COG)
slice of a military OSINT analysis project. The design goal is **eliminating
hallucination**: the LLM is treated as an *untrusted extraction mechanism*, and
every record must survive a four-stage gauntlet before it is persisted.

## The anti-hallucination pipeline

```text
text snippet
   │
   ▼  (1) LLM structured extraction  — LangChain .with_structured_output(Schema)
Pydantic instance
   │
   ▼  (2) Schema validation          — strict types, required citation, extra="forbid"
validated instance
   │
   ▼  (3) Deterministic entity guard — reef_name must be EXACTLY in MASTER_REEFS
guarded instance
   │
   ▼  (4) SQLite persistence         — strict INTEGER columns, transactional
spratly_fleet.db
```

If any stage fails, the record is dropped/flagged with an explicit status and
**nothing partial is written**. A hallucinated reef name (e.g. "Atlantis Reef")
is logged as a `DATA VIOLATION` and refused.

## Scope (v1)

- **In:** the Spratly COG slice — `WeaponSpecification` and
  `OutpostInfrastructure` extracted from the single core document
  (`rag_docs/OffensiveDefensiveStrike.pdf`, Dahm 2021, JHU/APL).
- **Out (reserved for the future RAG semantic-query phase):** the other four
  documents in `rag_docs/`. They are **not** used by this database-init task.

## Layout

The code is split into a reusable **engine** and a pluggable **domain pack**, so
adding a new theater (e.g. mainland China) means adding a sibling under
`domains/`, not rewriting the engine.

```text
cog-analyst/
  src/cog_analyst/
    config.py                     # paths + LLM backend defaults
    models/extraction.py          # WeaponSpecification (general)
    ingestion/                    # ENGINE (domain-agnostic)
      entity_guard.py             # EntityRegistry + deterministic guard
      extractor.py                # OpenAI-compatible .with_structured_output wrapper
      pipeline.py                 # generic extract -> validate -> guard -> persist
    db/store.py                   # CogStore: SQLite init, strict INTEGER cols
    domains/spratly/              # DOMAIN PACK (Spratly-specific)
      registry.py                 # MASTER_REEFS + REEF_REGISTRY
      models.py                   # OutpostInfrastructure
      source.py                   # Dahm 2021 citation + demo excerpts
  scripts/ingest_spratly.py       # entry point (--demo / --snippets / --local)
  tests/                          # 35 tests, no live LLM required
```

## Setup

Requires Python 3.9+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm]"   # 'llm' pulls langchain-openai for live runs
cp .env.example .env          # add OPENAI_API_KEY to run the extractor
```

## Run the ingestion engine

The deterministic stages (2–4) are fully tested without any API key. To run the
**full** pipeline including the LLM extraction (stage 1), set `OPENAI_API_KEY`
and use the bundled, citation-tagged excerpts from the core document:

```bash
python scripts/ingest_spratly.py --demo
```

Or ingest your own passages:

```bash
# snippets.json: {"weapons": ["...passage..."], "outposts": ["...passage..."]}
python scripts/ingest_spratly.py --snippets snippets.json
```

### Running fully local (no OpenAI, no API key)

The extractor talks to any **OpenAI-compatible** endpoint, so you can run the
LLM stage entirely offline. The easiest path on a Mac is **Ollama**:

```bash
brew install ollama
ollama serve &            # starts the local server
ollama pull qwen2.5       # or: llama3.1:8b — both are good at structured output

python scripts/ingest_spratly.py --demo --local
# pick a different local model:
python scripts/ingest_spratly.py --demo --local --model llama3.1:8b
```

`--local` points the extractor at Ollama's OpenAI-compatible API
(`http://localhost:11434/v1`). For other servers (LM Studio, vLLM, …), pass
`--base-url` directly:

```bash
python scripts/ingest_spratly.py --demo \
    --base-url http://localhost:1234/v1 --model my-model
```

You can also set the backend via environment variables (no flags needed):
`COG_LLM_BASE_URL`, `COG_LLM_MODEL`, `COG_LLM_API_KEY`.

**Note:** smaller local models (7–8B) will trip schema validation more often
than GPT-4o-mini. That is the pipeline working as designed — those records are
reported as `validation_error` and never persisted. If a model struggles to
emit valid structured output, try `--structured-method function_calling`.

## Tests

```bash
pytest        # 35 passed
```

The suite injects a `FakeExtractor` (see `tests/conftest.py`) so the full
pipeline — including the guard blocking a hallucinated reef and writing nothing —
is verified deterministically and offline.

## Data model

- `weapon_specifications(designator PK, export_variant, platform,
  max_range_km INTEGER, flight_profile, source_citation)`
- `outpost_infrastructure(reef_name PK, runway_length_meters INTEGER,
  fighter_hangar_count INTEGER)`
- `outpost_weapons(reef_name, weapon_designator)` — join table realizing
  `OutpostInfrastructure.verified_deployed_weapons`, FK to
  `outpost_infrastructure`.

## Provenance & disclaimer

All facts trace to the cited open-source document. This is an **analytical,
open-source** project; it produces no operational targeting guidance. Range and
infrastructure figures are as stated in the source and are not independently
verified here.
```

