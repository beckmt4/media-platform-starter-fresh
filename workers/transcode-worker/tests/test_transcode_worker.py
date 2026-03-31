from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

from transcode_worker.models import JobStatus, TranscodeJob, TranscodeJobResult
from transcode_worker.worker import (
    TranscodeWorker,
    _build_ffmpeg_cmd,
    _notify_catalog,
    _pick_encoder,
    status,
)

worker = TranscodeWorker()


def _job(
    file_path: str = "/nonexistent/src.mkv",
    output_path: str = "/nonexistent/out.mkv",
    item_id: str = "item-xyz",
    **kwargs,
) -> TranscodeJob:
    return TranscodeJob(item_id=item_id, file_path=file_path, output_path=output_path, **kwargs)


def _patch_run_deps(monkeypatch, tmp_path, *, create_output: bool = True):
    """Patch shutil.which and subprocess.run for a successful transcode."""
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")

    def fake_run(cmd, *, check, stdout, stderr, timeout):
        if create_output:
            out = cmd[-1]  # last arg is output_path
            import pathlib
            pathlib.Path(out).write_bytes(b"x" * 512)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr("subprocess.run", fake_run)


# ---------------------------------------------------------------------------
# Model defaults
# ---------------------------------------------------------------------------

def test_job_defaults():
    job = _job()
    assert job.target_codec == "hevc"
    assert job.container == "mkv"
    assert job.allow_nvenc is False
    assert job.copy_streams is True
    assert job.dry_run is False
    assert job.job_id


def test_job_ids_unique():
    assert _job().job_id != _job().job_id


def test_result_model():
    r = TranscodeJobResult(job_id="j1", item_id="i1", status=JobStatus.complete)
    assert r.notes == []
    assert r.output_path is None


# ---------------------------------------------------------------------------
# Encoder selection
# ---------------------------------------------------------------------------

def test_pick_encoder_sw_hevc(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert _pick_encoder("hevc", allow_nvenc=True) == "libx265"


def test_pick_encoder_nvenc_when_available(monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda t: "/usr/bin/nvidia-smi" if t == "nvidia-smi" else None
    )
    assert _pick_encoder("hevc", allow_nvenc=True) == "hevc_nvenc"


def test_pick_encoder_sw_when_nvenc_not_requested(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/nvidia-smi")
    assert _pick_encoder("hevc", allow_nvenc=False) == "libx265"


def test_pick_encoder_h264_sw():
    assert _pick_encoder("h264", allow_nvenc=False) == "libx264"


# ---------------------------------------------------------------------------
# ffmpeg command construction
# ---------------------------------------------------------------------------

def test_build_ffmpeg_cmd_copies_audio_and_subtitles(tmp_path):
    job = _job(
        file_path=str(tmp_path / "src.mkv"),
        output_path=str(tmp_path / "out.mkv"),
    )
    cmd = _build_ffmpeg_cmd(job, "libx265")
    assert "-c:a" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert "-c:s" in cmd
    assert cmd[cmd.index("-c:s") + 1] == "copy"
    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "libx265"


def test_build_ffmpeg_cmd_maps_all_streams(tmp_path):
    job = _job(
        file_path=str(tmp_path / "src.mkv"),
        output_path=str(tmp_path / "out.mkv"),
    )
    cmd = _build_ffmpeg_cmd(job, "libx265")
    assert "-map" in cmd
    assert "0" in cmd[cmd.index("-map") + 1]


def test_build_ffmpeg_cmd_mkv_format(tmp_path):
    job = _job(
        file_path=str(tmp_path / "src.mkv"),
        output_path=str(tmp_path / "out.mkv"),
        container="mkv",
    )
    cmd = _build_ffmpeg_cmd(job, "libx265")
    assert "-f" in cmd
    assert "matroska" in cmd


# ---------------------------------------------------------------------------
# In-place transcode guard
# ---------------------------------------------------------------------------

def test_in_place_transcode_returns_failed(tmp_path):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), output_path=str(src)))
    assert result.status == JobStatus.failed
    assert "in-place" in (result.error_message or "")


# ---------------------------------------------------------------------------
# File-not-found guard
# ---------------------------------------------------------------------------

def test_file_not_found_returns_failed():
    result = worker.run(_job())
    assert result.status == JobStatus.failed
    assert "not found" in (result.error_message or "")


# ---------------------------------------------------------------------------
# Tool-unavailable path
# ---------------------------------------------------------------------------

def test_tool_unavailable_when_ffmpeg_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), output_path=str(tmp_path / "out.mkv")))
    assert result.status == JobStatus.tool_unavailable
    assert result.error_message


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------

def test_dry_run_skips_execution(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(
        file_path=str(src),
        output_path=str(tmp_path / "out.mkv"),
        dry_run=True,
    ))
    assert result.status == JobStatus.skipped
    assert result.codec_used is not None
    assert result.size_bytes_before == src.stat().st_size
    assert any("dry_run" in n for n in result.notes)


def test_dry_run_output_file_not_created(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    out = tmp_path / "out.mkv"
    worker.run(_job(file_path=str(src), output_path=str(out), dry_run=True))
    assert not out.exists()


# ---------------------------------------------------------------------------
# Happy path — real ffmpeg execution (subprocess mocked)
# ---------------------------------------------------------------------------

def test_complete_returns_source_and_output_size(tmp_path, monkeypatch):
    _patch_run_deps(monkeypatch, tmp_path)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"x" * 1024)
    out = tmp_path / "out.mkv"
    result = worker.run(_job(file_path=str(src), output_path=str(out)))
    assert result.status == JobStatus.complete
    assert result.size_bytes_before == 1024
    assert result.size_bytes_after == 512
    assert result.codec_used == "libx265"
    assert result.output_path == str(out)


