from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from jav_normalizer.main import app
from jav_normalizer.models import EnrichResult, EnrichStatus, JavMetadata

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_normalize_standard_id():
    resp = client.post("/normalize", json={"raw": "SSIS-123.mkv"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["title"]["canonical_id"] == "SSIS-123"
    assert body["title"]["studio_code"] == "SSIS"
    assert body["title"]["title_number"] == "123"


def test_normalize_no_id():
    resp = client.post("/normalize", json={"raw": "Some Movie Without ID.mkv"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_id_found"
    assert resp.json()["title"] is None


def test_normalize_with_suffix():
    resp = client.post("/normalize", json={"raw": "PRED-456-UC.mkv"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"]["canonical_id"] == "PRED-456"
    assert body["title"]["stripped_suffix"] == "UC"


def test_normalize_ambiguous_returns_best():
    resp = client.post("/normalize", json={"raw": "SSIS-123 and IPX-456.mkv"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ambiguous"
    assert body["title"]["canonical_id"] == "SSIS-123"
    assert len(body["candidates"]) == 2


def test_normalize_all_candidates():
    resp = client.post("/normalize", json={
        "raw": "SSIS-123 and IPX-456.mkv",
        "return_all_candidates": True,
    })
    body = resp.json()
    ids = {c["canonical_id"] for c in body["candidates"]}
    assert ids == {"SSIS-123", "IPX-456"}


def test_normalize_missing_raw_returns_422():
    resp = client.post("/normalize", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /enrich
# ---------------------------------------------------------------------------

def _ok_enrich_result(canonical_id: str = "SSIS-123") -> EnrichResult:
    return EnrichResult(
        canonical_id=canonical_id,
        status=EnrichStatus.ok,
        metadata=JavMetadata(
            canonical_id=canonical_id,
            title="Super Title",
            studio="SOD",
            cast=["Actress A"],
            genres=["Drama"],
        ),
    )


def test_enrich_ok():
    with patch("jav_normalizer.main._enricher.enrich", return_value=_ok_enrich_result()):
        resp = client.post("/enrich", json={"canonical_id": "SSIS-123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["metadata"]["title"] == "Super Title"
    assert body["metadata"]["studio"] == "SOD"


def test_enrich_unavailable():
    unavailable = EnrichResult(
        canonical_id="SSIS-123",
        status=EnrichStatus.unavailable,
        notes=["JAV_METADATA_URL is not configured"],
    )
    with patch("jav_normalizer.main._enricher.enrich", return_value=unavailable):
        resp = client.post("/enrich", json={"canonical_id": "SSIS-123"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "unavailable"


def test_enrich_not_found():
    not_found = EnrichResult(
        canonical_id="SSIS-999",
        status=EnrichStatus.not_found,
        notes=["metadata service returned 404"],
    )
    with patch("jav_normalizer.main._enricher.enrich", return_value=not_found):
        resp = client.post("/enrich", json={"canonical_id": "SSIS-999"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_found"


def test_enrich_missing_canonical_id_returns_422():
    resp = client.post("/enrich", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /normalize-and-enrich
# ---------------------------------------------------------------------------

def test_normalize_and_enrich_ok():
    with patch("jav_normalizer.main._enricher.enrich", return_value=_ok_enrich_result()):
        resp = client.post("/normalize-and-enrich", json={"raw": "SSIS-123.mkv"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["normalize"]["status"] == "ok"
    assert body["normalize"]["title"]["canonical_id"] == "SSIS-123"
    assert body["enrich"]["status"] == "ok"
    assert body["enrich"]["metadata"]["title"] == "Super Title"


def test_normalize_and_enrich_no_id_skips_enrich():
    resp = client.post("/normalize-and-enrich", json={"raw": "No ID Here.mkv"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["normalize"]["status"] == "no_id_found"
    assert body["enrich"] is None


def test_normalize_and_enrich_missing_raw_returns_422():
    resp = client.post("/normalize-and-enrich", json={})
    assert resp.status_code == 422
