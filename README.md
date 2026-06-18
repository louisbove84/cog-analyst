# cog-analyst — Grounded Military OSINT Analysis

A grounded OSINT project for **Chinese air power / A2AD**. The design goal is
**eliminating hallucination**. Two deterministic ingestion paths feed relational
stores (ground truth); a vector store adds cited doctrinal context; a LangGraph
agent synthesizes COG analysis only from joined, cited evidence.

1. **WEG equipment catalog** (`data/weg.db`) — what systems can do (deterministic PDF scrape).
2. **PLA air laydown** (`data/oob.db`) — who fields them, from where (deterministic Markdown scrape).
3. **Doctrinal RAG** (`data/rag.db`) — embedded OSINT reports for cited context (supplementary, never authoritative).
4. **COG agent** (`cog/graph.py`) — resolve → retrieve (join) → context (RAG) → CC → CR → CV/CoG.

**Grounding hierarchy:** the structured DBs are ground truth. RAG is *context
only* — it may explain or corroborate a finding but never selects entities or
overrides a database fact, and every snippet is cited (`file p.N`).

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

> **Source of truth:** `data/weg.db` is the canonical capability catalog.
> `data/oob.db` is corroborating laydown (Wikipedia snapshot). Join them via
> `db/join_queries.py` — never fuzzy-match designators.

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

## Order of battle: the PLA air laydown store

Equipment specs say *what a system can do*; they cannot say *who fields it or
from where*. `data/oob.db` supplies that force-laydown layer, so a capability can
be tied to real units, bases, and theaters — the join the COG workflow needs.

`rag_docs/pla_air_oob.md` is a saved Chinese Wikipedia article (PLA Air Force /
Naval Aviation 编制序列). It is parsed **deterministically** — no LLM — by a
stateful Markdown table scraper (`ingestion/oob_markdown.py`):

- **Heading state** carries service (`空军`→PLAAF / `海军`→PLANAF / Training),
  role (`歼击机`→fighter, `无人机`→uav, …), and theater (`东部战区`→Eastern, …)
  across rows, since those are section headers, not table columns.
- **Content-based cell classification** (not column position): the source tables
  drift (UAV/carrier rows misalign columns), so each cell is routed by what it
  *is* — a real designator, a `[0-9X]` tactical code, a `战区` theater, or
  geography — making the parse resilient to layout noise. The trailing
  tail-number decoder matrix is skipped automatically.
- **Designator crosswalk** (`ingestion/designator.py`): a fixed, ordered prefix
  map turns Chinese designators into the Latin join key (`歼-20A`→`J-20`,
  `轰-6K`→`H-6`, `运-8`→`Y-8`), so OOB units join `weg.db` by `en_designator`.
  Division names that merely contain a role character (`第34运输机师`) are rejected.

```text
units                                   unit_aircraft
  unit_key PRIMARY KEY                    unit_key  ──┐ FK → units (ON DELETE CASCADE)
  unit_name / service / role             raw_designator   歼-20A   (verbatim)
  theater_command / location_text        cn_designator    歼-20    (canonical CN base)
  airbase / tactical_code / source_url   en_designator    J-20     (← WEG join key)
```

```bash
python scripts/ingest_oob.py --md rag_docs/pla_air_oob.md   # → data/oob.db (~100 units)
```

`db/oob_queries.py` exposes the read surface as **agent tools**:

| Function | Purpose |
|---|---|
| `units_for_aircraft(designator)` | "Who fields type X, and from where" — the capability→laydown join |
| `search_units(service, role, theater, location_contains)` | Set-level laydown filter |
| `aircraft_inventory(service)` | Fielding-unit count per type (variants collapse by Latin base) |
| `role_breakdown()` / `list_theaters()` | "What is this force made of?" discovery |

> **OSINT caveat:** the OOB source is Wikipedia (a point-in-time snapshot), not an
> authoritative order of battle. Treat `weg.db` as higher-confidence ground truth
> and the OOB layer as corroborating laydown; tactical codes are deliberately
> obfuscated (`78X1X`) in the source and stored verbatim, not as precise IDs.

## Capability × laydown join (agent Node 1)

