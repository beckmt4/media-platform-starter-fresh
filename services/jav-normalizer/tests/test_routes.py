from __future__ import annotations

from fastapi.testclient import TestClient

from jav_normalizer.main import app

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
