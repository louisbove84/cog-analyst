"""Configuration: filesystem paths (domain-agnostic).

Source provenance and per-domain dataset names live in their domain pack
(e.g. ``cog_analyst.domains.spratly.source``), not here.
"""

from __future__ import annotations

import os
from pathlib import Path

# repo_root/src/cog_analyst/config.py -> repo_root
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = REPO_ROOT / "data"
RAG_DOCS_DIR = REPO_ROOT / "rag_docs"

# Neutral default DB; domains/scripts may point at their own dataset file.
DEFAULT_DB_PATH = Path(
    os.environ.get("COG_ANALYST_DB", DATA_DIR / "cog_analyst.db")
)

# --- LLM backend defaults ---------------------------------------------------
# OpenAI is the default. Set COG_LLM_BASE_URL (+ COG_LLM_MODEL) to point the
# extractor at a local OpenAI-compatible server instead, with no code changes.
OLLAMA_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible API
LMSTUDIO_BASE_URL = "http://localhost:1234/v1"

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_LOCAL_MODEL = "qwen2.5"  # solid local model for structured extraction

LLM_BASE_URL = os.environ.get("COG_LLM_BASE_URL")  # None -> real OpenAI
LLM_API_KEY = os.environ.get("COG_LLM_API_KEY")
LLM_MODEL = os.environ.get("COG_LLM_MODEL")
