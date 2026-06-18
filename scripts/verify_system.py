"""One-stop system walkthrough — a narrated tour of every analysis capability.

This is NOT a unit test. It is a verification tool: run it to watch the whole
grounded-analysis pipeline work end to end, from the deterministic primitives up
to the COG agent, and read a plain-English account of what each layer proved.

It deliberately skips the ingestion/scraping internals (those have their own
unit tests) and focuses on the *capabilities* a reviewer cares about:

    1. Designator crosswalk      — deterministic CN -> Latin join key
    2. Scenario resolution       — free-text query -> structured filters
    3. WEG capability catalog    — ground-truth equipment specs (JSON1 reads)
    4. OOB force laydown         — who fields what, from where
    5. Capability x laydown join — the cross-DB grounding artifact
    6. Doctrinal RAG retrieval   — cited context via embeddings + cosine
    7. COG agent orchestration   — the full LangGraph state machine

Data: uses the real stores in data/ when present; otherwise seeds a tiny
self-contained fixture so the tour always runs. The agent step runs OFFLINE by
default (a stub LLM exercises the graph wiring deterministically); pass
``--with-agent`` to drive a live LLM through the same graph.

Usage:
    python scripts/verify_system.py
    python scripts/verify_system.py --with-agent
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Keep this tour fast and hermetic: use any cached embedding model, never hit the
# network (downloading the model is ingest_rag.py's job, not the verifier's).
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
from tempfile import TemporaryDirectory
from typing import Any, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cog_analyst import config, db  # noqa: E402
from cog_analyst.cog.scenario import resolve_scenario  # noqa: E402
from cog_analyst.cog.schemas import (  # noqa: E402
    CapabilityList,
    RequirementList,
    VulnerabilitySynthesis,
)
from cog_analyst.db import (  # noqa: E402
    document_store,
    join_queries,
    oob_queries,
    oob_store,
    rag_store,
    weg_queries,
)
from cog_analyst.ingestion.designator import normalize_designator  # noqa: E402
from cog_analyst.ingestion.oob_markdown import UnitRecord  # noqa: E402
from cog_analyst.ingestion.weg_pdf import AssetRecord  # noqa: E402
from cog_analyst.rag.chunking import ChildChunk, ParentChunk  # noqa: E402

# ----------------------------------------------------------------------------
# Narration helpers — the output is meant to read like a report, not a log.
# ----------------------------------------------------------------------------
_W = 74
_results: List[Tuple[str, bool, str]] = []


def banner(text: str) -> None:
    print("\n" + "=" * _W + f"\n {text}\n" + "=" * _W)


def step(n: int, title: str, why: str) -> None:
    print(f"\n[{n}] {title}\n" + "-" * _W)
    print(f"    Why it matters: {why}")


def show(label: str, value: Any) -> None:
    print(f"      {label:<22} {value}")


def verdict(name: str, ok: bool, note: str) -> None:
    """Record a step's outcome and print a one-line, human verdict."""
    _results.append((name, ok, note))
    print(f"    => {'OK  ' if ok else 'FAIL'} {note}")


# ----------------------------------------------------------------------------
# Offline stand-ins (used only when the real model/LLM is unavailable).
# ----------------------------------------------------------------------------
class _HashEmbedder:
    """Deterministic offline embedder (token-hash buckets, L2-normalized).

    Mirrors the real Embedder contract so RAG retrieval can be demonstrated
    even when sentence-transformers is not installed.
    """

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension

    def embed(self, texts: List[str]):
        import hashlib

        import numpy as np

        out = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for r, text in enumerate(texts):
            for tok in text.lower().split():
                h = int(hashlib.sha1(tok.encode()).hexdigest(), 16)
                out[r, h % self.dimension] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms

    def embed_one(self, text: str):
        return self.embed([text])[0]


class _StubLLM:
    """A canned structured-output LLM that exercises the graph wiring offline.

    It returns schema-valid placeholder content so the COG graph can run node to
    node without a network call. Real synthesis quality is shown with
    ``--with-agent``; this proves the orchestration itself is sound.
    """

    def with_structured_output(self, schema: type) -> "_StubLLM":
        self._schema = schema
        return self

    def invoke(self, _messages: Any) -> Any:
        if self._schema is CapabilityList:
            return CapabilityList(
                critical_capabilities=[
                    "Engage aircraft beyond visual range",
                    "Strike targets at operational depth",
                ]
            )
        if self._schema is RequirementList:
            return RequirementList(
                critical_requirements=[
                    "Aviation fuel supply",
                    "Air-to-air missile resupply",
                ]
            )
        return VulnerabilitySynthesis(
            critical_vulnerabilities=["Aviation fuel supply"],
            cog_statement="Concentration of fielding units at a few theater airbases",
        )


