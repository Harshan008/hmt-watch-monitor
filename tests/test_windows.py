from datetime import datetime, time
from zoneinfo import ZoneInfo

from src.config import Window
from src.scheduler import active_window_end, is_active, next_window_start

IST = ZoneInfo("Asia/Kolkata")
WINDOWS = [Window(time(9, 0), time(12, 0)), Window(time(15, 0), time(17, 0))]


def at(h, m, day=1):
    return datetime(2026, 10, day, h, m, tzinfo=IST)


def test_inside_and_outside_windows():
    assert is_active(WINDOWS, at(9, 0))
    assert is_active(WINDOWS, at(11, 59))
    assert not is_active(WINDOWS, at(12, 0))      # end is exclusive
    assert not is_active(WINDOWS, at(8, 59))
    assert is_active(WINDOWS, at(16, 30))
    assert not is_active(WINDOWS, at(23, 0))


def test_window_end():
    assert active_window_end(WINDOWS, at(10, 15)) == at(12, 0)
    assert active_window_end(WINDOWS, at(13, 0)) is None


def test_next_window_start():
    assert next_window_start(WINDOWS, at(8, 50)) == at(9, 0)
    assert next_window_start(WINDOWS, at(12, 30)) == at(15, 0)
    assert next_window_start(WINDOWS, at(18, 0)) == at(9, 0, day=2)


def test_midnight_crossing_window():
    windows = [Window(time(22, 0), time(1, 0))]
    assert is_active(windows, at(23, 30))
    assert is_active(windows, at(0, 30, day=2))
    assert not is_active(windows, at(1, 0, day=2))
    assert active_window_end(windows, at(23, 30)) == at(1, 0, day=2)
    assert active_window_end(windows, at(0, 30, day=2)) == at(1, 0, day=2)


def test_utc_input_is_evaluated_in_ist():
    # 04:00 UTC == 09:30 IST
    utc_now = datetime(2026, 10, 1, 4, 0, tzinfo=ZoneInfo("UTC")).astimezone(IST)
    assert is_active(WINDOWS, utc_now)
