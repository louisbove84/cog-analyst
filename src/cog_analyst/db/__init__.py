"""SQLite persistence layer: writes (database) and reads (queries)."""

from cog_analyst.db.database import (
    connect,
    initialize_database,
    insert_aircraft,
    insert_outpost,
    insert_radar,
    insert_weapon,
)
from cog_analyst.db.document_store import (
    WEG_SCHEMA,
    asset_count,
    get_asset,
    initialize_document_store,
    upsert_asset,
)
from cog_analyst.db.queries import (
    ALL_TABLES,
    counts,
    get_aircraft,
    get_column_type,
    get_outpost_aircraft,
    get_outpost_radar,
    get_outpost_weapons,
    get_radar,
    get_weapon,
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
    "initialize_database",
    "insert_weapon",
    "insert_aircraft",
    "insert_radar",
    "insert_outpost",
    "ALL_TABLES",
    "counts",
    "get_column_type",
    "get_weapon",
    "get_aircraft",
    "get_radar",
    "get_outpost_weapons",
    "get_outpost_aircraft",
    "get_outpost_radar",
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
]
