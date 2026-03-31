import json
import sqlite3
from pathlib import Path

from services.media_brain.step1_scan_endpoint import (
    detect_video_hdr,
    handle_scan_request,
    run_step1_inventory_complete,
)


def test_detect_video_hdr_identifies_hdr10_from_pq_transfer() -> None:
    hdr, hdr_format = detect_video_hdr(
        {
            "color_transfer": "smpte2084",
            "color_primaries": "bt2020",
            "side_data_list": [{"side_data_type": "Mastering display metadata"}],
        }
    )

    assert hdr is True
    assert hdr_format == "hdr10"


def test_detect_video_hdr_identifies_hlg() -> None:
    hdr, hdr_format = detect_video_hdr({"color_transfer": "arib-std-b67"})

    assert hdr is True
    assert hdr_format == "hlg"


def test_run_step1_inventory_complete_writes_hdr_metadata(tmp_path: Path, monkeypatch) -> None:
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
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "pix_fmt": "yuv420p10le",
                "color_transfer": "smpte2084",
                "color_primaries": "bt2020",
                "color_space": "bt2020nc",
                "tags": {"language": "und"},
                "disposition": {"default": 1, "forced": 0},
                "side_data_list": [{"side_data_type": "Mastering display metadata"}],
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
        "services.media_brain.step1_scan_endpoint.probe_media_file",
        lambda _: fake_ffprobe,
    )

    db_path = tmp_path / "media_brain.db"
    summary = run_step1_inventory_complete(scan_root=scan_root, db_path=db_path)

    assert summary.scanned_files == 1
    assert summary.inserted_or_updated == 1
    assert summary.failed_files == 0

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT path, state, video_tracks_json, audio_tracks_json, subtitle_tracks_json, sidecar_subtitles_json
            FROM media_records
            """
        ).fetchone()

    assert row is not None
    path, state, video_tracks_json, audio_tracks_json, subtitle_tracks_json, sidecar_subtitles_json = row
    assert path.endswith("sample.mkv")
    assert state == "needs_subtitle_review"

    video_tracks = json.loads(video_tracks_json)
    audio_tracks = json.loads(audio_tracks_json)
    subtitle_tracks = json.loads(subtitle_tracks_json)
    sidecars = json.loads(sidecar_subtitles_json)

    assert video_tracks[0]["hdr"] is True
    assert video_tracks[0]["hdr_format"] == "hdr10"
    assert audio_tracks[0]["language"] == "jpn"
    assert subtitle_tracks[0]["language"] == "eng"
    assert sidecars[0]["filename"] == "sample.en.srt"


def test_handle_scan_request_returns_inventory_summary(tmp_path: Path, monkeypatch) -> None:
    summary = {
        "scanned_files": 3,
        "inserted_or_updated": 3,
        "failed_files": 0,
        "db_path": tmp_path / "media_brain.db",
    }

    monkeypatch.setattr(
        "services.media_brain.step1_scan_endpoint.run_step1_inventory_complete",
        lambda scan_root, db_path: type("Summary", (), summary)(),
    )

    payload = {"scan_root": str(tmp_path / "library"), "db_path": str(tmp_path / "media_brain.db")}
    response = handle_scan_request(payload)

    assert response["scanned_files"] == 3
    assert response["inserted_or_updated"] == 3
    assert response["failed_files"] == 0
    assert response["db_path"].endswith("media_brain.db")
    assert response["state"] == "needs_subtitle_review"
