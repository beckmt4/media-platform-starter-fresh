import json
import sqlite3
from pathlib import Path

from services.media_brain.step1_inventory import (
    compute_media_id,
    detect_sidecar_subtitles,
    enumerate_tracks,
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


# ---------------------------------------------------------------------------
# enumerate_tracks / is_hdr tests
# ---------------------------------------------------------------------------

def test_enumerate_tracks_sdr_video_is_hdr_false() -> None:
    ffprobe = {"streams": [{"index": 0, "codec_type": "video", "codec_name": "h264",
                            "tags": {}, "disposition": {"default": 1, "forced": 0}}]}
    tracks = enumerate_tracks(ffprobe)
    assert tracks["video"][0]["is_hdr"] is False


def test_enumerate_tracks_hdr10_is_hdr_true() -> None:
    """bt2020 primaries + smpte2084 transfer = HDR10."""
    ffprobe = {"streams": [{"index": 0, "codec_type": "video", "codec_name": "hevc",
                            "color_primaries": "bt2020", "color_transfer": "smpte2084",
                            "tags": {}, "disposition": {"default": 1, "forced": 0}}]}
    tracks = enumerate_tracks(ffprobe)
    assert tracks["video"][0]["is_hdr"] is True


def test_enumerate_tracks_hlg_is_hdr_true() -> None:
    """bt2020 primaries + arib-std-b67 transfer = HLG."""
    ffprobe = {"streams": [{"index": 0, "codec_type": "video", "codec_name": "hevc",
                            "color_primaries": "bt2020", "color_transfer": "arib-std-b67",
                            "tags": {}, "disposition": {"default": 1, "forced": 0}}]}
    tracks = enumerate_tracks(ffprobe)
    assert tracks["video"][0]["is_hdr"] is True


def test_enumerate_tracks_pq_transfer_alone_is_hdr_true() -> None:
    """PQ transfer without bt2020 primaries still flags HDR (e.g. poorly tagged files)."""
    ffprobe = {"streams": [{"index": 0, "codec_type": "video", "codec_name": "hevc",
                            "color_primaries": "bt709", "color_transfer": "smpte2084",
                            "tags": {}, "disposition": {"default": 1, "forced": 0}}]}
    tracks = enumerate_tracks(ffprobe)
    assert tracks["video"][0]["is_hdr"] is True


def test_enumerate_tracks_audio_has_no_is_hdr() -> None:
    """Audio tracks should still have is_hdr=False (bt2020 fields absent)."""
    ffprobe = {"streams": [{"index": 0, "codec_type": "audio", "codec_name": "aac",
                            "channels": 2, "tags": {}, "disposition": {"default": 1, "forced": 0}}]}
    tracks = enumerate_tracks(ffprobe)
    assert tracks["audio"][0]["is_hdr"] is False


# ---------------------------------------------------------------------------
# State-preservation tests (re-scan idempotency)
# ---------------------------------------------------------------------------

_MINIMAL_FFPROBE = {
    "format": {"format_name": "matroska,webm", "duration": "30.0"},
    "streams": [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "tags": {},
            "disposition": {"default": 1, "forced": 0},
        }
    ],
}


def test_rescan_preserves_advanced_state(tmp_path: Path, monkeypatch) -> None:
    """Re-scanning a file whose state has advanced past needs_subtitle_review
    must not reset it back to the initial state.

    This guards against the ON CONFLICT DO UPDATE bug where state=excluded.state
    was included in the update set, silently undoing all Step 2/3 work.
    """
    scan_root = tmp_path / "library"
    scan_root.mkdir()
    media_file = scan_root / "movie.mkv"
    media_file.write_bytes(b"fake-video-content")

    monkeypatch.setattr(
        "services.media_brain.step1_inventory.probe_media_file",
        lambda _: _MINIMAL_FFPROBE,
    )

    db_path = tmp_path / "brain.db"

    # First scan: record is inserted with state=needs_subtitle_review.
    run_step1_inventory(scan_root=scan_root, db_path=db_path)

    # Simulate Steps 2 and 3 advancing the state.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE media_records SET state = 'needs_audio_review'"
        )
        conn.commit()

    # Second scan of the same file (same path + size → same media_id).
    run_step1_inventory(scan_root=scan_root, db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT state FROM media_records WHERE file_name = 'movie.mkv'"
        ).fetchone()

    assert row is not None
    assert row[0] == "needs_audio_review", (
        "Re-scan must not reset state; got %r instead of 'needs_audio_review'" % row[0]
    )


def test_rescan_updates_ffprobe_json_but_preserves_state(tmp_path: Path, monkeypatch) -> None:
    """Re-scan must refresh ffprobe data while leaving state untouched."""
    scan_root = tmp_path / "library"
    scan_root.mkdir()
    media_file = scan_root / "show.mkv"
    media_file.write_bytes(b"video-v1")

    first_probe = dict(_MINIMAL_FFPROBE)
    first_probe["format"] = {"format_name": "matroska,webm", "duration": "30.0", "version": "1"}

    second_probe = dict(_MINIMAL_FFPROBE)
    second_probe["format"] = {"format_name": "matroska,webm", "duration": "30.0", "version": "2"}

    call_count = {"n": 0}

    def fake_probe(_path):
        call_count["n"] += 1
        return first_probe if call_count["n"] == 1 else second_probe

    monkeypatch.setattr(
        "services.media_brain.step1_inventory.probe_media_file",
        fake_probe,
    )

    db_path = tmp_path / "brain.db"
    run_step1_inventory(scan_root=scan_root, db_path=db_path)

    # Advance state before re-scan.
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE media_records SET state = 'needs_subtitle_generation'")
        conn.commit()

    run_step1_inventory(scan_root=scan_root, db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT state, ffprobe_json FROM media_records WHERE file_name = 'show.mkv'"
        ).fetchone()

    assert row is not None
    state, ffprobe_json_str = row
    assert state == "needs_subtitle_generation", (
        "State must not be reset by re-scan"
    )
    probe_data = json.loads(ffprobe_json_str)
    assert probe_data["format"]["version"] == "2", (
        "ffprobe_json must be refreshed on re-scan"
    )
