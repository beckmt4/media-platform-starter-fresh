from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from .models import JobStatus, SubtitleJob, SubtitleJobResult

log = logging.getLogger("subtitle_worker.worker")

# Required runtime CLI tools per job type.
# faster-whisper availability is checked separately via _faster_whisper_available().
_REQUIRED_TOOLS: dict[str, list[str]] = {
    "generate": ["ffmpeg", "ffprobe"],
    "repair": [],
    "translate": [],
}

# Scratch directory for intermediate WAV files.
# Matches z4-media-01 /scratch (high-speed local NVMe); configurable per job.
_DEFAULT_SCRATCH_DIR = "/scratch/whisper_staging"

# Files longer than this (seconds) are chunked before transcription.
_CHUNK_THRESHOLD = 7200    # 2 hours
_CHUNK_DURATION = 1800     # 30-minute chunks
_CHUNK_OVERLAP = 30        # 30-second overlap between adjacent chunks


def _check_tools(job_type: str) -> list[str]:
    """Return list of missing tool names."""
    return [t for t in _REQUIRED_TOOLS.get(job_type, []) if not shutil.which(t)]


def _faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _pick_audio_stream(file_path: str, preferred_language: str | None = None) -> int:
    """Use ffprobe to find the best audio stream index.

    When preferred_language is given (e.g. "ja" for JAV), that language is
    selected first; falls back to the first audio track.  When
    preferred_language is None the default policy applies: English audio is
    preferred (preserve English audio when available), then first track.
    """
    # Normalise tag variants so callers can pass ISO 639-1 or ISO 639-2.
    _LANG_ALIASES: dict[str, set[str]] = {
        "en": {"en", "eng"},
        "ja": {"ja", "jpn"},
    }
    want: set[str] | None = None
    if preferred_language:
        key = preferred_language.lower()
        want = _LANG_ALIASES.get(key, {key})

    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams", "-select_streams", "a",
                file_path,
            ],
            timeout=30,
        )
        streams = json.loads(out).get("streams", [])

        if want:
            for s in streams:
                lang = s.get("tags", {}).get("language", "").lower()
                if lang in want:
                    log.debug(
                        "ffprobe selected preferred language=%s stream index=%d",
                        preferred_language, s["index"],
                    )
                    return s["index"]
        else:
            # Default: prefer English (policy: preserve English audio)
            for s in streams:
                lang = s.get("tags", {}).get("language", "").lower()
                if lang in ("eng", "en"):
                    log.debug("ffprobe selected English stream index=%d", s["index"])
                    return s["index"]

        if streams:
            log.debug("ffprobe fallback to first audio stream index=%d", streams[0]["index"])
            return streams[0]["index"]
    except Exception as exc:
        log.warning("ffprobe audio stream detection failed, defaulting to stream 0: %s", exc)
    return 0


