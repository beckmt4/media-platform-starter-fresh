import json
import sqlite3
from pathlib import Path

from services.media_brain.step1_inventory import (
    compute_media_id,
    detect_sidecar_subtitles,
    run_step1_inventory,
)


def test_compute_media_id_is_stable_for_same_path_and_size(tmp_path: Path) -> None:
    media_file = tmp_path / "example.mkv"
    media_file.write_bytes(b"12345")

    first = compute_media_id(media_file, media_file.stat().st_size)
    second = compute_media_id(media_file, media_file.stat().st_size)

    assert first == second


def test_detect_sidecar_subtitles_finds_exact_and_tagged_sidecars(tmp_path: Path) -> None:
    media_file = tmp_path / "movie.mkv"
    media_file.write_bytes(b"video")

    (tmp_path / "movie.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
    (tmp_path / "movie.en.ass").write_text("[Script Info]")
    (tmp_path / "movie-trailer.srt").write_text("ignore me")

    sidecars = detect_sidecar_subtitles(media_file)
    names = [item["filename"] for item in sidecars]

    assert names == ["movie.en.ass", "movie.srt"]


def test_run_step1_inventory_writes_media_records(tmp_path: Path, monkeypatch) -> None:
    scan_root = tmp_path / "library"
    scan_root.mkdir()

    media_file = scan_root / "sample.mkv"
    media_file.write_bytes(b"abcdefgh")
    (scan_root / "sample.en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")

    fake_ffprobe = {
        "format": {"format_name": "matroska,webm", "duration": "60.0"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "tags": {"language": "und"},
                "disposition": {"default": 1, "forced": 0},
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "tags": {"language": "jpn", "title": "Japanese Stereo"},
                "disposition": {"default": 1, "forced": 0},
            },
            {
                "index": 2,
                "codec_type": "subtitle",
                "codec_name": "subrip",
                "tags": {"language": "eng", "title": "English"},
                "disposition": {"default": 0, "forced": 0},
            },
        ],
    }

    monkeypatch.setattr(
        "services.media_brain.step1_inventory.probe_media_file",
        lambda _: fake_ffprobe,
    )

    db_path = tmp_path / "media_brain.db"
    summary = run_step1_inventory(scan_root=scan_root, db_path=db_path)

    assert summary.scanned_files == 1
    assert summary.inserted_or_updated == 1
    assert summary.failed_files == 0

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT path, state, audio_tracks_json, subtitle_tracks_json, sidecar_subtitles_json
            FROM media_records
            """
        ).fetchone()

    assert row is not None
    path, state, audio_tracks_json, subtitle_tracks_json, sidecar_subtitles_json = row
    assert path.endswith("sample.mkv")
    assert state == "needs_subtitle_review"

    audio_tracks = json.loads(audio_tracks_json)
    subtitle_tracks = json.loads(subtitle_tracks_json)
    sidecars = json.loads(sidecar_subtitles_json)

    assert audio_tracks[0]["language"] == "jpn"
    assert subtitle_tracks[0]["language"] == "eng"
    assert sidecars[0]["filename"] == "sample.en.srt"
