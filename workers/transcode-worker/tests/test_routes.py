from __future__ import annotations

from fastapi.testclient import TestClient

from transcode_worker.main import app

client = TestClient(app)


def _job_payload(**kwargs) -> dict:
    payload = {
        "item_id": "item-xyz",
        "file_path": "/nonexistent/src.mkv",
        "output_path": "/nonexistent/out.mkv",
    }
    payload.update(kwargs)
    return payload


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_returns_200():
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_has_status_and_tools():
    body = client.get("/health").json()
    assert "status" in body
    assert body["status"] in ("ready", "degraded")
    assert "tools" in body
    assert isinstance(body["tools"], dict)


def test_health_includes_mkvmerge():
    body = client.get("/health").json()
    assert "mkvmerge" in body["tools"]


def test_health_tools_are_booleans():
    body = client.get("/health").json()
    for v in body["tools"].values():
        assert isinstance(v, bool)


# ---------------------------------------------------------------------------
# POST /jobs — validation
# ---------------------------------------------------------------------------

def test_missing_output_path_returns_422():
    resp = client.post("/jobs", json={"item_id": "x", "file_path": "/src.mkv"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /jobs — file not found
# ---------------------------------------------------------------------------

def test_file_not_found_returns_failed():
    resp = client.post("/jobs", json=_job_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert "not found" in (body["error_message"] or "")


# ---------------------------------------------------------------------------
# POST /jobs — in-place guard
# ---------------------------------------------------------------------------

def test_in_place_transcode_returns_failed(tmp_path):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    resp = client.post("/jobs", json=_job_payload(
        file_path=str(src),
        output_path=str(src),
    ))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert "in-place" in (body["error_message"] or "")


# ---------------------------------------------------------------------------
# POST /jobs — dry_run
# ---------------------------------------------------------------------------

def test_dry_run_with_existing_file(tmp_path, monkeypatch):
    import shutil as sh
    monkeypatch.setattr(sh, "which", lambda t: f"/usr/bin/{t}")
    src = tmp_path / "src.mkv"
    src.write_bytes(b"fake")
    resp = client.post("/jobs", json=_job_payload(
        file_path=str(src),
        output_path=str(tmp_path / "out.mkv"),
        dry_run=True,
    ))
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"


def test_dry_run_includes_codec_used(tmp_path, monkeypatch):
    import shutil as sh
    monkeypatch.setattr(sh, "which", lambda t: f"/usr/bin/{t}")
    src = tmp_path / "src.mkv"
    src.write_bytes(b"fake")
    resp = client.post("/jobs", json=_job_payload(
        file_path=str(src),
        output_path=str(tmp_path / "out.mkv"),
        dry_run=True,
    ))
    body = resp.json()
    assert body["codec_used"] is not None


# ---------------------------------------------------------------------------
# POST /jobs — response shape
# ---------------------------------------------------------------------------

def test_response_includes_job_id():
    resp = client.post("/jobs", json=_job_payload())
    assert resp.json()["job_id"]


def test_response_includes_item_id():
    resp = client.post("/jobs", json=_job_payload())
    assert resp.json()["item_id"] == "item-xyz"


def test_response_includes_duration():
    resp = client.post("/jobs", json=_job_payload())
    body = resp.json()
    assert body["duration_seconds"] is not None
    assert body["duration_seconds"] >= 0.0


# ---------------------------------------------------------------------------
# POST /jobs — nvenc selection visible in response
# ---------------------------------------------------------------------------

def test_nvenc_encoder_used_when_available(tmp_path, monkeypatch):
    import shutil as sh
    monkeypatch.setattr(sh, "which", lambda t: f"/usr/bin/{t}")
    src = tmp_path / "src.mkv"
    src.write_bytes(b"fake")
    resp = client.post("/jobs", json=_job_payload(
        file_path=str(src),
        output_path=str(tmp_path / "out.mkv"),
        allow_nvenc=True,
    ))
    body = resp.json()
    if body["status"] == "complete":
        assert body["codec_used"] == "hevc_nvenc"
