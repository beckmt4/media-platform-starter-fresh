from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
os.environ.setdefault("POLICY_DIR", str(REPO_ROOT / "config" / "policies"))

from media_policy_engine.main import app, _evaluator  # noqa: E402

# Clear lru_cache so POLICY_DIR env var takes effect
_evaluator.cache_clear()

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_evaluate_hevc_returns_skip_transcode():
    payload = {
        "domain": "domestic_live_action_movie",
        "detected_original_language": "en",
        "video": {"codec": "hevc"},
    }
    resp = client.post("/evaluate", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    kinds = {a["kind"] for a in body["actions"]}
    assert "skip_transcode" in kinds


def test_evaluate_h264_returns_flag_for_transcode():
    payload = {
        "domain": "domestic_live_action_movie",
        "detected_original_language": "en",
        "video": {"codec": "h264"},
    }
    resp = client.post("/evaluate", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    kinds = {a["kind"] for a in body["actions"]}
    assert "flag_for_transcode" in kinds


def test_evaluate_unknown_subtitle_quarantined():
    payload = {
        "domain": "anime_series",
        "detected_original_language": "ja",
        "video": {"codec": "hevc"},
        "subtitle_tracks": [
            {"track_index": 0, "language": "unknown", "confidence": 0.4}
        ],
    }
    resp = client.post("/evaluate", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_review"] is True
    kinds = {a["kind"] for a in body["actions"]}
    assert "quarantine_subtitle" in kinds


def test_evaluate_adult_generates_english_subtitle():
    payload = {
        "domain": "jav_adult",
        "detected_original_language": "ja",
        "video": {"codec": "hevc"},
        "subtitle_tracks": [],
    }
    resp = client.post("/evaluate", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    kinds = {a["kind"] for a in body["actions"]}
    assert "generate_english_subtitles" in kinds


def test_evaluate_locked_item_skips_mutations():
    payload = {
        "domain": "domestic_live_action_movie",
        "detected_original_language": "en",
        "video": {"codec": "h264"},
        "catalog_tags": ["locked"],
    }
    resp = client.post("/evaluate", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    kinds = {a["kind"] for a in body["actions"]}
    assert "skip_transcode" in kinds
    assert "flag_for_transcode" not in kinds


def test_evaluate_invalid_domain_returns_422():
    payload = {
        "domain": "not_real",
        "detected_original_language": "en",
        "video": {"codec": "hevc"},
    }
    resp = client.post("/evaluate", json=payload)
    assert resp.status_code == 422
