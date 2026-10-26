"""A controllable clock. The demo runs at a fixed instant so every scenario is reproducible."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def parse(ts: str) -> datetime:
    if len(ts) == 10:  # a bare date
        ts += "T00:00:00Z"
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Clock:
    def __init__(self, start: str):
        self._now = parse(start)

    def now(self) -> datetime:
        return self._now

    def iso(self) -> str:
        return fmt(self._now)

    def advance(self, days: float = 0, seconds: float = 0) -> None:
        self._now += timedelta(days=days, seconds=seconds)

    def days_since(self, ts: str) -> float:
        return (self._now - parse(ts)).total_seconds() / 86400
