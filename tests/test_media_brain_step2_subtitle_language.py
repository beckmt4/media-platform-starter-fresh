import json
import sqlite3
from pathlib import Path

import pytest

from services.media_brain.step2_subtitle_language import (
    Step2Config,
    SubtitleLanguageDetectionError,
    _detect_with_langdetect,
    _detect_with_lingua,
    detect_language_from_text,
    detect_language_with_whisper,
    init_step2_db,
    run_step2_subtitle_language_detection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Existing behaviour (preserved)
# ---------------------------------------------------------------------------


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
        lambda text, config=None: ("fr", 0.75, "langdetect"),
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
        lambda text, config=None: ("es", 0.98, "langdetect"),
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


# ---------------------------------------------------------------------------
# Image-based codec variants all become needs_ocr
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("codec", ["hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"])
def test_all_image_based_codecs_are_flagged_for_ocr(tmp_path: Path, codec: str) -> None:
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "disc.mkv"
    media_path.write_bytes(b"video")

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id=f"media-{codec}",
            media_path=media_path,
            subtitle_tracks=[{"index": 0, "codec_name": codec, "language": "und"}],
            sidecars=[],
        )
        connection.commit()

    summary = run_step2_subtitle_language_detection(db_path=db_path, temp_root=tmp_path / "temp")
    assert summary.needs_ocr == 1
    assert summary.detected == 0
    assert summary.uncertain == 0


# ---------------------------------------------------------------------------
# Detector selection: detect_language_from_text dispatch
# ---------------------------------------------------------------------------


def test_langdetect_mode_calls_langdetect(monkeypatch) -> None:
    calls = []

    def fake_langdetect(text):
        calls.append(("langdetect", text))
        return ("en", 0.99, "langdetect")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language._detect_with_langdetect",
        fake_langdetect,
    )

    config = Step2Config(detector_mode="langdetect", min_sample_length=5)
    result = detect_language_from_text("Hello world this is English text", config)
    assert result == ("en", 0.99, "langdetect")
    assert calls[0][0] == "langdetect"


def test_lingua_mode_calls_lingua(monkeypatch) -> None:
    calls = []

    def fake_lingua(text):
        calls.append(("lingua", text))
        return ("en", 0.97, "lingua")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language._detect_with_lingua",
        fake_lingua,
    )

    config = Step2Config(detector_mode="lingua", min_sample_length=5)
    result = detect_language_from_text("Hello world this is English text", config)
    assert result == ("en", 0.97, "lingua")
    assert calls[0][0] == "lingua"


def test_auto_mode_prefers_lingua_when_available(monkeypatch) -> None:
    lingua_calls = []
    langdetect_calls = []

    def fake_lingua(text):
        lingua_calls.append(text)
        return ("en", 0.95, "lingua")

    def fake_langdetect(text):
        langdetect_calls.append(text)
        return ("en", 0.90, "langdetect")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language._detect_with_lingua",
        fake_lingua,
    )
    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language._detect_with_langdetect",
        fake_langdetect,
    )

    config = Step2Config(detector_mode="auto", min_sample_length=5)
    result = detect_language_from_text("Hello world this is English text", config)
    assert result[2] == "lingua"
    assert lingua_calls
    assert not langdetect_calls


def test_auto_mode_falls_back_to_langdetect_when_lingua_unavailable(monkeypatch) -> None:
    def lingua_missing(text):
        raise SubtitleLanguageDetectionError("lingua not installed")

    langdetect_calls = []

    def fake_langdetect(text):
        langdetect_calls.append(text)
        return ("en", 0.92, "langdetect")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language._detect_with_lingua",
        lingua_missing,
    )
    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language._detect_with_langdetect",
        fake_langdetect,
    )

    config = Step2Config(detector_mode="auto", min_sample_length=5)
    result = detect_language_from_text("Hello world this is English text", config)
    assert result[2] == "langdetect"
    assert langdetect_calls


# ---------------------------------------------------------------------------
# Low-confidence → uncertain
# ---------------------------------------------------------------------------


def test_low_confidence_result_stored_as_uncertain(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "movie.mp4"
    media_path.write_bytes(b"video")
    sidecar_path = tmp_path / "movie.srt"
    sidecar_path.write_text("some text here for detection", encoding="utf-8")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.detect_language_from_text",
        lambda text, config=None: ("de", 0.55, "langdetect"),
    )

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id="media-low",
            media_path=media_path,
            subtitle_tracks=[],
            sidecars=[{"path": str(sidecar_path), "filename": sidecar_path.name, "extension": ".srt"}],
        )
        connection.commit()

    summary = run_step2_subtitle_language_detection(db_path=db_path, temp_root=tmp_path / "temp")
    assert summary.uncertain == 1
    assert summary.detected == 0


# ---------------------------------------------------------------------------
# Whisper fallback
# ---------------------------------------------------------------------------


def test_whisper_fallback_used_when_extracted_text_is_too_short(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "episode.mkv"
    media_path.write_bytes(b"video")

    # Extraction returns text that is shorter than min_sample_length
    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.extract_embedded_subtitle_text",
        lambda *a, **kw: "Hi",  # 2 chars — below default min_sample_length of 20
    )

    whisper_calls = []

    def fake_whisper(media_path, config):
        whisper_calls.append(str(media_path))
        return ("ja", 0.95, "whisper_language")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.detect_language_with_whisper",
        fake_whisper,
    )

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id="media-whisper",
            media_path=media_path,
            subtitle_tracks=[{"index": 0, "codec_name": "subrip", "language": "und"}],
            sidecars=[],
        )
        connection.commit()

    config = Step2Config(whisper_fallback_enabled=True)
    summary = run_step2_subtitle_language_detection(
        db_path=db_path, temp_root=tmp_path / "temp", config=config
    )
    assert summary.detected == 1
    assert whisper_calls, "Whisper fallback should have been called"

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT detector_engine, detected_language FROM subtitle_track_language_labels"
        ).fetchone()
    assert row == ("whisper_language", "ja")


