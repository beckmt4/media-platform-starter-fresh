"""Unit tests for services/media_brain/step4_audio_extraction.py."""

from __future__ import annotations

import json
import sqlite3
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from services.media_brain.step4_audio_extraction import (
    FAILED_STATE,
    SOURCE_STATE,
    SUCCESS_STATE,
    ExtractionSummary,
    build_extract_audio_job,
    run_step4_audio_extraction,
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
            ("abc123def456", "/mnt/itv/adult/movie.mkv", "movie.mkv", ".mkv", 1_000_000, state),
        )
        conn.commit()
    return db_path


def _fake_success(url: str, payload: dict) -> dict:
    return {"job_id": payload["job_id"], "item_id": None, "status": "complete", "job_type": "extract_audio"}


def _fake_worker_failed(url: str, payload: dict) -> dict:
    return {"job_id": payload["job_id"], "status": "failed", "error_message": "ffmpeg not found"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_extraction_posts_extract_audio_job_type(tmp_path: Path) -> None:
    """Dispatcher must POST job_type=extract_audio (not generate)."""
    db_path = _make_db(tmp_path)
    posted: list[dict] = []

    def capture(url: str, payload: dict) -> dict:
        posted.append(payload)
        return _fake_success(url, payload)

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=capture):
        run_step4_audio_extraction(db_path=db_path, worker_url="http://worker:8100")

    assert len(posted) == 1
    assert posted[0]["job_type"] == "extract_audio"
    assert posted[0]["media_id"] == "abc123def456"
    assert posted[0]["file_path"] == "/mnt/itv/adult/movie.mkv"
    assert posted[0]["item_id"] is None


def test_extraction_advances_state_to_audio_extracted(tmp_path: Path) -> None:
    """Successful extraction must advance state to audio_extracted."""
    db_path = _make_db(tmp_path)

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=_fake_success):
        result = run_step4_audio_extraction(db_path=db_path, worker_url="http://worker:8100")

    assert result.extracted == 1
    assert result.failed == 0

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT state FROM media_records WHERE media_id = 'abc123def456'").fetchone()
    assert row[0] == SUCCESS_STATE


def test_extraction_writes_failed_state_on_http_error(tmp_path: Path) -> None:
    """Network failure must write state=failed (not leave state unchanged)."""
    db_path = _make_db(tmp_path)

    def always_fail(url: str, payload: dict) -> dict:
        raise urllib.error.URLError("connection refused")

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=always_fail):
        result = run_step4_audio_extraction(db_path=db_path, worker_url="http://worker:8100")

    assert result.failed == 1
    assert result.extracted == 0

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT state FROM media_records WHERE media_id = 'abc123def456'").fetchone()
    assert row[0] == FAILED_STATE


def test_extraction_writes_failed_state_on_worker_failure(tmp_path: Path) -> None:
    """Worker returning status=failed must also write state=failed in the DB."""
    db_path = _make_db(tmp_path)

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=_fake_worker_failed):
        result = run_step4_audio_extraction(db_path=db_path, worker_url="http://worker:8100")

    assert result.failed == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT state FROM media_records WHERE media_id = 'abc123def456'").fetchone()
    assert row[0] == FAILED_STATE


def test_extraction_skips_already_extracted_records(tmp_path: Path) -> None:
    """Records already in audio_extracted must not be re-dispatched."""
    db_path = _make_db(tmp_path, state=SUCCESS_STATE)
    posted: list[dict] = []

    def capture(url: str, payload: dict) -> dict:
        posted.append(payload)
        return _fake_success(url, payload)

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=capture):
        result = run_step4_audio_extraction(db_path=db_path, worker_url="http://worker:8100")

    assert len(posted) == 0
    assert result.extracted == 0
    assert result.failed == 0


def test_extraction_dry_run_makes_no_http_calls(tmp_path: Path) -> None:
    """dry_run=True must not issue HTTP calls or change state."""
    db_path = _make_db(tmp_path)
    posted: list[dict] = []

    def capture(url: str, payload: dict) -> dict:
        posted.append(payload)
        return _fake_success(url, payload)

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=capture):
        result = run_step4_audio_extraction(db_path=db_path, worker_url="http://worker:8100", dry_run=True)

    assert len(posted) == 0
    assert result.skipped == 1
    assert result.extracted == 0

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT state FROM media_records WHERE media_id = 'abc123def456'").fetchone()
    assert row[0] == SOURCE_STATE


def test_extraction_writes_state_transitions(tmp_path: Path) -> None:
    """A successful extraction must write a state_transitions row."""
    db_path = _make_db(tmp_path)

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=_fake_success):
        run_step4_audio_extraction(db_path=db_path, worker_url="http://worker:8100")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM state_transitions").fetchall()

    assert len(rows) == 1
    assert rows[0]["from_state"] == SOURCE_STATE
    assert rows[0]["to_state"] == SUCCESS_STATE
    assert rows[0]["reason"] == "extract_audio_complete"


def test_extraction_writes_processing_job_on_success(tmp_path: Path) -> None:
    """A successful dispatch must create a processing_jobs row with status=complete."""
    db_path = _make_db(tmp_path)

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=_fake_success):
        run_step4_audio_extraction(db_path=db_path, worker_url="http://worker:8100")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM processing_jobs WHERE media_id = 'abc123def456'").fetchone()

    assert row is not None
    assert row["status"] == "complete"
    assert row["job_type"] == "extract_audio"
    assert row["completed_at"] is not None


def test_build_extract_audio_job_schema() -> None:
    """build_extract_audio_job must produce a JSON-serializable payload with correct fields."""
    job = build_extract_audio_job("deadbeef", "/mnt/itv/adult/test.mkv")
    assert job["job_type"] == "extract_audio"
    assert job["media_id"] == "deadbeef"
    assert job["file_path"] == "/mnt/itv/adult/test.mkv"
    assert job["item_id"] is None
    assert job["dry_run"] is False
    assert "job_id" in job
    json.dumps(job)  # must not raise
