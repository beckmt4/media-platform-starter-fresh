from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class SubtitleUniversalPolicy(BaseModel):
    keep_forced: bool = True
    keep_english: bool = True
    quarantine_unknown_language: bool = True
    delete_exact_duplicates: bool = True
    keep_original_language_subtitles_when_present: bool = True


class SubtitleDomainPolicy(BaseModel):
    keep_sdh_english: bool = False
    keep_original_language_subtitles_when_present: bool | None = None
    keep_english: bool | None = None
    keep_signs_songs_when_present: bool = False
    keep_full_english: bool = False
    generate_english_if_missing: bool = False
    require_review_below_confidence: float | None = None


class SubtitlePolicy(BaseModel):
    version: int = 1
    universal: SubtitleUniversalPolicy = Field(default_factory=SubtitleUniversalPolicy)
    domains: dict[str, SubtitleDomainPolicy] = Field(default_factory=dict)


class AudioUniversalPolicy(BaseModel):
    preserve_original_language: bool = True
    preserve_english_if_available: bool = True
    remove_commentary_by_default: bool = True
    create_stereo_fallback_when_missing: bool = True


class AudioDomainPolicy(BaseModel):
    preferred_original_languages: list[str] = Field(default_factory=list)
    preferred_english: bool = False
    preserve_japanese_or_detected_original: bool = False
    preserve_english_if_available: bool | None = None
    preserve_detected_original: bool = False


class AudioPolicy(BaseModel):
    version: int = 1
    universal: AudioUniversalPolicy = Field(default_factory=AudioUniversalPolicy)
    domains: dict[str, AudioDomainPolicy] = Field(default_factory=dict)


class TranscodeUniversalPolicy(BaseModel):
    target_video_codec: str = "hevc"
    container: str = "mkv"
    skip_if_already_hevc: bool = True
    protect_remux: bool = True
    protect_high_bitrate_hdr_when_gpu_budget_is_poor: bool = True


class TranscodeDomainPolicy(BaseModel):
    allow_nvenc: bool = False
    tolerate_higher_compression: bool = False
    manual_review_for_banding_risk: bool = False
    skip_low_value_retranscodes: bool = False


class TranscodePolicy(BaseModel):
    version: int = 1
    universal: TranscodeUniversalPolicy = Field(default_factory=TranscodeUniversalPolicy)
    domains: dict[str, TranscodeDomainPolicy] = Field(default_factory=dict)


class LoadedPolicies(BaseModel):
    subtitle: SubtitlePolicy
    audio: AudioPolicy
    transcode: TranscodePolicy


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_policies(policies_dir: Path) -> LoadedPolicies:
    """Load and validate all policy files from the given directory."""
    return LoadedPolicies(
        subtitle=SubtitlePolicy.model_validate(
            _load_yaml(policies_dir / "subtitles.yaml")
        ),
        audio=AudioPolicy.model_validate(
            _load_yaml(policies_dir / "audio.yaml")
        ),
        transcode=TranscodePolicy.model_validate(
            _load_yaml(policies_dir / "transcode.yaml")
        ),
    )
