from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from .models import JobStatus, TranscodeJob, TranscodeJobResult

log = logging.getLogger("transcode_worker.worker")

_REQUIRED_TOOLS = ["ffmpeg", "ffprobe"]

# Hardware encoder names by codec
_NVENC_ENCODERS = {"hevc": "hevc_nvenc", "h264": "h264_nvenc", "av1": "av1_nvenc"}
_SW_ENCODERS = {"hevc": "libx265", "h264": "libx264", "av1": "libaom-av1"}


def _check_tools() -> list[str]:
    return [t for t in _REQUIRED_TOOLS if not shutil.which(t)]


def _pick_encoder(target_codec: str, allow_nvenc: bool) -> str:
    if allow_nvenc and shutil.which("nvidia-smi"):
        return _NVENC_ENCODERS.get(target_codec, f"{target_codec}_nvenc")
    return _SW_ENCODERS.get(target_codec, f"lib{target_codec}")


class TranscodeWorker:
    """Stateless transcode job executor.

    Stub behaviour:
    - dry_run=True: validates inputs, resolves encoder, returns skipped.
    - Source == destination: returns failed (never overwrite in place).
    - Source file missing: returns failed.
    - ffmpeg/ffprobe missing: returns tool_unavailable.
    - Otherwise: would invoke ffmpeg. In this stub returns complete with
      placeholder result.

    Source files are never deleted or overwritten. The caller is responsible
    for moving the output to its final location and updating catalog state.
    Reversibility is enforced by always writing to a separate output_path.
    """

    def run(self, job: TranscodeJob) -> TranscodeJobResult:
        log.info(
            "transcode job start job_id=%s codec=%s nvenc=%s file=%r dry_run=%s",
            job.job_id, job.target_codec, job.allow_nvenc, job.file_path, job.dry_run,
        )
        start = time.monotonic()

        result = self._run(job)
        result.duration_seconds = round(time.monotonic() - start, 3)

        log.info(
            "transcode job end job_id=%s status=%s duration=%.3fs",
            job.job_id, result.status, result.duration_seconds,
        )
        return result

    def _run(self, job: TranscodeJob) -> TranscodeJobResult:
        def _result(**kwargs) -> TranscodeJobResult:
            return TranscodeJobResult(
                job_id=job.job_id,
                item_id=job.item_id,
                **kwargs,
            )

        # Never transcode in place
        if Path(job.file_path).resolve() == Path(job.output_path).resolve():
            return _result(
                status=JobStatus.failed,
                error_message="output_path must differ from file_path — in-place transcode is not allowed",
            )

        src = Path(job.file_path)
        if not src.exists():
            return _result(
                status=JobStatus.failed,
                error_message=f"source file not found: {job.file_path}",
            )

        missing = _check_tools()
        if missing:
            return _result(
                status=JobStatus.tool_unavailable,
                error_message=f"required tools not on PATH: {', '.join(missing)}",
                notes=["install ffmpeg and ffprobe"],
            )

        encoder = _pick_encoder(job.target_codec, job.allow_nvenc)

        if job.dry_run:
            return _result(
                status=JobStatus.skipped,
                codec_used=encoder,
                size_bytes_before=src.stat().st_size,
                notes=[
                    f"dry_run=True — would encode with {encoder!r}",
                    f"output would be written to {job.output_path!r}",
                ],
            )

        # --- Real execution would happen here ---
        # ffmpeg invocation (not implemented in stub):
        #   ffmpeg -i <file_path>
        #          -map 0              (copy all streams)
        #          -c:v <encoder>      (re-encode video only)
        #          -c:a copy           (preserve audio — non-negotiable)
        #          -c:s copy           (preserve subtitles)
        #          <output_path>
        size_before = src.stat().st_size

        return _result(
            status=JobStatus.complete,
            output_path=job.output_path,
            codec_used=encoder,
            size_bytes_before=size_before,
            size_bytes_after=None,   # populated by real implementation
            notes=["stub: real ffmpeg execution not implemented — see worker.py"],
        )


def status() -> dict:
    """Return tool availability for health / status checks."""
    tools = {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "mkvmerge": bool(shutil.which("mkvmerge")),
        "nvidia-smi": bool(shutil.which("nvidia-smi")),
    }
    required_ok = tools["ffmpeg"] and tools["ffprobe"]
    return {
        "status": "ready" if required_ok else "degraded",
        "tools": tools,
    }
