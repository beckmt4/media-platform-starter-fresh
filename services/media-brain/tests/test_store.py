from __future__ import annotations

import pytest
from pathlib import Path

from media_brain.models import MediaBrainState, MediaItem
from media_brain.store import MediaBrainStore


@pytest.fixture()
def store(tmp_path: Path) -> MediaBrainStore:
    return MediaBrainStore(str(tmp_path / "test.db"))


def _make_item(media_id: str = "abc123", file_path: str = "/mnt/itv/adult/movie.mkv") -> MediaItem:
    return MediaItem(
        media_id=media_id,
        file_path=file_path,
        file_size=1_000_000,
        state=MediaBrainState.needs_subtitle_review,
        container_format="Matroska",
        duration_seconds=5400.0,
    )


def test_upsert_and_get(store: MediaBrainStore) -> None:
    item = _make_item()
    store.upsert(item)
    got = store.get("abc123")
    assert got is not None
    assert got.media_id == "abc123"
    assert got.file_path == "/mnt/itv/adult/movie.mkv"
    assert got.state == MediaBrainState.needs_subtitle_review
    assert got.container_format == "Matroska"
    assert got.duration_seconds == pytest.approx(5400.0)


def test_upsert_is_idempotent(store: MediaBrainStore) -> None:
    item = _make_item()
    store.upsert(item)
    store.upsert(item)
    assert store.count() == 1


def test_upsert_overwrites_state(store: MediaBrainStore) -> None:
    store.upsert(_make_item())
    updated = _make_item()
    updated.state = MediaBrainState.reviewed
    store.upsert(updated)
    got = store.get("abc123")
    assert got is not None
    assert got.state == MediaBrainState.reviewed


def test_get_by_path(store: MediaBrainStore) -> None:
    store.upsert(_make_item())
    got = store.get_by_path("/mnt/itv/adult/movie.mkv")
    assert got is not None
    assert got.media_id == "abc123"


def test_get_missing_returns_none(store: MediaBrainStore) -> None:
    assert store.get("does-not-exist") is None


def test_update_state(store: MediaBrainStore) -> None:
    store.upsert(_make_item())
    ok = store.update_state("abc123", MediaBrainState.reviewed)
    assert ok is True
    got = store.get("abc123")
    assert got is not None
    assert got.state == MediaBrainState.reviewed


def test_update_state_missing_returns_false(store: MediaBrainStore) -> None:
    assert store.update_state("no-such-id", MediaBrainState.reviewed) is False


def test_list_items(store: MediaBrainStore) -> None:
    store.upsert(_make_item("id1", "/mnt/a.mkv"))
    store.upsert(_make_item("id2", "/mnt/b.mkv"))
    items = store.list_items()
    assert len(items) == 2


def test_list_items_filter_by_state(store: MediaBrainStore) -> None:
    store.upsert(_make_item("id1"))
    item2 = _make_item("id2", "/mnt/b.mkv")
    item2.state = MediaBrainState.reviewed
    store.upsert(item2)

    pending = store.list_items(state=MediaBrainState.needs_subtitle_review)
    assert len(pending) == 1
    assert pending[0].media_id == "id1"


def test_count(store: MediaBrainStore) -> None:
    assert store.count() == 0
    store.upsert(_make_item("id1"))
    store.upsert(_make_item("id2", "/mnt/b.mkv"))
    assert store.count() == 2
    assert store.count(state=MediaBrainState.needs_subtitle_review) == 2
    assert store.count(state=MediaBrainState.reviewed) == 0


def test_tracks_roundtrip(store: MediaBrainStore) -> None:
    from media_brain.models import AudioTrackInfo, SubtitleTrackInfo, SubtitleTrackType, VideoTrackInfo

    item = _make_item()
    item.video_tracks = [VideoTrackInfo(track_index=0, codec="HEVC", width=1920, height=1080, is_hdr=False)]
    item.audio_tracks = [AudioTrackInfo(track_index=0, codec="AAC", detected_language="ja", channels=2, is_default=True)]
    item.subtitle_tracks = [SubtitleTrackInfo(track_index=0, codec="UTF-8", detected_language="en", confidence=1.0, track_type=SubtitleTrackType.full)]
    item.sidecar_files = ["/mnt/itv/adult/movie.srt"]
    store.upsert(item)

    got = store.get(item.media_id)
    assert got is not None
    assert got.video_tracks[0].codec == "HEVC"
    assert got.audio_tracks[0].detected_language == "ja"
    assert got.subtitle_tracks[0].track_type == SubtitleTrackType.full
    assert got.sidecar_files == ["/mnt/itv/adult/movie.srt"]
