from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MediaBrainState(StrEnum):
    needs_subtitle_review = "needs_subtitle_review"
    reviewed = "reviewed"
    error = "error"


class SubtitleTrackType(StrEnum):
    forced = "forced"
    sdh = "sdh"
    signs_songs = "signs_songs"
    full = "full"
    unknown = "unknown"


class VideoTrackInfo(BaseModel):
    track_index: int
    codec: str | None = None          # e.g. "HEVC", "AVC", "AV1"
    width: int | None = None
    height: int | None = None
    is_hdr: bool = False
    hdr_format: str | None = None     # e.g. "SMPTE ST 2086", "Dolby Vision"
    language_tag: str | None = None


class AudioTrackInfo(BaseModel):
    track_index: int
    codec: str | None = None          # e.g. "AAC", "AC-3", "DTS"
    language_tag: str | None = None   # raw container language tag
    detected_language: str = "unknown"
    channels: int | None = None
    is_default: bool = False


class SubtitleTrackInfo(BaseModel):
    track_index: int
    codec: str | None = None          # e.g. "UTF-8", "ASS", "PGS", "VobSub"
    language_tag: str | None = None   # raw container language tag
    detected_language: str = "unknown"
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    track_type: SubtitleTrackType = SubtitleTrackType.full
    title: str | None = None
    is_default: bool = False
    is_forced: bool = False


class MediaItem(BaseModel):
    """A fully scanned media file stored in media_brain.db."""

    media_id: str                             # SHA256(file_path + file_size)
    file_path: str
    file_size: int                            # bytes
    state: MediaBrainState = MediaBrainState.needs_subtitle_review
    container_format: str | None = None       # e.g. "Matroska", "MPEG-4"
    duration_seconds: float | None = None
    video_tracks: list[VideoTrackInfo] = Field(default_factory=list)
    audio_tracks: list[AudioTrackInfo] = Field(default_factory=list)
    subtitle_tracks: list[SubtitleTrackInfo] = Field(default_factory=list)
    sidecar_files: list[str] = Field(default_factory=list)  # absolute paths
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class FileScanRequest(BaseModel):
    file_path: str
    # Caller may supply mediainfo JSON to skip subprocess (useful in tests).
    mediainfo_json: dict | None = None


class DirectoryScanRequest(BaseModel):
    directory: str
    extensions: list[str] = Field(default_factory=lambda: [".mkv", ".mp4", ".avi"])
    recursive: bool = True


class DirectoryScanResponse(BaseModel):
    directory: str
    total_files: int
    scanned: int
    errors: int
    items: list[MediaItem]


class ItemListResponse(BaseModel):
    total: int
    items: list[MediaItem]
