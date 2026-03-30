from __future__ import annotations

from transcode_worker.models import JobStatus, TranscodeJob, TranscodeJobResult
from transcode_worker.worker import TranscodeWorker, _pick_encoder, status

worker = TranscodeWorker()


def _job(file_path: str = "/nonexistent/src.mkv",
         output_path: str = "/nonexistent/out.mkv",
         **kwargs) -> TranscodeJob:
    return TranscodeJob(
        item_id="item-xyz",
        file_path=file_path,
        output_path=output_path,
        **kwargs,
    )


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
    r = TranscodeJobResult(
        job_id="j1", item_id="i1",
        status=JobStatus.complete,
    )
    assert r.notes == []
    assert r.output_path is None


# ---------------------------------------------------------------------------
# Encoder selection
# ---------------------------------------------------------------------------

def test_pick_encoder_sw_hevc(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert _pick_encoder("hevc", allow_nvenc=True) == "libx265"


def test_pick_encoder_nvenc_when_available(monkeypatch):
    import shutil
    monkeypatch.setattr(
        shutil, "which", lambda t: "/usr/bin/nvidia-smi" if t == "nvidia-smi" else None
    )
    assert _pick_encoder("hevc", allow_nvenc=True) == "hevc_nvenc"


def test_pick_encoder_sw_when_nvenc_not_requested(monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    assert _pick_encoder("hevc", allow_nvenc=False) == "libx265"


def test_pick_encoder_h264_sw():
    assert _pick_encoder("h264", allow_nvenc=False) == "libx264"


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
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), output_path=str(tmp_path / "out.mkv")))
    assert result.status == JobStatus.tool_unavailable
    assert result.error_message


# ---------------------------------------------------------------------------
# dry_run
# ---------------------------------------------------------------------------

def test_dry_run_skips_execution(tmp_path, monkeypatch):
    import shutil as sh
    monkeypatch.setattr(sh, "which", lambda t: f"/usr/bin/{t}")
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
    import shutil as sh
    monkeypatch.setattr(sh, "which", lambda t: f"/usr/bin/{t}")
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    out = tmp_path / "out.mkv"
    worker.run(_job(file_path=str(src), output_path=str(out), dry_run=True))
    assert not out.exists()


# ---------------------------------------------------------------------------
# Stub complete path (ffmpeg mocked as available)
# ---------------------------------------------------------------------------

def test_stub_complete_returns_source_size(tmp_path, monkeypatch):
    import shutil as sh
    monkeypatch.setattr(sh, "which", lambda t: f"/usr/bin/{t}")
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"x" * 1024)
    result = worker.run(_job(
        file_path=str(src),
        output_path=str(tmp_path / "out.mkv"),
    ))
    assert result.status == JobStatus.complete
    assert result.size_bytes_before == 1024
    assert result.codec_used == "libx265"


def test_stub_complete_nvenc_when_available(tmp_path, monkeypatch):
    import shutil as sh
    monkeypatch.setattr(sh, "which", lambda t: f"/usr/bin/{t}")
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
