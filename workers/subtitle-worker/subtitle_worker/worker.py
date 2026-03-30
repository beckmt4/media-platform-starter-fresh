from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from .models import JobStatus, SubtitleJob, SubtitleJobResult

log = logging.getLogger("subtitle_worker.worker")

# Required runtime tools per job type.
_REQUIRED_TOOLS: dict[str, list[str]] = {
    "generate": ["whisper", "python"],   # faster-whisper exposed as 'whisper' CLI
    "repair": [],                         # pure Python / ffmpeg optional
    "translate": [],                      # pure Python stub
}


def _check_tools(job_type: str) -> list[str]:
    """Return list of missing tool names."""
    missing = []
    for tool in _REQUIRED_TOOLS.get(job_type, []):
        if tool != "python" and not shutil.which(tool):
            missing.append(tool)
    return missing


class SubtitleWorker:
    """Stateless subtitle job executor.

    Stub behaviour:
    - dry_run=True: validates inputs and returns skipped.
    - File missing: returns failed.
    - Required tool missing: returns tool_unavailable.
    - Otherwise: would invoke faster-whisper / repair logic.
      In this stub, returns complete with placeholder output path.

    Original and English audio tracks are never removed. Subtitle generation
    always targets a new file — the source media file is never mutated.
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

        # Validate source file exists
        src = Path(job.file_path)
        if not src.exists():
            return _result(
                status=JobStatus.failed,
                error_message=f"source file not found: {job.file_path}",
            )

        # Check required tools
        missing = _check_tools(job.job_type.value)
        if missing:
            return _result(
                status=JobStatus.tool_unavailable,
                error_message=f"required tools not on PATH: {', '.join(missing)}",
                notes=[f"install faster-whisper and ensure 'whisper' is on PATH"],
            )

        if job.dry_run:
            return _result(
                status=JobStatus.skipped,
                notes=[f"dry_run=True — would run {job.job_type.value} on {job.file_path!r}"],
            )

        # --- Real execution would happen here ---
        # faster-whisper / repair / translate logic is not implemented in this stub.
        # When implemented:
        #   generate  → subprocess faster-whisper → output .srt / .ass
        #   repair    → parse + re-time existing subtitle
        #   translate → translate subtitle lines to target_language
        output_dir = Path(job.output_dir) if job.output_dir else src.parent
        stem = src.stem
        output_path = str(output_dir / f"{stem}.{job.target_language}.srt")

        return _result(
            status=JobStatus.complete,
            output_path=output_path,
            detected_language=job.source_language or job.target_language,
            confidence=None,   # populated by real implementation
            notes=["stub: real execution not implemented — see worker.py"],
        )


def status() -> dict:
    """Return tool availability for health / status checks."""
    tools = {
        "whisper": bool(shutil.which("whisper")),
        "ffmpeg": bool(shutil.which("ffmpeg")),
    }
    available = all(tools.values())
    return {
        "status": "ready" if available else "degraded",
        "tools": tools,
    }
