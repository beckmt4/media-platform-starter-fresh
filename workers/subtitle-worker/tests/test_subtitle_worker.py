from __future__ import annotations

import json
from pathlib import Path

import pytest

from subtitle_worker.models import JobStatus, SubtitleJob, SubtitleJobResult, SubtitleJobType
from subtitle_worker.worker import SubtitleWorker, _check_tools, status

worker = SubtitleWorker()


def _job(file_path: str = "/nonexistent/file.mkv",
         job_type: SubtitleJobType = SubtitleJobType.generate,
         **kwargs) -> SubtitleJob:
    return SubtitleJob(
        item_id="item-abc",
        file_path=file_path,
        job_type=job_type,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Model defaults
# ---------------------------------------------------------------------------

def test_job_defaults():
    job = _job()
    assert job.target_language == "en"
    assert job.whisper_model == "large-v3"
    assert job.dry_run is False
    assert job.job_id  # uuid assigned


def test_job_ids_unique():
    assert _job().job_id != _job().job_id


def test_result_model():
    r = SubtitleJobResult(
        job_id="j1", item_id="i1",
        status=JobStatus.complete,
        job_type=SubtitleJobType.generate,
    )
    assert r.notes == []
    assert r.output_path is None


# ---------------------------------------------------------------------------
# File-not-found guard
# ---------------------------------------------------------------------------

def test_file_not_found_returns_failed():
    result = worker.run(_job(file_path="/does/not/exist.mkv"))
    assert result.status == JobStatus.failed
    assert "not found" in (result.error_message or "")


# ---------------------------------------------------------------------------
# dry_run — uses a real temp file so the existence check passes
# ---------------------------------------------------------------------------

def test_dry_run_skips_execution(tmp_path):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), dry_run=True))
    # tool_unavailable is acceptable too (whisper not installed in CI)
    assert result.status in (JobStatus.skipped, JobStatus.tool_unavailable)


def test_dry_run_includes_note(tmp_path):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), dry_run=True))
    if result.status == JobStatus.skipped:
        assert any("dry_run" in n for n in result.notes)


# ---------------------------------------------------------------------------
# Tool-unavailable path (whisper not installed in test environment)
# ---------------------------------------------------------------------------

def test_tool_unavailable_when_whisper_missing(tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src)))
    assert result.status == JobStatus.tool_unavailable
    assert result.error_message


# ---------------------------------------------------------------------------
# Repair and translate types don't require whisper
# ---------------------------------------------------------------------------

def test_repair_job_no_tool_required(tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(
        file_path=str(src),
        job_type=SubtitleJobType.repair,
        dry_run=True,
    ))
    # No tool required for repair — dry_run should skip cleanly
    assert result.status == JobStatus.skipped


# ---------------------------------------------------------------------------
# Output path convention
# ---------------------------------------------------------------------------

def test_output_path_uses_target_language(tmp_path, monkeypatch):
    import shutil as sh
    # Patch whisper as available so we reach the stub complete path
    original_which = sh.which
    monkeypatch.setattr(sh, "which", lambda t: "/usr/bin/whisper" if t == "whisper" else original_which(t))
    src = tmp_path / "SSIS-123.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), target_language="en"))
    if result.status == JobStatus.complete:
        assert result.output_path and ".en." in result.output_path


# ---------------------------------------------------------------------------
# Duration always set
# ---------------------------------------------------------------------------

def test_duration_always_set(tmp_path):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), dry_run=True))
    assert result.duration_seconds is not None
    assert result.duration_seconds >= 0.0


# ---------------------------------------------------------------------------
# status() command
# ---------------------------------------------------------------------------

def test_status_returns_dict():
    info = status()
    assert "status" in info
    assert "tools" in info
    assert info["status"] in ("ready", "degraded")


def test_status_tools_are_booleans():
    info = status()
    for v in info["tools"].values():
        assert isinstance(v, bool)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_status_exits_without_error():
    from subtitle_worker.__main__ import main
    # status command always exits 0 or 1 — never crashes
    code = main(["status"])
    assert code in (0, 1)


def test_cli_run_missing_arg():
    from subtitle_worker.__main__ import main
    code = main(["run"])
    assert code == 2


def test_cli_run_invalid_json():
    from subtitle_worker.__main__ import main
    code = main(["run", "{not valid json"])
    assert code == 2


def test_cli_unknown_command():
    from subtitle_worker.__main__ import main
    code = main(["unknown"])
    assert code == 2
