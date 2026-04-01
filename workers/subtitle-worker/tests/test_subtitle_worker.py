from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from subtitle_worker.models import JobStatus, SubtitleJob, SubtitleJobResult, SubtitleJobType
from subtitle_worker.worker import (
    SubtitleWorker,
    _CHUNK_THRESHOLD,
    _get_media_duration,
    _pick_audio_stream,
    _write_srt,
    status,
)

worker = SubtitleWorker()


def _job(
    file_path: str = "/nonexistent/file.mkv",
    job_type: SubtitleJobType = SubtitleJobType.generate,
    item_id: str = "item-abc",
    scratch_dir: str | None = None,
    **kwargs,
) -> SubtitleJob:
    return SubtitleJob(
        item_id=item_id,
        file_path=file_path,
        job_type=job_type,
        scratch_dir=scratch_dir,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Helpers used across multiple tests
# ---------------------------------------------------------------------------

def _fake_fw_module(segments=None, language="ja", language_probability=0.97):
    """Build a fake faster_whisper module with a controllable WhisperModel."""
    if segments is None:
        segments = [SimpleNamespace(start=0.0, end=2.5, text=" Hello world")]

    class FakeModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, *a, **kw):
            return iter(segments), SimpleNamespace(
                language=language,
                language_probability=language_probability,
            )

    return SimpleNamespace(WhisperModel=FakeModel)


def _patch_generate_deps(monkeypatch, tmp_path, *, language="ja", language_probability=0.97):
    """Patch all external calls for the generate happy path."""
    # faster_whisper importable
    monkeypatch.setattr("subtitle_worker.worker._faster_whisper_available", lambda: True)
    # CLI tools present
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    # ffprobe picks stream 0
    monkeypatch.setattr("subtitle_worker.worker._pick_audio_stream", lambda *_a, **_kw: 0)
    # duration probe returns None (< threshold → no chunking)
    monkeypatch.setattr("subtitle_worker.worker._get_media_duration", lambda _: None)
    # ffmpeg extraction returns a fake wav path
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    monkeypatch.setattr("subtitle_worker.worker._extract_audio", lambda *_a, **_kw: str(wav))
    # faster_whisper module
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        _fake_fw_module(language=language, language_probability=language_probability),
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
# dry_run — file existence check happens BEFORE dry_run is honoured
# ---------------------------------------------------------------------------

def test_dry_run_skips_execution(tmp_path):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), dry_run=True))
    assert result.status == JobStatus.skipped


def test_dry_run_includes_note(tmp_path):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src), dry_run=True))
    assert any("dry_run" in n for n in result.notes)


# ---------------------------------------------------------------------------
# Tool-unavailable — ffmpeg/ffprobe missing
# ---------------------------------------------------------------------------

def test_tool_unavailable_when_ffmpeg_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src)))
    assert result.status == JobStatus.tool_unavailable
    assert result.error_message


# ---------------------------------------------------------------------------
# Tool-unavailable — faster_whisper not importable
# ---------------------------------------------------------------------------

def test_tool_unavailable_when_faster_whisper_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr("subtitle_worker.worker._faster_whisper_available", lambda: False)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(file_path=str(src)))
    assert result.status == JobStatus.tool_unavailable
    assert "faster-whisper" in (result.error_message or "")


# ---------------------------------------------------------------------------
# generate — happy path (all deps mocked)
# ---------------------------------------------------------------------------

def test_generate_complete(tmp_path, monkeypatch):
    src = tmp_path / "SSIS-123.mkv"
    src.write_bytes(b"fake")
    _patch_generate_deps(monkeypatch, tmp_path, language="ja", language_probability=0.97)

    result = worker.run(_job(file_path=str(src), target_language="en", scratch_dir=str(tmp_path)))

    assert result.status == JobStatus.complete
    assert result.detected_language == "ja"
    assert result.confidence == 0.97
    assert result.output_path is not None
    assert result.output_path.endswith(".en.srt")
    assert Path(result.output_path).exists()


