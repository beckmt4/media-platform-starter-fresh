"""
End-to-end dry-run integration test.

Exercises the full intake chain without mutating any media files:

  arr webhook payload
    → catalog register      (catalog-api)
    → subtitle scan         (subtitle-intel)
    → build MediaFacts      (same logic as n8n Build MediaFacts node)
    → policy evaluate       (media-policy-engine)
    → review gate           (catalog-api review-queue)
    → worker dispatch       (subtitle-worker / transcode-worker, dry_run=True)
    → state update          (catalog-api PATCH state → active)

Requirements:
  All five service packages must be installed:
    pip install -e apps/catalog-api
    pip install -e services/media-policy-engine
    pip install -e services/subtitle-intel
    pip install -e workers/subtitle-worker
    pip install -e workers/transcode-worker

Tests are skipped automatically if any package is not importable.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Skip the whole module if any service package is missing
# ---------------------------------------------------------------------------

pytest.importorskip("catalog_api.main", reason="catalog-api not installed")
pytest.importorskip("subtitle_intel.main", reason="subtitle-intel not installed")
pytest.importorskip("media_policy_engine.main", reason="media-policy-engine not installed")
pytest.importorskip("subtitle_worker.main", reason="subtitle-worker not installed")
pytest.importorskip("transcode_worker.main", reason="transcode-worker not installed")

from catalog_api.main import app as catalog_app                      # noqa: E402
from catalog_api.store import store as _catalog_store                # noqa: E402
from media_policy_engine.main import _evaluator, app as policy_app  # noqa: E402
from starlette.testclient import TestClient                          # noqa: E402
from subtitle_intel.main import app as subtitle_app                  # noqa: E402
from subtitle_worker.main import app as sw_app                       # noqa: E402
from transcode_worker.main import app as tw_app                      # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent.parent / "services" / "subtitle-intel" / "tests" / "fixtures"

_MEDIAINFO_JAV = {
    "media": {
        "@ref": "/fake/SSIS-001.mkv",
        "track": [
            {"@type": "General", "Format": "Matroska"},
            {"@type": "Video", "Format": "AVC", "Language": "ja"},
            {"@type": "Audio", "Format": "AAC", "Language": "ja", "Channels": "2"},
            {"@type": "Text", "Format": "UTF-8", "Language": "ja",
             "Title": "Japanese", "Default": "Yes", "Forced": "No"},
        ],
    }
}

_MEDIAINFO_UNKNOWN_LANG = {
    "media": {
        "@ref": "/fake/mystery.mkv",
        "track": [
            {"@type": "General", "Format": "Matroska"},
            {"@type": "Video", "Format": "AVC"},
            {"@type": "Audio", "Format": "AAC"},
            # Subtitle with no language tag → detected_language="unknown", confidence=0.0
            {"@type": "Text", "Format": "UTF-8",
             "Title": "Unknown", "Default": "Yes", "Forced": "No"},
        ],
    }
}


@pytest.fixture(autouse=True)
def _reset_catalog_store():
    """Wipe the in-memory catalog store before each test."""
    _catalog_store._items.clear()
    _catalog_store._arr_locks.clear()
    _catalog_store._review_queue.clear()
    yield
    _catalog_store._items.clear()
    _catalog_store._arr_locks.clear()
    _catalog_store._review_queue.clear()


@pytest.fixture(autouse=True)
def _reset_policy_cache():
    """Clear the policy evaluator LRU cache so POLICY_DIR changes take effect."""
    _evaluator.cache_clear()
    yield
    _evaluator.cache_clear()


# ---------------------------------------------------------------------------
# Helper: build MediaFacts from ScanResult (mirrors n8n Build MediaFacts node)
# ---------------------------------------------------------------------------

def _build_media_facts(scan_result: dict, domain: str) -> dict:
    """
    Construct a MediaFacts dict from subtitle-intel ScanResult and domain.
    Mirrors the logic in the n8n 'Build MediaFacts' Code node.
    """
    subtitle_tracks = [
        {
            "track_index": t["track_index"],
            "language": t["detected_language"],
            "confidence": t["confidence"],
            "track_type": t["track_type"],
        }
        for t in scan_result.get("subtitle_tracks", [])
    ]

    _non_english = {
        "jav_adult", "international_live_action_movie", "international_live_action_tv",
        "international_animated_movie", "international_animated_tv",
        "anime_movie", "anime_series",
    }
    detected_original_language = "ja" if domain in _non_english else "en"

    return {
        "domain": domain,
        "file_path": scan_result.get("file_path", "/fake/path.mkv"),
        "detected_original_language": detected_original_language,
        "video": {"codec": "h264", "is_remux": False, "is_hdr": False, "bitrate_mbps": None},
        "audio_tracks": [],
        "subtitle_tracks": subtitle_tracks,
        "catalog_tags": [],
    }


# ---------------------------------------------------------------------------
# Tests: dispatched path (no review required)
# ---------------------------------------------------------------------------

def test_chain_review_gate_jav_adult(tmp_path):
    """
    jav_adult domain always requires human review before transcode
    (adult policy: skip_low_value_retranscodes → send_to_review).
    Verify the review gate path fires: review queue entry created, state→review,
    no worker dispatch.
    """
    with (
        TestClient(catalog_app) as catalog,
        TestClient(subtitle_app) as subtitle,
        TestClient(policy_app) as policy,
    ):
        # Step 1: register
        r = catalog.post("/items", json={
            "title": "SSIS-001",
            "domain": "jav_adult",
            "file_path": "/fake/SSIS-001.mkv",
            "state": "inbox",
        })
        assert r.status_code == 201, r.text
        item_id = r.json()["id"]

        # Step 2: scan
        r = subtitle.post("/scan", json={
            "file_path": "/fake/SSIS-001.mkv",
            "mediainfo_json": _MEDIAINFO_JAV,
        })
        assert r.status_code == 200, r.text
        scan = r.json()
        assert scan["status"] == "ok"
        assert any(t["detected_language"] == "ja" for t in scan["subtitle_tracks"])

        # Step 3: build MediaFacts
        facts = _build_media_facts(scan, domain="jav_adult")
        assert facts["subtitle_tracks"][0]["language"] == "ja"

        # Step 4: evaluate policy — adult domain always requires review before transcode
        r = policy.post("/evaluate", json=facts)
        assert r.status_code == 200, r.text
        evaluation = r.json()
        assert evaluation["domain"] == "jav_adult"
        assert evaluation["requires_review"], "adult policy should require review"
        action_kinds = [a["kind"] for a in evaluation["actions"]]
        assert "generate_english_subtitles" in action_kinds
        assert "send_to_review" in action_kinds

        # Step 5: review gate — create queue entry, transition state → review
        notes = "; ".join(evaluation.get("evaluation_notes", []))
        r = catalog.post("/review-queue", json={
            "item_id": item_id,
            "reason": f"Policy evaluation requires review. Notes: {notes}",
        })
        assert r.status_code == 201
        assert r.json()["item_id"] == item_id

        r = catalog.patch(f"/items/{item_id}", json={"state": "review"})
        assert r.json()["state"] == "review"

        # Confirm item is in the review queue (no worker was dispatched)
        r = catalog.get("/review-queue")
        assert any(e["item_id"] == item_id for e in r.json())


def test_chain_dispatched_domestic_h264(tmp_path):
    """
    domestic_live_action_movie, h264, no subtitles:
      policy → flag_for_transcode, generate_english_subtitles (or similar)
      transcode-worker → status=skipped (dry_run=True)
      catalog state → active
    """
    mediainfo = {
        "media": {
            "@ref": "/fake/Movie.2023.mkv",
            "track": [
                {"@type": "General", "Format": "Matroska"},
                {"@type": "Video", "Format": "AVC", "Language": "en"},
                {"@type": "Audio", "Format": "TrueHD", "Language": "en", "Channels": "8"},
            ],
        }
    }

    with (
        TestClient(catalog_app) as catalog,
        TestClient(subtitle_app) as subtitle,
        TestClient(policy_app) as policy,
        TestClient(tw_app) as tw,
    ):
        r = catalog.post("/items", json={
            "title": "Movie 2023",
            "domain": "domestic_live_action_movie",
            "file_path": "/fake/Movie.2023.mkv",
            "state": "inbox",
        })
        assert r.status_code == 201
        item_id = r.json()["id"]

        r = subtitle.post("/scan", json={
            "file_path": "/fake/Movie.2023.mkv",
            "mediainfo_json": mediainfo,
        })
        assert r.status_code == 200
        scan = r.json()

        facts = _build_media_facts(scan, domain="domestic_live_action_movie")
        r = policy.post("/evaluate", json=facts)
        assert r.status_code == 200
        evaluation = r.json()

        # h264 input should trigger transcode evaluation
        action_kinds = [a["kind"] for a in evaluation["actions"]]
        assert "flag_for_transcode" in action_kinds or "skip_transcode" in action_kinds

        # dispatch transcode worker dry_run
        r = tw.post("/jobs", json={
            "item_id": item_id,
            "file_path": "/fake/Movie.2023.mkv",
            "output_path": "/fake/Movie.2023.hevc.mkv",
            "target_codec": "hevc",
            "container": "mkv",
            "allow_nvenc": False,
            "copy_streams": True,
            "dry_run": True,
        })
        assert r.status_code in (200, 201), r.text
        job_result = r.json()
        assert job_result["status"] == "skipped"
        assert job_result["codec_used"] == "libx265"

        r = catalog.patch(f"/items/{item_id}", json={"state": "active"})
        assert r.json()["state"] == "active"


# ---------------------------------------------------------------------------
# Tests: review gate path
# ---------------------------------------------------------------------------

def test_chain_review_gate_unknown_language():
    """
    Unknown subtitle language (confidence=0.0):
      policy → requires_review=True
      catalog → item queued for review, state=review
      no worker dispatch
    """
    with (
        TestClient(catalog_app) as catalog,
        TestClient(subtitle_app) as subtitle,
        TestClient(policy_app) as policy,
    ):
        r = catalog.post("/items", json={
            "title": "Mystery",
            "domain": "domestic_live_action_movie",
            "file_path": "/fake/mystery.mkv",
            "state": "inbox",
        })
        assert r.status_code == 201
        item_id = r.json()["id"]

        r = subtitle.post("/scan", json={
            "file_path": "/fake/mystery.mkv",
            "mediainfo_json": _MEDIAINFO_UNKNOWN_LANG,
        })
        assert r.status_code == 200
        scan = r.json()
        # Unknown language → confidence=0.0
        assert any(t["detected_language"] == "unknown" for t in scan["subtitle_tracks"])

        facts = _build_media_facts(scan, domain="domestic_live_action_movie")
        r = policy.post("/evaluate", json=facts)
        assert r.status_code == 200
        evaluation = r.json()
        assert evaluation["requires_review"]

        # Create review queue entry
        notes = "; ".join(evaluation.get("evaluation_notes", []))
        r = catalog.post("/review-queue", json={
            "item_id": item_id,
            "reason": f"Policy evaluation requires review. Notes: {notes}",
        })
        assert r.status_code == 201
        entry = r.json()
        assert entry["item_id"] == item_id
        assert not entry["resolved"]

        # Transition state → review
        r = catalog.patch(f"/items/{item_id}", json={"state": "review"})
        assert r.json()["state"] == "review"

        # Confirm item is in review queue
        r = catalog.get("/review-queue")
        queue = r.json()
        assert any(e["item_id"] == item_id for e in queue)


# ---------------------------------------------------------------------------
# Tests: locked item bypass
# ---------------------------------------------------------------------------

def test_chain_locked_item_no_mutations():
    """
    Item tagged 'manual-source':
      policy → all actions are skip_transcode / keep_stream
      no generate or transcode actions dispatched
    """
    with (
        TestClient(catalog_app) as catalog,
        TestClient(policy_app) as policy,
    ):
        r = catalog.post("/items", json={
            "title": "Locked Movie",
            "domain": "domestic_live_action_movie",
            "file_path": "/fake/locked.mkv",
            "state": "inbox",
            "tags": ["manual-source"],
        })
        assert r.status_code == 201
        item_id = r.json()["id"]

        facts = {
            "domain": "domestic_live_action_movie",
            "file_path": "/fake/locked.mkv",
            "detected_original_language": "en",
            "video": {"codec": "h264", "is_remux": False, "is_hdr": False},
            "audio_tracks": [],
            "subtitle_tracks": [],
            "catalog_tags": ["manual-source"],
        }
        r = policy.post("/evaluate", json=facts)
        assert r.status_code == 200
        evaluation = r.json()

        mutation_actions = {"generate_english_subtitles", "flag_for_transcode", "remove_stream"}
        dispatched_kinds = {a["kind"] for a in evaluation["actions"]}
        assert not (dispatched_kinds & mutation_actions), (
            f"locked item should not produce mutation actions; got {dispatched_kinds}"
        )
