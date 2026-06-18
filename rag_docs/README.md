# Source documents (local only)

PDFs and Markdown exports in this folder are **not committed** to git (see
`.gitignore`). Place your open-source reference documents here before running
ingestion.

## Structured ground-truth sources (deterministic ingest)

- `fullwegexportcompressed.pdf` — ODIN **Worldwide Equipment Guide** export.
  Ingested deterministically into `data/weg.db` (China-only by default).
- `pla_air_oob.md` — saved Chinese Wikipedia PLA air OOB article. Ingested
  deterministically into `data/oob.db`.

## RAG corpus (embedded for cited context)

Everything else here is chunked + embedded into `data/rag.db` by
`scripts/ingest_rag.py` (the WEG source above is skipped automatically):

- DoD *China Military Power* reports (2019 / 2022 / 2024 / 2025)
- `OffensiveDefensiveStrike.pdf` and other think-tank analyses

These supply **doctrinal context only** — the agent cites them (`file p.N`) but
never treats them as authoritative over the structured stores.

Obtain copies from official/public sources and drop them into this directory
locally.
