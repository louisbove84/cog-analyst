"""COG graph nodes: resolve → retrieve → context → CC → CR → CV/CoG."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List

from cog_analyst.cog.scenario import resolve_scenario
from cog_analyst.cog.schemas import (
    CapabilityList,
    RequirementList,
    VulnerabilitySynthesis,
)
from cog_analyst.cog.state import AgentState
from cog_analyst.config import DEFAULT_RAG_CHILD_POOL, DEFAULT_RAG_MAX_PARENTS
from cog_analyst.db import join_queries, rag_store
from cog_analyst.db.database import connect
from cog_analyst.db.oob_store import initialize_oob_store

logger = logging.getLogger("cog_analyst.cog.nodes")

LLMFactory = Callable[[], Any]

_NODE2_PROMPT = (
    "You are a military capability analyst applying the Eikmeier COG method.\n"
    "A CRITICAL CAPABILITY is an ACTION the force can perform, phrased as a verb "
    "phrase, that is justified by a specific metric or armament in the data "
    "(e.g. 'Strike targets at operational depth' justified by 'Maximum Range: "
    "2000 km'; 'Engage aircraft beyond visual range' justified by a BVR missile).\n"
    "Rules:\n"
    "- Output ACTIONS, not equipment names. 'PL-15 BVR missile' is NOT a "
    "capability; 'Beyond-visual-range air-to-air engagement' IS.\n"
    "- Each capability must be supported by a metric/armament present in specs. "
    "If nothing supports an action, omit it.\n"
    "- Never copy a raw field value (a number, a place name, a designator) as a "
    "capability. Synthesize the action it enables."
)
_NODE3_PROMPT = (
    "You are applying the Eikmeier COG method.\n"
    "A CRITICAL REQUIREMENT is a resource, condition, or enabler that a "
    "capability NEEDS to function — e.g. 'Jet fuel (aviation kerosene) supply', "
    "'Air-to-air missile resupply', 'Operational runway >2400 m', 'Unjammed "
    "datalink / GPS', 'Engine maintenance & spares', 'AEW&C and tanker support'.\n"
    "Rules:\n"
    "- Derive requirements from the listed capabilities and the asset specs "
    "(engines imply fuel/maintenance; munitions imply resupply; sorties imply "
    "basing).\n"
    "- Output resource/enabler NOUNS, not actions and not raw data values.\n"
    "- NEVER output a place name, airbase, theater, designator, or bare number. "
    "Those are not requirements.\n"
    "- ``doctrinal_context`` (cited OSINT excerpts) MAY inform which requirements "
    "matter, but specs are authoritative; do not invent requirements unsupported "
    "by either."
)
_NODE4_PROMPT = (
    "You are applying the Eikmeier COG method to the assembled evidence.\n"
    "1. CRITICAL VULNERABILITIES: from the requirements, list those that are "
    "single points of failure or easily disrupted (e.g. reliance on a small "
    "number of fixed airbases, a jammable datalink, a scarce munition).\n"
    "2. CENTER OF GRAVITY: the single source of power the system depends on. It "
    "MUST be grounded in the evidence — name either a specific requirement, a "
    "named airbase/unit/theater from the laydown, or a capability hub that "
    "appears in the data. Phrase it as a meaningful clause, NOT a bare token: "
    "write 'Concentration of J-20 fighters at a few Eastern-theater airbases "
    "(e.g. Wuyishan)', NOT just 'Eastern'.\n"
    "``doctrinal_context`` (cited OSINT) may support your reasoning; when you "
    "rely on it, keep it consistent with the structured laydown and do not let "
    "it introduce entities absent from the evidence.\n"
    "Do not invent entities (units, hubs, depots) that are not in the evidence."
)


def _open_laydown_conn(oob_path: Path, weg_path: Path) -> sqlite3.Connection:
    conn = connect(oob_path)
    initialize_oob_store(conn)
    join_queries.attach_weg(conn, weg_path)
    return conn


def resolve_scenario_node(state: AgentState) -> Dict[str, Any]:
    """Node 0: turn the free-text query into deterministic retrieval filters.

    A weapon resolves to a designator; a location (e.g. Taiwan) expands to its
    responsible theater(s). Explicit filters already on the state win.
    """
    resolved = resolve_scenario(
        state.get("query", ""),
        designator=state.get("designator"),
        theater=state.get("theater"),
        role=state.get("role"),
    )
    return {
        "designator": resolved.designator,
        "theater": resolved.theater,
        "role": resolved.role,
        "matched_location": resolved.matched_location,
    }


def retrieve_context_node(
    state: AgentState,
    *,
    embedder: Any,
    rag_path: Path,
    child_pool: int = DEFAULT_RAG_CHILD_POOL,
    max_parents: int = DEFAULT_RAG_MAX_PARENTS,
) -> Dict[str, Any]:
    """Node 2: retrieve cited doctrinal context (RAG), scoped by the entities.

    Parent-child retrieval: rank ``child_pool`` small windows, de-duplicate onto
    distinct parent pages, and return at most ``max_parents`` of them so the LLM
    context stays bounded. The query embedding combines the user's question with
    the resolved entities (designator, location) so retrieval stays anchored to
    the structured set. Returns ``context_snippets`` (empty if the store is
    absent or retrieval fails — RAG is supplementary).
    """
    if not rag_path.exists():
        logger.info("RAG store not found at %s; skipping context", rag_path)
        return {"context_snippets": []}

    terms = [
        state.get("query", ""),
        state.get("designator") or "",
        state.get("matched_location") or "",
    ]
    query_text = " ".join(t for t in terms if t).strip()
    if not query_text:
        return {"context_snippets": []}

    # RAG is supplementary: a failed embed/search (missing key, network blip, or
    # a store built at a different embedding dimension) must not abort the
    # analysis — degrade to empty context instead.
    conn = connect(rag_path)
    try:
        vector = embedder.embed_one(query_text)
        hits = rag_store.search(
            conn, vector, child_pool=child_pool, max_parents=max_parents
        )
    except Exception as exc:  # noqa: BLE001 - context is optional, never fatal
        logger.warning("RAG retrieval failed (%s); continuing without context", exc)
        return {"context_snippets": []}
    finally:
        conn.close()

    snippets = [
        {
            "citation": hit.citation(),
            "source": hit.source,
            "page": hit.page,
            "text": hit.text,
            "score": round(hit.score, 4),
        }
        for hit in hits
    ]
    return {"context_snippets": snippets}


def retrieve_node(
    state: AgentState,
    *,
    oob_path: Path,
    weg_path: Path,
) -> Dict[str, Any]:
    """Node 1: join WEG specs to OOB laydown and dump JSON-ready rows."""
    conn = _open_laydown_conn(oob_path, weg_path)
    try:
        hits = join_queries.capability_laydown(
            conn,
            designator=state.get("designator"),
            theater=state.get("theater"),
            role=state.get("role"),
        )
        assets: List[Dict[str, Any]] = []
        for hit in hits:
            row = join_queries.laydown_as_dicts([hit])[0]
            if hit.weg_asset_title:
                # Pull the quantitative sections (Automotive/Dimensions/Armament),
                # not just System — that is where range/ceiling/speed actually live.
                row["weg_specs"] = join_queries.laydown_specs(conn, hit.weg_asset_title)
            assets.append(row)
        if not assets:
            return {
                "raw_assets": [],
                "error": "No matching laydown rows for the query filters.",
            }
        return {"raw_assets": assets, "error": None}
    finally:
        conn.close()


def _capability_view(assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-asset capability slice: identity + specs only (no geography).

    Geography is withheld from CC/CR reasoning so the model cannot echo airbase
    or theater strings as capabilities/requirements.
    """
    view = []
    for asset in assets:
        view.append(
            {
                "designator": asset.get("en_designator"),
                "type": (asset.get("weg_asset_title") or "").split("(")[0].strip(),
                "specs": asset.get("weg_specs", {}),
            }
        )
    return view


