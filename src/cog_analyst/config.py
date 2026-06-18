"""Configuration: filesystem paths and LLM backend resolution.

Loads ``REPO_ROOT/.env`` at import time (real environment variables always win),
then exposes a single ``resolve_llm_settings`` entry point that turns CLI flags +
environment into a concrete :class:`LLMSettings`. Source provenance and per-domain
dataset names live in their domain pack, not here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# repo_root/src/cog_analyst/config.py -> repo_root
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = REPO_ROOT / "data"
RAG_DOCS_DIR = REPO_ROOT / "rag_docs"
WEG_DB_PATH = DATA_DIR / "weg.db"
OOB_DB_PATH = DATA_DIR / "oob.db"
RAG_DB_PATH = DATA_DIR / "rag.db"


def _load_dotenv() -> None:
    """Parse ``REPO_ROOT/.env`` into the environment without overriding real vars.

    Minimal ``KEY=VALUE`` parser (no external dependency). Lines that are blank,
    comments, or lack ``=`` are ignored. Surrounding quotes are stripped. Real
    environment variables take precedence (``setdefault``).
    """
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv()

# Neutral default DB; domains/scripts may point at their own dataset file.
DEFAULT_DB_PATH = Path(
    os.environ.get("COG_ANALYST_DB", str(DATA_DIR / "cog_analyst.db"))
)

# --- LLM backend presets ----------------------------------------------------
OLLAMA_BASE_URL = "http://localhost:11434/v1"  # Ollama's OpenAI-compatible API
LMSTUDIO_BASE_URL = "http://localhost:1234/v1"

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_LOCAL_MODEL = "qwen2.5"  # solid local model for structured extraction


@dataclass(frozen=True)
class LLMSettings:
    """Fully-resolved settings for constructing an extractor client."""

    model: str
    base_url: Optional[str]
    api_key: Optional[str]
    structured_output_method: Optional[str] = None

    @property
    def where(self) -> str:
        """Human-readable backend label for logging."""
        return self.base_url or "OpenAI API"


def resolve_llm_settings(
    *,
    backend: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    structured_output_method: Optional[str] = None,
) -> LLMSettings:
    """Resolve LLM settings from explicit args, then env, then sensible defaults.

    Precedence for each value: explicit argument > environment variable > preset.

    Backends:
      - ``openai`` (default): real OpenAI unless ``COG_LLM_BASE_URL`` is set
        (e.g. xAI/Grok at ``https://api.x.ai/v1``).
      - ``ollama`` / ``lmstudio``: local OpenAI-compatible servers.
    """
    backend = (backend or os.environ.get("COG_LLM_BACKEND") or "openai").lower()
    base_url = base_url or os.environ.get("COG_LLM_BASE_URL")
    api_key = api_key or os.environ.get("COG_LLM_API_KEY")
    model = model or os.environ.get("COG_LLM_MODEL")

    if base_url is None:
        if backend == "ollama":
            base_url = OLLAMA_BASE_URL
            api_key = api_key or "ollama"
        elif backend == "lmstudio":
            base_url = LMSTUDIO_BASE_URL
            api_key = api_key or "lmstudio"
        elif backend not in ("openai", ""):
            raise ValueError(
                f"unknown COG_LLM_BACKEND={backend!r}; expected "
                f"'openai', 'ollama', or 'lmstudio'"
            )

    if model is None:
        model = DEFAULT_LOCAL_MODEL if base_url is not None else DEFAULT_OPENAI_MODEL

    return LLMSettings(
        model=model,
        base_url=base_url,
        api_key=api_key,
        structured_output_method=structured_output_method,
    )


# --- RAG embedding backend --------------------------------------------------
DEFAULT_GOOGLE_EMBED_MODEL = "gemini-embedding-001"
DEFAULT_GOOGLE_EMBED_DIM = 768  # recommended compact cut (vs 3072 default)
DEFAULT_LOCAL_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# --- RAG retrieval (parent-child) -------------------------------------------
# child_pool: how many child windows are ranked before de-dup (match precision).
# max_parents: distinct parent pages passed to the LLM (the context-size cap).
DEFAULT_RAG_CHILD_POOL = 15
DEFAULT_RAG_MAX_PARENTS = 4


@dataclass(frozen=True)
class EmbedSettings:
    """Fully-resolved settings for constructing a RAG embedder."""

    backend: str  # "google" | "local"
    model: str
    dimension: int  # requested output dim (0 = model-defined, for local)
    api_key: Optional[str]


def resolve_embed_settings(
    *,
    backend: Optional[str] = None,
    model: Optional[str] = None,
    dimension: Optional[int] = None,
    api_key: Optional[str] = None,
) -> EmbedSettings:
    """Resolve embedding settings: explicit args > env > defaults.

    Default backend is ``google`` (hosted Gemini embeddings, ``gemini-embedding-
    001`` @ 768 dims). Set ``COG_EMBED_BACKEND=local`` to use a local
    sentence-transformers model instead. The Google key is read from
    ``COG_EMBED_API_KEY``, then ``GEMINI_API_KEY``, then ``GOOGLE_API_KEY``.
    """
    backend = (backend or os.environ.get("COG_EMBED_BACKEND") or "google").lower()
    model = model or os.environ.get("COG_EMBED_MODEL")

    if backend == "local":
        return EmbedSettings(
            backend="local",
            model=model or DEFAULT_LOCAL_EMBED_MODEL,
            dimension=0,
            api_key=None,
        )
    if backend != "google":
        raise ValueError(
            f"unknown COG_EMBED_BACKEND={backend!r}; expected 'google' or 'local'"
        )

    dim_env = os.environ.get("COG_EMBED_DIM")
    dimension = dimension or (int(dim_env) if dim_env else DEFAULT_GOOGLE_EMBED_DIM)
    api_key = (
        api_key
        or os.environ.get("COG_EMBED_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )
    return EmbedSettings(
        backend="google",
        model=model or DEFAULT_GOOGLE_EMBED_MODEL,
        dimension=dimension,
        api_key=api_key,
    )
