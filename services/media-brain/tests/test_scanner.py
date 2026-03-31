from __future__ import annotations

import pytest
from pathlib import Path

from media_brain.models import MediaBrainState, SubtitleTrackType
from media_brain.scanner import MediaBrainScanner, _find_sidecars, _int_or_none

from .conftest import SAMPLE_MEDIAINFO_HDR, SAMPLE_MEDIAINFO_JSON


@pytest.fixture()
def scanner() -> MediaBrainScanner:
    return MediaBrainScanner()


@pytest.fixture()
def fake_media_file(tmp_path: Path) -> Path:
    f = tmp_path / "show.mkv"
    f.write_bytes(b"\x00" * 1024)
    return f


# ---------------------------------------------------------------------------
# scan_file with injected mediainfo JSON
# ---------------------------------------------------------------------------

def test_scan_file_basic(scanner: MediaBrainScanner, fake_media_file: Path) -> None:
    item = scanner.scan_file(str(fake_media_file), mediainfo_json=SAMPLE_MEDIAINFO_JSON)
    assert item.state == MediaBrainState.needs_subtitle_review
    assert item.container_format == "Matroska"
    assert item.duration_seconds == pytest.approx(5400.0)
    assert item.file_size == 1024


def test_scan_file_generates_stable_media_id(scanner: MediaBrainScanner, fake_media_file: Path) -> None:
    item1 = scanner.scan_file(str(fake_media_file), mediainfo_json=SAMPLE_MEDIAINFO_JSON)
    item2 = scanner.scan_file(str(fake_media_file), mediainfo_json=SAMPLE_MEDIAINFO_JSON)
    assert item1.media_id == item2.media_id
    assert len(item1.media_id) == 64  # SHA-256 hex


def test_scan_file_video_tracks(scanner: MediaBrainScanner, fake_media_file: Path) -> None:
    item = scanner.scan_file(str(fake_media_file), mediainfo_json=SAMPLE_MEDIAINFO_JSON)
    assert len(item.video_tracks) == 1
    v = item.video_tracks[0]
    assert v.codec == "HEVC"
    assert v.width == 1920
    assert v.height == 1080
    assert v.is_hdr is False


def test_scan_file_hdr_detected(scanner: MediaBrainScanner, fake_media_file: Path) -> None:
    item = scanner.scan_file(str(fake_media_file), mediainfo_json=SAMPLE_MEDIAINFO_HDR)
    assert item.video_tracks[0].is_hdr is True
    assert item.video_tracks[0].hdr_format == "SMPTE ST 2086"
    assert item.video_tracks[0].width == 3840
    assert item.video_tracks[0].height == 2160


def test_scan_file_audio_tracks(scanner: MediaBrainScanner, fake_media_file: Path) -> None:
    item = scanner.scan_file(str(fake_media_file), mediainfo_json=SAMPLE_MEDIAINFO_JSON)
    assert len(item.audio_tracks) == 2
    a0, a1 = item.audio_tracks
    assert a0.codec == "AAC"
    assert a0.detected_language == "ja"
    assert a0.channels == 2
    assert a0.is_default is True
    assert a1.codec == "AC-3"
    assert a1.detected_language == "en"
    assert a1.channels == 6


def test_scan_file_subtitle_tracks(scanner: MediaBrainScanner, fake_media_file: Path) -> None:
    item = scanner.scan_file(str(fake_media_file), mediainfo_json=SAMPLE_MEDIAINFO_JSON)
    assert len(item.subtitle_tracks) == 1
    s = item.subtitle_tracks[0]
    assert s.detected_language == "en"
    assert s.confidence == pytest.approx(1.0)
    assert s.track_type == SubtitleTrackType.full
    assert s.is_forced is False


def test_scan_file_missing(scanner: MediaBrainScanner, tmp_path: Path) -> None:
    item = scanner.scan_file(str(tmp_path / "nonexistent.mkv"))
    assert item.state == MediaBrainState.error
    assert "not found" in (item.error_message or "")


# ---------------------------------------------------------------------------
# Sidecar detection
# ---------------------------------------------------------------------------

def test_find_sidecars(tmp_path: Path) -> None:
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"\x00")
    (tmp_path / "movie.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
    (tmp_path / "movie.en.ass").write_text("")
    (tmp_path / "other.srt").write_text("")  # different stem — should not appear

    sidecars = _find_sidecars(str(media))
    names = {Path(s).name for s in sidecars}
    assert "movie.srt" in names
    assert "movie.en.ass" in names
    assert "other.srt" not in names


def test_find_sidecars_no_sidecars(tmp_path: Path) -> None:
    media = tmp_path / "clean.mkv"
    media.write_bytes(b"\x00")
    assert _find_sidecars(str(media)) == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_int_or_none_plain() -> None:
    assert _int_or_none("6") == 6


def test_int_or_none_with_text() -> None:
    assert _int_or_none("2 channels") == 2


def test_int_or_none_none() -> None:
    assert _int_or_none(None) is None


def test_int_or_none_spaced_number() -> None:
    # mediainfo sometimes formats large numbers with spaces: "48 000"
    assert _int_or_none("48 000") == 48000


# ---------------------------------------------------------------------------
# Directory scan
# ---------------------------------------------------------------------------

def test_scan_directory(scanner: MediaBrainScanner, tmp_path: Path) -> None:
    (tmp_path / "a.mkv").write_bytes(b"\x00" * 512)
    (tmp_path / "b.mp4").write_bytes(b"\x00" * 256)
    (tmp_path / "c.txt").write_bytes(b"ignore me")

    # We can't call real mediainfo in unit tests, but we can verify the
    # scanner at least finds the right files before handing them off.
    # Patch scan_file to avoid subprocess.
    scanned: list[str] = []

    original = scanner.scan_file

    def fake_scan(file_path: str, **_: object) -> object:
        scanned.append(file_path)
        return original(file_path, mediainfo_json={"media": {"track": [{"@type": "General", "Format": "Matroska"}]}})

    scanner.scan_file = fake_scan  # type: ignore[method-assign]
    items = scanner.scan_directory(str(tmp_path), extensions=[".mkv", ".mp4"])
    assert len(items) == 2
    assert all(Path(p).suffix in {".mkv", ".mp4"} for p in scanned)
