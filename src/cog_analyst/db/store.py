"""SQLite persistence for verified COG data (engine; domain-agnostic).

`CogStore` is the trusted boundary: nothing is written unless it (a) passed
Pydantic validation and (b) cleared the deterministic entity guard. The reef
registry is *injected* (not hardcoded), so the same store serves any domain that
supplies an appropriate registry.

Note: the table shapes here (weapon_specifications, outpost_infrastructure,
outpost_weapons) currently match the Spratly slice. Generalizing the table
schema itself to arbitrary domains is deferred until a second domain exists
(rule of three); for now only the *names*, the *guard*, and the *engine* are
domain-neutral.

`max_range_km`, `runway_length_meters`, and `fighter_hangar_count` are strict
INTEGER columns.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Union

from cog_analyst import config
from cog_analyst.models.extraction import WeaponSpecification

if TYPE_CHECKING:  # type-only; avoids the engine depending on a domain at runtime
    from cog_analyst.domains.spratly.models import OutpostInfrastructure
    from cog_analyst.ingestion.entity_guard import EntityRegistry

logger = logging.getLogger("cog_analyst.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS weapon_specifications (
    designator      TEXT    PRIMARY KEY,
    export_variant  TEXT,
    platform        TEXT    NOT NULL,
    max_range_km    INTEGER NOT NULL,
    flight_profile  TEXT    NOT NULL,
    source_citation TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS outpost_infrastructure (
    reef_name            TEXT    PRIMARY KEY,
    runway_length_meters INTEGER,
    fighter_hangar_count INTEGER
);

CREATE TABLE IF NOT EXISTS outpost_weapons (
    reef_name         TEXT NOT NULL,
    weapon_designator TEXT NOT NULL,
    PRIMARY KEY (reef_name, weapon_designator),
    FOREIGN KEY (reef_name) REFERENCES outpost_infrastructure (reef_name)
);
"""

_CANONICAL_TABLES = (
    "outpost_weapons",
    "weapon_specifications",
    "outpost_infrastructure",
)


class CogStore:
    """Typed SQLite wrapper for verified weapon and outpost records."""

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        reef_registry: "Optional[EntityRegistry]" = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else config.DEFAULT_DB_PATH
        self._reef_registry = reef_registry
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.init_db()

    def init_db(self) -> None:
        """Create tables if they do not exist (idempotent)."""

        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "CogStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----------------------------------------------------------------- writes
    def insert_weapon(self, weapon: WeaponSpecification) -> str:
        """Upsert a validated weapon specification. Returns its designator."""

        self.conn.execute(
            """
            INSERT INTO weapon_specifications
                (designator, export_variant, platform, max_range_km,
                 flight_profile, source_citation)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(designator) DO UPDATE SET
                export_variant  = excluded.export_variant,
                platform        = excluded.platform,
                max_range_km    = excluded.max_range_km,
                flight_profile  = excluded.flight_profile,
                source_citation = excluded.source_citation;
            """,
            (
                weapon.designator,
                weapon.export_variant,
                weapon.platform,
                weapon.max_range_km,
                weapon.flight_profile,
                weapon.source_citation,
            ),
        )
        self.conn.commit()
        logger.info("Inserted weapon_specification: %s", weapon.designator)
        return weapon.designator

    def insert_outpost(self, outpost: "OutpostInfrastructure") -> str:
        """Insert an outpost + its weapon relations. Returns the reef name.

        Runs the injected reef registry first. If the reef name is not in the
        registry, an EntityGuardViolation propagates and NOTHING is written. If
        no registry was configured, refuses rather than writing unguarded data.
        """

        if self._reef_registry is None:
            raise ValueError(
                "CogStore has no reef_registry configured; refusing to insert "
                "an outpost without a deterministic guard."
            )
        canonical_reef = self._reef_registry.enforce(outpost.reef_name)

        try:
            self.conn.execute(
                """
                INSERT INTO outpost_infrastructure
                    (reef_name, runway_length_meters, fighter_hangar_count)
                VALUES (?, ?, ?)
                ON CONFLICT(reef_name) DO UPDATE SET
                    runway_length_meters = excluded.runway_length_meters,
                    fighter_hangar_count = excluded.fighter_hangar_count;
                """,
                (
                    canonical_reef,
                    outpost.runway_length_meters,
                    outpost.fighter_hangar_count,
                ),
            )
            for designator in outpost.verified_deployed_weapons:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO outpost_weapons
                        (reef_name, weapon_designator)
                    VALUES (?, ?);
                    """,
                    (canonical_reef, designator),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

        logger.info(
            "Inserted outpost_infrastructure: %s (%d weapon links)",
            canonical_reef,
            len(outpost.verified_deployed_weapons),
        )
        return canonical_reef

    # ----------------------------------------------------------------- reads
    def counts(self) -> dict:
        cur = self.conn.cursor()
        result = {}
        for table in _CANONICAL_TABLES:
            cur.execute(f"SELECT COUNT(*) AS n FROM {table};")
            result[table] = cur.fetchone()["n"]
        return result

    def get_column_type(self, table: str, column: str) -> Optional[str]:
        """Return the declared SQL type for a column (used to assert INTEGER)."""

        for row in self.conn.execute(f"PRAGMA table_info({table});"):
            if row["name"] == column:
                return row["type"]
        return None

    def get_weapon(self, designator: str) -> Optional[WeaponSpecification]:
        row = self.conn.execute(
            "SELECT * FROM weapon_specifications WHERE designator = ?;",
            (designator,),
        ).fetchone()
        if row is None:
            return None
        return WeaponSpecification(
            designator=row["designator"],
            export_variant=row["export_variant"],
            platform=row["platform"],
            max_range_km=row["max_range_km"],
            flight_profile=row["flight_profile"],
            source_citation=row["source_citation"],
        )

    def get_outpost_weapons(self, reef_name: str) -> List[str]:
        return [
            r["weapon_designator"]
            for r in self.conn.execute(
                "SELECT weapon_designator FROM outpost_weapons "
                "WHERE reef_name = ? ORDER BY weapon_designator;",
                (reef_name,),
            )
        ]
