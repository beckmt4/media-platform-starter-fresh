"""Unit tests for services/media_brain/step4_dispatch.py."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from services.media_brain.step4_dispatch import (
    QUEUED_STATE,
    SOURCE_STATE,
    DispatchSummary,
    build_subtitle_job,
    dispatch_pending_jobs,
    fetch_pending_dispatch,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path, state: str = SOURCE_STATE) -> Path:
    """Minimal media_brain.db with one record in the requested state."""
    db_path = tmp_path / "brain.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE media_records (
                media_id              TEXT PRIMARY KEY,
                path                  TEXT NOT NULL UNIQUE,
                file_name             TEXT NOT NULL,
                extension             TEXT NOT NULL,
                size_bytes            INTEGER NOT NULL,
                ffprobe_json          TEXT NOT NULL,
                video_tracks_json     TEXT NOT NULL,
                audio_tracks_json     TEXT NOT NULL,
                subtitle_tracks_json  TEXT NOT NULL,
                sidecar_subtitles_json TEXT NOT NULL,
                state                 TEXT NOT NULL,
                scanned_at            TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO media_records
                (media_id, path, file_name, extension, size_bytes,
                 ffprobe_json, video_tracks_json, audio_tracks_json,
                 subtitle_tracks_json, sidecar_subtitles_json, state, scanned_at)
            VALUES (?, ?, ?, ?, ?, '{}', '[]', '[]', '[]', '[]', ?, '2024-01-01T00:00:00+00:00')
            """,
            (
                "abc123def456",
                "/mnt/itv/adult/movie.mkv",
                "movie.mkv",
                ".mkv",
                1_000_000,
                state,
            ),
        )
        conn.commit()
    return db_path


def _fake_http_success(url: str, payload: dict) -> dict:
    """Simulate a 200 OK from the subtitle worker."""
    return {
        "job_id": payload["job_id"],
        "item_id": None,
        "status": "pending",
        "job_type": "generate",
    }


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_dispatch_posts_correct_job_schema(tmp_path: Path) -> None:
    """Dispatcher must POST a job with the correct media_id, file_path, job_type,
    and item_id=None."""
    db_path = _make_db(tmp_path, state=SOURCE_STATE)
    posted: list[dict] = []

    def capture(url: str, payload: dict) -> dict:
        posted.append(payload)
        return _fake_http_success(url, payload)

    with patch("services.media_brain.step4_dispatch._http_post", side_effect=capture):
        result = dispatch_pending_jobs(db_path=db_path, worker_url="http://worker:8100")

    assert result.dispatched == 1
    assert len(posted) == 1
    job = posted[0]
    assert job["media_id"] == "abc123def456"
    assert job["file_path"] == "/mnt/itv/adult/movie.mkv"
    assert job["job_type"] == "generate"
    assert job["item_id"] is None
    assert job["target_language"] == "en"


def test_dispatch_advances_state_to_queued(tmp_path: Path) -> None:
    """Successful dispatch must advance media_records.state to subtitle_generation_queued."""
    db_path = _make_db(tmp_path, state=SOURCE_STATE)

    with patch(
        "services.media_brain.step4_dispatch._http_post",
        side_effect=_fake_http_success,
    ):
        dispatch_pending_jobs(db_path=db_path, worker_url="http://worker:8100")

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT state FROM media_records WHERE media_id = 'abc123def456'"
        ).fetchone()

    assert row is not None
    assert row[0] == QUEUED_STATE, f"expected {QUEUED_STATE!r}, got {row[0]!r}"


def test_dispatch_skips_already_queued_records(tmp_path: Path) -> None:
    """Records already in subtitle_generation_queued must not be re-dispatched.

    These records are simply not selected by fetch_pending_dispatch, so the
    HTTP mock is never called.
    """
    db_path = _make_db(tmp_path, state=QUEUED_STATE)
    posted: list[dict] = []

    def capture(url: str, payload: dict) -> dict:
        posted.append(payload)
        return _fake_http_success(url, payload)

    with patch("services.media_brain.step4_dispatch._http_post", side_effect=capture):
        result = dispatch_pending_jobs(db_path=db_path, worker_url="http://worker:8100")

    assert len(posted) == 0
    assert result.dispatched == 0
    assert result.failed == 0


def test_dispatch_leaves_state_on_http_failure(tmp_path: Path) -> None:
    """HTTP failure must leave state unchanged so the record is retried on the next run."""
    db_path = _make_db(tmp_path, state=SOURCE_STATE)

    def always_fail(url: str, payload: dict) -> dict:
        raise urllib.error.URLError("connection refused")

    with patch("services.media_brain.step4_dispatch._http_post", side_effect=always_fail):
        result = dispatch_pending_jobs(db_path=db_path, worker_url="http://worker:8100")

    assert result.failed == 1
    assert result.dispatched == 0

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT state FROM media_records WHERE media_id = 'abc123def456'"
        ).fetchone()
    assert row[0] == SOURCE_STATE, "state must remain in SOURCE_STATE after HTTP failure"


def test_dispatch_dry_run_makes_no_http_calls_and_no_state_changes(tmp_path: Path) -> None:
    """dry_run=True must not issue any HTTP calls and must not modify state."""
    db_path = _make_db(tmp_path, state=SOURCE_STATE)
    posted: list[dict] = []

    def capture(url: str, payload: dict) -> dict:
        posted.append(payload)
        return _fake_http_success(url, payload)

    with patch("services.media_brain.step4_dispatch._http_post", side_effect=capture):
        result = dispatch_pending_jobs(
            db_path=db_path,
            worker_url="http://worker:8100",
            dry_run=True,
        )

    assert len(posted) == 0
    assert result.dispatched == 0
    assert result.skipped == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT state FROM media_records WHERE media_id = 'abc123def456'"
        ).fetchone()
    assert row[0] == SOURCE_STATE


def test_dispatch_wav_stem_uses_media_id(tmp_path: Path) -> None:
    """The media_id field in the POSTed job must match the DB record's media_id.

    The subtitle worker uses job.media_id as the WAV filename stem, producing
    [media_id].wav output.  This test guards against the media_id being dropped
    or substituted with job_id.
    """
    db_path = _make_db(tmp_path, state=SOURCE_STATE)
    posted: list[dict] = []

    def capture(url: str, payload: dict) -> dict:
        posted.append(payload)
        return _fake_http_success(url, payload)

    with patch("services.media_brain.step4_dispatch._http_post", side_effect=capture):
        dispatch_pending_jobs(db_path=db_path, worker_url="http://worker:8100")

    assert posted[0]["media_id"] == "abc123def456"


def test_build_subtitle_job_is_json_serializable() -> None:
    """build_subtitle_job must produce a complete, JSON-serializable payload."""
    job = build_subtitle_job("deadbeef01", "/mnt/itv/adult/test.mkv")

    assert job["media_id"] == "deadbeef01"
    assert job["file_path"] == "/mnt/itv/adult/test.mkv"
    assert job["job_type"] == "generate"
    assert job["item_id"] is None
    assert job["target_language"] == "en"
    assert job["dry_run"] is False
    assert "job_id" in job

    # Must not raise — the dispatcher sends this as the HTTP body.
    json.dumps(job)
