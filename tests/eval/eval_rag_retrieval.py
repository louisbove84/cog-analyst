"""Retrieval-quality eval for the RAG store (NOT a pytest unit test).

This measures whether semantic retrieval surfaces the *right pages* for a set of
hand-curated queries — the feedback loop for chunking/embedding decisions. It is
deliberately separate from ``tests/`` unit tests: it needs the real
``data/rag.db`` and a live embedding backend, so it is run on demand, not in CI.

What it reports per query:
  * the top retrieved parent pages (citation + score + snippet)
  * page hit@k  — did an expected (source, page +/- tol) appear in the top-k?
  * source hit@k — did an expected document appear at all?
  * reciprocal rank of the first correct page (for MRR)

Aggregate summary (all computed from the gold answer key):
  * page hit@k, source hit@k, MRR
  * precision@k (gold) — of top-k slots, fraction that match a labeled page
  * recall@k (gold) — of all labeled pages, fraction recovered in top-k
  * nDCG@k (gold) — ranking quality when labels are binary relevant/irrelevant

NOT measured here (need LLM-as-judge or agent output):
  * true precision@k (relevance of non-labeled pages)
  * faithfulness / groundedness / answer relevancy (generation metrics)

Usage:
    python tests/eval/eval_rag_retrieval.py
    python tests/eval/eval_rag_retrieval.py --max-parents 4 --tol 1 --show-chars 140
    python tests/eval/eval_rag_retrieval.py --only j20_stealth_fighter

Because the seeded expected pages are UNVERIFIED candidates, treat the first run
as a worksheet: read the snippets, confirm against the PDFs, and correct
``queries.yaml``. Misses are listed explicitly so you know what to inspect.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cog_analyst import config, db  # noqa: E402
from cog_analyst.db import rag_store  # noqa: E402
from cog_analyst.rag.embedder import build_embedder  # noqa: E402

GOLD_PATH = Path(__file__).resolve().parent / "queries.yaml"


@dataclass
class CaseResult:
    case_id: str
    query: str
    page_hit: bool
    source_hit: bool
    reciprocal_rank: float
    best_rank: Optional[int]
    verified: bool
    precision_at_k: float
    recall_at_k: float
    ndcg_at_k: float
    gold_in_top_k: int
    gold_label_count: int


def _expected_pairs(case: dict) -> List[Tuple[str, int]]:
    return [(e["source"], int(e["page"])) for e in case.get("expected", [])]


_QUOTE_SUBS = {"\u00ad": "", "’": "'", "‘": "'", "“": '"', "”": '"', "—": "-", "–": "-"}


def _normalize(text: str) -> str:
    """Fold smart quotes/dashes, drop soft hyphens, collapse whitespace."""
    for src, dst in _QUOTE_SUBS.items():
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text).strip().lower()


def validate_gold_quotes(conn, cases: List[dict]) -> Tuple[int, List[str]]:
    """Confirm each expected `quote` is real text on its cited page.

    This is the guard against a stale/typo'd answer key: if a quote can't be
    found on the page it claims, the (query -> page) label is no longer trustworthy.
    """
    total = 0
    missing: List[str] = []
    for case in cases:
        for entry in case.get("expected", []):
            quote = entry.get("quote")
            if not quote:
                continue
            total += 1
            row = conn.execute(
                "SELECT text FROM rag_parents WHERE source=? AND page=?",
                (entry["source"], entry["page"]),
            ).fetchone()
            page_text = _normalize(row["text"]) if row else ""
            if _normalize(quote) not in page_text:
                where = f"{_short(entry['source'])} p.{entry['page']}"
                missing.append(f"{case['id']} -> {where}")
    return total, missing


def _page_matches(
    expected: List[Tuple[str, int]], source: str, page: int, tol: int
) -> bool:
    return any(
        source == exp_src and abs(page - exp_page) <= tol
        for exp_src, exp_page in expected
    )


def _labels_found(
    hits, expected: List[Tuple[str, int]], tol: int
) -> set[Tuple[str, int]]:
    """Distinct gold (source, page) labels surfaced in ``hits``."""
    found: set[Tuple[str, int]] = set()
    for hit in hits:
        for exp_src, exp_page in expected:
            if hit.source == exp_src and abs(hit.page - exp_page) <= tol:
                found.add((exp_src, exp_page))
    return found


def _precision_recall_ndcg(
    hits,
    expected: List[Tuple[str, int]],
    *,
    k: int,
    tol: int,
) -> Tuple[float, float, float, int]:
    """Gold-based precision@k, recall@k, and nDCG@k for one query."""
    if not expected:
        return 0.0, 0.0, 0.0, 0

    top = hits[:k]
    relevances = [
        1.0 if _page_matches(expected, hit.source, hit.page, tol) else 0.0
        for hit in top
    ]
    gold_in_top_k = int(sum(relevances))
    precision = gold_in_top_k / k if k else 0.0

    found = _labels_found(top, expected, tol)
    recall = len(found) / len(expected)

    # Ideal DCG: all relevant labels ranked first (up to k slots).
    ideal = [1.0] * min(k, len(expected)) + [0.0] * max(0, k - len(expected))
    ndcg = _ndcg(relevances, ideal[:k])

    return precision, recall, ndcg, gold_in_top_k


def _ndcg(relevances: List[float], ideal: List[float]) -> float:
    if not relevances or sum(relevances) == 0:
        return 0.0

    def dcg(scores: List[float]) -> float:
        return sum(s / math.log2(i + 2) for i, s in enumerate(scores))

    idcg = dcg(ideal)
    return dcg(relevances) / idcg if idcg else 0.0


def _short(source: str, width: int = 46) -> str:
    """Shorten a long filename for readable tabular output."""
    return source if len(source) <= width else source[: width - 3] + "..."


def evaluate_case(
    conn,
    embedder,
    case: dict,
    *,
    child_pool: int,
    max_parents: int,
    tol: int,
    show_chars: int,
) -> CaseResult:
    query = case["query"]
    expected = _expected_pairs(case)
    expected_sources = {s for s, _ in expected}

    vector = embedder.embed_one(query)
    hits = rag_store.search(
        conn, vector, child_pool=child_pool, max_parents=max_parents
    )

    verified = case.get("verified", False)
    print(f"\n[{case['id']}] {query}  {'(verified)' if verified else '(UNVERIFIED)'}")
    if case.get("note"):
        print(f"    note: {case['note']}")
    print("    expected (the answer key — each page must truly be on-topic):")
    for entry in case.get("expected", []):
        quote = entry.get("quote", "")
        quote_str = f'  "{quote[:90]}..."' if quote else ""
        print(f"      - {_short(entry['source'])} p.{entry['page']}{quote_str}")
    if not verified:
        print("    (relevance not yet human-confirmed — treat results as a worksheet)")

    best_rank: Optional[int] = None
    source_hit = False
    print("    top retrieved pages:")
    for rank, hit in enumerate(hits, start=1):
        page_ok = _page_matches(expected, hit.source, hit.page, tol)
        source_hit = source_hit or hit.source in expected_sources
        if page_ok and best_rank is None:
            best_rank = rank
        mark = "✓" if page_ok else " "
        snippet = hit.text[:show_chars].replace("\n", " ")
        print(
            f"      {mark} {rank}. {_short(hit.source)} p.{hit.page} "
            f"(score {hit.score:.3f})  {snippet}..."
        )

    page_hit = best_rank is not None
    rr = 1.0 / best_rank if best_rank else 0.0
    precision, recall, ndcg, gold_in_top_k = _precision_recall_ndcg(
        hits, expected, k=max_parents, tol=tol
    )
    print(
        f"    => page hit@{max_parents}: {'YES' if page_hit else 'NO '}"
        f"  (rank {best_rank if best_rank else '-'})   "
        f"source hit: {'YES' if source_hit else 'NO'}"
        f"\n       precision@{max_parents}: {precision:.2f}  "
        f"recall@{max_parents}: {recall:.2f}  "
        f"nDCG@{max_parents}: {ndcg:.3f}  "
        f"({gold_in_top_k}/{len(expected)} gold labels in top-{max_parents})"
    )
    return CaseResult(
        case["id"],
        query,
        page_hit,
        source_hit,
        rr,
        best_rank,
        verified,
        precision,
        recall,
        ndcg,
        gold_in_top_k,
        len(expected),
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="RAG retrieval-quality eval.")
    parser.add_argument("--db", type=Path, default=config.RAG_DB_PATH)
    parser.add_argument("--gold", type=Path, default=GOLD_PATH)
    parser.add_argument("--child-pool", type=int, default=config.DEFAULT_RAG_CHILD_POOL)
    parser.add_argument(
        "--max-parents", type=int, default=config.DEFAULT_RAG_MAX_PARENTS
    )
    parser.add_argument(
        "--tol", type=int, default=1, help="Page tolerance for a page hit (+/-)."
    )
    parser.add_argument("--show-chars", type=int, default=120)
    parser.add_argument("--only", help="Run a single case by id.")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"RAG store not found: {args.db}\nRun: python scripts/ingest_rag.py")
        return 2

    cases = yaml.safe_load(args.gold.read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
        if not cases:
            print(f"no case with id={args.only!r}")
            return 2

    settings = config.resolve_embed_settings()
    print(
        f"Embedding backend: {settings.backend} ({settings.model}, "
        f"dim={settings.dimension or 'model-defined'})"
    )
    try:
        embedder = build_embedder()
    except Exception as exc:  # noqa: BLE001 - eval needs a live backend
        print(f"Could not build embedder: {exc}")
        print("Set GEMINI_API_KEY (or COG_EMBED_BACKEND=local) and retry.")
        return 2

    conn = db.connect(args.db)
    try:
        store_dim = conn.execute(
            "SELECT value FROM rag_meta WHERE key='dimension'"
        ).fetchone()
        if store_dim and int(store_dim["value"]) != embedder.dimension:
            print(
                f"WARNING: store dim {store_dim['value']} != embedder dim "
                f"{embedder.dimension}. Re-ingest after changing backends."
            )
        print(
            f"Store: {rag_store.parent_count(conn)} parents, "
            f"{rag_store.chunk_count(conn)} children"
        )
        q_total, q_missing = validate_gold_quotes(conn, cases)
        print(
            f"Gold quote validation: {q_total - len(q_missing)}/{q_total} "
            "quotes confirmed on their cited page"
        )
        for item in q_missing:
            print(f"   !! MISSING QUOTE: {item}")
        results = [
            evaluate_case(
                conn,
                embedder,
                case,
                child_pool=args.child_pool,
                max_parents=args.max_parents,
                tol=args.tol,
                show_chars=args.show_chars,
            )
            for case in cases
        ]
    finally:
        conn.close()

    _summary(results, args.max_parents)
    return 0


def _metric_key(k: int) -> None:
    """Plain-language definitions printed before the aggregate score block."""
    print("\n    " + "-" * 66)
    print("    METRIC KEY  (scores use verified gold pages in queries.yaml)")
    print("    " + "-" * 66)
    print(
        f"    k={k}  Top-{k} parent pages returned per query (after child ranking).\n"
        "\n"
        "    page hit@k     Did at least ONE labeled (source, page) appear in top-k?\n"
        "                   Binary pass/fail per query. Easiest bar to clear.\n"
        "\n"
        "    source hit@k   Did at least one labeled *document* appear (any page)?\n"
        "                   Coarser than page hit — right report, maybe wrong page.\n"
        "\n"
        "    MRR            Mean Reciprocal Rank of the first labeled page.\n"
        "                   rank 1 -> 1.0, rank 2 -> 0.5, rank 4 -> 0.25, miss -> 0.\n"
        "                   Higher = labeled pages ranked closer to the top.\n"
        "\n"
        f"    precision@{k}  Of the {k} retrieved slots, what fraction are\n"
        "                   labeled pages? Low is normal when k > gold labels —\n"
        "                   other slots may be on-topic but are not scored here.\n"
        "\n"
        f"    recall@{k}     Of ALL gold labels for a query, what fraction\n"
        f"                   appear in top-{k}? Key for multi-label cases.\n"
        "\n"
        f"    nDCG@{k}       Normalized Discounted Cumulative Gain — ranking\n"
        "                   quality. 1.0 = all labeled pages ranked first.\n"
        "\n"
        "    macro          Average per-query score (each query equal weight).\n"
        "    micro          Pool all queries then divide (multi-label weighs more)."
    )


def _summary(results: List[CaseResult], k: int) -> None:
    n = len(results)
    if not n:
        return

    page_hits = sum(r.page_hit for r in results)
    source_hits = sum(r.source_hit for r in results)
    mrr = sum(r.reciprocal_rank for r in results) / n
    mean_precision = sum(r.precision_at_k for r in results) / n
    mean_recall = sum(r.recall_at_k for r in results) / n
    mean_ndcg = sum(r.ndcg_at_k for r in results) / n
    total_gold = sum(r.gold_label_count for r in results)
    total_gold_in_top = sum(r.gold_in_top_k for r in results)
    micro_precision = total_gold_in_top / (n * k) if n and k else 0.0
    micro_recall = total_gold_in_top / total_gold if total_gold else 0.0

    print("\n" + "=" * 70)
    print(" RAG RETRIEVAL SUMMARY")
    print("=" * 70)
    print(
        f"\n    {n} queries, k={k}, gold labels={total_gold}\n"
        "    Per-query rows (PASS = at least one labeled page in top-k):\n"
    )
    for r in results:
        flag = "PASS" if r.page_hit else ("DOC " if r.source_hit else "MISS")
        rank = f"rank {r.best_rank}" if r.best_rank else "no page hit"
        print(
            f"      {flag}  {r.case_id:<26} {rank:<14} "
            f"P@{k}={r.precision_at_k:.2f} R@{k}={r.recall_at_k:.2f} "
            f"nDCG={r.ndcg_at_k:.3f}"
        )

    _metric_key(k)

    print("\n    " + "-" * 66)
    print("    AGGREGATE METRICS (gold-labeled retrieval)")
    print("    " + "-" * 66)
    print(f"    page hit@{k}          {page_hits}/{n} ({page_hits / n:.1%})")
    print(f"    source hit@{k}        {source_hits}/{n} ({source_hits / n:.1%})")
    print(f"    MRR                   {mrr:.3f}")
    print(f"    precision@{k} (macro) {mean_precision:.3f}")
    print(f"    precision@{k} (micro) {micro_precision:.3f}")
    print(f"    recall@{k} (macro)    {mean_recall:.3f}")
    print(f"    recall@{k} (micro)    {micro_recall:.3f}")
    print(f"    nDCG@{k} (macro)      {mean_ndcg:.3f}")

    print("\n    " + "-" * 66)
    print("    NOT MEASURED HERE")
    print("    " + "-" * 66)
    print(
        "    true precision@k     relevance of pages NOT in the gold set\n"
        "    faithfulness         final answer claims supported by context\n"
        "    groundedness         answer sticks to retrieved sources\n"
        "    answer relevancy     answer addresses the question\n"
        "    (above need LLM-as-judge and/or agent output — see eval README)"
    )

    misses = [r.case_id for r in results if not r.page_hit]
    if misses:
        print(f"\n    inspect these (no page hit): {', '.join(misses)}")
    unverified = [r.case_id for r in results if not r.verified]
    if unverified:
        print(
            "\n    UNVERIFIED gold (relevance not human-confirmed): "
            f"{', '.join(unverified)}"
        )
    print()


if __name__ == "__main__":
    raise SystemExit(main())
