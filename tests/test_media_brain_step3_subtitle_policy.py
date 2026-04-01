import json
import sqlite3
from pathlib import Path

import pytest

from services.media_brain.step3_subtitle_policy import (
    evaluate_subtitle_policy,
    fetch_media_for_policy,
    fetch_track_labels,
    init_step3_db,
    run_step3_subtitle_policy,
)


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def create_step1_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS media_records (
            media_id               TEXT PRIMARY KEY,
            path                   TEXT NOT NULL,
            file_name              TEXT NOT NULL,
            subtitle_tracks_json   TEXT NOT NULL,
            sidecar_subtitles_json TEXT NOT NULL,
            state                  TEXT NOT NULL
        )
        """
    )


def create_step2_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS subtitle_track_language_labels (
            track_key           TEXT PRIMARY KEY,
            media_id            TEXT NOT NULL,
            media_path          TEXT NOT NULL,
            track_source        TEXT NOT NULL,
            stream_index        INTEGER,
            sidecar_path        TEXT,
            codec_name          TEXT,
            existing_language_tag TEXT,
            normalized_language_tag TEXT,
            sample_text         TEXT,
            sample_char_count   INTEGER NOT NULL DEFAULT 0,
            detected_language   TEXT,
            detected_confidence REAL,
            detector_engine     TEXT,
            review_status       TEXT NOT NULL,
            ocr_state           TEXT,
            scanned_at          TEXT NOT NULL
        )
        """
    )


