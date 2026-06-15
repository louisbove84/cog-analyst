# cog-analyst — Grounded Military OSINT Ingestion Engine

A grounded ingestion engine for a military OSINT analysis project. The design
goal is **eliminating hallucination**. Two complementary ingestion paths feed a
hybrid relational store:

1. **Deterministic document ingestion (source of truth).** A typography-driven
   PDF scraper turns a large equipment-guide export into structured records with
   **no LLM in the loop** — the strongest possible grounding.
2. **LLM-assisted extraction (Spratly COG slice).** Where prose must be turned
   into typed facts, the LLM is treated as an *untrusted extractor*: every record
   survives strict validation and a separate deterministic scrub before it counts.

## Ground truth: the WEG hybrid document store

`rag_docs/fullwegexportcompressed.pdf` is the ODIN **Worldwide Equipment Guide**
export (~12k pages). It is an **air-domain** catalog — every asset is an aircraft,
UAV, helicopter, or air-launched weapon. It is parsed **deterministically** into
`data/weg.db` and is the **canonical source of truth** for asset identity and
specifications. Because no model is involved, nothing here can be hallucinated.

**Project focus — Chinese air power / A2AD.** The export contains 700 air assets
across many countries; ingestion is filtered to **China only by default** (188
assets: ~46% UAVs, the rest fighters, transports, AEW&C, EW, and air/anti-ship
missiles). Override with `--origin <country>` or `--all-origins`.

### One-pass dynamic-JSON ingestion

Document layouts vary wildly between asset domains, so we use a **hybrid
document-relational** pattern instead of brittle wide tables:

```text
weg_assets
  asset_title      TEXT PRIMARY KEY   ← UNIQUE identity; blocks duplicate records
  source_url       TEXT               ← promoted from "WEG Location:"
  notes            TEXT               ← the descriptive "Notes" prose
  dynamic_payload  TEXT (JSON)        ← all variable sections, as nested JSON
```

A single **stateful layout-stream scraper** (`ingestion/weg_pdf.py`, PyMuPDF)
sweeps the document in reading order and routes content by typography:

| Typography | Role | Becomes |
|---|---|---|
| 16.0pt | Asset title | new record (PK boundary) |
| 12.0pt | Section heading | top-level JSON key |
| 9.4pt | Sub-section heading | nested JSON key |
| 8.0pt | Body / `Label: value` | text / parsed key/value pair |
| `For Training Use Only`, `Exported (UTC) @ …`, page numbers | page furniture | discarded |

- **Stateful across page breaks:** a section that spills onto the next page keeps
  accumulating into the same JSON key (page furniture is stripped first).
- **Key/value parsing preserves structure regardless of label length** — a long,
  descriptive spec label is still captured as a `{label: value}` pair; only lines
  with no `": "` delimiter fall back to free text. The `Notes` prose is exempt so
  the paragraph is never shredded.
- **Parameterized UPSERT:** each asset is written with
  `INSERT … ON CONFLICT(asset_title) DO UPDATE`, so re-ingesting cleanly
  overwrites a record (and its JSON payload) instead of duplicating it.

```bash
pip install -e ".[pdf]"                       # PyMuPDF

python scripts/ingest_weg.py --limit 25       # sample the first 25 kept assets
python scripts/ingest_weg.py                  # China-only ingest -> data/weg.db (188 assets)
python scripts/ingest_weg.py --origin Russia  # keep a different country instead
python scripts/ingest_weg.py --all-origins    # keep every country (700 assets)
sqlite3 data/weg.db "SELECT asset_title, source_url FROM weg_assets LIMIT 5;"
```

> **Source of truth:** `data/weg.db` is the canonical catalog. The LLM pipeline
> writes extracted records raw; reconciling designator aliases against the
> deterministic WEG catalog (normalize + exact match, plus a small explicit alias
> table where needed) is a deliberate, auditable step — no fuzzy embedding match.

### Querying the store (agent tool layer)

`dynamic_payload` is **schema-on-read** — section keys vary per asset — so reads
use SQLite's JSON1 functions (`json_extract`, `json_each`) instead of fixed
columns. `db/weg_queries.py` exposes the read surface that doubles as **agent
tools**, each returning grounded rows with a citable `source_url`:

| Function | Purpose |
|---|---|
| `search_assets(origin, domain, name_contains, limit)` | Set-level filter ("Chinese UAVs") |
| `list_origins()` / `category_breakdown(origin)` | "What is in this corpus?" discovery |
| `get_asset_sections(title)` | Ask the data what sections an asset *has* |
| `get_asset_section(title, section)` | Fetch one narrow slice (avoids dumping whole payloads) |

The agent pattern is: filter → discover sections → fetch only what's needed →
synthesize **only** from returned rows, citing `source_url`. Exercise it by hand:

```bash
python scripts/query_weg.py breakdown                 # corpus composition
python scripts/query_weg.py search --domain UAV       # all Chinese UAVs
python scripts/query_weg.py sections "J-20 (FAGIN) Chinese Stealth Air Superiority Fighter"
python scripts/query_weg.py section  "J-20 (FAGIN) Chinese Stealth Air Superiority Fighter" Variants
```

## The LLM anti-hallucination pipeline (Spratly COG slice)

