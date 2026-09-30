"""Tiny JSON state file. Only slowly-changing fields are stored, so the file (and the
git commit made by the workflow) changes only when something meaningful happens."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional

from .models import PARSER_VERSION

log = logging.getLogger(__name__)


@dataclass
class TargetState:
    last_status: Optional[str] = None       # last *known* status: IN_STOCK / OUT_OF_STOCK
    last_alert_at: Optional[str] = None      # ISO datetime
    last_alert_kind: Optional[str] = None
    consecutive_blocks: int = 0
    blocked_until: Optional[str] = None      # ISO datetime; circuit open until then
    unknown_alerted: bool = False
    title: Optional[str] = None
    last_price: Optional[float] = None
    parser_version: str = PARSER_VERSION

    def blocked_until_dt(self) -> Optional[datetime]:
        return datetime.fromisoformat(self.blocked_until) if self.blocked_until else None

    def last_alert_dt(self) -> Optional[datetime]:
        return datetime.fromisoformat(self.last_alert_at) if self.last_alert_at else None


_KNOWN_FIELDS = {f.name for f in fields(TargetState)}


def load_state(path) -> Dict[str, TargetState]:
    path = Path(path)
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        log.error("state file %s is corrupt (%s); starting fresh", path, exc)
        return {}
    states = {}
    for tid, data in (raw or {}).items():
        if isinstance(data, dict):
            states[tid] = TargetState(**{k: v for k, v in data.items() if k in _KNOWN_FIELDS})
    return states


def dump_state(states: Dict[str, TargetState], keep_ids: Iterable[str]) -> str:
    keep = set(keep_ids)
    payload = {tid: asdict(st) for tid, st in sorted(states.items()) if tid in keep}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def save_state(path, states: Dict[str, TargetState], keep_ids: Iterable[str]) -> bool:
    """Write the state file only if content changed. Returns True when written."""
    path = Path(path)
    new_text = dump_state(states, keep_ids)
    old_text = path.read_text(encoding="utf-8") if path.exists() else None
    if new_text == old_text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)
    return True
