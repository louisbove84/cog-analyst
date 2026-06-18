"""SQLite persistence layer: writes and read-only query helpers."""

from cog_analyst.db.database import connect
from cog_analyst.db.document_store import (
    WEG_SCHEMA,
    asset_count,
    get_asset,
    initialize_document_store,
    upsert_asset,
)
from cog_analyst.db.join_queries import (
    SPEC_SECTIONS,
    LaydownHit,
    attach_weg,
    capability_laydown,
    laydown_as_dicts,
    laydown_payload_slice,
    laydown_specs,
)
from cog_analyst.db.oob_queries import (
    UnitHit,
    aircraft_inventory,
    list_theaters,
    role_breakdown,
    search_units,
    units_for_aircraft,
)
from cog_analyst.db.oob_store import (
    OOB_SCHEMA,
    get_unit,
    initialize_oob_store,
    unit_count,
    upsert_unit,
)
from cog_analyst.db.rag_store import (
    RAG_SCHEMA,
    ContextHit,
    add_children,
    add_parents,
    chunk_count,
    initialize_rag_store,
    parent_count,
    search,
)
from cog_analyst.db.weg_queries import (
    AssetHit,
    category_breakdown,
    get_asset_section,
    get_asset_sections,
    list_origins,
    search_assets,
)

__all__ = [
    "connect",
    "WEG_SCHEMA",
    "initialize_document_store",
    "upsert_asset",
    "get_asset",
    "asset_count",
    "AssetHit",
    "search_assets",
    "list_origins",
    "category_breakdown",
    "get_asset_sections",
    "get_asset_section",
    "OOB_SCHEMA",
    "initialize_oob_store",
    "upsert_unit",
    "get_unit",
    "unit_count",
    "UnitHit",
    "search_units",
    "units_for_aircraft",
    "aircraft_inventory",
    "role_breakdown",
    "list_theaters",
    "LaydownHit",
    "attach_weg",
    "capability_laydown",
    "laydown_as_dicts",
    "laydown_payload_slice",
    "laydown_specs",
    "SPEC_SECTIONS",
    "RAG_SCHEMA",
    "ContextHit",
    "initialize_rag_store",
    "add_parents",
    "add_children",
    "search",
    "chunk_count",
    "parent_count",
]