The pipeline **ingests raw**, so you can inspect exactly what the
LLM wrote before any downstream reconciliation against ground truth.

```text
INGEST (LLM → DB, as-is)
text snippet
   │  (1) LLM structured extraction  — LangChain .with_structured_output(Schema)
   │  (2) Schema validation          — strict types, required citation, extra="forbid"
   │  (3) SQLite persistence         — writes raw rows (aliases kept)
spratly_fleet.db  ← inspect with sqlite3
```

Records are persisted raw. Reconciliation against ground truth (mapping a
designator alias like `HQ-9B SAMs` onto its canonical entry) is a deliberate
downstream step against the WEG store — normalize + exact match, with a small
explicit alias table for the irregular leftovers. No fuzzy embedding matching,
so a merge can never silently fuse two genuinely different systems.

### Hub-and-spoke data model

The outpost is the hub; weapons, aircraft, and radar are reusable catalogs linked
by designator:

- `weapon_specifications(designator PK, max_range_km, source_citation)`
- `aircraft_specifications(designator PK, combat_radius_km, source_citation)`
- `radar_specifications(designator PK, max_detection_range_km, source_citation)`
- `outpost_infrastructure(reef_name PK, runway_length_meters, fighter_hangar_count)`
- `outpost_weapons / outpost_aircraft / outpost_radar(reef_name, designator)` —
  join tables (FK to the hub) realizing the outpost's deployed-capability lists.

## Layout

The code is split into a reusable **engine**, a pluggable **domain pack**, and
the deterministic **WEG document pipeline**.

```text
cog-analyst/
  src/cog_analyst/
    config.py                     # paths + LLM backend resolution (.env aware)
    models/schemas.py             # WeaponSpecification, AircraftSpecification,
                                  #   RadarSpecification, OutpostInfrastructure
    ingestion/                    # ENGINE (domain-agnostic)
      interfaces.py               # StructuredExtractor ABC + ExtractionError
      extractor.py                # OpenAI-compatible .with_structured_output wrapper
      pipeline.py                 # generic extract -> validate -> persist (raw)
      entity_guard.py             # EntityRegistry deterministic allowlist
      weg_pdf.py                  # WEG layout-stream scraper (deterministic)
    db/
      database.py                 # connect + init + insert_* (writes)
      queries.py                  # counts, get_* (reads)
      document_store.py           # weg_assets UPSERT + reads (hybrid store)
      weg_queries.py              # JSON1 agent-tool reads (search/sections/...)
    domains/spratly/              # DOMAIN PACK (Spratly-specific)
      registry.py                 # MASTER_REEFS + REEF_REGISTRY
      source.py                   # Dahm 2021 citation + demo excerpts
  scripts/
    ingest_spratly.py             # LLM pipeline (--demo / --snippets / --backend)
    ingest_weg.py                 # deterministic WEG PDF -> data/weg.db (China-only)
    query_weg.py                  # demo CLI for the JSON1 query/tool layer
  tests/                          # no live LLM or network required
```

## Setup

Requires Python 3.9+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm,pdf]"
# llm: LangChain extractor   pdf: WEG scraper (PyMuPDF)
cp .env.example .env          # choose a backend (ChatGPT / Grok / Ollama) and fill it in
```

## Choosing an LLM backend (ChatGPT, Grok, or local Ollama)

The extractor runs against any **OpenAI-compatible** endpoint. Set it once in
`.env` (auto-loaded) via `COG_LLM_BACKEND`:

| `COG_LLM_BACKEND` | What runs | What you need |
|---|---|---|
| `openai` (default) | Hosted ChatGPT, or any `COG_LLM_BASE_URL` (e.g. Grok at `https://api.x.ai/v1`) | `COG_LLM_API_KEY` |
| `ollama` | Local model (`qwen2.5`) | Ollama installed + `ollama serve` |
| `lmstudio` | Local LM Studio server | LM Studio running |

Precedence is **CLI flag > `.env` / env var > default**, so you can also flip
per-run with `--backend openai|ollama|lmstudio` or `--base-url`.

## Run the LLM ingestion engine

The deterministic stages are fully tested without any API key. To run the full
pipeline (including LLM extraction) against the bundled, citation-tagged excerpts:

```bash
python scripts/ingest_spratly.py --demo                  # uses COG_LLM_BACKEND from .env
python scripts/ingest_spratly.py --demo --backend ollama # force local Ollama
```

Or ingest your own passages:

```bash
# snippets.json: {"weapons": [...], "aircraft": [...], "radar": [...], "outposts": [...]}
python scripts/ingest_spratly.py --snippets snippets.json
```

**Note:** smaller local models (7–8B) trip schema validation more often than
GPT-4o-mini. That is the pipeline working as designed — those records are
reported as `validation_error` and never persisted. Try
`--structured-method function_calling` if a model struggles with structured output.

## Tests

```bash
pytest
```

The suite injects a `FakeExtractor` and a deterministic embedder
(`tests/conftest.py`), and builds a synthetic WEG-style PDF, so the entire system
— LLM pipeline, entity guard, and document scraper — is verified offline.

## Provenance & disclaimer

All facts trace to cited open-source documents. This is an **analytical,
open-source** project; it produces no operational targeting guidance. Figures are
as stated in the sources and are not independently verified here.
