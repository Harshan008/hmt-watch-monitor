"""Selling-window logic (timezone-aware, handles windows that cross midnight)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from .config import Window


def _window_bounds(window: Window, day: datetime) -> Tuple[datetime, datetime]:
    """Concrete (start, end) datetimes for a window that starts on `day`'s date."""
    start = day.replace(hour=window.start.hour, minute=window.start.minute, second=0, microsecond=0)
    end = day.replace(hour=window.end.hour, minute=window.end.minute, second=0, microsecond=0)
    if window.end <= window.start:  # crosses midnight
        end += timedelta(days=1)
    return start, end


def _candidate_bounds(windows: List[Window], now: datetime):
    for offset in (-1, 0, 1):
        day = now + timedelta(days=offset)
        for w in windows:
            yield _window_bounds(w, day)


def active_window_end(windows: List[Window], now: datetime) -> Optional[datetime]:
    """If `now` is inside a window, return when that window ends; else None."""
    ends = [end for start, end in _candidate_bounds(windows, now) if start <= now < end]
    return max(ends) if ends else None


def next_window_start(windows: List[Window], now: datetime) -> datetime:
    return min(start for start, _ in _candidate_bounds(windows, now) if start > now)


def is_active(windows: List[Window], now: datetime) -> bool:
    return active_window_end(windows, now) is not None