def test_whisper_fallback_used_when_extraction_fails(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "episode.mkv"
    media_path.write_bytes(b"video")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.extract_embedded_subtitle_text",
        lambda *a, **kw: (_ for _ in ()).throw(
            SubtitleLanguageDetectionError("ffmpeg failed")
        ),
    )

    def fake_whisper(media_path, config):
        return ("ko", 0.93, "whisper_language")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.detect_language_with_whisper",
        fake_whisper,
    )

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id="media-whisper-fail",
            media_path=media_path,
            subtitle_tracks=[{"index": 0, "codec_name": "subrip", "language": "und"}],
            sidecars=[],
        )
        connection.commit()

    config = Step2Config(whisper_fallback_enabled=True)
    summary = run_step2_subtitle_language_detection(
        db_path=db_path, temp_root=tmp_path / "temp", config=config
    )
    assert summary.detected == 1

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT detector_engine, detected_language FROM subtitle_track_language_labels"
        ).fetchone()
    assert row == ("whisper_language", "ko")


def test_whisper_fallback_low_confidence_stores_uncertain(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "episode.mkv"
    media_path.write_bytes(b"video")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.extract_embedded_subtitle_text",
        lambda *a, **kw: "",  # empty — triggers whisper fallback
    )

    def fake_whisper(media_path, config):
        return ("fr", 0.45, "whisper_language")  # low confidence

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.detect_language_with_whisper",
        fake_whisper,
    )

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id="media-whisper-low",
            media_path=media_path,
            subtitle_tracks=[{"index": 0, "codec_name": "subrip", "language": "und"}],
            sidecars=[],
        )
        connection.commit()

    config = Step2Config(whisper_fallback_enabled=True)
    summary = run_step2_subtitle_language_detection(
        db_path=db_path, temp_root=tmp_path / "temp", config=config
    )
    assert summary.uncertain == 1

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT review_status, detector_engine FROM subtitle_track_language_labels"
        ).fetchone()
    assert row == ("uncertain", "whisper_language")


def test_whisper_fallback_itself_fails_stores_uncertain(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "episode.mkv"
    media_path.write_bytes(b"video")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.extract_embedded_subtitle_text",
        lambda *a, **kw: "",
    )

    def fake_whisper_fails(media_path, config):
        raise SubtitleLanguageDetectionError("faster-whisper not installed")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.detect_language_with_whisper",
        fake_whisper_fails,
    )

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id="media-whisper-error",
            media_path=media_path,
            subtitle_tracks=[{"index": 0, "codec_name": "subrip", "language": "und"}],
            sidecars=[],
        )
        connection.commit()

    config = Step2Config(whisper_fallback_enabled=True)
    summary = run_step2_subtitle_language_detection(
        db_path=db_path, temp_root=tmp_path / "temp", config=config
    )
    assert summary.uncertain == 1

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT review_status, detector_engine FROM subtitle_track_language_labels"
        ).fetchone()
    assert row == ("uncertain", "whisper_language")


def test_whisper_disabled_extraction_failure_counts_as_failed(tmp_path: Path, monkeypatch) -> None:
    """When Whisper fallback is off, extraction errors are not silenced."""
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "episode.mkv"
    media_path.write_bytes(b"video")

    monkeypatch.setattr(
        "services.media_brain.step2_subtitle_language.extract_embedded_subtitle_text",
        lambda *a, **kw: (_ for _ in ()).throw(
            SubtitleLanguageDetectionError("ffmpeg missing")
        ),
    )

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id="media-no-whisper",
            media_path=media_path,
            subtitle_tracks=[{"index": 0, "codec_name": "subrip", "language": "und"}],
            sidecars=[],
        )
        connection.commit()

    config = Step2Config(whisper_fallback_enabled=False)
    summary = run_step2_subtitle_language_detection(
        db_path=db_path, temp_root=tmp_path / "temp", config=config
    )
    assert summary.failed_tracks == 1
    assert summary.detected == 0


# ---------------------------------------------------------------------------
# no_text short-circuit when whisper disabled
# ---------------------------------------------------------------------------


def test_empty_text_with_no_fallback_stores_uncertain(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "media_brain.db"
    media_path = tmp_path / "movie.mp4"
    media_path.write_bytes(b"video")
    sidecar_path = tmp_path / "movie.srt"
    sidecar_path.write_text("", encoding="utf-8")  # empty sidecar

    with sqlite3.connect(db_path) as connection:
        create_step1_media_table(connection)
        init_step2_db(connection)
        insert_media_record(
            connection,
            media_id="media-empty",
            media_path=media_path,
            subtitle_tracks=[],
            sidecars=[{"path": str(sidecar_path), "filename": sidecar_path.name, "extension": ".srt"}],
        )
        connection.commit()

    config = Step2Config(whisper_fallback_enabled=False)
    summary = run_step2_subtitle_language_detection(
        db_path=db_path, temp_root=tmp_path / "temp", config=config
    )
    assert summary.uncertain == 1

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT review_status, detector_engine FROM subtitle_track_language_labels"
        ).fetchone()
    assert row[0] == "uncertain"
    assert row[1] == "no_text"