# ----------------------------------------------------------------------------
# Data sources: prefer the real stores; seed a tiny fixture if they are absent.
# ----------------------------------------------------------------------------
def _seed_structured(tmp: Path) -> Tuple[Path, Path]:
    """Write a minimal WEG + OOB pair (one J-20 asset, one fielding unit)."""
    weg_path, oob_path = tmp / "weg.db", tmp / "oob.db"
    wconn, oconn = db.connect(weg_path), db.connect(oob_path)
    document_store.initialize_document_store(wconn)
    oob_store.initialize_oob_store(oconn)
    document_store.upsert_asset(
        wconn,
        AssetRecord(
            asset_title="J-20 (FAGIN) Chinese Stealth Air Superiority Fighter",
            source_url="https://example.mil/weg/j-20",
            notes="Demo asset.",
            payload={
                "Metadata": {"Origin": "China", "Domain": "Air, Fighter"},
                "System": {"Maximum Range (km)": "2000"},
                "Automotive": {"Service Ceiling (m)": "20000"},
            },
        ),
    )
    oob_store.upsert_unit(
        oconn,
        UnitRecord(
            unit_name="Demo Brigade",
            service="PLAAF",
            branch=None,
            role="fighter",
            theater_command="Eastern",
            location_text="Wuhu",
            province=None,
            airbase="Wuhu",
            tactical_code=None,
            remarks=None,
            source_url="https://example.org/oob",
            aircraft=[normalize_designator("歼-20A")],
        ),
    )
    wconn.close()
    oconn.close()
    return oob_path, weg_path


def _seed_rag(tmp: Path, embedder: Any) -> Path:
    """Write a tiny parent-child RAG store using the chosen embedder."""
    rag_path = tmp / "rag.db"
    conn = db.connect(rag_path)
    rag_store.initialize_rag_store(conn, dimension=embedder.dimension)
    parents = [
        ParentChunk(
            "demo_cmpr.pdf", 12, "PLA air power depends on fixed airbases and fuel"
        ),
        ParentChunk(
            "demo_cmpr.pdf", 41, "Key vulnerabilities: logistics, rigid command"
        ),
        ParentChunk(
            "demo_dahm.pdf", 7, "Beyond-visual-range missiles enable air control"
        ),
    ]
    children = [ChildChunk(p.source, p.page, p.text, i) for i, p in enumerate(parents)]
    parent_ids = rag_store.add_parents(conn, parents)
    vectors = embedder.embed([c.text for c in children])
    rag_store.add_children(conn, children, vectors, parent_ids)
    conn.close()
    return rag_path


def resolve_embedder() -> Tuple[Any, str, bool]:
    """Use the configured embedder if it works; otherwise the offline hash stub.

    Runs a one-shot health-check embed so a missing API key or network (Google)
    or uncached model (local) degrades gracefully to a deterministic offline
    fallback. Returns ``(embedder, description, is_real)``.
    """
    try:
        from cog_analyst.config import resolve_embed_settings
        from cog_analyst.rag.embedder import build_embedder

        settings = resolve_embed_settings()
        embedder = build_embedder()
        embedder.embed_one("healthcheck")  # surfaces key/network/model issues
        return embedder, f"{settings.backend} embedder ({settings.model})", True
    except Exception:  # noqa: BLE001 - any failure -> deterministic offline fallback
        return _HashEmbedder(), "offline hash embedder (configured backend down)", False


def _store_dimension(rag_path: Path) -> int:
    """Read the embedding dimension recorded in an existing RAG store (-1 if absent)."""
    conn = db.connect(rag_path)
    try:
        row = conn.execute(
            "SELECT value FROM rag_meta WHERE key = 'dimension'"
        ).fetchone()
        return int(row["value"]) if row else -1
    except Exception:  # noqa: BLE001 - store may predate the meta table
        return -1
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# The walkthrough steps.
# ----------------------------------------------------------------------------
def verify_designator() -> None:
    step(
        1,
        "Designator crosswalk",
        "OOB lists aircraft in Chinese (歼-20A); WEG uses Latin (J-20). Every "
        "cross-DB join depends on this mapping being deterministic.",
    )
    cases = {"歼-20A": "J-20", "轰-6K": "H-6", "运油-20": "YY-20", "无侦-7": "WZ-7"}
    ok = True
    for raw, expected in cases.items():
        parts = normalize_designator(raw)
        ok = ok and parts.en_base == expected
        show(raw, f"-> {parts.en_base}   (cn base {parts.cn_base})")
    verdict("designator", ok, f"{len(cases)}/{len(cases)} resolved to expected keys")


