"""Shared test fixtures."""

from __future__ import annotations

import hashlib
from typing import List

import numpy as np
import pytest

from cog_analyst import db
from cog_analyst.db import document_store, join_queries, oob_store
from cog_analyst.ingestion.designator import normalize_designator
from cog_analyst.ingestion.oob_markdown import UnitRecord
from cog_analyst.ingestion.weg_pdf import AssetRecord
from cog_analyst.rag.embedder import Embedder


class FakeEmbedder(Embedder):
    """Deterministic offline embedder: hashes tokens into a fixed-dim vector.

    Stands in for sentence-transformers so RAG tests run without ML deps or
    network. Vectors are L2-normalized so dot product == cosine, matching the
    real embedder's contract; shared tokens yield higher similarity.
    """

    def __init__(self, dimension: int = 32) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: List[str]) -> np.ndarray:
        out = np.zeros((len(texts), self._dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in text.lower().split():
                h = int(hashlib.sha1(token.encode()).hexdigest(), 16)
                out[row, h % self._dimension] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


@pytest.fixture()
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture()
def laydown_dbs(tmp_path):
    """Minimal WEG + OOB stores joined for cross-DB query tests."""
    weg_conn = db.connect(tmp_path / "weg.db")
    oob_conn = db.connect(tmp_path / "oob.db")
    document_store.initialize_document_store(weg_conn)
    oob_store.initialize_oob_store(oob_conn)
    document_store.upsert_asset(
        weg_conn,
        AssetRecord(
            asset_title="J-20 (FAGIN) Chinese Stealth Air Superiority Fighter",
            source_url="https://example.mil/weg/j-20",
            notes="Test asset.",
            payload={
                "Metadata": {"Origin": "China", "Domain": "Air, Fighter"},
                "System": {
                    "Maximum Range (km)": "2000",
                    "Ceiling (m)": "20000",
                },
            },
        ),
    )
    oob_store.upsert_unit(
        oob_conn,
        UnitRecord(
            unit_name="空9旅",
            service="PLAAF",
            branch=None,
            role="fighter",
            theater_command="Eastern",
            location_text="安徽芜湖市湾里机场",
            province="安徽省",
            airbase="湾里机场",
            tactical_code="62X0X",
            remarks="上海基地",
            source_url="https://example.org/oob",
            aircraft=[normalize_designator("歼-20A")],
        ),
    )
    join_queries.attach_weg(oob_conn, tmp_path / "weg.db")
    yield oob_conn, weg_conn
    oob_conn.close()
    weg_conn.close()