def test_generate_srt_content(tmp_path, monkeypatch):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    segs = [
        SimpleNamespace(start=0.0, end=1.5, text=" First line"),
        SimpleNamespace(start=2.0, end=3.5, text=" Second line"),
    ]
    monkeypatch.setattr("subtitle_worker.worker._faster_whisper_available", lambda: True)
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr("subtitle_worker.worker._pick_audio_stream", lambda *_a, **_kw: 0)
    monkeypatch.setattr("subtitle_worker.worker._get_media_duration", lambda _: None)
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    monkeypatch.setattr("subtitle_worker.worker._extract_audio", lambda *_a, **_kw: str(wav))
    monkeypatch.setitem(sys.modules, "faster_whisper", _fake_fw_module(segments=segs))

    result = worker.run(_job(file_path=str(src), target_language="en", scratch_dir=str(tmp_path)))

    assert result.status == JobStatus.complete
    srt = Path(result.output_path).read_text(encoding="utf-8")
    assert "1\n" in srt
    assert "First line" in srt
    assert "Second line" in srt
    assert "-->" in srt


def test_generate_output_uses_target_language(tmp_path, monkeypatch):
    src = tmp_path / "SSIS-123.mkv"
    src.write_bytes(b"fake")
    _patch_generate_deps(monkeypatch, tmp_path)

    result = worker.run(_job(file_path=str(src), target_language="ja", scratch_dir=str(tmp_path)))

    assert result.status == JobStatus.complete
    assert ".ja.srt" in (result.output_path or "")


def test_generate_custom_output_dir(tmp_path, monkeypatch):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    out_dir = tmp_path / "subs"
    _patch_generate_deps(monkeypatch, tmp_path)

    result = worker.run(_job(file_path=str(src), output_dir=str(out_dir), scratch_dir=str(tmp_path)))

    assert result.status == JobStatus.complete
    assert str(out_dir) in (result.output_path or "")
    assert out_dir.exists()


# ---------------------------------------------------------------------------
# generate — ffmpeg extraction failure
# ---------------------------------------------------------------------------

def test_generate_ffmpeg_failure(tmp_path, monkeypatch):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    monkeypatch.setattr("subtitle_worker.worker._faster_whisper_available", lambda: True)
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr("subtitle_worker.worker._pick_audio_stream", lambda *_a, **_kw: 0)
    monkeypatch.setattr("subtitle_worker.worker._get_media_duration", lambda _: None)
    monkeypatch.setattr(
        "subtitle_worker.worker._extract_audio",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, "ffmpeg")
        ),
    )

    result = worker.run(_job(file_path=str(src), scratch_dir=str(tmp_path)))

    assert result.status == JobStatus.failed
    assert "audio extraction failed" in (result.error_message or "")


def test_generate_ffmpeg_timeout(tmp_path, monkeypatch):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    monkeypatch.setattr("subtitle_worker.worker._faster_whisper_available", lambda: True)
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr("subtitle_worker.worker._pick_audio_stream", lambda *_a, **_kw: 0)
    monkeypatch.setattr("subtitle_worker.worker._get_media_duration", lambda _: None)
    monkeypatch.setattr(
        "subtitle_worker.worker._extract_audio",
        lambda *_a, **_kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("ffmpeg", 600)),
    )

    result = worker.run(_job(file_path=str(src), scratch_dir=str(tmp_path)))

    assert result.status == JobStatus.failed
    assert "timed out" in (result.error_message or "")


# ---------------------------------------------------------------------------
# generate — transcription failure
# ---------------------------------------------------------------------------

def test_generate_transcription_failure(tmp_path, monkeypatch):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    monkeypatch.setattr("subtitle_worker.worker._faster_whisper_available", lambda: True)
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr("subtitle_worker.worker._pick_audio_stream", lambda *_a, **_kw: 0)
    monkeypatch.setattr("subtitle_worker.worker._get_media_duration", lambda _: None)
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    monkeypatch.setattr("subtitle_worker.worker._extract_audio", lambda *_a, **_kw: str(wav))

    class BrokenModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, *a, **kw):
            raise RuntimeError("CUDA out of memory")

    monkeypatch.setitem(
        sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=BrokenModel)
    )

    result = worker.run(_job(file_path=str(src), scratch_dir=str(tmp_path)))

    assert result.status == JobStatus.failed
    assert "transcription failed" in (result.error_message or "")


# ---------------------------------------------------------------------------
# generate — catalog notification
# ---------------------------------------------------------------------------

