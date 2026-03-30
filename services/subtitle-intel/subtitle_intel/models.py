from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class SubtitleTrackType(StrEnum):
    forced = "forced"
    sdh = "sdh"
    signs_songs = "signs_songs"
    full = "full"
    unknown = "unknown"


class ScanStatus(StrEnum):
    ok = "ok"
    file_not_found = "file_not_found"
    mediainfo_error = "mediainfo_error"
    no_subtitle_tracks = "no_subtitle_tracks"


class SubtitleTrackInfo(BaseModel):
    """All known facts about a single subtitle track after inspection."""

    track_index: int
    codec: str | None = None  # e.g. "UTF-8", "ASS", "PGS", "VobSub"
    language_tag: str | None = None  # language from container metadata, ISO 639
    detected_language: str  # final language determination ("unknown" if unresolvable)
    confidence: float = Field(ge=0.0, le=1.0)
    track_type: SubtitleTrackType = SubtitleTrackType.full
    title: str | None = None  # track title from container metadata
    is_default: bool = False
    is_forced: bool = False


class ScanRequest(BaseModel):
    file_path: str
    # Optional: caller may supply the mediainfo JSON to avoid re-running the tool.
    mediainfo_json: dict | None = None


class ScanResult(BaseModel):
    file_path: str
    status: ScanStatus
    subtitle_tracks: list[SubtitleTrackInfo] = Field(default_factory=list)
    error_message: str | None = None

    @property
    def has_english(self) -> bool:
        return any(t.detected_language == "en" for t in self.subtitle_tracks)

    @property
    def has_unknown_language(self) -> bool:
        return any(t.detected_language == "unknown" for t in self.subtitle_tracks)

    @property
    def requires_review(self) -> bool:
        return self.has_unknown_language or self.status != ScanStatus.ok
