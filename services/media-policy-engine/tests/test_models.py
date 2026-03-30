from __future__ import annotations

import pytest
from pydantic import ValidationError

from media_policy_engine.models import (
    AudioTrackFacts,
    AudioTrackType,
    MediaDomain,
    MediaFacts,
    PolicyActionKind,
    SubtitleTrackFacts,
    SubtitleTrackType,
    VideoFacts,
)


def _base_facts(**kwargs) -> MediaFacts:
    defaults = dict(
        domain=MediaDomain.domestic_live_action_movie,
        detected_original_language="en",
        video=VideoFacts(codec="h264"),
    )
    defaults.update(kwargs)
    return MediaFacts(**defaults)


def test_media_facts_minimal():
    facts = _base_facts()
    assert facts.domain == MediaDomain.domestic_live_action_movie
    assert facts.audio_tracks == []
    assert facts.subtitle_tracks == []
    assert facts.catalog_tags == []


def test_media_facts_rejects_invalid_domain():
    with pytest.raises(ValidationError):
        _base_facts(domain="not_a_domain")


def test_subtitle_track_confidence_bounds():
    # valid
    SubtitleTrackFacts(track_index=0, language="en", confidence=0.95)
    with pytest.raises(ValidationError):
        SubtitleTrackFacts(track_index=0, language="en", confidence=1.5)
    with pytest.raises(ValidationError):
        SubtitleTrackFacts(track_index=0, language="en", confidence=-0.1)


def test_subtitle_track_type_defaults_to_full():
    track = SubtitleTrackFacts(track_index=0, language="en")
    assert track.track_type == SubtitleTrackType.full


def test_audio_track_type_defaults_to_original():
    track = AudioTrackFacts(track_index=0, language="en")
    assert track.track_type == AudioTrackType.original
    assert track.is_stereo is False


def test_video_facts_defaults():
    v = VideoFacts(codec="hevc")
    assert v.is_remux is False
    assert v.is_hdr is False
    assert v.bitrate_mbps is None


def test_media_domain_count():
    assert len(MediaDomain) == 11


def test_policy_action_kind_values():
    assert PolicyActionKind.keep_stream.value == "keep_stream"
    assert PolicyActionKind.quarantine_subtitle.value == "quarantine_subtitle"
    assert PolicyActionKind.generate_english_subtitles.value == "generate_english_subtitles"
