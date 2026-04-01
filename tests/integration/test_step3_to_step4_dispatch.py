"""Integration tests: Step 3 policy decision → Step 4 audio extraction.

Exercises the full state transition chain using an in-process SQLite DB and a
mocked HTTP endpoint.  No subtitle worker process is required.

State chain under test:
  needs_subtitle_review
    → (Step 3: no English subtitle)  → needs_subtitle_generation
    → (Step 4 audio extraction)      → audio_extracted
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from services.media_brain.step3_subtitle_policy import run_step3_subtitle_policy
from services.media_brain.step4_audio_extraction import SOURCE_STATE, SUCCESS_STATE as EXTRACTED_STATE


# ---------------------------------------------------------------------------
# DB setup helpers
# ---------------------------------------------------------------------------

def _init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables needed by Steps 2, 3, and 4."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS media_records (
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
        "CREATE INDEX IF NOT EXISTS idx_media_records_state ON media_records(state)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subtitle_track_language_labels (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id            TEXT NOT NULL,
            track_key           TEXT NOT NULL,
            track_source        TEXT NOT NULL DEFAULT 'embedded',
            detected_language   TEXT,
            detected_confidence REAL,
            detector_engine     TEXT,
            review_status       TEXT NOT NULL,
            sample_text         TEXT,
            labeled_at          TEXT NOT NULL DEFAULT '2024-01-01T00:00:00+00:00'
        )
        """
    )


def _insert_media(
    conn: sqlite3.Connection,
    media_id: str,
    path: str,
    subtitle_tracks: list | None = None,
) -> None:
    subtitle_json = json.dumps(subtitle_tracks or [])
    conn.execute(
        """
        INSERT INTO media_records
            (media_id, path, file_name, extension, size_bytes,
             ffprobe_json, video_tracks_json, audio_tracks_json,
             subtitle_tracks_json, sidecar_subtitles_json, state, scanned_at)
        VALUES (?, ?, ?, ?, ?, '{}', '[]', '[]', ?, '[]', 'needs_subtitle_review',
                '2024-01-01T00:00:00+00:00')
        """,
        (media_id, path, path.split("/")[-1], ".mkv", 500_000, subtitle_json),
    )


def _insert_label(
    conn: sqlite3.Connection,
    media_id: str,
    track_key: str,
    language: str,
    review_status: str,
) -> None:
    conn.execute(
        """
        INSERT INTO subtitle_track_language_labels
            (media_id, track_key, detected_language, review_status)
        VALUES (?, ?, ?, ?)
        """,
        (media_id, track_key, language, review_status),
    )


def _get_state(conn: sqlite3.Connection, media_id: str) -> str:
    row = conn.execute(
        "SELECT state FROM media_records WHERE media_id = ?", (media_id,)
    ).fetchone()
    assert row is not None, f"no record for media_id={media_id!r}"
    return row[0]


def _fake_http_success(url: str, payload: dict) -> dict:
    return {"job_id": payload["job_id"], "item_id": None, "status": "complete", "job_type": "extract_audio"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_english_subtitle_dispatches_job(tmp_path: Path) -> None:
    """Full chain: no English subtitle → Step 3 writes needs_subtitle_generation
    → dispatch_after=True → state = audio_extracted."""
    db_path = tmp_path / "brain.db"
    media_id = "chain_test_001"

    with sqlite3.connect(db_path) as conn:
        _init_schema(conn)
        # File has a Japanese subtitle only — no English.
        _insert_media(conn, media_id, "/mnt/itv/adult/jpn_only.mkv")
        _insert_label(conn, media_id, "embedded:0", "ja", "detected")
        conn.commit()

    posted: list[dict] = []

    def capture(url: str, payload: dict) -> dict:
        posted.append(payload)
        return _fake_http_success(url, payload)

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=capture):
        summary = run_step3_subtitle_policy(
            db_path=db_path,
            dispatch_after=True,
            worker_url="http://mock-worker:8100",
        )

    assert summary.needs_subtitle_generation == 1
    assert summary.has_english_subtitle == 0
    assert len(posted) == 1, "exactly one job must be POSTed"
    assert posted[0]["media_id"] == media_id
    assert posted[0]["job_type"] == "extract_audio"

    with sqlite3.connect(db_path) as conn:
        assert _get_state(conn, media_id) == EXTRACTED_STATE