def test_generate_catalog_notified(tmp_path, monkeypatch):
    import urllib.request

    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    monkeypatch.setenv("CATALOG_API_URL", "http://catalog-api:8000")
    _patch_generate_deps(monkeypatch, tmp_path)

    notify_calls: list[tuple] = []

    def _fake_notify(item_id: str, catalog_url: str) -> None:
        notify_calls.append((item_id, catalog_url))

    monkeypatch.setattr("subtitle_worker.worker._notify_catalog", _fake_notify)

    result = worker.run(_job(file_path=str(src), item_id="item-xyz", scratch_dir=str(tmp_path)))

    assert result.status == JobStatus.complete
    assert len(notify_calls) == 1
    assert notify_calls[0] == ("item-xyz", "http://catalog-api:8000")


def test_generate_no_catalog_call_when_url_unset(tmp_path, monkeypatch):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    monkeypatch.delenv("CATALOG_API_URL", raising=False)
    _patch_generate_deps(monkeypatch, tmp_path)

    notify_calls: list = []
    monkeypatch.setattr(
        "subtitle_worker.worker._notify_catalog",
        lambda *_: notify_calls.append(True),
    )

    result = worker.run(_job(file_path=str(src), scratch_dir=str(tmp_path)))

    assert result.status == JobStatus.complete
    assert notify_calls == []


# ---------------------------------------------------------------------------
# Repair and translate — stubs return skipped
# ---------------------------------------------------------------------------

def test_repair_job_returns_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    result = worker.run(_job(
        file_path=str(src),
        job_type=SubtitleJobType.repair,
        dry_run=True,
    ))
    assert result.status == JobStatus.skipped


# ---------------------------------------------------------------------------
# _write_srt unit tests
# ---------------------------------------------------------------------------

def test_write_srt_format(tmp_path):
    segs = [
        SimpleNamespace(start=0.0, end=2.5, text=" Hello world"),
        SimpleNamespace(start=3.0, end=5.0, text="  Second line  "),
    ]
    out = tmp_path / "test.srt"
    _write_srt(segs, out)
    content = out.read_text(encoding="utf-8")

    assert "1\n" in content
    assert "00:00:00,000 --> 00:00:02,500\n" in content
    assert "Hello world\n" in content
    assert "2\n" in content
    assert "Second line\n" in content


def test_write_srt_timestamp_rollover(tmp_path):
    segs = [SimpleNamespace(start=3661.5, end=3663.0, text="Late")]
    out = tmp_path / "test.srt"
    _write_srt(segs, out)
    content = out.read_text(encoding="utf-8")
    assert "01:01:01,500 --> 01:01:03,000" in content


# ---------------------------------------------------------------------------
# _pick_audio_stream unit tests
# ---------------------------------------------------------------------------

def test_pick_audio_stream_prefers_english(monkeypatch):
    ffprobe_output = json.dumps({
        "streams": [
            {"index": 1, "tags": {"language": "jpn"}},
            {"index": 2, "tags": {"language": "eng"}},
            {"index": 3, "tags": {"language": "fre"}},
        ]
    }).encode()
    monkeypatch.setattr(
        "subprocess.check_output", lambda *_a, **_kw: ffprobe_output
    )
    assert _pick_audio_stream("/fake/file.mkv") == 2


def test_pick_audio_stream_fallback_to_first(monkeypatch):
    ffprobe_output = json.dumps({
        "streams": [{"index": 5, "tags": {"language": "jpn"}}]
    }).encode()
    monkeypatch.setattr(
        "subprocess.check_output", lambda *_a, **_kw: ffprobe_output
    )
    assert _pick_audio_stream("/fake/file.mkv") == 5


def test_pick_audio_stream_ffprobe_failure_returns_zero(monkeypatch):
    def _fail(*_a, **_kw):
        raise subprocess.CalledProcessError(1, "ffprobe")

    monkeypatch.setattr("subprocess.check_output", _fail)
    assert _pick_audio_stream("/fake/file.mkv") == 0


