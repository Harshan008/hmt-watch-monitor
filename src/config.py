"""Load and validate config/targets.yml. Invalid config fails fast with a clear message."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

MODES = ("strict_free", "near_realtime")
SITES = ("in", "store")
_ID_RE = re.compile(r"^[a-z0-9_\-]+$")
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
SITE_DOMAINS = {"in": "hmtwatches.in", "store": "hmtwatches.store"}


class ConfigError(ValueError):
    pass


@dataclass
class Window:
    start: time
    end: time

    def __str__(self) -> str:
        return f"{self.start:%H:%M}-{self.end:%H:%M}"


@dataclass
class RequestConfig:
    connect_timeout_seconds: float = 15
    timeout_seconds: float = 60
    max_retries: int = 2
    backoff_base_seconds: float = 5
    jitter_seconds: float = 3
    blocked_threshold: int = 2
    blocked_cooldown_minutes: int = 30
    concurrency: int = 1
    user_agent: str = "HMT-Stock-Monitor/1.0 (personal restock alert; github.com/Harshan008)"


@dataclass
class AlertConfig:
    cooldown_minutes: int = 10
    alert_unknown: bool = False
    alert_possible_stock: bool = True
    alert_blocked: bool = True
    alert_recovery: bool = False


@dataclass
class Target:
    id: str
    name: str
    product_id: object  # int for site="in"; UUID string (sku) for site="store"
    url: str
    enabled: bool = True
    rule: str = "auto"
    site: str = "in"


@dataclass
class Config:
    timezone: str
    tz: ZoneInfo
    mode: str
    interval_seconds: int
    pre_window_wait_minutes: int
    max_session_minutes: int
    active_windows: List[Window]
    request: RequestConfig
    alerts: AlertConfig
    targets: List[Target]
    base_url: str = "https://www.hmtwatches.in"
    store_base_url: str = "https://www.hmtwatches.store"

    @property
    def enabled_targets(self) -> List[Target]:
        return [t for t in self.targets if t.enabled]


def _parse_hhmm(value, where: str) -> time:
    if not isinstance(value, str) or not _HHMM_RE.match(value):
        raise ConfigError(f'{where}: expected "HH:MM" (24h, quoted), got {value!r}')
    h, m = value.split(":")
    return time(int(h), int(m))


def _dataclass_from(cls, data, where: str):
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: must be a mapping")
    allowed = set(cls.__dataclass_fields__)
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}; allowed: {sorted(allowed)}")
    obj = cls(**data)
    for name, f in cls.__dataclass_fields__.items():
        default = f.default
        val = getattr(obj, name)
        if isinstance(default, bool):
            if not isinstance(val, bool):
                raise ConfigError(f"{where}.{name}: must be true/false")
        elif isinstance(default, (int, float)):
            if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0:
                raise ConfigError(f"{where}.{name}: must be a non-negative number")
    return obj


def parse_config(raw) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")

    tz_name = raw.get("timezone", "Asia/Kolkata")
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"timezone: unknown timezone {tz_name!r}")

    mode = raw.get("mode", "strict_free")
    if mode not in MODES:
        raise ConfigError(f"mode: must be one of {MODES}, got {mode!r}")

    interval = raw.get("interval_seconds", 300)
    if isinstance(interval, bool) or not isinstance(interval, int):
        raise ConfigError("interval_seconds: must be an integer")
    if mode == "near_realtime" and interval < 30:
        raise ConfigError("interval_seconds: must be >= 30 in near_realtime mode (be gentle with HMT)")
    if mode == "strict_free" and interval < 300:
        raise ConfigError("interval_seconds: must be >= 300 in strict_free mode (GitHub minimum is 5 min)")

    pre_wait = raw.get("pre_window_wait_minutes", 10)
    max_session = raw.get("max_session_minutes", 330)
    for key, val in (("pre_window_wait_minutes", pre_wait), ("max_session_minutes", max_session)):
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            raise ConfigError(f"{key}: must be a non-negative integer")
    if max_session > 350:
        raise ConfigError("max_session_minutes: must be <= 350 (GitHub job limit is 6h)")

    windows_raw = raw.get("active_windows")
    if not isinstance(windows_raw, list) or not windows_raw:
        raise ConfigError("active_windows: must be a non-empty list of {start, end}")
    windows = []
    for i, w in enumerate(windows_raw):
        where = f"active_windows[{i}]"
        if not isinstance(w, dict) or set(w) != {"start", "end"}:
            raise ConfigError(f"{where}: must have exactly 'start' and 'end'")
        start, end = _parse_hhmm(w["start"], f"{where}.start"), _parse_hhmm(w["end"], f"{where}.end")
        if start == end:
            raise ConfigError(f"{where}: start and end must differ")
        windows.append(Window(start, end))

    request = _dataclass_from(RequestConfig, raw.get("request"), "request")
    if request.concurrency != 1:
        raise ConfigError("request.concurrency: only 1 is supported (sequential, low site load)")
    if request.timeout_seconds <= 0:
        raise ConfigError("request.timeout_seconds: must be > 0")
    alerts = _dataclass_from(AlertConfig, raw.get("alerts"), "alerts")

    targets_raw = raw.get("targets")
    if not isinstance(targets_raw, list) or not targets_raw:
        raise ConfigError("targets: must be a non-empty list")
    targets, seen = [], set()
    for i, t in enumerate(targets_raw):
        where = f"targets[{i}]"
        if not isinstance(t, dict):
            raise ConfigError(f"{where}: must be a mapping")
        for key in ("id", "name", "product_id", "url"):
            if key not in t:
                raise ConfigError(f"{where}: missing required key '{key}'")
        tid = t["id"]
        if not isinstance(tid, str) or not _ID_RE.match(tid):
            raise ConfigError(f"{where}.id: use lowercase letters, digits, _ or - (got {tid!r})")
        if tid in seen:
            raise ConfigError(f"{where}.id: duplicate id {tid!r}")
        seen.add(tid)

        site = t.get("site", "in")
        if site not in SITES:
            raise ConfigError(f"{where}.site: must be one of {SITES}, got {site!r}")
        domain = SITE_DOMAINS[site]

        pid = t["product_id"]
        if site == "in":
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                raise ConfigError(
                    f"{where}.product_id: must be a positive integer for site 'in' "
                    f"(run: python -m src.add_target <url>)")
        else:  # store
            if not isinstance(pid, str) or not _UUID_RE.match(pid):
                raise ConfigError(
                    f"{where}.product_id: must be a UUID string for site 'store' "
                    f"(run: python -m src.add_target <url>)")
            pid = pid.lower()

        url = t["url"]
        parsed = urlparse(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != "https" or not parsed.netloc.endswith(domain):
            raise ConfigError(f"{where}.url: must be an https://www.{domain}/... link (site: {site!r})")
        enabled = t.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"{where}.enabled: must be true/false")
        rule = t.get("rule", "auto")
        if rule != "auto":
            raise ConfigError(f"{where}.rule: only 'auto' is supported")
        extra = set(t) - {"id", "name", "product_id", "url", "enabled", "rule", "site"}
        if extra:
            raise ConfigError(f"{where}: unknown keys {sorted(extra)}")
        targets.append(Target(tid, str(t["name"]), pid, url, enabled, rule, site))
    if not any(t.enabled for t in targets):
        raise ConfigError("targets: at least one target must have enabled: true")

    return Config(
        timezone=tz_name, tz=tz, mode=mode, interval_seconds=interval,
        pre_window_wait_minutes=pre_wait, max_session_minutes=max_session,
        active_windows=windows, request=request, alerts=alerts, targets=targets,
    )


def load_config(path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}")
    return parse_config(raw)
