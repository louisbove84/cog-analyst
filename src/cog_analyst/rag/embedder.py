"""Embedding contracts and a local sentence-transformers implementation.

The :class:`Embedder` ABC isolates the rest of the system from any specific
embedding backend, so tests inject a deterministic fake and production can swap
local models for an API without touching the store or graph. Vectors are
L2-normalized so a dot product equals cosine similarity.

``sentence_transformers`` is imported lazily so importing this module (and the
offline test suite) needs no heavyweight ML dependency installed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    import numpy as np

__all__ = [
    "Embedder",
    "SentenceTransformerEmbedder",
    "GoogleEmbedder",
    "build_embedder",
]

# Local sentence-transformers default (used only when backend == "local").
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class Embedder(ABC):
    """Turns text into L2-normalized float32 vectors for cosine retrieval."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Length of each embedding vector."""
        raise NotImplementedError

    @abstractmethod
    def embed(self, texts: List[str]) -> "np.ndarray":
        """Embed a batch of texts into an ``(n, dimension)`` float32 array."""
        raise NotImplementedError

    def embed_one(self, text: str) -> "np.ndarray":
        """Embed a single text into a ``(dimension,)`` vector."""
        return self.embed([text])[0]


class SentenceTransformerEmbedder(Embedder):
    """Local embedder backed by a sentence-transformers model (offline)."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - exercised without deps
            raise ImportError(
                "RAG embeddings require sentence-transformers. "
                "Install with: pip install 'cog-analyst[rag]'"
            ) from exc
        self._model = SentenceTransformer(model_name)
        dimension = self._model.get_sentence_embedding_dimension()
        if dimension is None:
            raise ValueError(f"Model {model_name!r} has no embedding dimension")
        self._dimension = int(dimension)

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: List[str]) -> "np.ndarray":
        import numpy as np

        if not texts:
            return np.empty((0, self._dimension), dtype=np.float32)
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return vectors.astype(np.float32)


def _l2_normalize(vectors: "np.ndarray") -> "np.ndarray":
    """L2-normalize rows so dot product equals cosine similarity."""
    import numpy as np

    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32)


class GoogleEmbedder(Embedder):
    """Hosted Gemini embeddings via the ``google-genai`` SDK.

    Uses the asymmetric retrieval task types — ``RETRIEVAL_DOCUMENT`` when
    embedding corpus chunks and ``RETRIEVAL_QUERY`` for a search query — which
    measurably improves retrieval over a single task type. ``gemini-embedding-001``
    only pre-normalizes 3072-dim output, so we always L2-normalize to keep the
    store's cosine==dot-product assumption valid at any dimension.

    The SDK and ``types`` module are imported lazily, and a ``client`` can be
    injected for offline testing.
    """

    def __init__(
        self,
        model: str = "gemini-embedding-001",
        *,
        dimension: int = 768,
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        self._model = model
        self._dimension = dimension
        if client is not None:
            self._client = client
            return
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - exercised without deps
            raise ImportError(
                "Google embeddings require google-genai. "
                "Install with: pip install 'cog-analyst[rag]'"
            ) from exc
        self._client = genai.Client(api_key=api_key) if api_key else genai.Client()

    @property
    def dimension(self) -> int:
        return self._dimension

    def _config(self, task_type: str) -> Any:
        # Prefer the typed config; fall back to a dict so injected test clients
        # work without the SDK installed.
        try:
            from google.genai import types

            return types.EmbedContentConfig(
                task_type=task_type, output_dimensionality=self._dimension
            )
        except ImportError:  # pragma: no cover - only without the SDK
            return {
                "task_type": task_type,
                "output_dimensionality": self._dimension,
            }

    def _embed(self, texts: List[str], task_type: str) -> "np.ndarray":
        import numpy as np

        if not texts:
            return np.empty((0, self._dimension), dtype=np.float32)
        # Gemini batchEmbedContents allows at most 100 texts per request.
        batch_size = 100
        parts: List["np.ndarray"] = []
        config = self._config(task_type)
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = self._client.models.embed_content(
                model=self._model,
                contents=batch,
                config=config,
            )
            parts.append(
                np.asarray([e.values for e in response.embeddings], dtype=np.float32)
            )
        vectors = np.vstack(parts) if parts else np.empty((0, self._dimension))
        return _l2_normalize(vectors)

    def embed(self, texts: List[str]) -> "np.ndarray":
        # Corpus documents at ingest time.
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_one(self, text: str) -> "np.ndarray":
        # A search query — different task type than the documents.
        return self._embed([text], "RETRIEVAL_QUERY")[0]


def build_embedder() -> Embedder:
    """Construct the configured embedder (Google by default; local optional)."""
    from cog_analyst.config import resolve_embed_settings

    settings = resolve_embed_settings()
    if settings.backend == "local":
        return SentenceTransformerEmbedder(settings.model)
    return GoogleEmbedder(
        settings.model,
        dimension=settings.dimension,
        api_key=settings.api_key,
    )