# Step 4: JAV audio selection — preferred_language="ja" picks Japanese track
def test_pick_audio_stream_prefers_japanese_when_requested(monkeypatch):
    """JAV files: source_language=ja → pick jpn track even when eng is present."""
    ffprobe_output = json.dumps({
        "streams": [
            {"index": 1, "tags": {"language": "jpn"}},
            {"index": 2, "tags": {"language": "eng"}},
        ]
    }).encode()
    monkeypatch.setattr("subprocess.check_output", lambda *_a, **_kw: ffprobe_output)
    assert _pick_audio_stream("/fake/jav.mkv", preferred_language="ja") == 1


def test_pick_audio_stream_preferred_ja_iso639_2(monkeypatch):
    """Caller may pass ISO 639-2 tag 'jpn' as preferred_language."""
    ffprobe_output = json.dumps({
        "streams": [
            {"index": 3, "tags": {"language": "jpn"}},
        ]
    }).encode()
    monkeypatch.setattr("subprocess.check_output", lambda *_a, **_kw: ffprobe_output)
    assert _pick_audio_stream("/fake/jav.mkv", preferred_language="jpn") == 3


def test_pick_audio_stream_preferred_language_falls_back_to_first(monkeypatch):
    """If preferred language not found, fall back to first audio track."""
    ffprobe_output = json.dumps({
        "streams": [
            {"index": 7, "tags": {"language": "kor"}},
            {"index": 8, "tags": {"language": "eng"}},
        ]
    }).encode()
    monkeypatch.setattr("subprocess.check_output", lambda *_a, **_kw: ffprobe_output)
    # Preferred ja not present → first stream
    assert _pick_audio_stream("/fake/jav.mkv", preferred_language="ja") == 7


# ---------------------------------------------------------------------------
# Step 4: scratch path
# ---------------------------------------------------------------------------

def test_generate_uses_media_id_for_wav_filename(tmp_path, monkeypatch):
    """WAV is written to scratch_dir/{media_id}.wav."""
    src = tmp_path / "SSIS-123.mkv"
    src.write_bytes(b"fake")

    captured: list[str] = []

    def _fake_extract(file_path, stream_index, out_path, **_kw):
        captured.append(out_path)
        Path(out_path).write_bytes(b"RIFF")
        return out_path

    monkeypatch.setattr("subtitle_worker.worker._faster_whisper_available", lambda: True)
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr("subtitle_worker.worker._pick_audio_stream", lambda *_a, **_kw: 0)
    monkeypatch.setattr("subtitle_worker.worker._get_media_duration", lambda _: None)
    monkeypatch.setattr("subtitle_worker.worker._extract_audio", _fake_extract)
    monkeypatch.setitem(sys.modules, "faster_whisper", _fake_fw_module())

    scratch = tmp_path / "scratch"
    result = worker.run(_job(
        file_path=str(src),
        media_id="abc123",
        scratch_dir=str(scratch),
    ))

    assert result.status == JobStatus.complete
    assert len(captured) == 1
    assert captured[0].endswith("abc123.wav")
    assert str(scratch) in captured[0]


def test_generate_wav_cleaned_up_after_success(tmp_path, monkeypatch):
    """Scratch WAV is deleted after transcription completes."""
    src = tmp_path / "SSIS-123.mkv"
    src.write_bytes(b"fake")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    wav = scratch / "myjob.wav"

    def _fake_extract(file_path, stream_index, out_path, **_kw):
        Path(out_path).write_bytes(b"RIFF")
        return out_path

    monkeypatch.setattr("subtitle_worker.worker._faster_whisper_available", lambda: True)
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr("subtitle_worker.worker._pick_audio_stream", lambda *_a, **_kw: 0)
    monkeypatch.setattr("subtitle_worker.worker._get_media_duration", lambda _: None)
    monkeypatch.setattr("subtitle_worker.worker._extract_audio", _fake_extract)
    monkeypatch.setitem(sys.modules, "faster_whisper", _fake_fw_module())

    result = worker.run(_job(
        file_path=str(src),
        scratch_dir=str(scratch),
    ))

    assert result.status == JobStatus.complete
    # No .wav files should remain in scratch
    assert list(scratch.glob("*.wav")) == []


# ---------------------------------------------------------------------------
# Step 4: chunking for files >2h
# ---------------------------------------------------------------------------

