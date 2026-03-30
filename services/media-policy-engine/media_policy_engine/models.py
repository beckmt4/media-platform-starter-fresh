from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared domain enum (must stay in sync with config/media-domains.yaml)
# ---------------------------------------------------------------------------

class MediaDomain(StrEnum):
    domestic_live_action_movie = "domestic_live_action_movie"
    domestic_live_action_tv = "domestic_live_action_tv"
    international_live_action_movie = "international_live_action_movie"
    international_live_action_tv = "international_live_action_tv"
    domestic_animated_movie = "domestic_animated_movie"
    domestic_animated_tv = "domestic_animated_tv"
    international_animated_movie = "international_animated_movie"
    international_animated_tv = "international_animated_tv"
    anime_movie = "anime_movie"
    anime_series = "anime_series"
    jav_adult = "jav_adult"


# ---------------------------------------------------------------------------
# Input: inspected media facts
# ---------------------------------------------------------------------------

class SubtitleTrackType(StrEnum):
    forced = "forced"
    sdh = "sdh"
    signs_songs = "signs_songs"
    full = "full"
    unknown = "unknown"


class AudioTrackType(StrEnum):
    original = "original"
    commentary = "commentary"
    stereo_fallback = "stereo_fallback"
    descriptive = "descriptive"
    unknown = "unknown"


class SubtitleTrackFacts(BaseModel):
    track_index: int
    language: str  # ISO 639-1 / BCP-47, e.g. "en", "ja", "unknown"
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    track_type: SubtitleTrackType = SubtitleTrackType.full


class AudioTrackFacts(BaseModel):
    track_index: int
    language: str  # ISO 639-1 / BCP-47
    track_type: AudioTrackType = AudioTrackType.original
    is_stereo: bool = False


class VideoFacts(BaseModel):
    codec: str  # "hevc", "h264", "av1", etc.
    is_remux: bool = False
    is_hdr: bool = False
    bitrate_mbps: float | None = None


class MediaFacts(BaseModel):
    """All inspected facts about a single media file needed for policy evaluation."""

    domain: MediaDomain
    file_path: str | None = None
    detected_original_language: str  # primary language of the content, e.g. "en", "ja"
    video: VideoFacts
    audio_tracks: list[AudioTrackFacts] = Field(default_factory=list)
    subtitle_tracks: list[SubtitleTrackFacts] = Field(default_factory=list)
    # Tags already applied by the catalog (e.g. "manual-source" blocks upgrades)
    catalog_tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Output: policy actions
# ---------------------------------------------------------------------------

class PolicyActionKind(StrEnum):
    keep_stream = "keep_stream"
    relabel_stream = "relabel_stream"
    quarantine_subtitle = "quarantine_subtitle"
    generate_english_subtitles = "generate_english_subtitles"
    remove_stream = "remove_stream"
    skip_transcode = "skip_transcode"
    flag_for_transcode = "flag_for_transcode"
    create_stereo_fallback = "create_stereo_fallback"
    send_to_review = "send_to_review"


class StreamTarget(StrEnum):
    subtitle = "subtitle"
    audio = "audio"
    video = "video"
    file = "file"


class PolicyAction(BaseModel):
    kind: PolicyActionKind
    stream_target: StreamTarget
    track_index: int | None = None  # None means the action applies to the whole file
    reason: str
    requires_review: bool = False


class PolicyEvaluationResult(BaseModel):
    domain: MediaDomain
    file_path: str | None = None
    actions: list[PolicyAction]
    requires_review: bool  # True if any action has requires_review=True
    evaluation_notes: list[str] = Field(default_factory=list)
