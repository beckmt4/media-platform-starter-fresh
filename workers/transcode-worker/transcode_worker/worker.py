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


def _build_ffmpeg_cmd(job: TranscodeJob, encoder: str) -> list[str]:
    """Build ffmpeg command. Audio and subtitles are always copied; only video is re-encoded."""
    cmd = [
        "ffmpeg", "-y",
        "-i", job.file_path,
        "-map", "0",          # copy all streams
        "-c:v", encoder,      # re-encode video
        "-c:a", "copy",       # preserve audio — non-negotiable
        "-c:s", "copy",       # preserve subtitles
    ]
    if job.container == "mkv":
        cmd += ["-f", "matroska"]
    cmd.append(job.output_path)
    return cmd


def _notify_catalog(item_id: str, catalog_url: str) -> None:
    """Append transcode-complete tag to catalog item. Never raises."""
    try:
        get_req = urllib.request.Request(f"{catalog_url}/items/{item_id}")
        with urllib.request.urlopen(get_req, timeout=5) as resp:
            item = json.loads(resp.read())
        tags = item.get("tags", [])
        if "transcode-complete" not in tags:
            tags.append("transcode-complete")
        item["tags"] = tags
        patch_data = json.dumps(item).encode()
        patch_req = urllib.request.Request(
            f"{catalog_url}/items/{item_id}",
            data=patch_data,
            method="PATCH",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(patch_req, timeout=5)
        log.info("catalog notified item_id=%s tag=transcode-complete", item_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("catalog notify failed item_id=%s error=%s", item_id, exc)


class TranscodeWorker:
    """Stateless transcode job executor.

    - dry_run=True: validates inputs, resolves encoder, returns skipped.
    - Source == destination: returns failed (never overwrite in place).
    - Source file missing: returns failed.
    - ffmpeg/ffprobe missing: returns tool_unavailable.
    - ffmpeg non-zero exit: returns failed, output file removed if partial.
    - ffmpeg timeout: returns failed, output file removed if partial.
    - Otherwise: invokes ffmpeg, captures output size, notifies catalog.

    Source files are never deleted or overwritten. The caller is responsible
    for moving the output to its final location and updating catalog state.
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
                error_message=(
                    "output_path must differ from file_path"
                    " — in-place transcode is not allowed"
                ),
            )

        encoder = _pick_encoder(job.target_codec, job.allow_nvenc)

        if job.dry_run:
            src_for_size = Path(job.file_path)
            size_before = src_for_size.stat().st_size if src_for_size.exists() else None
            return _result(
                status=JobStatus.skipped,
                codec_used=encoder,
                size_bytes_before=size_before,
                notes=[
                    f"dry_run=True — would encode with {encoder!r}",
                    f"output would be written to {job.output_path!r}",
                ],
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

        size_before = src.stat().st_size
        out = Path(job.output_path)
        cmd = _build_ffmpeg_cmd(job, encoder)

        try:
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=7200,  # 2-hour hard limit
            )
        except subprocess.CalledProcessError as exc:
            _cleanup(out)
            stderr_tail = (exc.stderr or b"")[-1000:].decode(errors="replace")
            return _result(
                status=JobStatus.failed,
                codec_used=encoder,
                size_bytes_before=size_before,
                error_message=f"ffmpeg exited with code {exc.returncode}",
                notes=[f"stderr: {stderr_tail}"],
            )
        except subprocess.TimeoutExpired:
            _cleanup(out)
            return _result(
                status=JobStatus.failed,
                codec_used=encoder,
                size_bytes_before=size_before,
                error_message="ffmpeg timed out after 7200 seconds",
            )

        size_after = out.stat().st_size if out.exists() else None

        catalog_url = os.environ.get("CATALOG_API_URL", "").strip()
        if catalog_url and job.item_id:
            _notify_catalog(job.item_id, catalog_url)

        return _result(
            status=JobStatus.complete,
            output_path=job.output_path,
            codec_used=encoder,
            size_bytes_before=size_before,
            size_bytes_after=size_after,
        )


def _cleanup(path: Path) -> None:
    """Remove a partial output file, ignoring errors."""
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


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
