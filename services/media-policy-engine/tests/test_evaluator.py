from __future__ import annotations

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


def _facts(
    domain=MediaDomain.domestic_live_action_movie,
    original_lang="en",
    codec="h264",
    is_remux=False,
    is_hdr=False,
    subtitles=None,
    audio=None,
    tags=None,
) -> MediaFacts:
    return MediaFacts(
        domain=domain,
        detected_original_language=original_lang,
        video=VideoFacts(codec=codec, is_remux=is_remux, is_hdr=is_hdr),
        subtitle_tracks=subtitles or [],
        audio_tracks=audio or [],
        catalog_tags=tags or [],
    )


# ---------------------------------------------------------------------------
# Transcode rules
# ---------------------------------------------------------------------------

def test_skip_transcode_already_hevc(evaluator):
    result = evaluator.evaluate(_facts(codec="hevc"))
    kinds = {a.kind for a in result.actions}
    assert PolicyActionKind.skip_transcode in kinds


def test_flag_for_transcode_h264(evaluator):
    result = evaluator.evaluate(_facts(codec="h264"))
    kinds = {a.kind for a in result.actions}
    assert PolicyActionKind.flag_for_transcode in kinds


def test_skip_transcode_remux(evaluator):
    result = evaluator.evaluate(_facts(codec="h264", is_remux=True))
    kinds = {a.kind for a in result.actions}
    assert PolicyActionKind.skip_transcode in kinds
    assert PolicyActionKind.flag_for_transcode not in kinds


def test_hdr_transcode_requires_review(evaluator):
    result = evaluator.evaluate(_facts(codec="h264", is_hdr=True))
    assert result.requires_review
    kinds = {a.kind for a in result.actions}
    assert PolicyActionKind.send_to_review in kinds


def test_anime_banding_risk_requires_review(evaluator):
    result = evaluator.evaluate(_facts(
        domain=MediaDomain.anime_series,
        original_lang="ja",
        codec="h264",
    ))
    assert result.requires_review
    kinds = {a.kind for a in result.actions}
    assert PolicyActionKind.send_to_review in kinds


def test_locked_item_skips_transcode(evaluator):
    result = evaluator.evaluate(_facts(codec="h264", tags=["locked"]))
    kinds = {a.kind for a in result.actions}
    assert PolicyActionKind.skip_transcode in kinds
    assert PolicyActionKind.flag_for_transcode not in kinds


# ---------------------------------------------------------------------------
# Subtitle rules
# ---------------------------------------------------------------------------

def test_unknown_language_subtitle_quarantined(evaluator):
    subs = [SubtitleTrackFacts(track_index=0, language="unknown", confidence=0.5)]
    result = evaluator.evaluate(_facts(subtitles=subs))
    kinds = {a.kind for a in result.actions}
    assert PolicyActionKind.quarantine_subtitle in kinds
    assert result.requires_review


def test_forced_subtitle_kept(evaluator):
    subs = [SubtitleTrackFacts(track_index=0, language="en", track_type=SubtitleTrackType.forced)]
    result = evaluator.evaluate(_facts(subtitles=subs))
    sub_actions = [a for a in result.actions if a.track_index == 0]
    assert any(a.kind == PolicyActionKind.keep_stream for a in sub_actions)


def test_english_subtitle_kept(evaluator):
    subs = [SubtitleTrackFacts(track_index=0, language="en")]
    result = evaluator.evaluate(_facts(subtitles=subs))
    sub_actions = [a for a in result.actions if a.track_index == 0]
    assert any(a.kind == PolicyActionKind.keep_stream for a in sub_actions)


def test_sdh_english_kept_for_domestic(evaluator):
    subs = [SubtitleTrackFacts(track_index=0, language="en", track_type=SubtitleTrackType.sdh)]
    result = evaluator.evaluate(_facts(
        domain=MediaDomain.domestic_live_action_movie,
        subtitles=subs,
    ))
    sub_actions = [a for a in result.actions if a.track_index == 0]
    assert any(a.kind == PolicyActionKind.keep_stream for a in sub_actions)


def test_anime_signs_songs_kept(evaluator):
    subs = [SubtitleTrackFacts(
        track_index=0, language="en", track_type=SubtitleTrackType.signs_songs
    )]
    result = evaluator.evaluate(_facts(
        domain=MediaDomain.anime_series,
        original_lang="ja",
        codec="hevc",
        subtitles=subs,
    ))
    sub_actions = [a for a in result.actions if a.track_index == 0]
    assert any(a.kind == PolicyActionKind.keep_stream for a in sub_actions)


