"""Offline guard for the RAG eval gold set (tests/eval/queries.yaml).

This does NOT run retrieval (that needs a live backend — see
``tests/eval/eval_rag_retrieval.py``). It only keeps the gold dataset honest so
the eval never breaks on a malformed entry: unique ids, well-formed expected
(source, page) pairs, and source filenames that point at real corpus PDFs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

GOLD_PATH = Path(__file__).resolve().parent / "eval" / "queries.yaml"
RAG_DOCS = Path(__file__).resolve().parents[1] / "rag_docs"


@pytest.fixture(scope="module")
def cases():
    return yaml.safe_load(GOLD_PATH.read_text(encoding="utf-8"))


# TLDR: The gold YAML loads and is a non-empty list of cases.
def test_gold_loads(cases):
    assert isinstance(cases, list) and cases


# TLDR: Every case has the required, correctly-typed fields.
def test_case_schema(cases):
    for case in cases:
        assert isinstance(case.get("id"), str) and case["id"]
        assert isinstance(case.get("query"), str) and case["query"]
        assert isinstance(case.get("verified"), bool)
        assert isinstance(case.get("expected"), list) and case["expected"]
        for exp in case["expected"]:
            assert set(exp) >= {"source", "page"}
            assert isinstance(exp["source"], str) and exp["source"].endswith(".pdf")
            assert isinstance(exp["page"], int) and exp["page"] > 0


# TLDR: Verified cases must carry a relevance `quote` on every expected page.
def test_verified_cases_have_quotes(cases):
    for case in cases:
        if not case.get("verified"):
            continue
        for exp in case["expected"]:
            quote = exp.get("quote", "")
            assert isinstance(quote, str) and quote.strip(), (
                f"verified case {case['id']!r} page {exp['page']} needs a quote"
            )


# TLDR: Case ids are unique (so --only and the summary are unambiguous).
def test_ids_unique(cases):
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))


# TLDR: Referenced source PDFs actually exist in rag_docs/ (skips if docs absent).
def test_expected_sources_exist(cases):
    if not RAG_DOCS.exists():
        pytest.skip("rag_docs/ not present in this checkout")
    available = {p.name for p in RAG_DOCS.glob("*.pdf")}
    if not available:
        pytest.skip("no PDFs in rag_docs/")
    referenced = {exp["source"] for c in cases for exp in c["expected"]}
    missing = referenced - available
    assert not missing, f"gold references missing PDFs: {sorted(missing)}"