`db/join_queries.py` `ATTACH`es `weg.db` onto an OOB connection and joins
`unit_aircraft.en_designator` to `weg_assets.asset_title`. One call returns unit +
base + theater + WEG spec slice — the single grounded artifact Node 1 needs.

| Function | Purpose |
|---|---|
| `capability_laydown(designator, theater, role, service)` | Joined unit/aircraft/WEG rows |
| `laydown_payload_slice(asset_title, section)` | Narrow WEG section (e.g. `System`) |
| `laydown_as_dicts(hits)` | JSON-ready rows for agent state |

```bash
python scripts/query_laydown.py --designator J-20
python scripts/query_laydown.py --designator H-6 --role bomber
```

## Doctrinal context: the RAG vector store

Specs and laydown say *what* and *where*; they cannot say *why a dependency
matters* or *what is a known weakness*. The doctrinal PDFs in `rag_docs/` (DoD
*China Military Power* reports, think-tank analyses) supply that. They are chunked
with a **Parent-Child** scheme, **embedded** with Google's Gemini embeddings, and
stored in `data/rag.db` for cosine retrieval — so the agent can pull cited
strategic context to inform (never define) its reasoning.

**Parent-Child retrieval** embeds *small* passages for precise matching but feeds
*large* passages to the LLM for full context:

```text
rag_parents                       rag_chunks (children, embedded)
  parent_id PK                      chunk_id PK
  source / page                     parent_id  ── FK → rag_parents
  text  (one full page)             source / page
                                    text  (~150-word window)
                                    embedding BLOB  (L2-normalized; cosine == dot)
```

1. Embed each **child** window (~150 words) → precise semantic match.
2. Rank the top `child_pool` children, **de-duplicate onto distinct parent
   pages**, and return at most `max_parents` of them (the context-size cap).
3. The LLM reads the full **parent page**, cited as `file p.N`.

- **Embedder is swappable** (`rag/embedder.py`, `Embedder` ABC). Default is
  **Google `gemini-embedding-001` @ 768 dims** (`GoogleEmbedder`, needs
  `GEMINI_API_KEY`); set `COG_EMBED_BACKEND=local` for an offline
  sentence-transformers model instead.
- **Asymmetric task types** — documents are embedded with `RETRIEVAL_DOCUMENT`
  and queries with `RETRIEVAL_QUERY`, which improves retrieval quality.
- **Retrieval knobs** (`config.py`): `DEFAULT_RAG_CHILD_POOL=15` (match breadth),
  `DEFAULT_RAG_MAX_PARENTS=4` (distinct pages → LLM). Exact cosine over the
  loaded matrix; swap in FAISS/Chroma or Vertex Vector Search to scale.
- **WEG/OOB source files are skipped** — those have their own deterministic
  pipelines and are not part of the RAG corpus.

```bash
pip install -e ".[rag]"                      # pymupdf + numpy + google-genai
export GEMINI_API_KEY=...                     # https://aistudio.google.com/apikey
python scripts/ingest_rag.py                  # embed every PDF in rag_docs/ -> data/rag.db
python scripts/ingest_rag.py --pdf rag_docs/China_Military_Power_2019.pdf  # one file

# Offline alternative (no API key): pip install -e '.[rag-local]'
COG_EMBED_BACKEND=local python scripts/ingest_rag.py
```

> **Note:** the embedding dimension is baked into `data/rag.db`. If you switch
> backend/model/dimension, re-run `ingest_rag.py` to rebuild the store.

## COG agent (LangGraph)

Workflow: **resolve_scenario → retrieve → retrieve_context → CC → CR → CV/CoG**.

- **resolve_scenario** (deterministic): turns the free-text query into structured
  filters. A weapon → designator (via the CN→Latin crosswalk); a location →
  responsible theater(s) via a hand-authored map (`cog/scenario.py`,
  `Taiwan → Eastern+Southern`). Entity selection never touches the LLM.
- **retrieve** (deterministic): the WEG×OOB capability laydown join (ground truth).
- **retrieve_context** (RAG): embeds the entity-scoped query and fetches cited
  snippets. **Optional** — if `data/rag.db` is absent the agent runs without it.
