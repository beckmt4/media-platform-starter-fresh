import json
import sqlite3
from pathlib import Path

from services.media_brain.step2_subtitle_language import (
    init_step2_db,
    run_step2_subtitle_language_detection,
)


def create_step1_media_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE media_records (
            media_id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            subtitle_tracks_json TEXT NOT NULL,
            sidecar_subtitles_json TEXT NOT NULL,
            state TEXT NOT NULL
        )
        """
    )


def insert_media_record(
    connection: sqlite3.Connection,
    *,
    media_id: str,
    media_path: Path,
    subtitle_tracks: list[dict],
    sidecars: list[dict],
) -> None:
    connection.execute(
        """
        INSERT INTO media_records (media_id, path, file_name, subtitle_tracks_json, sidecar_subtitles_json, state)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            media_id,
            str(media_path),
            media_path.name,
            json.dumps(subtitle_tracks),
            json.dumps(sidecars),
            "needs_subtitle_review",
        ),
    )


def test_trusted_existing_embedded_language_tag_is_preserved(tmp_path: Path) -> None:
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "sample.mkv"
    media_path.write_bytes(b"video")

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id="media-1",
            media_path=media_path,
            subtitle_tracks=[{"index": 2, "codec_name": "subrip", "language": "eng"}],
            sidecars=[],
        )
        connection.commit()

    summary = run_step2_subtitle_language_detection(db_path=db_path, temp_root=tmp_path / "temp")
    assert summary.trusted_existing == 1
    assert summary.detected == 0

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT review_status, detected_language, detector_engine
            FROM subtitle_track_language_labels
            """
        ).fetchone()

    assert row == ("trusted_existing", "en", "existing_tag")


def test_uncertain_sidecar_track_is_queued_for_manual_review(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "movie.mp4"
    media_path.write_bytes(b"video")
    sidecar_path = tmp_path / "movie.srt"
    sidecar_path.write_text("Bonjour tout le monde. Bonjour tout le monde.", encoding="utf-8")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.detect_language_from_text",
        lambda text: ("fr", 0.75, "langdetect"),
    )

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id="media-2",
            media_path=media_path,
            subtitle_tracks=[],
            sidecars=[{"path": str(sidecar_path), "filename": sidecar_path.name, "extension": ".srt"}],
        )
        connection.commit()

    summary = run_step2_subtitle_language_detection(db_path=db_path, temp_root=tmp_path / "temp")
    assert summary.uncertain == 1

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT track_source, review_status, detected_language, detected_confidence
            FROM subtitle_track_language_labels
            """
        ).fetchone()

    assert row == ("sidecar", "uncertain", "fr", 0.75)


def test_image_based_embedded_subtitle_is_flagged_for_ocr(tmp_path: Path) -> None:
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "disc.mkv"
    media_path.write_bytes(b"video")

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id="media-3",
            media_path=media_path,
            subtitle_tracks=[{"index": 3, "codec_name": "hdmv_pgs_subtitle", "language": "und"}],
            sidecars=[],
        )
        connection.commit()

    summary = run_step2_subtitle_language_detection(db_path=db_path, temp_root=tmp_path / "temp")
    assert summary.needs_ocr == 1

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT review_status, ocr_state, codec_name
            FROM subtitle_track_language_labels
            """
        ).fetchone()

    assert row == ("needs_ocr", "future", "hdmv_pgs_subtitle")


def test_confident_embedded_detection_is_stored(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "episode.mkv"
    media_path.write_bytes(b"video")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.extract_embedded_subtitle_text",
        lambda media_path, stream_index, temp_root: "Hola mundo. Hola mundo. Hola mundo.",
    )
    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.detect_language_from_text",
        lambda text: ("es", 0.98, "langdetect"),
    )

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id="media-4",
            media_path=media_path,
            subtitle_tracks=[{"index": 4, "codec_name": "subrip", "language": "und"}],
            sidecars=[],
        )
        connection.commit()

    summary = run_step2_subtitle_language_detection(db_path=db_path, temp_root=tmp_path / "temp")
    assert summary.detected == 1

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT review_status, detected_language, detected_confidence
            FROM subtitle_track_language_labels
            """
        ).fetchone()

    assert row == ("detected", "es", 0.98)