def _get_media_duration(file_path: str) -> float | None:
    """Return file duration in seconds via ffprobe, or None on failure."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                file_path,
            ],
            timeout=30,
        )
        raw = json.loads(out).get("format", {}).get("duration")
        return float(raw) if raw is not None else None
    except Exception as exc:
        log.warning("ffprobe duration probe failed: %s", exc)
        return None


def _extract_audio(
    file_path: str,
    stream_index: int,
    out_path: str,
    *,
    start_seconds: float | None = None,
    duration_seconds: float | None = None,
) -> str:
    """Extract one audio stream to a 16 kHz mono WAV for whisper.

    16 kHz mono is the format faster-whisper expects for best accuracy.
    Writes to out_path directly (caller is responsible for the directory).
    start_seconds / duration_seconds enable chunked extraction.
    """
    cmd = ["ffmpeg", "-y"]
    if start_seconds is not None:
        cmd += ["-ss", str(start_seconds)]
    cmd += ["-i", file_path]
    if duration_seconds is not None:
        cmd += ["-t", str(duration_seconds)]
    cmd += [
        "-map", f"0:{stream_index}",
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        out_path,
    ]
    subprocess.check_call(
        cmd,
        timeout=600,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return out_path


def _extract_audio_chunks(
    file_path: str,
    stream_index: int,
    scratch_dir: Path,
    wav_stem: str,
    total_duration: float,
) -> list[tuple[Path, float]]:
    """Chunk a long file into 30-min WAV segments with 30-second overlap.

    Returns a list of (wav_path, chunk_start_time_seconds) tuples.
    """
    step = _CHUNK_DURATION - _CHUNK_OVERLAP  # 1770 s between chunk starts
    chunks: list[tuple[Path, float]] = []
    chunk_index = 0
    start = 0.0
    while start < total_duration:
        out_path = scratch_dir / f"{wav_stem}_chunk{chunk_index}.wav"
        log.debug(
            "extracting chunk %d start=%.1fs duration=%ds → %s",
            chunk_index, start, _CHUNK_DURATION, out_path,
        )
        _extract_audio(
            file_path, stream_index, str(out_path),
            start_seconds=start,
            duration_seconds=_CHUNK_DURATION,
        )
        chunks.append((out_path, start))
        chunk_index += 1
        start += step
    return chunks


def _write_srt(segments: list, output_path: Path) -> None:
    """Serialize faster-whisper Segment objects to an SRT file."""

    def _ts(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int(round((t % 1) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with output_path.open("w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{_ts(seg.start)} --> {_ts(seg.end)}\n")
            f.write(f"{seg.text.strip()}\n\n")


def _notify_catalog(item_id: str, catalog_url: str) -> None:
    """PATCH catalog-api to append subtitle-complete tag on the media item.

    Fire-and-forget: logs a warning on failure but never raises.
    """
    base = catalog_url.rstrip("/")
    try:
        req = urllib.request.Request(f"{base}/items/{item_id}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            item = json.loads(resp.read())
        tags: list[str] = item.get("tags", [])
        if "subtitle-complete" not in tags:
            tags.append("subtitle-complete")
        data = json.dumps({"tags": tags}).encode()
        patch = urllib.request.Request(
            f"{base}/items/{item_id}",
            data=data,
            method="PATCH",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(patch, timeout=5)
        log.info("catalog notified item_id=%s tags=%s", item_id, tags)
    except (urllib.error.URLError, OSError, Exception) as exc:
        log.warning("catalog notify failed item_id=%s: %s", item_id, exc)


class SubtitleWorker:
    """Stateless subtitle job executor.

    generate  → ffprobe picks audio stream → ffmpeg extracts 16 kHz mono WAV
              → faster-whisper transcribes → writes .{lang}.srt
              → optionally PATCHes catalog-api (CATALOG_API_URL env var)

    repair    → stub (not yet implemented)
    translate → stub (not yet implemented)

    The source media file is never mutated. Output is always a new .srt file.
    Original and English audio tracks are preserved.
    """

    def run(self, job: SubtitleJob) -> SubtitleJobResult:
        log.info(
            "subtitle job start job_id=%s type=%s file=%r dry_run=%s",
            job.job_id, job.job_type, job.file_path, job.dry_run,
        )
        start = time.monotonic()
        result = self._run(job)
        result.duration_seconds = round(time.monotonic() - start, 3)
        log.info(
            "subtitle job end job_id=%s status=%s duration=%.3fs",
            job.job_id, result.status, result.duration_seconds,
        )
        return result

    def _run(self, job: SubtitleJob) -> SubtitleJobResult:
        def _result(**kwargs) -> SubtitleJobResult:
            return SubtitleJobResult(
                job_id=job.job_id,
                item_id=job.item_id,
                job_type=job.job_type,
                **kwargs,
            )

        if job.dry_run:
            return _result(
                status=JobStatus.skipped,
                notes=[f"dry_run=True — would run {job.job_type.value} on {job.file_path!r}"],
            )

        src = Path(job.file_path)
        if not src.exists():
            return _result(
                status=JobStatus.failed,
                error_message=f"source file not found: {job.file_path}",
            )

        missing = _check_tools(job.job_type.value)
        if missing:
            return _result(
                status=JobStatus.tool_unavailable,
                error_message=f"required tools not on PATH: {', '.join(missing)}",
                notes=["install ffmpeg and ffprobe and ensure they are on PATH"],
            )

        if job.job_type.value == "generate":
            return self._run_generate(job, src, _result)

        # repair / translate — not yet implemented
        return _result(
            status=JobStatus.skipped,
            notes=[f"{job.job_type.value} not yet implemented"],
        )

    def _run_generate(self, job: SubtitleJob, src: Path, _result) -> SubtitleJobResult:
        if not _faster_whisper_available():
            return _result(
                status=JobStatus.tool_unavailable,
                error_message="faster-whisper is not installed",
                notes=["pip install faster-whisper"],
            )

        output_dir = Path(job.output_dir) if job.output_dir else src.parent
        output_path = output_dir / f"{src.stem}.{job.target_language}.srt"

        # JAV files: source_language="ja" → prefer first/Japanese audio track.
        stream_index = _pick_audio_stream(str(src), preferred_language=job.source_language)

        scratch_dir = Path(job.scratch_dir) if job.scratch_dir else Path(_DEFAULT_SCRATCH_DIR)
        scratch_dir.mkdir(parents=True, exist_ok=True)
        wav_stem = job.media_id or job.job_id

        # Track all WAV paths for cleanup in the finally block.
        wav_paths: list[Path] = []
        info = None
        try:
            duration = _get_media_duration(str(src))
            chunked = duration is not None and duration > _CHUNK_THRESHOLD

            if chunked:
                log.info(
                    "job_id=%s duration=%.0fs > %ds — using chunked audio extraction",
                    job.job_id, duration, _CHUNK_THRESHOLD,
                )
                try:
                    chunk_list = _extract_audio_chunks(
                        str(src), stream_index, scratch_dir, wav_stem, duration,
                    )
                except subprocess.CalledProcessError as exc:
                    return _result(
                        status=JobStatus.failed,
                        error_message=f"audio extraction failed (exit {exc.returncode})",
                    )
                except subprocess.TimeoutExpired:
                    return _result(
                        status=JobStatus.failed,
                        error_message="audio extraction timed out",
                    )
                wav_paths = [p for p, _ in chunk_list]
            else:
                wav_path = scratch_dir / f"{wav_stem}.wav"
                try:
                    _extract_audio(str(src), stream_index, str(wav_path))
                except subprocess.CalledProcessError as exc:
                    return _result(
                        status=JobStatus.failed,
                        error_message=f"audio extraction failed (exit {exc.returncode})",
                    )
                except subprocess.TimeoutExpired:
                    return _result(
                        status=JobStatus.failed,
                        error_message="audio extraction timed out",
                    )
                wav_paths = [wav_path]
                chunk_list = [(wav_path, 0.0)]

            # Transcribe — one pass per chunk, merge with absolute timestamps.
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel(job.whisper_model, device="cpu", compute_type="int8")
                all_segments: list = []
                for i, (chunk_wav, chunk_start) in enumerate(chunk_list):
                    segs_gen, info = model.transcribe(
                        str(chunk_wav),
                        language=job.source_language,
                        beam_size=5,
                    )
                    for seg in segs_gen:
                        # Drop the overlap region from non-first chunks to avoid
                        # duplicate speech at chunk boundaries.
                        if i > 0 and seg.start < _CHUNK_OVERLAP:
                            continue
                        all_segments.append(SimpleNamespace(
                            start=seg.start + chunk_start,
                            end=seg.end + chunk_start,
                            text=seg.text,
                        ))
            except Exception as exc:
                return _result(
                    status=JobStatus.failed,
                    error_message=f"transcription failed: {exc}",
                )

        finally:
            for p in wav_paths:
                try:
                    p.unlink(missing_ok=True)
                except OSError as exc:
                    log.warning("failed to remove scratch WAV %s: %s", p, exc)

        # Write SRT
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            _write_srt(all_segments, output_path)
        except OSError as exc:
            return _result(
                status=JobStatus.failed,
                error_message=f"failed to write SRT: {exc}",
            )

        log.info(
            "transcription complete job_id=%s lang=%s confidence=%.3f segments=%d output=%r",
            job.job_id, info.language, info.language_probability,
            len(all_segments), str(output_path),
        )

        catalog_url = os.environ.get("CATALOG_API_URL", "").strip()
        if catalog_url and job.item_id:
            _notify_catalog(job.item_id, catalog_url)

        notes = [
            f"model={job.whisper_model}",
            f"audio_stream={stream_index}",
            f"segments={len(all_segments)}",
        ]
        if chunked:
            notes.append(f"chunks={len(chunk_list)}")

        return _result(
            status=JobStatus.complete,
            output_path=str(output_path),
            detected_language=info.language,
            confidence=round(info.language_probability, 4),
            notes=notes,
        )


def status() -> dict:
    """Return tool availability for health / status checks."""
    tools = {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "faster_whisper": _faster_whisper_available(),
    }
    return {
        "status": "ready" if all(tools.values()) else "degraded",
        "tools": tools,
    }
