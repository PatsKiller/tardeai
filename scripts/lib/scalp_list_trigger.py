"""Event trigger on the scalp list's ``as_of``: host-side watermarks for L246, L708 and L636's proposal stage.

Operator decision (4), 2026-10-10: these consumers fire when the scalp list advances, instead of polling on the
clock. The n8n event router is not on ``main``, and L246 sends Telegram (n8n sends nothing, AGENTS.md §23.3), so the
trigger is a host watermark: the consumer's cron line runs a cheap gate often; the gate decides; the consumer commits
the ``as_of`` it consumed after a successful run.

Decisions (``decide``):

- ``FIRE_NEW_SYMBOLS``  the list advanced and holds a symbol this consumer has not fired on today;
- ``FIRE_ADVANCE``      the list advanced and ``min_interval_min`` has passed since the consumer last fired;
- ``FIRE_STALE_LIST``   the list is older than its failed SLO (15 min) and ``legacy_every_min`` has passed: a stalled
                        list must not starve a consumer (it falls back to its legacy cadence, never silence);
- ``FIRE_LEGACY_CLOCK`` the hot tier is off (no ``SCALP_HOT_TIER=1``, or the kill file): fire on the consumer's
                        legacy clock slot, so rolling back by kill file restores the legacy cadence without a
                        crontab edit;
- ``SKIP_*``            otherwise, with the reason.

Store: ``<state_root>/data/runtime/scalp_hot_tier/trigger_watermarks.json`` (``ScalpListTriggerWatermarks@v1``).
Single writer: this module's :func:`commit` (exclusive lock, atomic replace). :func:`decide` is read-only, so a dry
run that calls it cannot reach the write (AGENTS.md §6).
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from lib import scalp_hot_tier as hot
except ImportError:  # imported as scripts.lib.*
    from scripts.lib import scalp_hot_tier as hot  # type: ignore

SCHEMA = "ScalpListTriggerWatermarks@v1"
REL = Path("data") / "runtime" / "scalp_hot_tier" / "trigger_watermarks.json"

#: per-consumer knobs: legacy cadence (minutes, offset) and the minimum spacing between advance-fires
CONSUMERS: dict[str, dict[str, Any]] = {
    # L246 social_scalp_scanner: legacy 0,30 6-9 (sends Telegram itself; GO de-dup unchanged)
    "social-scalp-scanner": {"legacy_every_min": 30, "legacy_offset_min": 0, "min_interval_min": 10.0},
    # L708 Hermes scalp catalyst: legacy 25 6-15
    "hermes-scalp-catalyst": {"legacy_every_min": 60, "legacy_offset_min": 25, "min_interval_min": 2.0},
    # L636 proposal stage (signal sync + proposal generation): legacy every 5 min with the lane
    "l636-proposal-stage": {"legacy_every_min": 5, "legacy_offset_min": 0, "min_interval_min": 5.0},
}
#: a cron grid of */2 lands up to this many minutes after a legacy slot
SLOT_TOLERANCE_MIN = 2


def store_path(state_root: Path | str | None = None) -> Path:
    return Path(state_root or hot._state_root()) / REL


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load(state_root: Path | str | None = None) -> dict[str, Any]:
    """Read-only. Missing/unreadable -> empty doc (every consumer looks never-fired: the safe side is to fire)."""
    try:
        doc = json.loads(store_path(state_root).read_text())
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _legacy_slot(now_et: datetime, every: int, offset: int) -> bool:
    minute_of_day = now_et.hour * 60 + now_et.minute
    return (minute_of_day - offset) % every < SLOT_TOLERANCE_MIN


def decide(
    consumer: str,
    list_env: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    hot_enabled: bool | None = None,
    state_root: Path | str | None = None,
    doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Should ``consumer`` run now? Pure read: never writes."""
    cfg = CONSUMERS[consumer]
    t = hot.now_et(now)
    enabled = hot.enabled(state_root=state_root) if hot_enabled is None else bool(hot_enabled)
    wm = ((doc if doc is not None else load(state_root)).get("consumers") or {}).get(consumer) or {}
    last_fired = _parse(wm.get("fired_at"))
    since_fire = (t - last_fired).total_seconds() / 60.0 if last_fired else None
    list_as_of = _parse((list_env or {}).get("as_of"))
    last_as_of = _parse(wm.get("list_as_of"))
    symbols = [str(s).upper() for s in ((list_env or {}).get("symbols") or [])]
    today = t.date().isoformat()
    seen = set(wm.get("symbols_fired", [])) if wm.get("day") == today else set()
    new_symbols = sorted(set(symbols) - seen)
    out = {
        "consumer": consumer,
        "hot_tier_enabled": enabled,
        "now_et": t.isoformat(),
        "list_as_of": list_as_of.isoformat() if list_as_of else None,
        "watermark_as_of": last_as_of.isoformat() if last_as_of else None,
        "minutes_since_fire": None if since_fire is None else round(since_fire, 2),
        "new_symbols": new_symbols[:50],
    }
    legacy_due = _legacy_slot(t, int(cfg["legacy_every_min"]), int(cfg["legacy_offset_min"])) and (
        since_fire is None or since_fire >= SLOT_TOLERANCE_MIN
    )
    if not enabled:
        return {**out, "fire": legacy_due, "decision": "FIRE_LEGACY_CLOCK" if legacy_due else "SKIP_NOT_LEGACY_SLOT"}
    advanced = list_as_of is not None and (last_as_of is None or list_as_of > last_as_of)
    list_age_min = (t - list_as_of).total_seconds() / 60.0 if list_as_of else None
    out["list_age_min"] = None if list_age_min is None else round(list_age_min, 2)
    stale_list = list_age_min is None or list_age_min > hot.SLOS["scalp_list"]["degraded"]
    if advanced and new_symbols:
        return {**out, "fire": True, "decision": "FIRE_NEW_SYMBOLS"}
    if advanced and (since_fire is None or since_fire >= float(cfg["min_interval_min"])):
        return {**out, "fire": True, "decision": "FIRE_ADVANCE"}
    if stale_list and (since_fire is None or since_fire >= float(cfg["legacy_every_min"])):
        return {**out, "fire": True, "decision": "FIRE_STALE_LIST"}
    if advanced:
        return {**out, "fire": False, "decision": "SKIP_MIN_INTERVAL"}
    return {**out, "fire": False, "decision": "SKIP_NO_ADVANCE"}


