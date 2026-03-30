from __future__ import annotations

import pytest
from pydantic import ValidationError

from catalog_api.models import (
    ArrLockState,
    ArrLockTag,
    MediaDomain,
    MediaItem,
    MediaItemState,
    MediaItemUpdate,
    ReviewQueueEntry,
)


def test_media_item_defaults():
    item = MediaItem(title="Test Movie", domain=MediaDomain.domestic_live_action_movie)
    assert item.state == MediaItemState.inbox
    assert item.arr_monitored is True
    assert item.tags == []
    assert item.file_path is None
    assert item.id  # uuid assigned


def test_media_item_id_is_unique():
    a = MediaItem(title="A", domain=MediaDomain.anime_movie)
    b = MediaItem(title="B", domain=MediaDomain.anime_movie)
    assert a.id != b.id


def test_media_item_with_tags():
    item = MediaItem(
        title="Locked Title",
        domain=MediaDomain.jav_adult,
        tags=[ArrLockTag.manual_source, ArrLockTag.locked, ArrLockTag.no_upgrade],
        arr_monitored=False,
    )
    assert ArrLockTag.manual_source in item.tags
    assert item.arr_monitored is False


def test_media_item_rejects_invalid_domain():
    with pytest.raises(ValidationError):
        MediaItem(title="Bad", domain="not_a_domain")


def test_media_item_rejects_invalid_state():
    with pytest.raises(ValidationError):
        MediaItem(title="Bad", domain=MediaDomain.anime_series, state="unknown_state")


def test_media_item_update_partial():
    update = MediaItemUpdate(state=MediaItemState.review)
    dumped = update.model_dump(exclude_unset=True)
    assert "state" in dumped
    assert "title" not in dumped


def test_arr_lock_state_defaults():
    lock = ArrLockState(item_id="abc-123")
    assert lock.block_upgrades is False
    assert lock.monitored is True
    assert lock.tags == []


def test_arr_lock_state_manual_source():
    lock = ArrLockState(
        item_id="abc-123",
        block_upgrades=True,
        monitored=False,
        tags=[ArrLockTag.manual_source, ArrLockTag.locked, ArrLockTag.no_upgrade],
    )
    assert lock.block_upgrades is True
    assert ArrLockTag.no_upgrade in lock.tags


def test_review_queue_entry_defaults():
    entry = ReviewQueueEntry(item_id="abc-123", reason="subtitle confidence below threshold")
    assert entry.resolved is False
    assert entry.resolved_at is None
    assert entry.resolution_note is None
    assert entry.id


def test_media_domain_enum_values():
    assert MediaDomain.jav_adult.value == "jav_adult"
    assert MediaDomain.anime_series.value == "anime_series"
    assert len(MediaDomain) == 11