def test_generate_long_file_uses_chunks(tmp_path, monkeypatch):
    """Files longer than _CHUNK_THRESHOLD trigger chunked extraction."""
    src = tmp_path / "long.mkv"
    src.write_bytes(b"fake")

    chunk_calls: list[dict] = []

    def _fake_chunk(file_path, stream_index, scratch_dir, wav_stem, total_duration):
        chunk_calls.append({"duration": total_duration})
        # Return two fake chunks
        c0 = scratch_dir / f"{wav_stem}_chunk0.wav"
        c1 = scratch_dir / f"{wav_stem}_chunk1.wav"
        c0.write_bytes(b"RIFF")
        c1.write_bytes(b"RIFF")
        return [(c0, 0.0), (c1, 1770.0)]

    monkeypatch.setattr("subtitle_worker.worker._faster_whisper_available", lambda: True)
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr("subtitle_worker.worker._pick_audio_stream", lambda *_a, **_kw: 0)
    monkeypatch.setattr("subtitle_worker.worker._get_media_duration", lambda _: float(_CHUNK_THRESHOLD + 1))
    monkeypatch.setattr("subtitle_worker.worker._extract_audio_chunks", _fake_chunk)
    monkeypatch.setitem(sys.modules, "faster_whisper", _fake_fw_module())

    result = worker.run(_job(
        file_path=str(src),
        scratch_dir=str(tmp_path),
    ))

    assert result.status == JobStatus.complete
    assert len(chunk_calls) == 1
    assert any("chunks=2" in n for n in result.notes)


def test_generate_chunk_overlap_segments_dropped(tmp_path, monkeypatch):
    """Segments within the overlap window of non-first chunks are skipped."""
    src = tmp_path / "long.mkv"
    src.write_bytes(b"fake")

    # Chunk 0: 2 segments (both kept)
    # Chunk 1: segment at 10s (inside overlap of 30s → dropped), segment at 35s (kept)
    chunk0_segs = [
        SimpleNamespace(start=0.0, end=1.0, text=" A"),
        SimpleNamespace(start=5.0, end=6.0, text=" B"),
    ]
    chunk1_segs = [
        SimpleNamespace(start=10.0, end=11.0, text=" OVERLAP_DROPPED"),
        SimpleNamespace(start=35.0, end=36.0, text=" C"),
    ]

    call_count = [0]

    class FakeModel:
        def __init__(self, *a, **kw):
            pass

        def transcribe(self, wav_path, **kw):
            i = call_count[0]
            call_count[0] += 1
            segs = chunk0_segs if i == 0 else chunk1_segs
            return iter(segs), SimpleNamespace(language="ja", language_probability=0.97)

    def _fake_chunk(file_path, stream_index, scratch_dir, wav_stem, total_duration):
        c0 = scratch_dir / f"{wav_stem}_chunk0.wav"
        c1 = scratch_dir / f"{wav_stem}_chunk1.wav"
        c0.write_bytes(b"RIFF")
        c1.write_bytes(b"RIFF")
        return [(c0, 0.0), (c1, 1770.0)]

    monkeypatch.setattr("subtitle_worker.worker._faster_whisper_available", lambda: True)
    monkeypatch.setattr("shutil.which", lambda t: f"/usr/bin/{t}")
    monkeypatch.setattr("subtitle_worker.worker._pick_audio_stream", lambda *_a, **_kw: 0)
    monkeypatch.setattr("subtitle_worker.worker._get_media_duration", lambda _: float(_CHUNK_THRESHOLD + 1))
    monkeypatch.setattr("subtitle_worker.worker._extract_audio_chunks", _fake_chunk)
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeModel))

    result = worker.run(_job(file_path=str(src), scratch_dir=str(tmp_path)))

    assert result.status == JobStatus.complete
    srt = Path(result.output_path).read_text(encoding="utf-8")
    assert "OVERLAP_DROPPED" not in srt
    assert "\nC\n" in srt
    # Chunk 1 segment at 35s gets offset to absolute 1770 + 35 = 1805s
    assert "00:30:05" in srt


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


def test_status_includes_expected_keys():
    info = status()
    assert "ffmpeg" in info["tools"]
    assert "ffprobe" in info["tools"]
    assert "faster_whisper" in info["tools"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_status_exits_without_error():
    from subtitle_worker.__main__ import main
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