def commit(
    consumer: str,
    list_env: dict[str, Any] | None,
    *,
    decision: str,
    now: datetime | None = None,
    state_root: Path | str | None = None,
) -> dict[str, Any]:
    """Record that ``consumer`` consumed ``list_env`` (call only after a successful real run)."""
    if consumer not in CONSUMERS:
        raise KeyError(consumer)
    t = hot.now_et(now)
    path = store_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    with open(lock, "a") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            doc = load(state_root)
            doc["schema"] = SCHEMA
            cons = doc.setdefault("consumers", {})
            prev = cons.get(consumer) or {}
            today = t.date().isoformat()
            fired: set[str] = set(prev.get("symbols_fired", [])) if prev.get("day") == today else set()
            syms = [str(s).upper() for s in ((list_env or {}).get("symbols") or [])]
            fired.update(syms)
            first_seen = dict(doc.get("first_seen", {}).get(today) or {})
            for s in syms:
                first_seen.setdefault(s, (list_env or {}).get("as_of") or t.isoformat())
            doc["first_seen"] = {today: first_seen}  # one day kept: arrival times for the research SLO
            cons[consumer] = {
                "fired_at": t.isoformat(),
                "decision": decision,
                "list_as_of": (list_env or {}).get("as_of"),
                "list_source": (list_env or {}).get("list_source"),
                "day": today,
                "symbols_fired": sorted(fired),
            }
            fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
            with os.fdopen(fd, "w") as fh:
                json.dump(doc, fh, indent=1, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            return cons[consumer]
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def first_seen_today(
    now: datetime | None = None, *, state_root: Path | str | None = None, doc: dict[str, Any] | None = None
) -> dict[str, str]:
    t = hot.now_et(now)
    d = doc if doc is not None else load(state_root)
    return dict((d.get("first_seen") or {}).get(t.date().isoformat()) or {})


def gate_main(consumer: str, *, argv: Iterable[str] = (), list_env: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convenience for a script's ``__main__``: read the list projection, decide, print one JSON line."""
    if list_env is None:
        try:
            from lib.data_broker import scalp_list as sl
        except ImportError:
            from scripts.lib.data_broker import scalp_list as sl  # type: ignore
        list_env = sl.get_scalp_list()
    d = decide(consumer, list_env)
    d["gate"] = "scalp_list_trigger"
    print(json.dumps(d, default=str))
    return {"decision": d, "list_env": list_env}
