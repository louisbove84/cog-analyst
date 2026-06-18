"""Typed state for the COG LangGraph workflow."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """Mutable graph state passed between nodes."""

    query: str
    designator: Optional[str]
    theater: Optional[str]
    role: Optional[str]
    matched_location: Optional[str]
    raw_assets: List[Dict[str, Any]]
    context_snippets: List[Dict[str, Any]]
    critical_capabilities: List[str]
    critical_requirements: List[str]
    critical_vulnerabilities: List[str]
    cog_statement: str
    error: Optional[str]
