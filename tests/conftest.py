import copy
from pathlib import Path

import pytest

from src.config import parse_config

FIXTURES = Path(__file__).parent / "fixtures"

BASE_RAW = {
    "timezone": "Asia/Kolkata",
    "mode": "strict_free",
    "interval_seconds": 300,
    "active_windows": [{"start": "09:00", "end": "12:00"}, {"start": "15:00", "end": "17:00"}],
    "request": {"timeout_seconds": 60, "max_retries": 2, "jitter_seconds": 3,
                "blocked_threshold": 2, "blocked_cooldown_minutes": 30},
    "alerts": {"cooldown_minutes": 10},
    "targets": [{
        "id": "stellar_dasl10",
        "name": "HMT Stellar DASL 10 R Black",
        "product_id": 534,
        "url": "https://www.hmtwatches.in/product_all_details?id=abc",
        "enabled": True,
    }],
}


@pytest.fixture
def raw_config():
    return copy.deepcopy(BASE_RAW)


@pytest.fixture
def config(raw_config):
    return parse_config(raw_config)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
