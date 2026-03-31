from __future__ import annotations

from fastapi.testclient import TestClient

from subtitle_worker.main import app

client = TestClient(app)


def _job_payload(**kwargs) -> dict:
    payload = {
        "item_id": "item-abc",
        "file_path": "/nonexistent/movie.mkv",
        "job_type": "generate",
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


def test_health_tools_are_booleans():
    body = client.get("/health").json()
    for v in body["tools"].values():
        assert isinstance(v, bool)


# ---------------------------------------------------------------------------
# POST /jobs — validation
# ---------------------------------------------------------------------------

def test_missing_required_fields_returns_422():
    resp = client.post("/jobs", json={"item_id": "x"})
    assert resp.status_code == 422


def test_invalid_job_type_returns_422():
    resp = client.post("/jobs", json=_job_payload(job_type="unknown_type"))
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
# POST /jobs — dry_run
# ---------------------------------------------------------------------------

def test_dry_run_with_existing_file(tmp_path):
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    resp = client.post("/jobs", json=_job_payload(file_path=str(src), dry_run=True))
    assert resp.status_code == 200
    body = resp.json()
    # skipped (dry_run) or tool_unavailable (whisper absent in CI) — both valid
    assert body["status"] in ("skipped", "tool_unavailable")


# ---------------------------------------------------------------------------
# POST /jobs — response shape
# ---------------------------------------------------------------------------

def test_response_includes_job_id():
    resp = client.post("/jobs", json=_job_payload())
    body = resp.json()
    assert "job_id" in body
    assert body["job_id"]


def test_response_includes_item_id():
    resp = client.post("/jobs", json=_job_payload())
    body = resp.json()
    assert body["item_id"] == "item-abc"


def test_response_includes_job_type():
    resp = client.post("/jobs", json=_job_payload())
    body = resp.json()
    assert body["job_type"] == "generate"


def test_response_includes_duration():
    resp = client.post("/jobs", json=_job_payload())
    body = resp.json()
    assert body["duration_seconds"] is not None
    assert body["duration_seconds"] >= 0.0


# ---------------------------------------------------------------------------
# POST /jobs — repair type (no whisper required)
# ---------------------------------------------------------------------------

def test_repair_job_dry_run(tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "which", lambda _: None)
    src = tmp_path / "movie.mkv"
    src.write_bytes(b"fake")
    resp = client.post("/jobs", json=_job_payload(
        file_path=str(src),
        job_type="repair",
        dry_run=True,
    ))
    assert resp.status_code == 200
    assert resp.json()["status"] == "skipped"
