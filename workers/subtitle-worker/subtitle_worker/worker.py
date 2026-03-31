from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .models import JobStatus, SubtitleJob, SubtitleJobResult

log = logging.getLogger("subtitle_worker.worker")

# Required runtime CLI tools per job type.
# faster-whisper availability is checked separately via _faster_whisper_available().
_REQUIRED_TOOLS: dict[str, list[str]] = {
    "generate": ["ffmpeg", "ffprobe"],
    "repair": [],
    "translate": [],
}


def _check_tools(job_type: str) -> list[str]:
    """Return list of missing tool names."""
    return [t for t in _REQUIRED_TOOLS.get(job_type, []) if not shutil.which(t)]


def _faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _pick_audio_stream(file_path: str) -> int:
    """Use ffprobe to find the best audio stream index.

    Preference: English audio track → first audio track → 0.
    Honours the policy: preserve English audio when available.
    """
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


def _extract_audio(file_path: str, stream_index: int, tmp_dir: str) -> str:
    """Extract one audio stream to a 16 kHz mono WAV for whisper.

    16 kHz mono is the format faster-whisper expects for best accuracy.
    """
    out_path = os.path.join(tmp_dir, "audio.wav")
    subprocess.check_call(
        [
            "ffmpeg", "-y",
            "-i", file_path,
            "-map", f"0:{stream_index}",
            "-ac", "1",
            "-ar", "16000",
            "-f", "wav",
            out_path,
        ],
        timeout=600,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return out_path


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

        stream_index = _pick_audio_stream(str(src))

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Extract selected audio stream to a temp WAV
            try:
                wav_path = _extract_audio(str(src), stream_index, tmp_dir)
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

            # Transcribe
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel(job.whisper_model, device="cpu", compute_type="int8")
                segments_gen, info = model.transcribe(
                    wav_path,
                    language=job.source_language,
                    beam_size=5,
                )
                segments = list(segments_gen)  # consume generator inside context
            except Exception as exc:
                return _result(
                    status=JobStatus.failed,
                    error_message=f"transcription failed: {exc}",
                )

        # Write SRT (outside tmp_dir context — wav already consumed)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            _write_srt(segments, output_path)
        except OSError as exc:
            return _result(
                status=JobStatus.failed,
                error_message=f"failed to write SRT: {exc}",
            )

        log.info(
            "transcription complete job_id=%s lang=%s confidence=%.3f segments=%d output=%r",
            job.job_id, info.language, info.language_probability,
            len(segments), str(output_path),
        )

        catalog_url = os.environ.get("CATALOG_API_URL", "").strip()
        if catalog_url and job.item_id:
            _notify_catalog(job.item_id, catalog_url)

        return _result(
            status=JobStatus.complete,
            output_path=str(output_path),
            detected_language=info.language,
            confidence=round(info.language_probability, 4),
            notes=[
                f"model={job.whisper_model}",
                f"audio_stream={stream_index}",
                f"segments={len(segments)}",
            ],
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
