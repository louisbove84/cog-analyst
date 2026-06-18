"""RAG layer: chunk doctrinal PDFs, embed them, retrieve cited context.

This is **supplementary** to the structured ground truth (`weg.db` / `oob.db`).
Retrieved snippets add doctrinal/strategic context to the CR/CV/CoG reasoning but
never select entities or override a database fact.
"""

from cog_analyst.rag.embedder import (
    Embedder,
    GoogleEmbedder,
    SentenceTransformerEmbedder,
    build_embedder,
)

__all__ = [
    "Embedder",
    "GoogleEmbedder",
    "SentenceTransformerEmbedder",
    "build_embedder",
]