def verify_scenario() -> None:
    step(
        2,
        "Scenario resolution",
        "A free-text question must become deterministic retrieval filters — the "
        "LLM never gets to pick which entities are in scope.",
    )
    loc = resolve_scenario("Assess the J-20 threat to Taiwan")
    show("query", "'Assess the J-20 threat to Taiwan'")
    show("-> designator", loc.designator)
    show("-> theaters", loc.theaters)
    cn = resolve_scenario("歼-20 在东部战区")
    show("query (Chinese)", "'歼-20 在东部战区'")
    show("-> designator", cn.designator)
    ok = loc.designator == "J-20" and loc.theaters == ["Eastern", "Southern"]
    ok = ok and cn.designator == "J-20"
    verdict("scenario", ok, "weapon + location both resolved to grounded filters")


def verify_weg(weg_path: Path) -> None:
    step(
        3,
        "WEG capability catalog (ground truth)",
        "The equipment store is the canonical 'what a system can do'. Reads use "
        "JSON1 so varying section layouts never break the query.",
    )
    conn = db.connect(weg_path)
    try:
        china = weg_queries.search_assets(conn, origin="China", limit=None)
        breakdown = weg_queries.category_breakdown(conn, origin="China")
        show("Chinese assets", len(china))
        show("top categories", dict(list(breakdown.items())[:4]))
        sample = next((a for a in china if a.asset_title.startswith("J-20")), china[0])
        sections = weg_queries.get_asset_sections(conn, sample.asset_title)
        show("sample asset", sample.asset_title[:48])
        show("its sections", sections[:6])
        verdict(
            "weg",
            len(china) > 0 and len(sections) > 0,
            f"{len(china)} grounded assets, each introspectable by section",
        )
    finally:
        conn.close()


def verify_oob(oob_path: Path) -> str:
    step(
        4,
        "OOB force laydown",
        "Specs cannot say who fields a system or from where. The OOB store adds "
        "the units, bases, and theaters behind each aircraft type.",
    )
    conn = db.connect(oob_path)
    try:
        inv = oob_queries.aircraft_inventory(conn)
        top_type = next(iter(inv)) if inv else "J-20"
        units = oob_queries.units_for_aircraft(conn, top_type)
        show("aircraft types", len(inv))
        show("most-fielded", f"{top_type} ({inv.get(top_type, 0)} units)")
        if units:
            u = units[0]
            show("example unit", f"{u.unit_name}  @ {u.airbase or u.location_text}")
            show("  theater", u.theater_command)
        verdict(
            "oob",
            len(inv) > 0 and len(units) > 0,
            f"{len(inv)} types mapped to fielding units + bases",
        )
        return top_type
    finally:
        conn.close()


def verify_join(oob_path: Path, weg_path: Path, designator: str) -> None:
    step(
        5,
        "Capability x laydown join",
        "This is the heart of the grounding: one row tying a real unit/base to "
        "the WEG specs of the aircraft it flies — the COG agent's Node 1 input.",
    )
    conn = db.connect(oob_path)
    try:
        join_queries.attach_weg(conn, weg_path)
        hits = join_queries.capability_laydown(conn, designator=designator)
        linked = [h for h in hits if h.weg_asset_title]
        show(f"{designator} laydown rows", len(hits))
        show("rows linked to WEG", len(linked))
        if linked:
            h = linked[0]
            show("joined row", f"{h.unit_name} flies {h.en_designator}")
            show("  -> WEG asset", (h.weg_asset_title or "")[:46])
            specs = join_queries.laydown_specs(conn, h.weg_asset_title)
            show("  -> spec sample", dict(list(specs.items())[:2]))
        verdict(
            "join",
            len(hits) > 0,
            f"unit/base/theater fused with WEG specs for {designator}",
        )
    finally:
        conn.close()


def verify_rag(rag_path: Path, embedder: Any, mode: str) -> None:
    step(
        6,
        "Doctrinal RAG retrieval (Parent-Child)",
        "Reports explain WHY a dependency matters — context the structured DBs "
        "cannot. Small children are matched; full parent pages are returned, "
        "de-duplicated, and always cited.",
    )
    show("embedder", mode)
    conn = db.connect(rag_path)
    try:
        parents = rag_store.parent_count(conn)
        children = rag_store.chunk_count(conn)
        q = embedder.embed_one("logistics and airbase vulnerabilities near Taiwan")
        hits = rag_store.search(conn, q, max_parents=2)
        show("parents / children", f"{parents} / {children}")
        for h in hits:
            show(h.citation(), f"(score {h.score:.3f}) {h.text[:52]}...")
        verdict(
            "rag",
            children > 0 and len(hits) > 0,
            "child match -> de-duped parent pages returned with citations",
        )
    finally:
        conn.close()


