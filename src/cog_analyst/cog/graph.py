"""LangGraph assembly for the bottom-up COG workflow."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import Any, Optional

from cog_analyst.cog.nodes import (
    default_embedder,
    default_llm,
    extract_cc_node,
    map_cr_node,
    resolve_scenario_node,
    retrieve_context_node,
    retrieve_node,
    synthesize_cv_cog_node,
)
from cog_analyst.cog.state import AgentState
from cog_analyst.config import OOB_DB_PATH, RAG_DB_PATH, WEG_DB_PATH

logger = logging.getLogger("cog_analyst.cog.graph")

__all__ = ["build_graph", "run_analysis"]


def build_graph(
    *,
    oob_path: Path = OOB_DB_PATH,
    weg_path: Path = WEG_DB_PATH,
    rag_path: Path = RAG_DB_PATH,
    llm: Optional[Any] = None,
    embedder: Optional[Any] = None,
):
    """Compile resolve → retrieve → context → CC → CR → CV/CoG."""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        raise ImportError(
            "LangGraph is required. Install with: pip install 'cog-analyst[agent]'"
        ) from exc

    llm_instance = llm or default_llm()
    # Only build an embedder if the RAG store exists (context is optional).
    embedder_instance = embedder
    if embedder_instance is None and rag_path.exists():
        embedder_instance = default_embedder()

    graph = StateGraph(AgentState)
    graph.add_node("resolve_scenario", resolve_scenario_node)
    graph.add_node(
        "retrieve",
        partial(retrieve_node, oob_path=oob_path, weg_path=weg_path),
    )
    graph.add_node(
        "retrieve_context",
        partial(retrieve_context_node, embedder=embedder_instance, rag_path=rag_path),
    )
    graph.add_node("extract_cc", partial(extract_cc_node, llm=llm_instance))
    graph.add_node("map_cr", partial(map_cr_node, llm=llm_instance))
    graph.add_node(
        "synthesize_cv_cog",
        partial(synthesize_cv_cog_node, llm=llm_instance),
    )

    graph.set_entry_point("resolve_scenario")
    graph.add_edge("resolve_scenario", "retrieve")
    graph.add_edge("retrieve", "retrieve_context")
    graph.add_edge("retrieve_context", "extract_cc")
    graph.add_edge("extract_cc", "map_cr")
    graph.add_edge("map_cr", "synthesize_cv_cog")
    graph.add_edge("synthesize_cv_cog", END)

    return graph.compile()


def run_analysis(
    query: str,
    *,
    designator: Optional[str] = None,
    theater: Optional[str] = None,
    role: Optional[str] = None,
    oob_path: Path = OOB_DB_PATH,
    weg_path: Path = WEG_DB_PATH,
    rag_path: Path = RAG_DB_PATH,
    llm: Optional[Any] = None,
    embedder: Optional[Any] = None,
) -> AgentState:
    """Run the full graph and return the final state."""
    app = build_graph(
        oob_path=oob_path,
        weg_path=weg_path,
        rag_path=rag_path,
        llm=llm,
        embedder=embedder,
    )
    initial: AgentState = {
        "query": query,
        "designator": designator,
        "theater": theater,
        "role": role,
        "matched_location": None,
        "raw_assets": [],
        "context_snippets": [],
        "critical_capabilities": [],
        "critical_requirements": [],
        "critical_vulnerabilities": [],
        "cog_statement": "",
        "error": None,
    }
    return app.invoke(initial)
