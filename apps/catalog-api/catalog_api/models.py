from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class MediaDomain(str, Enum):
    domestic_live_action_movie = "domestic_live_action_movie"
    domestic_live_action_tv = "domestic_live_action_tv"
    international_live_action_movie = "international_live_action_movie"
    international_live_action_tv = "international_live_action_tv"
    domestic_animated_movie = "domestic_animated_movie"
    domestic_animated_tv = "domestic_animated_tv"
    international_animated_movie = "international_animated_movie"
    international_animated_tv = "international_animated_tv"
    anime_movie = "anime_movie"
    anime_series = "anime_series"
    jav_adult = "jav_adult"


class MediaItemState(str, Enum):
    inbox = "inbox"
    review = "review"
    quarantine = "quarantine"
    active = "active"
    locked = "locked"
    error = "error"


class ArrLockTag(str, Enum):
    manual_source = "manual-source"
    locked = "locked"
    no_upgrade = "no-upgrade"
    subtitle_complete = "subtitle-complete"
    needs_review = "needs-review"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MediaItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    domain: MediaDomain
    state: MediaItemState = MediaItemState.inbox
    file_path: str | None = None
    tags: list[ArrLockTag] = Field(default_factory=list)
    arr_monitored: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class MediaItemUpdate(BaseModel):
    title: str | None = None
    state: MediaItemState | None = None
    file_path: str | None = None
    tags: list[ArrLockTag] | None = None
    arr_monitored: bool | None = None


class ArrLockState(BaseModel):
    item_id: str
    block_upgrades: bool = False
    monitored: bool = True
    tags: list[ArrLockTag] = Field(default_factory=list)


class ReviewQueueEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    item_id: str
    reason: str
    created_at: datetime = Field(default_factory=_utcnow)
    resolved: bool = False
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class ReviewQueueResolve(BaseModel):
    resolution_note: str | None = None
