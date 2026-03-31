from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from .hasher import compute_media_id
from .models import (
    AudioTrackInfo,
    MediaBrainState,
    MediaItem,
    SubtitleTrackInfo,
    SubtitleTrackType,
    VideoTrackInfo,
)

log = logging.getLogger("media_brain.scanner")

_MEDIA_EXTENSIONS = frozenset({".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts"})
_SIDECAR_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".vtt"})

# Subtitle title keywords for track classification
_SDH_KEYWORDS = {"sdh", "hearing impaired", "hi", "cc", "closed caption"}
_SIGNS_SONGS_KEYWORDS = {"signs", "songs", "signs & songs", "signs and songs", "forced subs"}

# HDR transfer characteristic strings reported by mediainfo
_HDR_TRANSFER = {"PQ", "HLG", "SMPTE ST 2084"}


# ---------------------------------------------------------------------------
# Language normalisation (metadata-only; no model inference)
# ---------------------------------------------------------------------------

_LANG_ALIASES: dict[str, str] = {
    "eng": "en", "jpn": "ja", "zho": "zh", "chi": "zh",
    "fre": "fr", "fra": "fr", "ger": "de", "deu": "de",
    "spa": "es", "por": "pt", "kor": "ko", "ita": "it",
    "rus": "ru", "ara": "ar", "hin": "hi", "tha": "th",
}


def _normalise_language(raw: str | None) -> tuple[str, float]:
    """Return (iso_639_1_code, confidence). Confidence 0.0 when tag is absent."""
    if not raw:
        return "unknown", 0.0
    tag = raw.strip().lower()
    return _LANG_ALIASES.get(tag, tag), 1.0


# ---------------------------------------------------------------------------
# Track parsers
# ---------------------------------------------------------------------------

def _parse_video_tracks(tracks: list[dict]) -> list[VideoTrackInfo]:
    results: list[VideoTrackInfo] = []
    index = 0
    for track in tracks:
        if track.get("@type") != "Video":
            continue
        codec = track.get("Format") or None
        width = _int_or_none(track.get("Width"))
        height = _int_or_none(track.get("Height"))
        hdr_format = track.get("HDR_Format") or track.get("HDR_Format_String") or None
        transfer = track.get("transfer_characteristics") or track.get("transfer_characteristics_Original") or ""
        is_hdr = bool(hdr_format) or any(t in transfer for t in _HDR_TRANSFER)
        lang_tag = track.get("Language") or None
        results.append(VideoTrackInfo(
            track_index=index,
            codec=codec,
            width=width,
            height=height,
            is_hdr=is_hdr,
            hdr_format=hdr_format,
            language_tag=lang_tag,
        ))
        index += 1
    return results


def _parse_audio_tracks(tracks: list[dict]) -> list[AudioTrackInfo]:
    results: list[AudioTrackInfo] = []
    index = 0
    for track in tracks:
        if track.get("@type") != "Audio":
            continue
        codec = track.get("Format") or None
        lang_tag = track.get("Language") or None
        detected_lang, _ = _normalise_language(lang_tag)
        channels = _int_or_none(track.get("Channels"))
        is_default = track.get("Default", "No").strip().lower() == "yes"
        results.append(AudioTrackInfo(
            track_index=index,
            codec=codec,
            language_tag=lang_tag,
            detected_language=detected_lang,
            channels=channels,
            is_default=is_default,
        ))
        index += 1
    return results


def _parse_subtitle_tracks(tracks: list[dict]) -> list[SubtitleTrackInfo]:
    results: list[SubtitleTrackInfo] = []
    index = 0
    for track in tracks:
        if track.get("@type") != "Text":
            continue
        raw_lang = track.get("Language")
        detected_lang, confidence = _normalise_language(raw_lang)
        is_forced = track.get("Forced", "No").strip().lower() == "yes"
        is_default = track.get("Default", "No").strip().lower() == "yes"
        title = track.get("Title") or None
        codec = track.get("Format") or None
        track_type = _classify_subtitle_type(is_forced, title)
        results.append(SubtitleTrackInfo(
            track_index=index,
            codec=codec,
            language_tag=raw_lang,
            detected_language=detected_lang,
            confidence=confidence,
            track_type=track_type,
            title=title,
            is_default=is_default,
            is_forced=is_forced,
        ))
        index += 1
    return results


def _classify_subtitle_type(is_forced: bool, title: str | None) -> SubtitleTrackType:
    if is_forced:
        return SubtitleTrackType.forced
    if title:
        lower = title.lower()
        if any(kw in lower for kw in _SDH_KEYWORDS):
            return SubtitleTrackType.sdh
        if any(kw in lower for kw in _SIGNS_SONGS_KEYWORDS):
            return SubtitleTrackType.signs_songs
    return SubtitleTrackType.full


