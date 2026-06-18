# RAG retrieval eval

This folder holds the **retrieval-quality** check for the RAG layer. It answers a
different question than `tests/`:

| | `tests/` (pytest) | `tests/eval/` (this) |
|---|---|---|
| Question | "Does the code work?" | "Does retrieval return the *right pages*?" |
| Speed | Fast, offline | Slower; needs `data/rag.db` + live embeddings |
| Data | Synthetic fixtures | Hand-curated gold queries |
| Runs in CI | Yes | No (run on demand) |

Unit tests (e.g. `test_rag_store.py`) prove the parent-child mechanics work.
They do **not** prove that *"PLA logistics weaknesses"* retrieves the page that
actually discusses logistics. That is what this eval is for.

## Files

- `queries.yaml` — the gold set: each case is a query plus expected
  `(source, page, quote)` triples. The **`quote`** is the exact on-page text that
  makes the page relevant — it is the auditable evidence that the (query → page)
  label is real, and it is printed every run. **Page = PDF page index**
  (PyMuPDF, 1-based; the same number as the `file p.N` citation), which is usually
  NOT the printed page number.
- `eval_rag_retrieval.py` — runs semantic retrieval for each query and reports
  page hit@k, source hit@k, and MRR, with a text snippet of every retrieved page.
- `../test_eval_dataset.py` — offline pytest that keeps `queries.yaml` valid
  (schema, unique ids, sources exist). This one *does* run in CI.

## Running it

```bash
# Needs GEMINI_API_KEY (or COG_EMBED_BACKEND=local) and a built data/rag.db.
python tests/eval/eval_rag_retrieval.py

# Tuning / focus:
python tests/eval/eval_rag_retrieval.py --max-parents 4 --tol 1 --show-chars 160
python tests/eval/eval_rag_retrieval.py --only logistics_vulnerabilities
```

## Verifying a case (your loop)

1. Run the eval; read the snippet next to each retrieved page.
2. Open the cited PDF to that **PDF page index** and confirm the topic.
3. Fix `expected` in `queries.yaml` to the truly-correct page(s) and set
   `verified: true`.
4. Re-run. A `MISS` after verification is a real retrieval gap — see below.

## Reading the results (miss taxonomy)

| Symptom | Likely cause | Knob to try |
|---|---|---|
| Right topic, wrong page | embedding/query mismatch | reword query; check `RETRIEVAL_QUERY` |
| Right page, low rank | child window too coarse | smaller `--child-words` at ingest |
| Junk text in the page | PDF header/footer noise | strip noise in `chunking.py`, re-ingest |
| Whole document never found | corpus gap / dilution | ingest the doc; prefix title to children |
| Page found, but agent ignores it | not a retrieval problem | prompts / graph (see LangSmith) |

## Adding a case

Append to `queries.yaml`:

```yaml
- id: short_unique_id
  query: "natural language question"
  expected:
    - source: China_Military_Power_2019.pdf
      page: 58
      quote: "exact on-page text proving this page answers the query"
  verified: false   # flip to true once you've confirmed every quote on the PDF
  note: "what 'relevant' means here / caveats"
```

Keep queries phrased like a real analyst question, and prefer 1–3 expected pages
per case (the highest-signal pages, not every page that mentions the term).

## What this metric does and does NOT measure

- It measures **whether retrieval surfaces pages you have declared relevant**
  (via the `quote`). The query is embedded and compared against the *whole
  corpus*; `expected` is only the grading key — it is never embedded.
- `page hit@k` is **recall-flavored against a small, hand-built key**, so a miss
  can mean "the gold is incomplete," not "retrieval is broken." It does NOT
  independently judge whether an *arbitrary* retrieved page is on-topic.
- To measure precision of relevance without exhaustive labels, add an
  LLM-as-judge pass (grade each retrieved page 0/1/2 against the query) — a good
  complement, not yet implemented here.