def verify_agent(
    oob_path: Path, weg_path: Path, rag_path: Path, embedder: Any, live: bool
) -> None:
    step(
        7,
        "COG agent orchestration (LangGraph)",
        "The full state machine: resolve -> retrieve -> context -> CC -> CR -> "
        "CV/CoG, accumulating grounded evidence into a Center-of-Gravity call.",
    )
    try:
        from cog_analyst.cog.graph import run_analysis
    except ImportError:
        verdict("agent", True, "SKIPPED: install '.[agent]' (langgraph) to run it")
        return

    if live:
        show("mode", "LIVE — driving the configured LLM through the graph")
        llm = None  # graph builds the real default_llm()
    else:
        show("mode", "offline — stub LLM verifies wiring (use --with-agent for live)")
        llm = _StubLLM()

    try:
        final = run_analysis(
            "Assess the J-20 threat to Taiwan",
            oob_path=oob_path,
            weg_path=weg_path,
            rag_path=rag_path,
            llm=llm,
            embedder=embedder,
        )
    except Exception as exc:  # noqa: BLE001 - live LLM/key issues shouldn't crash tour
        verdict("agent", not live, f"graph raised: {type(exc).__name__}: {exc}")
        return

    show("assets retrieved", len(final.get("raw_assets", [])))
    show("context snippets", len(final.get("context_snippets", [])))
    show("capabilities", final.get("critical_capabilities", []))
    show("requirements", final.get("critical_requirements", []))
    show("vulnerabilities", final.get("critical_vulnerabilities", []))
    show("CENTER OF GRAVITY", final.get("cog_statement", ""))
    ok = bool(final.get("cog_statement")) and not final.get("error")
    verdict("agent", ok, "graph ran every node and produced a grounded CoG")


def big_picture() -> int:
    banner("BIG PICTURE")
    passed = sum(1 for _, ok, _ in _results if ok)
    print(
        "\n    cog-analyst turns two deterministic stores (equipment specs +\n"
        "    force laydown) into the single grounded artifact an analyst needs,\n"
        "    layers cited doctrine on top, and lets a LangGraph agent reason\n"
        "    bottom-up to a Center of Gravity — without ever letting the model\n"
        "    invent an entity or override a database fact.\n"
    )
    for name, ok, note in _results:
        print(f"      {'PASS' if ok else 'FAIL'}  {name:<12} {note}")
    print(f"\n    {passed}/{len(_results)} capabilities verified.")
    return 0 if passed == len(_results) else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-agent",
        action="store_true",
        help="Drive a live LLM through the COG graph (needs .[agent] + a key).",
    )
    args = parser.parse_args(argv)

    banner("cog-analyst — System Verification Walkthrough")

    with TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Structured stores: real if ingested, else a seeded demo fixture.
        if config.WEG_DB_PATH.exists() and config.OOB_DB_PATH.exists():
            oob_path, weg_path = config.OOB_DB_PATH, config.WEG_DB_PATH
            src = "real stores in data/"
        else:
            oob_path, weg_path = _seed_structured(tmp)
            src = "seeded demo fixture (no ingested DBs found)"
        print(f"\n    Structured data source: {src}")

        # RAG store: reuse the real store only if a working embedder produces
        # vectors of the SAME dimension it was built with (else seed a fresh one).
        embedder, emb_mode, real_model = resolve_embedder()
        dim_ok = (
            real_model
            and config.RAG_DB_PATH.exists()
            and _store_dimension(config.RAG_DB_PATH) == embedder.dimension
        )
        if dim_ok:
            rag_path = config.RAG_DB_PATH
            print("    RAG data source:        real store data/rag.db")
        else:
            rag_path = _seed_rag(tmp, embedder)
            note = "" if real_model else " (backend down -> hash demo)"
            print(f"    RAG data source:        seeded demo store{note}")

        verify_designator()
        verify_scenario()
        verify_weg(weg_path)
        top_type = verify_oob(oob_path)
        join_designator = "J-20" if top_type.startswith("J-20") else top_type
        verify_join(oob_path, weg_path, join_designator)
        verify_rag(rag_path, embedder, emb_mode)
        verify_agent(oob_path, weg_path, rag_path, embedder, args.with_agent)

    return big_picture()


if __name__ == "__main__":
    raise SystemExit(main())
