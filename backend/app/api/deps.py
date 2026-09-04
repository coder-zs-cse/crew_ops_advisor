"""Shared application state: the world, the advisor, and the virtual clock.

The dataset is frozen at 2026-09-14T18:00Z. A real desk's watchers fire against
wall-clock time, which here would sit two years past the schedule and find
nothing. So the app runs on a *virtual clock* the demo can advance: watchers,
"today", and relative dates all read from it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from threading import Lock

from ..agent.runner import Advisor
from ..config import get_settings
from ..core.loader import load_world
from ..core.timeutil import fmt_dt, parse_dt
from ..core.world import World


class VirtualClock:
    """A movable 'now' anchored on the dataset snapshot."""

    def __init__(self, start: datetime) -> None:
        self._start = start
        self._now = start
        self._lock = Lock()

    @property
    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, value: datetime) -> datetime:
        with self._lock:
            self._now = value
            return self._now

    def advance(self, *, hours: float = 0.0, days: float = 0.0) -> datetime:
        with self._lock:
            self._now = self._now + timedelta(hours=hours, days=days)
            return self._now

    def reset(self) -> datetime:
        with self._lock:
            self._now = self._start
            return self._now

    def as_dict(self) -> dict:
        now = self.now
        return {
            "now_utc": fmt_dt(now),
            "date": now.date().isoformat(),
            "snapshot_utc": fmt_dt(self._start),
            "offset_hours": round((now - self._start).total_seconds() / 3600, 2),
        }


@lru_cache(maxsize=1)
def get_world() -> World:
    settings = get_settings()
    from ..core.dataset import ensure_dataset

    path = ensure_dataset(seed=settings.data_seed, dest=settings.data_dir)
    return load_world(str(path))


@lru_cache(maxsize=1)
def get_advisor() -> Advisor:
    return Advisor(get_world())


@lru_cache(maxsize=1)
def get_clock() -> VirtualClock:
    return VirtualClock(parse_dt(get_settings().snapshot_utc))
