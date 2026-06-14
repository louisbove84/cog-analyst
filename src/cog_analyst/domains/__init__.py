"""Domain packs.

Each domain (e.g. ``spratly``) supplies its own entity registries, extraction
models, and source provenance, all built on the shared engine in
``cog_analyst.ingestion`` and ``cog_analyst.db``. Adding a new theater of
analysis means adding a sibling package here, not changing the engine.
"""