- **CC / CR / CV-CoG**: LangChain structured output with hard prompt constraints
  (omit INA metrics; CoG must name an entity in the evidence). RAG context feeds
  **CR / CV / CoG only** — capability extraction (CC) stays metric-grounded.

```bash
pip install -e ".[agent,rag]"    # langgraph + embeddings

# Location-driven (theater inferred, designator inferred, RAG context pulled):
python scripts/run_cog_agent.py --query "Assess the J-20 threat to Taiwan"

# Explicit overrides still win:
python scripts/run_cog_agent.py \\
    --query "Assess J-20 eastern theater laydown" \\
    --designator J-20 --theater Eastern
```

Graph state carries `raw_assets`, `context_snippets`, `critical_capabilities`,
`critical_requirements`, `critical_vulnerabilities`, and `cog_statement` — the
structured layers cite WEG/OOB URLs, the context layer cites `file p.N`.

## Layout

```text
cog-analyst/
  src/cog_analyst/
    config.py                     # paths + LLM backend resolution (.env aware)
    ingestion/
      weg_pdf.py                    # WEG layout-stream scraper (deterministic)
      oob_markdown.py             # PLA OOB Markdown table scraper (deterministic)
      designator.py               # Chinese→Latin aircraft designator crosswalk
      interfaces.py / extractor.py  # optional OpenAI-compatible structured output
    db/
      database.py                 # connect()
      document_store.py           # weg_assets UPSERT + reads
      weg_queries.py              # JSON1 agent-tool reads
      oob_store.py / oob_queries.py
      join_queries.py             # WEG × OOB capability laydown join
      rag_store.py                # SQLite vector store + cosine search
    rag/
      embedder.py                 # Embedder ABC + Google/local implementations
      chunking.py                 # parent-child PDF chunker (page parents + windows)
    cog/
      graph.py / nodes.py / schemas.py / state.py
      scenario.py                 # query → deterministic filters (location→theater)
  scripts/
    ingest_weg.py / ingest_oob.py / ingest_rag.py
    query_weg.py / query_laydown.py
    run_cog_agent.py
  tests/                          # offline except [agent] integration
```

## Setup

Requires Python 3.9+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,pdf,agent,rag]"
# pdf: WEG scraper   agent: LangGraph   rag: embeddings   dev: pytest/ruff/mypy
cp .env.example .env          # LLM backend for run_cog_agent.py (nodes 2–4)
```

## Choosing an LLM backend (ChatGPT, Grok, or local Ollama)

The COG agent (nodes 2–4) runs against any **OpenAI-compatible** endpoint. Set
it once in `.env` (auto-loaded) via `COG_LLM_BACKEND`:

| `COG_LLM_BACKEND` | What runs | What you need |
|---|---|---|
| `openai` (default) | Hosted ChatGPT, or any `COG_LLM_BASE_URL` (e.g. Grok at `https://api.x.ai/v1`) | `COG_LLM_API_KEY` |
| `ollama` | Local model (`qwen2.5`) | Ollama installed + `ollama serve` |
| `lmstudio` | Local LM Studio server | LM Studio running |

Precedence is **env var > default**. Ingest scripts need no API key.

## Tests

```bash
pytest
```

Deterministic ingestion, join queries, and the retrieve node run fully offline.
Nodes 2–4 require ``pip install -e '.[agent]'`` and a configured LLM to exercise
end-to-end via ``run_cog_agent.py``.

### System walkthrough (one-stop review)

`scripts/verify_system.py` is a **narrated tour** of every analysis capability —
designator crosswalk → scenario resolution → WEG → OOB → join → RAG → the full
COG graph — printed as a plain-English report, not just pass/fail. It uses the
real `data/` stores when present (else seeds a tiny fixture) and runs the agent
graph **offline** with a stub LLM by default.

```bash
python scripts/verify_system.py                # offline narrated walkthrough
python scripts/verify_system.py --with-agent   # drive a live LLM through the graph
```

## Provenance & disclaimer

All facts trace to cited open-source documents. This is an **analytical,
open-source** project; it produces no operational targeting guidance. Figures are
as stated in the sources and are not independently verified here.