def test_complete_nvenc_when_available(tmp_path, monkeypatch):
    _patch_run_deps(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "shutil.which", lambda t: f"/usr/bin/{t}"
    )
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(
        file_path=str(src),
        output_path=str(tmp_path / "out.mkv"),
        allow_nvenc=True,
    ))
    assert result.status == JobStatus.complete
    assert result.codec_used == "hevc_nvenc"


# ---------------------------------------------------------------------------
# ffmpeg failure paths
# ---------------------------------------------------------------------------

def test_ffmpeg_nonzero_exit_returns_failed(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")

    def fake_run(cmd, **_):
        raise subprocess.CalledProcessError(1, cmd, stderr=b"encoder error")

    monkeypatch.setattr("subprocess.run", fake_run)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), output_path=str(tmp_path / "out.mkv")))
    assert result.status == JobStatus.failed
    assert "1" in (result.error_message or "")
    assert any("encoder error" in n for n in result.notes)


def test_ffmpeg_nonzero_cleans_up_partial_output(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    out = tmp_path / "out.mkv"

    def fake_run(cmd, **_):
        out.write_bytes(b"partial")
        raise subprocess.CalledProcessError(1, cmd, stderr=b"")

    monkeypatch.setattr("subprocess.run", fake_run)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    worker.run(_job(file_path=str(src), output_path=str(out)))
    assert not out.exists()


def test_ffmpeg_timeout_returns_failed(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")

    def fake_run(cmd, **_):
        raise subprocess.TimeoutExpired(cmd, 7200)

    monkeypatch.setattr("subprocess.run", fake_run)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), output_path=str(tmp_path / "out.mkv")))
    assert result.status == JobStatus.failed
    assert "timed out" in (result.error_message or "")


def test_ffmpeg_timeout_cleans_up_partial_output(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    out = tmp_path / "out.mkv"

    def fake_run(cmd, **_):
        out.write_bytes(b"partial")
        raise subprocess.TimeoutExpired(cmd, 7200)

    monkeypatch.setattr("subprocess.run", fake_run)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    worker.run(_job(file_path=str(src), output_path=str(out)))
    assert not out.exists()


# ---------------------------------------------------------------------------
# Catalog notification
# ---------------------------------------------------------------------------

def test_catalog_notified_on_success(tmp_path, monkeypatch):
    _patch_run_deps(monkeypatch, tmp_path)
    monkeypatch.setenv("CATALOG_API_URL", "http://catalog-api:8000")

    notified = []

    def fake_notify(item_id, catalog_url):
        notified.append((item_id, catalog_url))

    monkeypatch.setattr("transcode_worker.worker._notify_catalog", fake_notify)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(
        file_path=str(src),
        output_path=str(tmp_path / "out.mkv"),
        item_id="item-abc",
    ))
    assert result.status == JobStatus.complete
    assert notified == [("item-abc", "http://catalog-api:8000")]


def test_catalog_not_notified_when_env_unset(tmp_path, monkeypatch):
    _patch_run_deps(monkeypatch, tmp_path)
    monkeypatch.delenv("CATALOG_API_URL", raising=False)

    notified = []
    monkeypatch.setattr(
        "transcode_worker.worker._notify_catalog",
        lambda item_id, url: notified.append(item_id),
    )
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    worker.run(_job(file_path=str(src), output_path=str(tmp_path / "out.mkv")))
    assert notified == []


def test_catalog_not_notified_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setenv("CATALOG_API_URL", "http://catalog-api:8000")
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **_: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, cmd, stderr=b"")
        ),
    )
    notified = []
    monkeypatch.setattr(
        "transcode_worker.worker._notify_catalog",
        lambda item_id, url: notified.append(item_id),
    )
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    worker.run(_job(file_path=str(src), output_path=str(tmp_path / "out.mkv")))
    assert notified == []


# ---------------------------------------------------------------------------
# Duration always set
# ---------------------------------------------------------------------------

def test_duration_always_set(tmp_path):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), output_path=str(tmp_path / "out.mkv")))
    assert result.duration_seconds is not None


# ---------------------------------------------------------------------------
# status()
# ---------------------------------------------------------------------------

def test_status_returns_dict():
    info = status()
    assert "status" in info
    assert "tools" in info
    assert info["status"] in ("ready", "degraded")


def test_status_includes_mkvmerge():
    info = status()
    assert "mkvmerge" in info["tools"]


def test_status_tools_are_booleans():
    for v in status()["tools"].values():
        assert isinstance(v, bool)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_status_exits_without_crash():
    from transcode_worker.__main__ import main
    code = main(["status"])
    assert code in (0, 1)


def test_cli_run_missing_arg():
    from transcode_worker.__main__ import main
    assert main(["run"]) == 2


def test_cli_run_invalid_json():
    from transcode_worker.__main__ import main
    assert main(["run", "{bad json"]) == 2


def test_cli_unknown_command():
    from transcode_worker.__main__ import main
    assert main(["unknown"]) == 2
