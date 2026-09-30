from pathlib import Path

import pytest

from src.config import ConfigError, load_config, parse_config


def test_valid_config(config):
    assert config.mode == "strict_free"
    assert len(config.enabled_targets) == 1
    assert config.enabled_targets[0].product_id == 534


def test_repo_config_file_is_valid():
    cfg = load_config(Path(__file__).parent.parent / "config" / "targets.yml")
    assert cfg.enabled_targets


@pytest.mark.parametrize("mutate, message", [
    (lambda r: r.update(targets=[]), "targets"),
    (lambda r: r["targets"][0].update(url="http://evil.example.com/x"), "url"),
    (lambda r: r["targets"][0].update(product_id="abc"), "product_id"),
    (lambda r: r["targets"][0].pop("product_id"), "product_id"),
    (lambda r: r.update(interval_seconds=60), "interval_seconds"),
    (lambda r: r.update(mode="turbo"), "mode"),
    (lambda r: r.update(active_windows=[{"start": "9am", "end": "12:00"}]), "HH:MM"),
    (lambda r: r.update(active_windows=[]), "active_windows"),
    (lambda r: r["request"].update(concurrency=4), "concurrency"),
    (lambda r: r["request"].update(bogus=1), "unknown keys"),
    (lambda r: r["targets"][0].update(enabled=False), "at least one"),
    (lambda r: r.update(timezone="Mars/Olympus"), "timezone"),
])
def test_invalid_config_fails_with_helpful_error(raw_config, mutate, message):
    mutate(raw_config)
    with pytest.raises(ConfigError, match=message):
        parse_config(raw_config)


def test_near_realtime_minimum_interval(raw_config):
    raw_config.update(mode="near_realtime", interval_seconds=10)
    with pytest.raises(ConfigError, match=">= 30"):
        parse_config(raw_config)
    raw_config["interval_seconds"] = 60
    assert parse_config(raw_config).interval_seconds == 60


def test_duplicate_target_ids(raw_config):
    raw_config["targets"].append(dict(raw_config["targets"][0]))
    with pytest.raises(ConfigError, match="duplicate"):
        parse_config(raw_config)
