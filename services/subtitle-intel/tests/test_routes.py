from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from subtitle_intel.main import app

client = TestClient(app)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_scan_with_supplied_json_anime():
    payload = {
        "file_path": "/fake/anime.mkv",
        "mediainfo_json": _load("mediainfo_anime.json"),
    }
    resp = client.post("/scan", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["subtitle_tracks"]) == 4


def test_scan_forced_track_in_result():
    payload = {
        "file_path": "/fake/anime.mkv",
        "mediainfo_json": _load("mediainfo_anime.json"),
    }
    resp = client.post("/scan", json=payload)
    tracks = resp.json()["subtitle_tracks"]
    forced = [t for t in tracks if t["track_type"] == "forced"]
    assert len(forced) == 1


def test_scan_no_subtitle_tracks():
    payload = {
        "file_path": "/fake/nosubs.mkv",
        "mediainfo_json": _load("mediainfo_no_subtitles.json"),
    }
    resp = client.post("/scan", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "no_subtitle_tracks"
    assert body["subtitle_tracks"] == []


def test_scan_unknown_language_flags_review():
    payload = {
        "file_path": "/fake/title.mkv",
        "mediainfo_json": _load("mediainfo_no_lang_tag.json"),
    }
    resp = client.post("/scan", json=payload)
    body = resp.json()
    assert body["status"] == "ok"
    assert body["subtitle_tracks"][0]["detected_language"] == "unknown"
    assert body["subtitle_tracks"][0]["confidence"] == 0.0


def test_scan_file_not_found_no_json():
    payload = {"file_path": "/does/not/exist/file.mkv"}
    resp = client.post("/scan", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "file_not_found"


def test_scan_invalid_request_missing_file_path():
    resp = client.post("/scan", json={})
    assert resp.status_code == 422