def _laydown_view(assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-asset laydown slice for CoG reasoning: who/where + identity."""
    view = []
    for asset in assets:
        view.append(
            {
                "unit_name": asset.get("unit_name"),
                "designator": asset.get("en_designator"),
                "theater_command": asset.get("theater_command"),
                "airbase": asset.get("airbase"),
                "location_text": asset.get("location_text"),
            }
        )
    return view


def _invoke_structured(
    llm: Any, schema: type, system: str, user_payload: Dict[str, Any]
) -> Any:
    structured = llm.with_structured_output(schema)
    return structured.invoke(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
    )


def extract_cc_node(state: AgentState, *, llm: Any) -> Dict[str, Any]:
    """Node 2: map operational metrics to critical capabilities."""
    if state.get("error") or not state.get("raw_assets"):
        return {}
    result = _invoke_structured(
        llm,
        CapabilityList,
        _NODE2_PROMPT,
        {"assets": _capability_view(state["raw_assets"])},
    )
    return {"critical_capabilities": result.critical_capabilities}


def _context_for_prompt(state: AgentState) -> List[Dict[str, Any]]:
    """Trim RAG snippets to (citation, text) for prompt economy."""
    return [
        {"citation": s.get("citation"), "text": s.get("text")}
        for s in state.get("context_snippets", [])
    ]


def map_cr_node(state: AgentState, *, llm: Any) -> Dict[str, Any]:
    """Node 3: map capabilities to critical requirements (RAG-informed)."""
    if state.get("error") or not state.get("critical_capabilities"):
        return {}
    result = _invoke_structured(
        llm,
        RequirementList,
        _NODE3_PROMPT,
        {
            "assets": _capability_view(state.get("raw_assets", [])),
            "critical_capabilities": state["critical_capabilities"],
            "doctrinal_context": _context_for_prompt(state),
        },
    )
    return {"critical_requirements": result.critical_requirements}


def synthesize_cv_cog_node(state: AgentState, *, llm: Any) -> Dict[str, Any]:
    """Node 4: derive CVs and a grounded CoG statement (RAG-informed)."""
    if state.get("error") or not state.get("critical_requirements"):
        return {}
    result = _invoke_structured(
        llm,
        VulnerabilitySynthesis,
        _NODE4_PROMPT,
        {
            "laydown": _laydown_view(state.get("raw_assets", [])),
            "critical_capabilities": state.get("critical_capabilities", []),
            "critical_requirements": state["critical_requirements"],
            "doctrinal_context": _context_for_prompt(state),
        },
    )
    return {
        "critical_vulnerabilities": result.critical_vulnerabilities,
        "cog_statement": result.cog_statement,
    }


def default_llm() -> Any:
    """Build the default ChatOpenAI client from ``config.resolve_llm_settings``."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "COG agent requires LangChain. "
            "Install with: pip install 'cog-analyst[agent]'"
        ) from exc
    from cog_analyst.config import resolve_llm_settings

    settings = resolve_llm_settings()
    kwargs: Dict[str, Any] = {"model": settings.model}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    if settings.api_key:
        kwargs["api_key"] = settings.api_key
    return ChatOpenAI(**kwargs)


def default_embedder() -> Any:
    """Build the configured RAG embedder (Google hosted by default)."""
    from cog_analyst.rag.embedder import build_embedder

    return build_embedder()