def insert_media_record(
    connection: sqlite3.Connection,
    *,
    media_id: str,
    path: str = "/mnt/itv/adult/sample.mkv",
    subtitle_tracks: list | None = None,
    sidecars: list | None = None,
    state: str = "needs_subtitle_review",
) -> None:
    connection.execute(
        """
        INSERT INTO media_records (media_id, path, file_name, subtitle_tracks_json, sidecar_subtitles_json, state)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            media_id,
            path,
            Path(path).name,
            json.dumps(subtitle_tracks or []),
            json.dumps(sidecars or []),
            state,
        ),
    )


def insert_track_label(
    connection: sqlite3.Connection,
    *,
    track_key: str,
    media_id: str,
    detected_language: str | None,
    review_status: str,
    track_source: str = "embedded",
    detected_confidence: float | None = 1.0,
) -> None:
    connection.execute(
        """
        INSERT INTO subtitle_track_language_labels (
            track_key, media_id, media_path, track_source,
            detected_language, detected_confidence, review_status, scanned_at,
            sample_char_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, '2026-01-01T00:00:00+00:00', 0)
        """,
        (
            track_key,
            media_id,
            "/mnt/itv/adult/sample.mkv",
            track_source,
            detected_language,
            detected_confidence,
            review_status,
        ),
    )


# ---------------------------------------------------------------------------
# Unit tests for the pure decision function
# ---------------------------------------------------------------------------

def _make_label(
    track_key: str,
    detected_language: str | None,
    review_status: str,
) -> dict:
    return {
        "track_key": track_key,
        "track_source": "embedded",
        "detected_language": detected_language,
        "review_status": review_status,
    }


def test_evaluate_policy_english_trusted_existing() -> None:
    labels = [_make_label("mid:embedded:2", "en", "trusted_existing")]
    decision = evaluate_subtitle_policy("mid", labels, [{"index": 2}], [])
    assert decision.policy_decision == "has_english_subtitle"
    assert decision.next_state == "needs_audio_review"
    assert decision.english_track_key == "mid:embedded:2"


def test_evaluate_policy_english_detected() -> None:
    labels = [_make_label("mid:embedded:2", "en", "detected")]
    decision = evaluate_subtitle_policy("mid", labels, [{"index": 2}], [])
    assert decision.policy_decision == "has_english_subtitle"
    assert decision.next_state == "needs_audio_review"


def test_evaluate_policy_uncertain_english_does_not_qualify() -> None:
    """A track with review_status=uncertain must NOT be accepted as English."""
    labels = [_make_label("mid:embedded:2", "en", "uncertain")]
    decision = evaluate_subtitle_policy("mid", labels, [{"index": 2}], [])
    assert decision.policy_decision == "needs_subtitle_generation"
    assert decision.next_state == "needs_subtitle_generation"


def test_evaluate_policy_ocr_does_not_qualify() -> None:
    labels = [_make_label("mid:embedded:2", "en", "needs_ocr")]
    decision = evaluate_subtitle_policy("mid", labels, [{"index": 2}], [])
    assert decision.policy_decision == "needs_subtitle_generation"


def test_evaluate_policy_non_english_subtitle_queues_generation() -> None:
    labels = [_make_label("mid:embedded:2", "ja", "trusted_existing")]
    subtitle_tracks = [{"index": 2}]
    decision = evaluate_subtitle_policy("mid", labels, subtitle_tracks, [])
    assert decision.policy_decision == "needs_subtitle_generation"
    assert decision.has_any_subtitle is True
    assert decision.subtitle_track_count == 1


def test_evaluate_policy_no_subtitles_at_all() -> None:
    decision = evaluate_subtitle_policy("mid", [], [], [])
    assert decision.policy_decision == "needs_subtitle_generation"
    assert decision.has_any_subtitle is False
    assert decision.subtitle_track_count == 0
    assert decision.sidecar_count == 0


def test_evaluate_policy_sidecar_only_no_english() -> None:
    sidecars = [{"path": "/mnt/itv/adult/movie.ja.srt", "filename": "movie.ja.srt"}]
    labels = [_make_label("mid:sidecar:/mnt/itv/adult/movie.ja.srt", "ja", "trusted_existing")]
    decision = evaluate_subtitle_policy("mid", labels, [], sidecars)
    assert decision.policy_decision == "needs_subtitle_generation"
    assert decision.has_any_subtitle is True
    assert decision.sidecar_count == 1


def test_evaluate_policy_english_sidecar_qualifies() -> None:
    sidecars = [{"path": "/mnt/itv/adult/movie.en.srt", "filename": "movie.en.srt"}]
    labels = [_make_label("mid:sidecar:/mnt/itv/adult/movie.en.srt", "en", "trusted_existing")]
    decision = evaluate_subtitle_policy("mid", labels, [], sidecars)
    assert decision.policy_decision == "has_english_subtitle"
    assert decision.next_state == "needs_audio_review"


def test_evaluate_policy_first_english_track_wins() -> None:
    labels = [
        _make_label("mid:embedded:1", "ja", "trusted_existing"),
        _make_label("mid:embedded:2", "en", "trusted_existing"),
        _make_label("mid:embedded:3", "en", "trusted_existing"),
    ]
    decision = evaluate_subtitle_policy("mid", labels, [{}, {}, {}], [])
    assert decision.english_track_key == "mid:embedded:2"


# ---------------------------------------------------------------------------
# Integration tests — full DB roundtrip
# ---------------------------------------------------------------------------

def test_run_step3_has_english_subtitle_advances_state(tmp_path: Path) -> None:
    db_path = tmp_path / "media_brain.db"

    with sqlite3.connect(db_path) as conn:
        create_step1_table(conn)
        create_step2_table(conn)
        init_step3_db(conn)
        insert_media_record(
            conn,
            media_id="media-1",
            subtitle_tracks=[{"index": 2, "codec_name": "subrip"}],
        )
        insert_track_label(
            conn,
            track_key="media-1:embedded:2",
            media_id="media-1",
            detected_language="en",
            review_status="trusted_existing",
        )
        conn.commit()

    summary = run_step3_subtitle_policy(db_path=db_path)

    assert summary.processed_files == 1
    assert summary.has_english_subtitle == 1
    assert summary.needs_subtitle_generation == 0
    assert summary.failed_files == 0

    with sqlite3.connect(db_path) as conn:
        state_row = conn.execute(
            "SELECT state FROM media_records WHERE media_id = ?", ("media-1",)
        ).fetchone()
        decision_row = conn.execute(
            "SELECT policy_decision, english_track_key, has_any_subtitle FROM step3_policy_decisions WHERE media_id = ?",
            ("media-1",),
        ).fetchone()

    assert state_row[0] == "needs_audio_review"
    assert decision_row[0] == "has_english_subtitle"
    assert decision_row[1] == "media-1:embedded:2"
    assert decision_row[2] == 1


def test_run_step3_no_subtitle_queues_generation(tmp_path: Path) -> None:
    db_path = tmp_path / "media_brain.db"

    with sqlite3.connect(db_path) as conn:
        create_step1_table(conn)
        create_step2_table(conn)
        init_step3_db(conn)
        insert_media_record(conn, media_id="media-2", subtitle_tracks=[], sidecars=[])
        conn.commit()

    summary = run_step3_subtitle_policy(db_path=db_path)

    assert summary.needs_subtitle_generation == 1

    with sqlite3.connect(db_path) as conn:
        state_row = conn.execute(
            "SELECT state FROM media_records WHERE media_id = ?", ("media-2",)
        ).fetchone()
        decision_row = conn.execute(
            "SELECT policy_decision, has_any_subtitle, sidecar_count FROM step3_policy_decisions WHERE media_id = ?",
            ("media-2",),
        ).fetchone()

    assert state_row[0] == "needs_subtitle_generation"
    assert decision_row[0] == "needs_subtitle_generation"
    assert decision_row[1] == 0
    assert decision_row[2] == 0


def test_run_step3_non_english_subtitle_queues_generation(tmp_path: Path) -> None:
    db_path = tmp_path / "media_brain.db"

    with sqlite3.connect(db_path) as conn:
        create_step1_table(conn)
        create_step2_table(conn)
        init_step3_db(conn)
        insert_media_record(
            conn,
            media_id="media-3",
            subtitle_tracks=[{"index": 1, "codec_name": "subrip"}],
        )
        insert_track_label(
            conn,
            track_key="media-3:embedded:1",
            media_id="media-3",
            detected_language="ja",
            review_status="trusted_existing",
        )
        conn.commit()

    summary = run_step3_subtitle_policy(db_path=db_path)

    assert summary.needs_subtitle_generation == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT policy_decision, has_any_subtitle, subtitle_track_count FROM step3_policy_decisions WHERE media_id = ?",
            ("media-3",),
        ).fetchone()

    assert row[0] == "needs_subtitle_generation"
    assert row[1] == 1   # there IS a subtitle, just not English
    assert row[2] == 1


def test_run_step3_uncertain_english_queues_generation(tmp_path: Path) -> None:
    """Uncertain English must NOT advance to needs_audio_review."""
    db_path = tmp_path / "media_brain.db"

    with sqlite3.connect(db_path) as conn:
        create_step1_table(conn)
        create_step2_table(conn)
        init_step3_db(conn)
        insert_media_record(
            conn,
            media_id="media-4",
            subtitle_tracks=[{"index": 1}],
        )
        insert_track_label(
            conn,
            track_key="media-4:embedded:1",
            media_id="media-4",
            detected_language="en",
            review_status="uncertain",
            detected_confidence=0.65,
        )
        conn.commit()

    summary = run_step3_subtitle_policy(db_path=db_path)

    assert summary.needs_subtitle_generation == 1
    assert summary.has_english_subtitle == 0


def test_run_step3_only_processes_needs_subtitle_review_state(tmp_path: Path) -> None:
    """Files in other states must be ignored."""
    db_path = tmp_path / "media_brain.db"

    with sqlite3.connect(db_path) as conn:
        create_step1_table(conn)
        create_step2_table(conn)
        init_step3_db(conn)
        insert_media_record(conn, media_id="active-1", state="active", subtitle_tracks=[])
        insert_media_record(conn, media_id="review-1", state="needs_subtitle_review", subtitle_tracks=[])
        conn.commit()

    summary = run_step3_subtitle_policy(db_path=db_path)

    assert summary.processed_files == 1

    with sqlite3.connect(db_path) as conn:
        untouched = conn.execute(
            "SELECT state FROM media_records WHERE media_id = ?", ("active-1",)
        ).fetchone()

    assert untouched[0] == "active"


def test_run_step3_is_idempotent(tmp_path: Path) -> None:
    """Running Step 3 twice must not double-count or error."""
    db_path = tmp_path / "media_brain.db"

    with sqlite3.connect(db_path) as conn:
        create_step1_table(conn)
        create_step2_table(conn)
        init_step3_db(conn)
        insert_media_record(conn, media_id="media-5", subtitle_tracks=[])
        conn.commit()

    run_step3_subtitle_policy(db_path=db_path)
    summary = run_step3_subtitle_policy(db_path=db_path)

    # Second run finds 0 records in needs_subtitle_review (state was already advanced)
    assert summary.processed_files == 0

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM step3_policy_decisions").fetchone()[0]

    assert count == 1


def test_run_step3_multiple_files_mixed_decisions(tmp_path: Path) -> None:
    db_path = tmp_path / "media_brain.db"

    with sqlite3.connect(db_path) as conn:
        create_step1_table(conn)
        create_step2_table(conn)
        init_step3_db(conn)

        # File A — has English
        insert_media_record(conn, media_id="A", subtitle_tracks=[{"index": 1}])
        insert_track_label(conn, track_key="A:embedded:1", media_id="A", detected_language="en", review_status="detected")

        # File B — Japanese only
        insert_media_record(conn, media_id="B", subtitle_tracks=[{"index": 1}])
        insert_track_label(conn, track_key="B:embedded:1", media_id="B", detected_language="ja", review_status="trusted_existing")

        # File C — no subtitles
        insert_media_record(conn, media_id="C", subtitle_tracks=[])

        conn.commit()

    summary = run_step3_subtitle_policy(db_path=db_path)

    assert summary.processed_files == 3
    assert summary.has_english_subtitle == 1
    assert summary.needs_subtitle_generation == 2
    assert summary.failed_files == 0