def test_adult_low_confidence_subtitle_requires_review(evaluator):
    # adult policy: require_review_below_confidence: 0.82
    subs = [SubtitleTrackFacts(track_index=0, language="en", confidence=0.75)]
    result = evaluator.evaluate(_facts(
        domain=MediaDomain.jav_adult,
        original_lang="ja",
        codec="hevc",
        subtitles=subs,
    ))
    assert result.requires_review
    review_actions = [a for a in result.actions if a.kind == PolicyActionKind.send_to_review]
    assert review_actions


def test_adult_generate_english_if_missing(evaluator):
    # no subtitle tracks → should queue generation
    result = evaluator.evaluate(_facts(
        domain=MediaDomain.jav_adult,
        original_lang="ja",
        codec="hevc",
    ))
    kinds = {a.kind for a in result.actions}
    assert PolicyActionKind.generate_english_subtitles in kinds


def test_adult_no_generate_if_english_present(evaluator):
    subs = [SubtitleTrackFacts(track_index=0, language="en", confidence=0.90)]
    result = evaluator.evaluate(_facts(
        domain=MediaDomain.jav_adult,
        original_lang="ja",
        codec="hevc",
        subtitles=subs,
    ))
    kinds = {a.kind for a in result.actions}
    assert PolicyActionKind.generate_english_subtitles not in kinds


def test_original_language_subtitle_kept(evaluator):
    subs = [SubtitleTrackFacts(track_index=0, language="ja")]
    result = evaluator.evaluate(_facts(
        domain=MediaDomain.anime_movie,
        original_lang="ja",
        codec="hevc",
        subtitles=subs,
    ))
    sub_actions = [a for a in result.actions if a.track_index == 0]
    assert any(a.kind == PolicyActionKind.keep_stream for a in sub_actions)


# ---------------------------------------------------------------------------
# Audio rules
# ---------------------------------------------------------------------------

def test_commentary_track_removed(evaluator):
    audio = [AudioTrackFacts(
        track_index=0, language="en", track_type=AudioTrackType.commentary
    )]
    result = evaluator.evaluate(_facts(audio=audio))
    audio_actions = [a for a in result.actions if a.track_index == 0]
    assert any(a.kind == PolicyActionKind.remove_stream for a in audio_actions)


def test_original_language_audio_kept(evaluator):
    audio = [AudioTrackFacts(track_index=0, language="en")]
    result = evaluator.evaluate(_facts(original_lang="en", audio=audio))
    audio_actions = [a for a in result.actions if a.track_index == 0]
    assert any(a.kind == PolicyActionKind.keep_stream for a in audio_actions)


def test_english_audio_kept_for_international(evaluator):
    audio = [
        AudioTrackFacts(track_index=0, language="ja"),
        AudioTrackFacts(track_index=1, language="en"),
    ]
    result = evaluator.evaluate(_facts(
        domain=MediaDomain.international_live_action_movie,
        original_lang="ja",
        codec="hevc",
        audio=audio,
    ))
    en_actions = [a for a in result.actions if a.track_index == 1]
    assert any(a.kind == PolicyActionKind.keep_stream for a in en_actions)


def test_no_stereo_triggers_fallback_creation(evaluator):
    audio = [AudioTrackFacts(track_index=0, language="en", is_stereo=False)]
    result = evaluator.evaluate(_facts(audio=audio))
    kinds = {a.kind for a in result.actions}
    assert PolicyActionKind.create_stereo_fallback in kinds


def test_stereo_present_no_fallback(evaluator):
    audio = [AudioTrackFacts(track_index=0, language="en", is_stereo=True)]
    result = evaluator.evaluate(_facts(audio=audio))
    kinds = {a.kind for a in result.actions}
    assert PolicyActionKind.create_stereo_fallback not in kinds


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

def test_result_requires_review_aggregate(evaluator):
    subs = [SubtitleTrackFacts(track_index=0, language="unknown")]
    result = evaluator.evaluate(_facts(subtitles=subs))
    # quarantine_subtitle sets requires_review=True on the action
    assert result.requires_review is True


def test_result_no_review_clean_file(evaluator):
    audio = [AudioTrackFacts(track_index=0, language="en", is_stereo=True)]
    subs = [SubtitleTrackFacts(track_index=1, language="en")]
    result = evaluator.evaluate(_facts(codec="hevc", audio=audio, subtitles=subs))
    assert result.requires_review is False
