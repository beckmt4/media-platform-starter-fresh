from __future__ import annotations

from subtitle_intel.models import ScanStatus, SubtitleTrackType
from subtitle_intel.scanner import SubtitleScanner, _classify_track_type, _normalise_language

scanner = SubtitleScanner()


# ---------------------------------------------------------------------------
# Language normalisation
# ---------------------------------------------------------------------------

def test_normalise_iso_639_1_passthrough():
    lang, conf = _normalise_language("en")
    assert lang == "en"
    assert conf == 1.0


def test_normalise_iso_639_2_to_iso_639_1():
    assert _normalise_language("eng") == ("en", 1.0)
    assert _normalise_language("jpn") == ("ja", 1.0)
    assert _normalise_language("fre") == ("fr", 1.0)
    assert _normalise_language("deu") == ("de", 1.0)


def test_normalise_none_returns_unknown():
    lang, conf = _normalise_language(None)
    assert lang == "unknown"
    assert conf == 0.0


def test_normalise_empty_string_returns_unknown():
    lang, conf = _normalise_language("")
    assert lang == "unknown"
    assert conf == 0.0


# ---------------------------------------------------------------------------
# Track type classification
# ---------------------------------------------------------------------------

def test_classify_forced_flag():
    assert _classify_track_type(is_forced=True, title=None) == SubtitleTrackType.forced


def test_classify_sdh_by_title():
    assert _classify_track_type(False, "English SDH") == SubtitleTrackType.sdh
    assert _classify_track_type(False, "English (Hearing Impaired)") == SubtitleTrackType.sdh
    assert _classify_track_type(False, "CC") == SubtitleTrackType.sdh


def test_classify_signs_songs_by_title():
    assert _classify_track_type(False, "Signs & Songs") == SubtitleTrackType.signs_songs
    assert _classify_track_type(False, "Signs and Songs") == SubtitleTrackType.signs_songs
    assert _classify_track_type(False, "Forced Subs") == SubtitleTrackType.signs_songs


def test_classify_full_fallback():
    assert _classify_track_type(False, "English") == SubtitleTrackType.full
    assert _classify_track_type(False, None) == SubtitleTrackType.full


# ---------------------------------------------------------------------------
# Anime fixture parsing
# ---------------------------------------------------------------------------

def test_anime_track_count(mediainfo_anime):
    result = scanner.scan("/fake/path.mkv", mediainfo_json=mediainfo_anime)
    assert result.status == ScanStatus.ok
    assert len(result.subtitle_tracks) == 4


def test_anime_has_english(mediainfo_anime):
    result = scanner.scan("/fake/path.mkv", mediainfo_json=mediainfo_anime)
    assert result.has_english is True


def test_anime_forced_track_detected(mediainfo_anime):
    result = scanner.scan("/fake/path.mkv", mediainfo_json=mediainfo_anime)
    forced = [t for t in result.subtitle_tracks if t.track_type == SubtitleTrackType.forced]
    assert len(forced) == 1
    assert forced[0].detected_language == "en"


def test_anime_signs_songs_track_detected(mediainfo_anime):
    result = scanner.scan("/fake/path.mkv", mediainfo_json=mediainfo_anime)
    ss = [t for t in result.subtitle_tracks if t.track_type == SubtitleTrackType.signs_songs]
    assert len(ss) == 1


def test_anime_japanese_track_present(mediainfo_anime):
    result = scanner.scan("/fake/path.mkv", mediainfo_json=mediainfo_anime)
    ja = [t for t in result.subtitle_tracks if t.detected_language == "ja"]
    assert len(ja) == 1


def test_anime_track_indices_sequential(mediainfo_anime):
    result = scanner.scan("/fake/path.mkv", mediainfo_json=mediainfo_anime)
    indices = [t.track_index for t in result.subtitle_tracks]
    assert indices == list(range(len(result.subtitle_tracks)))


# ---------------------------------------------------------------------------
# Domestic fixture parsing
# ---------------------------------------------------------------------------

def test_domestic_sdh_track_detected(mediainfo_domestic):
    result = scanner.scan("/fake/movie.mkv", mediainfo_json=mediainfo_domestic)
    sdh = [t for t in result.subtitle_tracks if t.track_type == SubtitleTrackType.sdh]
    assert len(sdh) == 1
    assert sdh[0].detected_language == "en"


def test_domestic_full_english_track(mediainfo_domestic):
    result = scanner.scan("/fake/movie.mkv", mediainfo_json=mediainfo_domestic)
    full = [
        t for t in result.subtitle_tracks
        if t.track_type == SubtitleTrackType.full and t.detected_language == "en"
    ]
    assert len(full) == 1
    assert full[0].is_default is True


def test_domestic_french_track(mediainfo_domestic):
    result = scanner.scan("/fake/movie.mkv", mediainfo_json=mediainfo_domestic)
    fr = [t for t in result.subtitle_tracks if t.detected_language == "fr"]
    assert len(fr) == 1


# ---------------------------------------------------------------------------
# No language tag → unknown
# ---------------------------------------------------------------------------

def test_no_lang_tag_returns_unknown(mediainfo_no_lang_tag):
    result = scanner.scan("/fake/title.mkv", mediainfo_json=mediainfo_no_lang_tag)
    assert result.status == ScanStatus.ok
    assert len(result.subtitle_tracks) == 1
    track = result.subtitle_tracks[0]
    assert track.detected_language == "unknown"
    assert track.confidence == 0.0
    assert result.has_unknown_language is True
    assert result.requires_review is True


# ---------------------------------------------------------------------------
# No subtitle tracks
# ---------------------------------------------------------------------------

def test_no_subtitle_tracks_status(mediainfo_no_subtitles):
    result = scanner.scan("/fake/nosubs.mkv", mediainfo_json=mediainfo_no_subtitles)
    assert result.status == ScanStatus.no_subtitle_tracks
    assert result.subtitle_tracks == []


# ---------------------------------------------------------------------------
# File not found (no mediainfo_json supplied)
# ---------------------------------------------------------------------------

def test_file_not_found():
    result = scanner.scan("/does/not/exist/file.mkv")
    assert result.status == ScanStatus.file_not_found
    assert "not found" in (result.error_message or "")


# ---------------------------------------------------------------------------
# Malformed mediainfo JSON
# ---------------------------------------------------------------------------

def test_malformed_mediainfo_json():
    result = scanner.scan("/fake/path.mkv", mediainfo_json={"bad": "structure"})
    assert result.status == ScanStatus.mediainfo_error
