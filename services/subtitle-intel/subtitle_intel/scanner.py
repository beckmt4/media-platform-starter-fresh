from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from .models import (
    ScanResult,
    ScanStatus,
    SubtitleTrackInfo,
    SubtitleTrackType,
)

log = logging.getLogger("subtitle_intel.scanner")

# Track title keywords used to classify track type.
_SDH_KEYWORDS = {"sdh", "hearing impaired", "hi", "cc", "closed caption"}
_SIGNS_SONGS_KEYWORDS = {"signs", "songs", "signs & songs", "signs and songs", "forced subs"}


def _classify_track_type(is_forced: bool, title: str | None) -> SubtitleTrackType:
    if is_forced:
        return SubtitleTrackType.forced
    if title:
        lower = title.lower()
        if any(kw in lower for kw in _SDH_KEYWORDS):
            return SubtitleTrackType.sdh
        if any(kw in lower for kw in _SIGNS_SONGS_KEYWORDS):
            return SubtitleTrackType.signs_songs
    return SubtitleTrackType.full


def _normalise_language(raw: str | None) -> tuple[str, float]:
    """Return (language_code, confidence).

    Confidence is 1.0 when the tag comes from clean container metadata,
    0.0 when there is no tag (caller should escalate to audio-based detection).

    This stub does not call any language detection model. In production,
    tracks with confidence=0.0 would be submitted to faster-whisper or
    a langdetect pass.
    """
    if not raw:
        return "unknown", 0.0
    tag = raw.strip().lower()
    # Normalise common variants to ISO 639-1
    _ALIASES: dict[str, str] = {
        "eng": "en",
        "jpn": "ja",
        "zho": "zh",
        "chi": "zh",
        "fre": "fr",
        "fra": "fr",
        "ger": "de",
        "deu": "de",
        "spa": "es",
        "por": "pt",
        "kor": "ko",
        "ita": "it",
        "rus": "ru",
    }
    normalised = _ALIASES.get(tag, tag)
    return normalised, 1.0


def _parse_mediainfo_output(data: dict, file_path: str) -> ScanResult:
    """Parse a mediainfo --Output=JSON dict into a ScanResult.

    Only Text tracks are extracted. Track ordering follows the container order.
    """
    try:
        tracks = data["media"]["track"]
    except (KeyError, TypeError) as exc:
        return ScanResult(
            file_path=file_path,
            status=ScanStatus.mediainfo_error,
            error_message=f"unexpected mediainfo JSON structure: {exc}",
        )

    subtitle_tracks: list[SubtitleTrackInfo] = []
    subtitle_index = 0

    for track in tracks:
        if track.get("@type") != "Text":
            continue

        raw_lang = track.get("Language")
        detected_lang, confidence = _normalise_language(raw_lang)

        is_forced = track.get("Forced", "No").strip().lower() == "yes"
        is_default = track.get("Default", "No").strip().lower() == "yes"
        title = track.get("Title") or None
        codec = track.get("Format") or None

        track_type = _classify_track_type(is_forced, title)

        subtitle_tracks.append(SubtitleTrackInfo(
            track_index=subtitle_index,
            codec=codec,
            language_tag=raw_lang,
            detected_language=detected_lang,
            confidence=confidence,
            track_type=track_type,
            title=title,
            is_default=is_default,
            is_forced=is_forced,
        ))
        subtitle_index += 1

    if not subtitle_tracks:
        return ScanResult(
            file_path=file_path,
            status=ScanStatus.no_subtitle_tracks,
        )

    return ScanResult(
        file_path=file_path,
        status=ScanStatus.ok,
        subtitle_tracks=subtitle_tracks,
    )


class SubtitleScanner:
    """Inspects media files and returns subtitle track facts.

    Stub behaviour:
    - If the caller supplies ``mediainfo_json``, it is parsed directly
      (no subprocess, no file system access — safe for tests and CI).
    - If ``mediainfo_json`` is None and mediainfo is on PATH, it is invoked
      as a subprocess.
    - If mediainfo is not installed, returns a mediainfo_error status.

    Language detection in this stub is metadata-only. Tracks with no
    language tag receive detected_language="unknown" and confidence=0.0.
    A future implementation will submit those tracks to faster-whisper.
    """

    def scan(self, file_path: str, mediainfo_json: dict | None = None) -> ScanResult:
        path = Path(file_path)

        if mediainfo_json is not None:
            log.debug("scan: using supplied mediainfo_json for %s", file_path)
            return _parse_mediainfo_output(mediainfo_json, file_path)

        if not path.exists():
            return ScanResult(
                file_path=file_path,
                status=ScanStatus.file_not_found,
                error_message=f"file not found: {file_path}",
            )

        return self._scan_with_mediainfo(file_path)

    def _scan_with_mediainfo(self, file_path: str) -> ScanResult:
        if not shutil.which("mediainfo"):
            return ScanResult(
                file_path=file_path,
                status=ScanStatus.mediainfo_error,
                error_message="mediainfo is not installed or not on PATH",
            )

        try:
            result = subprocess.run(
                ["mediainfo", "--Output=JSON", file_path],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            )
        except subprocess.TimeoutExpired:
            return ScanResult(
                file_path=file_path,
                status=ScanStatus.mediainfo_error,
                error_message="mediainfo timed out",
            )
        except subprocess.CalledProcessError as exc:
            return ScanResult(
                file_path=file_path,
                status=ScanStatus.mediainfo_error,
                error_message=f"mediainfo exited {exc.returncode}: {exc.stderr.strip()}",
            )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return ScanResult(
                file_path=file_path,
                status=ScanStatus.mediainfo_error,
                error_message=f"mediainfo output is not valid JSON: {exc}",
            )

        return _parse_mediainfo_output(data, file_path)