def test_english_subtitle_no_dispatch(tmp_path: Path) -> None:
    """English subtitle confirmed → Step 3 writes needs_audio_review → no dispatch."""
    db_path = tmp_path / "brain.db"
    media_id = "chain_test_002"

    with sqlite3.connect(db_path) as conn:
        _init_schema(conn)
        _insert_media(conn, media_id, "/mnt/itv/adult/eng_sub.mkv")
        _insert_label(conn, media_id, "embedded:0", "en", "trusted_existing")
        conn.commit()

    posted: list[dict] = []

    def capture(url: str, payload: dict) -> dict:
        posted.append(payload)
        return _fake_http_success(url, payload)

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=capture):
        summary = run_step3_subtitle_policy(
            db_path=db_path,
            dispatch_after=True,
            worker_url="http://mock-worker:8100",
        )

    assert summary.has_english_subtitle == 1
    assert summary.needs_subtitle_generation == 0
    assert len(posted) == 0, "no job must be dispatched when English subtitle exists"

    with sqlite3.connect(db_path) as conn:
        assert _get_state(conn, media_id) == "needs_audio_review"


def test_uncertain_english_label_routes_to_manual_review(tmp_path: Path) -> None:
    """A label with review_status='uncertain' must route to needs_manual_subtitle_review.
    It must NOT be dispatched to the subtitle worker.
    """
    db_path = tmp_path / "brain.db"
    media_id = "chain_test_003"

    with sqlite3.connect(db_path) as conn:
        _init_schema(conn)
        _insert_media(conn, media_id, "/mnt/itv/adult/uncertain.mkv")
        # English detected but confidence was below threshold → review_status=uncertain
        _insert_label(conn, media_id, "embedded:0", "en", "uncertain")
        conn.commit()

    posted: list[dict] = []

    def capture(url: str, payload: dict) -> dict:
        posted.append(payload)
        return _fake_http_success(url, payload)

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=capture):
        summary = run_step3_subtitle_policy(
            db_path=db_path,
            dispatch_after=True,
            worker_url="http://mock-worker:8100",
        )

    assert summary.needs_manual_subtitle_review == 1
    assert summary.needs_subtitle_generation == 0
    assert summary.has_english_subtitle == 0
    assert len(posted) == 0, "uncertain records must not be dispatched to the worker"

    with sqlite3.connect(db_path) as conn:
        assert _get_state(conn, media_id) == "needs_manual_subtitle_review"


def test_full_chain_is_idempotent(tmp_path: Path) -> None:
    """Running Step 3 + dispatch twice on the same DB must dispatch each record
    exactly once.  The second run finds no records in needs_subtitle_generation
    (they are already subtitle_generation_queued) and makes no additional POSTs.
    """
    db_path = tmp_path / "brain.db"
    media_id = "chain_test_004"

    with sqlite3.connect(db_path) as conn:
        _init_schema(conn)
        _insert_media(conn, media_id, "/mnt/itv/adult/idempotent.mkv")
        _insert_label(conn, media_id, "embedded:0", "ja", "detected")
        conn.commit()

    post_count = {"n": 0}

    def count_posts(url: str, payload: dict) -> dict:
        post_count["n"] += 1
        return _fake_http_success(url, payload)

    with patch("services.media_brain.step4_audio_extraction._http_post", side_effect=count_posts):
        # First run: Step 3 evaluates, step4 extracts audio.
        run_step3_subtitle_policy(
            db_path=db_path,
            dispatch_after=True,
            worker_url="http://mock-worker:8100",
        )
        # Second run: Step 3 finds no records in needs_subtitle_review (already advanced).
        run_step3_subtitle_policy(
            db_path=db_path,
            dispatch_after=True,
            worker_url="http://mock-worker:8100",
        )

    assert post_count["n"] == 1, (
        f"job must be dispatched exactly once; got {post_count['n']} POST(s)"
    )

    with sqlite3.connect(db_path) as conn:
        assert _get_state(conn, media_id) == EXTRACTED_STATE


def test_no_subtitle_labels_routes_to_generation(tmp_path: Path) -> None:
    """A file with no subtitle tracks and no language labels must be routed to
    needs_subtitle_generation (generate from scratch)."""
    db_path = tmp_path / "brain.db"
    media_id = "chain_test_005"

    with sqlite3.connect(db_path) as conn:
        _init_schema(conn)
        _insert_media(conn, media_id, "/mnt/itv/adult/no_subs.mkv")
        # No labels inserted — clean file with no subtitles at all.
        conn.commit()

    with patch(
        "services.media_brain.step4_audio_extraction._http_post",
        side_effect=_fake_http_success,
    ):
        summary = run_step3_subtitle_policy(
            db_path=db_path,
            dispatch_after=True,
            worker_url="http://mock-worker:8100",
        )

    assert summary.needs_subtitle_generation == 1

    with sqlite3.connect(db_path) as conn:
        assert _get_state(conn, media_id) == EXTRACTED_STATE
