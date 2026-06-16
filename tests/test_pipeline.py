"""End-to-end pipeline tests using an injected fake extractor (no live LLM)."""

import functools

from cog_analyst import db
from cog_analyst.ingestion import ExtractionError
from cog_analyst.ingestion.pipeline import IngestionPipeline, IngestStatus
from cog_analyst.models import OutpostInfrastructure, WeaponSpecification


# TLDR: A clean weapon snippet flows extract -> validate -> persist and lands in the DB.
def test_weapon_snippet_inserts(conn, fake_extractor):
    fake_extractor.register(
        WeaponSpecification,
        "HQ-9B",
        WeaponSpecification(
            designator="HQ-9B", max_range_km=300, source_citation="Dahm p.6"
        ),
    )
    pipeline = IngestionPipeline(fake_extractor)
    result = pipeline.ingest(
        "...the HQ-9B SAM ranges 300 km...",
        WeaponSpecification,
        functools.partial(db.insert_weapon, conn),
    )
    assert result.status is IngestStatus.INSERTED
    assert db.get_weapon(conn, "HQ-9B") is not None


# TLDR: An outpost snippet inserts and its capability links are persisted.
def test_valid_outpost_snippet_inserts(conn, fake_extractor):
    fake_extractor.register(
        OutpostInfrastructure,
        "Fiery Cross",
        OutpostInfrastructure(
            reef_name="Fiery Cross Reef",
            runway_length_meters=3000,
            verified_deployed_weapons=["HQ-9B", "YJ-12"],
        ),
    )
    pipeline = IngestionPipeline(fake_extractor)
    result = pipeline.ingest(
        "...Fiery Cross Reef has a 3,000-meter runway...",
        OutpostInfrastructure,
        functools.partial(db.insert_outpost, conn),
    )
    assert result.status is IngestStatus.INSERTED
    assert db.get_outpost_weapons(conn, "Fiery Cross Reef") == ["HQ-9B", "YJ-12"]


# TLDR: The pipeline doesn't guard on write - an unknown reef is still inserted raw.
def test_unknown_reef_inserts_raw(conn, fake_extractor):
    """The write path does not guard; an unknown reef is persisted raw.
    Reconciliation against ground truth happens downstream, not on write."""
    fake_extractor.register(
        OutpostInfrastructure,
        "phantom",
        OutpostInfrastructure(
            reef_name="Phantom Reef", verified_deployed_weapons=["MADE-UP-9"]
        ),
    )
    pipeline = IngestionPipeline(fake_extractor)
    result = pipeline.ingest(
        "...the phantom outpost...",
        OutpostInfrastructure,
        functools.partial(db.insert_outpost, conn),
    )
    assert result.status is IngestStatus.INSERTED
    assert db.counts(conn)["outpost_infrastructure"] == 1


# TLDR: An extractor failure is caught and reported as a status, not a crash.
def test_extraction_error_is_captured(conn, fake_extractor):
    fake_extractor.register_error(
        WeaponSpecification, "boom", ExtractionError("LLM transport failure")
    )
    pipeline = IngestionPipeline(fake_extractor)
    result = pipeline.ingest(
        "...boom...", WeaponSpecification, functools.partial(db.insert_weapon, conn)
    )
    assert result.status is IngestStatus.EXTRACTION_ERROR
    assert "transport failure" in result.detail
