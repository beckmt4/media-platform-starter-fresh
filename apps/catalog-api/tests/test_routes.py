from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from catalog_api.main import app
from catalog_api.store import store


@pytest.fixture(autouse=True)
def reset_store():
    """Wipe in-memory store before each test."""
    store._items.clear()
    store._arr_locks.clear()
    store._review_queue.clear()
    yield


client = TestClient(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

def _make_item(**kwargs) -> dict:
    base = {"title": "Test Movie", "domain": "anime_movie"}
    base.update(kwargs)
    return base


def test_create_and_get_item():
    resp = client.post("/items", json=_make_item())
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Test Movie"
    assert data["state"] == "inbox"

    item_id = data["id"]
    get_resp = client.get(f"/items/{item_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == item_id


def test_list_items_empty():
    resp = client.get("/items")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_items_after_create():
    client.post("/items", json=_make_item(title="Alpha"))
    client.post("/items", json=_make_item(title="Beta"))
    resp = client.get("/items")
    assert len(resp.json()) == 2


def test_get_item_not_found():
    resp = client.get("/items/does-not-exist")
    assert resp.status_code == 404


def test_update_item_state():
    item_id = client.post("/items", json=_make_item()).json()["id"]
    resp = client.patch(f"/items/{item_id}", json={"state": "review"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "review"
    assert resp.json()["title"] == "Test Movie"


def test_update_item_not_found():
    resp = client.patch("/items/ghost", json={"state": "active"})
    assert resp.status_code == 404


def test_update_item_tags():
    item_id = client.post("/items", json=_make_item()).json()["id"]
    resp = client.patch(
        f"/items/{item_id}",
        json={"tags": ["manual-source", "locked", "no-upgrade"], "arr_monitored": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "manual-source" in body["tags"]
    assert body["arr_monitored"] is False


# ---------------------------------------------------------------------------
# Locks
# ---------------------------------------------------------------------------

def test_set_and_get_lock():
    item_id = client.post("/items", json=_make_item()).json()["id"]
    lock_payload = {
        "item_id": item_id, "block_upgrades": True, "monitored": False, "tags": ["locked"],
    }
    put_resp = client.put(f"/items/{item_id}/lock", json=lock_payload)
    assert put_resp.status_code == 200
    assert put_resp.json()["block_upgrades"] is True

    get_resp = client.get(f"/items/{item_id}/lock")
    assert get_resp.status_code == 200
    assert get_resp.json()["monitored"] is False


def test_get_lock_item_not_found():
    resp = client.get("/items/ghost/lock")
    assert resp.status_code == 404


def test_set_lock_item_id_mismatch():
    item_id = client.post("/items", json=_make_item()).json()["id"]
    resp = client.put(f"/items/{item_id}/lock", json={"item_id": "different-id"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Review queue
# ---------------------------------------------------------------------------

def test_create_and_list_queue_entry():
    item_id = client.post("/items", json=_make_item()).json()["id"]
    entry = {"item_id": item_id, "reason": "subtitle confidence 0.71 < 0.82"}
    resp = client.post("/review-queue", json=entry)
    assert resp.status_code == 201
    assert resp.json()["resolved"] is False

    list_resp = client.get("/review-queue")
    assert len(list_resp.json()) == 1


def test_create_queue_entry_item_not_found():
    resp = client.post("/review-queue", json={"item_id": "ghost", "reason": "test"})
    assert resp.status_code == 404


def test_resolve_queue_entry():
    item_id = client.post("/items", json=_make_item()).json()["id"]
    entry_id = client.post(
        "/review-queue", json={"item_id": item_id, "reason": "needs human check"}
    ).json()["id"]

    resp = client.post(f"/review-queue/{entry_id}/resolve", json={"resolution_note": "approved"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["resolved"] is True
    assert body["resolution_note"] == "approved"
    assert body["resolved_at"] is not None


def test_resolve_queue_entry_not_found():
    resp = client.post("/review-queue/ghost/resolve", json={})
    assert resp.status_code == 404


def test_resolved_entries_hidden_by_default():
    item_id = client.post("/items", json=_make_item()).json()["id"]
    entry_id = client.post(
        "/review-queue", json={"item_id": item_id, "reason": "check"}
    ).json()["id"]
    client.post(f"/review-queue/{entry_id}/resolve", json={})

    resp = client.get("/review-queue")
    assert resp.json() == []

    resp_all = client.get("/review-queue?include_resolved=true")
    assert len(resp_all.json()) == 1


def test_resolve_already_resolved_returns_404():
    item_id = client.post("/items", json=_make_item()).json()["id"]
    entry_id = client.post(
        "/review-queue", json={"item_id": item_id, "reason": "check"}
    ).json()["id"]
    client.post(f"/review-queue/{entry_id}/resolve", json={})
    resp = client.post(f"/review-queue/{entry_id}/resolve", json={})
    assert resp.status_code == 404
