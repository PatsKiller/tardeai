"""Durable semantic condition state for operator alerts.

Unchanged conditions do not create new operator events. Transitions do.

This is not a new notification plane — it is the missing state machine in front
of alert_events / Telegram so a timer, scorer cycle, or health re-check cannot
mint a new identity for the same material state.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Resolved at call time so tests can redirect via TRADEAI_ALERT_STATE_PATH / TRADEAI_ROOT.
_DEFAULT_REL = Path("data") / "runtime" / "alert_condition_state.json"


def _root() -> Path:
    env = os.environ.get("TRADEAI_ROOT") or os.environ.get("MATURITY_CONTROL_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def store_path(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    override = os.environ.get("TRADEAI_ALERT_STATE_PATH")
    if override:
        return Path(override)
    return _root() / _DEFAULT_REL


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict[str, Any]:
    return {
        "schema": "alert_condition_state@v1",
        "updated_at": _now(),
        "conditions": {},
        "metrics": {
            "new": 0,
            "ongoing": 0,
            "recovered": 0,
            "reversed": 0,
            "suppressed": 0,
        },
        "today_et": "",
        "today_metrics": {
            "new": 0,
            "ongoing": 0,
            "recovered": 0,
            "reversed": 0,
            "suppressed": 0,
        },
    }


def load_store(path: Path | None = None) -> dict[str, Any]:
    p = store_path(path)
    if not p.exists():
        return _empty()
    try:
        data = json.loads(p.read_text())
    except Exception:
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("conditions", {})
    data.setdefault("metrics", _empty()["metrics"])
    data.setdefault("today_metrics", _empty()["today_metrics"])
    return data


def save_store(data: dict[str, Any], path: Path | None = None) -> None:
    p = store_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now()
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _roll_today(data: dict[str, Any]) -> None:
    today = datetime.now(ET).date().isoformat()
    if data.get("today_et") != today:
        data["today_et"] = today
        data["today_metrics"] = {
            "new": 0,
            "ongoing": 0,
            "recovered": 0,
            "reversed": 0,
            "suppressed": 0,
        }


def _bump(data: dict[str, Any], action: str) -> None:
    _roll_today(data)
    data["metrics"][action] = int(data["metrics"].get(action, 0)) + 1
    data["today_metrics"][action] = int(data["today_metrics"].get(action, 0)) + 1
    if action in ("ongoing",):
        data["metrics"]["suppressed"] = int(data["metrics"].get("suppressed", 0)) + 1
        data["today_metrics"]["suppressed"] = int(data["today_metrics"].get("suppressed", 0)) + 1


def observe(
    key: str,
    state: str,
    *,
    alertable: bool = True,
    path: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record the current material state of a condition.

    alertable=True  → this observation is a problem / notify-worthy state
    alertable=False → this observation is healthy / recovered / not paging

    Returns:
      action:   new | ongoing | recovered | reversed | cleared
      notify:   whether an operator event should be created
      previous: last state or None
      uid:      durable semantic identity for this transition
    """
    key = str(key or "").strip()
    state = str(state or "").strip()
    if not key:
        raise ValueError("condition key required")

    data = load_store(path)
    conds = data["conditions"]
    prev = conds.get(key)
    prev_state = (prev or {}).get("state")
    prev_alertable = bool((prev or {}).get("alertable")) if prev else None

    if prev is None:
        action = "new" if alertable else "cleared"
        notify = bool(alertable)
    elif prev_state == state and bool(prev_alertable) == bool(alertable):
        action = "ongoing"
        notify = False
    elif prev_alertable and not alertable:
        action = "recovered"
        notify = True
    elif prev_state != state:
        action = "reversed" if alertable else "cleared"
        notify = bool(alertable) or action == "recovered"
        if action == "cleared":
            notify = False
    else:
        # same state string, alertable flipped False→True
        action = "new"
        notify = True

    rec = {
        "state": state,
        "alertable": bool(alertable),
        "updated_at": _now(),
        "last_action": action,
        "notify_count": int((prev or {}).get("notify_count", 0)) + (1 if notify else 0),
        "suppress_count": int((prev or {}).get("suppress_count", 0)) + (0 if notify else 1),
        "first_seen_at": (prev or {}).get("first_seen_at") or _now(),
    }
    if extra:
        rec["extra"] = extra
    conds[key] = rec

    metric_key = action if action in data["metrics"] else ("suppressed" if not notify else "new")
    if action == "cleared":
        metric_key = "recovered" if prev_alertable else "ongoing"
        if not prev_alertable:
            metric_key = "ongoing"
    if action == "ongoing" or not notify:
        _bump(data, "ongoing" if action == "ongoing" else metric_key)
        if action != "ongoing" and notify is False and action == "cleared" and not prev_alertable:
            pass
    else:
        _bump(data, action if action in ("new", "recovered", "reversed") else "new")

    save_store(data, path)

    uid = f"{key}:{state}"
    if action == "recovered":
        uid = f"{key}:RECOVERED:{prev_state or 'unknown'}"
    return {
        "action": action,
        "notify": notify,
        "previous": prev_state,
        "uid": uid,
        "key": key,
        "state": state,
        "suppress_count": rec["suppress_count"],
        "notify_count": rec["notify_count"],
    }


def today_metrics(path: Path | None = None) -> dict[str, Any]:
    data = load_store(path)
    _roll_today(data)
    return {
        "date_et": data.get("today_et"),
        **{k: int(data.get("today_metrics", {}).get(k, 0)) for k in
           ("new", "ongoing", "recovered", "reversed", "suppressed")},
        "unresolved": sum(
            1 for c in data.get("conditions", {}).values() if c.get("alertable")
        ),
    }


def unresolved_conditions(path: Path | None = None, *, prefix: str | None = None) -> list[dict[str, Any]]:
    data = load_store(path)
    out = []
    for key, rec in (data.get("conditions") or {}).items():
        if not rec.get("alertable"):
            continue
        if prefix and not key.startswith(prefix):
            continue
        out.append({"key": key, **rec})
    out.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return out