def _find_sidecars(file_path: str) -> list[str]:
    """Return paths of sidecar subtitle files adjacent to *file_path*."""
    path = Path(file_path)
    stem = path.stem
    parent = path.parent
    sidecars: list[str] = []
    for candidate in parent.iterdir():
        if candidate.suffix.lower() in _SIDECAR_EXTENSIONS and candidate.stem.startswith(stem):
            sidecars.append(str(candidate))
    return sorted(sidecars)


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        # mediainfo sometimes returns "2 channels" or "48 000" — take digits only
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        return int(digits) if digits else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def _parse_mediainfo(data: dict, file_path: str, file_size: int, media_id: str) -> MediaItem:
    try:
        tracks = data["media"]["track"]
    except (KeyError, TypeError) as exc:
        return MediaItem(
            media_id=media_id,
            file_path=file_path,
            file_size=file_size,
            state=MediaBrainState.error,
            error_message=f"unexpected mediainfo JSON structure: {exc}",
        )

    # General track holds container-level info
    general = next((t for t in tracks if t.get("@type") == "General"), {})
    container_format = general.get("Format") or None
    duration_raw = general.get("Duration")
    duration_seconds: float | None = None
    if duration_raw is not None:
        try:
            duration_seconds = float(duration_raw)
        except (ValueError, TypeError):
            pass

    video_tracks = _parse_video_tracks(tracks)
    audio_tracks = _parse_audio_tracks(tracks)
    subtitle_tracks = _parse_subtitle_tracks(tracks)
    sidecar_files = _find_sidecars(file_path)

    return MediaItem(
        media_id=media_id,
        file_path=file_path,
        file_size=file_size,
        state=MediaBrainState.needs_subtitle_review,
        container_format=container_format,
        duration_seconds=duration_seconds,
        video_tracks=video_tracks,
        audio_tracks=audio_tracks,
        subtitle_tracks=subtitle_tracks,
        sidecar_files=sidecar_files,
    )


class MediaBrainScanner:
    """Runs mediainfo on a file and returns a fully populated MediaItem.

    If ``mediainfo_json`` is supplied the subprocess is skipped — useful
    for tests and for callers that already have the output.
    """

    def scan_file(self, file_path: str, mediainfo_json: dict | None = None) -> MediaItem:
        path = Path(file_path)

        if not path.exists():
            return MediaItem(
                media_id="unknown",
                file_path=file_path,
                file_size=0,
                state=MediaBrainState.error,
                error_message=f"file not found: {file_path}",
            )

        try:
            media_id, file_size = compute_media_id(file_path)
        except OSError as exc:
            return MediaItem(
                media_id="unknown",
                file_path=file_path,
                file_size=0,
                state=MediaBrainState.error,
                error_message=f"could not stat file: {exc}",
            )

        if mediainfo_json is not None:
            log.debug("scan_file: using supplied mediainfo_json for %s", file_path)
            return _parse_mediainfo(mediainfo_json, file_path, file_size, media_id)

        return self._run_mediainfo(file_path, file_size, media_id)

    def scan_directory(
        self,
        directory: str,
        extensions: list[str] | None = None,
        recursive: bool = True,
    ) -> list[MediaItem]:
        exts = frozenset(e.lower() if e.startswith(".") else f".{e.lower()}" for e in (extensions or [".mkv", ".mp4", ".avi"]))
        root = Path(directory)
        if not root.is_dir():
            log.error("scan_directory: not a directory: %s", directory)
            return []

        pattern = "**/*" if recursive else "*"
        files = [p for p in root.glob(pattern) if p.is_file() and p.suffix.lower() in exts]
        log.info("scan_directory: found %d files under %s", len(files), directory)

        results: list[MediaItem] = []
        for f in files:
            log.debug("scan_directory: scanning %s", f)
            item = self.scan_file(str(f))
            results.append(item)
        return results

    def _run_mediainfo(self, file_path: str, file_size: int, media_id: str) -> MediaItem:
        if not shutil.which("mediainfo"):
            return MediaItem(
                media_id=media_id,
                file_path=file_path,
                file_size=file_size,
                state=MediaBrainState.error,
                error_message="mediainfo is not installed or not on PATH",
            )

        try:
            result = subprocess.run(
                ["mediainfo", "--Output=JSON", file_path],
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
        except subprocess.TimeoutExpired:
            return MediaItem(
                media_id=media_id,
                file_path=file_path,
                file_size=file_size,
                state=MediaBrainState.error,
                error_message="mediainfo timed out",
            )
        except subprocess.CalledProcessError as exc:
            return MediaItem(
                media_id=media_id,
                file_path=file_path,
                file_size=file_size,
                state=MediaBrainState.error,
                error_message=f"mediainfo exited {exc.returncode}: {exc.stderr.strip()}",
            )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return MediaItem(
                media_id=media_id,
                file_path=file_path,
                file_size=file_size,
                state=MediaBrainState.error,
                error_message=f"mediainfo output is not valid JSON: {exc}",
            )

        return _parse_mediainfo(data, file_path, file_size, media_id)
