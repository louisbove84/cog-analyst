"""End-to-end pipeline tests using an injected fake extractor (no live LLM)."""

from cog_analyst.domains.spratly import OutpostInfrastructure
from cog_analyst.ingestion.pipeline import IngestionPipeline, IngestStatus
from cog_analyst.models import WeaponSpecification


def test_weapon_snippet_inserts(store, fake_extractor):
    fake_extractor.register(
        WeaponSpecification,
        "HQ-9B",
        WeaponSpecification(
            designator="HQ-9B",
            platform="Road-mobile TEL",
            max_range_km=300,
            flight_profile="vertical launch",
            source_citation="Dahm 2021, p.6",
        ),
    )
    pipeline = IngestionPipeline(fake_extractor)
    result = pipeline.ingest(
        "...the HQ-9B SAM ranges 300 km...", WeaponSpecification, store.insert_weapon
    )
    assert result.status is IngestStatus.INSERTED
    assert store.get_weapon("HQ-9B") is not None


def test_valid_outpost_snippet_inserts(store, fake_extractor):
    fake_extractor.register(
        OutpostInfrastructure,
        "Fiery Cross",
        OutpostInfrastructure(
            reef_name="Fiery Cross Reef",
            runway_length_meters=3000,
            fighter_hangar_count=24,
            verified_deployed_weapons=["HQ-9B", "YJ-12"],
        ),
    )
    pipeline = IngestionPipeline(fake_extractor)
    result = pipeline.ingest(
        "...Fiery Cross Reef has a 3,000-meter runway...",
        OutpostInfrastructure,
        store.insert_outpost,
    )
    assert result.status is IngestStatus.INSERTED
    assert store.get_outpost_weapons("Fiery Cross Reef") == ["HQ-9B", "YJ-12"]


def test_hallucinated_outpost_is_guard_blocked(store, fake_extractor):
    # The (untrusted) extractor emits a schema-valid but non-existent reef.
    fake_extractor.register(
        OutpostInfrastructure,
        "phantom",
        OutpostInfrastructure(
            reef_name="Phantom Reef",
            runway_length_meters=4000,
            fighter_hangar_count=50,
            verified_deployed_weapons=["MADE-UP-9"],
        ),
    )
    pipeline = IngestionPipeline(fake_extractor)
    result = pipeline.ingest(
        "...the phantom outpost...", OutpostInfrastructure, store.insert_outpost
    )
    assert result.status is IngestStatus.GUARD_VIOLATION
    assert result.identifier == "Phantom Reef"
    # Nothing persisted.
    assert store.counts()["outpost_infrastructure"] == 0
    assert store.counts()["outpost_weapons"] == 0


def test_extraction_error_is_captured(store, fake_extractor):
    fake_extractor.register_error(
        WeaponSpecification, "boom", RuntimeError("LLM transport failure")
    )
    pipeline = IngestionPipeline(fake_extractor)
    result = pipeline.ingest("...boom...", WeaponSpecification, store.insert_weapon)
    assert result.status is IngestStatus.EXTRACTION_ERROR
    assert "transport failure" in result.detail
