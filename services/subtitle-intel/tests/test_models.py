from __future__ import annotations

import pytest
from pydantic import ValidationError

from subtitle_intel.models import (
    ScanResult,
    ScanStatus,
    SubtitleTrackInfo,
    SubtitleTrackType,
)


def _track(**kwargs) -> SubtitleTrackInfo:
    defaults = dict(
        track_index=0,
        detected_language="en",
        confidence=1.0,
    )
    defaults.update(kwargs)
    return SubtitleTrackInfo(**defaults)


def test_track_defaults():
    t = _track()
    assert t.track_type == SubtitleTrackType.full
    assert t.is_default is False
    assert t.is_forced is False
    assert t.codec is None
    assert t.title is None


def test_track_confidence_bounds():
    _track(confidence=0.0)
    _track(confidence=1.0)
    with pytest.raises(ValidationError):
        _track(confidence=1.1)
    with pytest.raises(ValidationError):
        _track(confidence=-0.01)


def test_scan_result_has_english():
    result = ScanResult(
        file_path="/foo.mkv",
        status=ScanStatus.ok,
        subtitle_tracks=[_track(detected_language="en")],
    )
    assert result.has_english is True


def test_scan_result_no_english():
    result = ScanResult(
        file_path="/foo.mkv",
        status=ScanStatus.ok,
        subtitle_tracks=[_track(detected_language="ja")],
    )
    assert result.has_english is False


def test_scan_result_has_unknown_language():
    result = ScanResult(
        file_path="/foo.mkv",
        status=ScanStatus.ok,
        subtitle_tracks=[_track(detected_language="unknown", confidence=0.0)],
    )
    assert result.has_unknown_language is True
    assert result.requires_review is True


def test_scan_result_requires_review_on_error():
    result = ScanResult(
        file_path="/foo.mkv",
        status=ScanStatus.mediainfo_error,
        error_message="tool not found",
    )
    assert result.requires_review is True


def test_scan_result_no_review_clean():
    result = ScanResult(
        file_path="/foo.mkv",
        status=ScanStatus.ok,
        subtitle_tracks=[_track(detected_language="en")],
    )
    assert result.requires_review is False


def test_scan_result_empty_tracks_default():
    result = ScanResult(file_path="/foo.mkv", status=ScanStatus.no_subtitle_tracks)
    assert result.subtitle_tracks == []
    assert result.has_english is False
