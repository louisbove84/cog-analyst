"""cog-analyst: grounded ingestion engine for the Spratly Islands COG slice.

v1 builds the deterministic structured core: LLM-as-untrusted-extractor ->
Pydantic validation -> deterministic entity guard -> SQLite. No semantic RAG
query pipeline yet (the other rag_docs are reserved for that later phase).
"""

__version__ = "0.1.0"
