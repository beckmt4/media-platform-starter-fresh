from __future__ import annotations

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from media_brain.main import app, _get_store
from media_brain.models import MediaBrainState
from media_brain.store import MediaBrainStore

from .conftest import SAMPLE_MEDIAINFO_JSON


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MediaBrainStore:
    """Replace the global store with a fresh temp-db for each test."""
    store = MediaBrainStore(str(tmp_path / "test.db"))
    monkeypatch.setattr("media_brain.main._store", store)
    return store


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def fake_mkv(tmp_path: Path) -> Path:
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"\x00" * 2048)
    return f


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["total_items"] == 0


# ---------------------------------------------------------------------------
# POST /scan/file
# ---------------------------------------------------------------------------

def test_scan_file_endpoint(client: TestClient, fake_mkv: Path) -> None:
    resp = client.post("/scan/file", json={
        "file_path": str(fake_mkv),
        "mediainfo_json": SAMPLE_MEDIAINFO_JSON,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == MediaBrainState.needs_subtitle_review
    assert data["container_format"] == "Matroska"
    assert len(data["video_tracks"]) == 1
    assert len(data["audio_tracks"]) == 2
    assert len(data["subtitle_tracks"]) == 1


def test_scan_file_persisted(client: TestClient, fake_mkv: Path, isolated_store: MediaBrainStore) -> None:
    resp = client.post("/scan/file", json={
        "file_path": str(fake_mkv),
        "mediainfo_json": SAMPLE_MEDIAINFO_JSON,
    })
    media_id = resp.json()["media_id"]
    stored = isolated_store.get(media_id)
    assert stored is not None
    assert stored.media_id == media_id


def test_scan_file_missing_file(client: TestClient) -> None:
    resp = client.post("/scan/file", json={"file_path": "/nonexistent/path/movie.mkv"})
    assert resp.status_code == 200  # error is represented in state, not HTTP status
    data = resp.json()
    assert data["state"] == MediaBrainState.error


# ---------------------------------------------------------------------------
# POST /scan/directory
# ---------------------------------------------------------------------------

def test_scan_directory_endpoint(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.mkv").write_bytes(b"\x00" * 512)
    (tmp_path / "b.mkv").write_bytes(b"\x00" * 512)

    # Inject mediainfo JSON so the scanner doesn't call the subprocess.
    import media_brain.scanner as scanner_module

    original_run = scanner_module.MediaBrainScanner._run_mediainfo

    def fake_run(self: object, file_path: str, file_size: int, media_id: str) -> object:
        from media_brain.scanner import _parse_mediainfo
        return _parse_mediainfo(SAMPLE_MEDIAINFO_JSON, file_path, file_size, media_id)

    monkeypatch.setattr(scanner_module.MediaBrainScanner, "_run_mediainfo", fake_run)

    resp = client.post("/scan/directory", json={"directory": str(tmp_path), "extensions": [".mkv"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_files"] == 2
    assert data["errors"] == 0


# ---------------------------------------------------------------------------
# GET /items
# ---------------------------------------------------------------------------

def test_list_items_empty(client: TestClient) -> None:
    resp = client.get("/items")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_list_items_after_scan(client: TestClient, fake_mkv: Path) -> None:
    client.post("/scan/file", json={"file_path": str(fake_mkv), "mediainfo_json": SAMPLE_MEDIAINFO_JSON})
    resp = client.get("/items")
    data = resp.json()
    assert data["total"] == 1


def test_list_items_state_filter(client: TestClient, fake_mkv: Path, isolated_store: MediaBrainStore) -> None:
    client.post("/scan/file", json={"file_path": str(fake_mkv), "mediainfo_json": SAMPLE_MEDIAINFO_JSON})
    resp = client.get("/items", params={"state": MediaBrainState.needs_subtitle_review})
    assert resp.json()["total"] == 1
    resp2 = client.get("/items", params={"state": MediaBrainState.reviewed})
    assert resp2.json()["total"] == 0


# ---------------------------------------------------------------------------
# GET /items/{media_id}
# ---------------------------------------------------------------------------

def test_get_item(client: TestClient, fake_mkv: Path) -> None:
    scan = client.post("/scan/file", json={"file_path": str(fake_mkv), "mediainfo_json": SAMPLE_MEDIAINFO_JSON})
    media_id = scan.json()["media_id"]
    resp = client.get(f"/items/{media_id}")
    assert resp.status_code == 200
    assert resp.json()["media_id"] == media_id


def test_get_item_not_found(client: TestClient) -> None:
    resp = client.get("/items/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /items/{media_id}/state
# ---------------------------------------------------------------------------

def test_patch_state(client: TestClient, fake_mkv: Path) -> None:
    scan = client.post("/scan/file", json={"file_path": str(fake_mkv), "mediainfo_json": SAMPLE_MEDIAINFO_JSON})
    media_id = scan.json()["media_id"]
    resp = client.patch(f"/items/{media_id}/state", params={"state": MediaBrainState.reviewed})
    assert resp.status_code == 200
    assert resp.json()["state"] == MediaBrainState.reviewed


def test_patch_state_not_found(client: TestClient) -> None:
    resp = client.patch("/items/ghost/state", params={"state": MediaBrainState.reviewed})
    assert resp.status_code == 404
