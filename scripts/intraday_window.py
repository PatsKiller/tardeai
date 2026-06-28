#!/usr/bin/env python3
"""Fail-closed intraday trading-window resolver (P0-3).

Shared by the ATM auto-approval fast-path and the proposal lifecycle. The single hard
rule: a window-config parsing failure NEVER allows an autonomous/auto-approval action.

  * Non-intraday strategies are unrestricted (``applicable=False``).
  * An intraday strategy whose ``intraday_execution.trading_window_et`` is missing,
    malformed, or unparsable is BLOCKED with code ``intraday_window_config_invalid``.
  * An intraday strategy evaluated outside its valid window is BLOCKED with code
    ``outside_intraday_window``.

This module is import-light (no DB, no pytz) so it is cleanly unit-testable. ET is
resolved via ``zoneinfo`` and boundaries are inclusive on both ends.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
INVALID_CODE = "intraday_window_config_invalid"
OUTSIDE_CODE = "outside_intraday_window"


def _strategy_yaml_path(strategy_id: str) -> Path:
    return ROOT / "config" / "strategies" / f"{strategy_id}.yaml"


def _hhmm_to_minutes(v: Any) -> int:
    parts = str(v).strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"not HH:MM: {v!r}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"out of range: {v!r}")
    return h * 60 + m


def parse_window(raw: Any) -> tuple[str, Any]:
    """Parse a ``{'start','end'}`` HH:MM ET window.

    Returns ``("ok", {...})`` with ``start_min``/``end_min`` or ``("invalid", reason)``.
    Fails closed on anything it cannot positively validate.
    """
    if not isinstance(raw, dict):
        return ("invalid", "window_not_mapping")
    s, e = raw.get("start"), raw.get("end")
    if s is None or e is None:
        return ("invalid", "window_missing_start_or_end")
    try:
        sm, em = _hhmm_to_minutes(s), _hhmm_to_minutes(e)
    except Exception as ex:  # malformed time tokens
        return ("invalid", f"window_unparsable:{ex}")
    if sm >= em:
        return ("invalid", f"window_non_positive_span:{s}-{e}")
    return ("ok", {"start": str(s), "end": str(e), "start_min": sm, "end_min": em})


def now_in_window(parsed: dict, now_et: dt.datetime | None = None) -> bool:
    """True if ``now_et`` (ET) falls within the parsed window. Boundaries inclusive.

    Fails CLOSED: any error computing the comparison returns False (block), never True.
    """
    try:
        if now_et is None:
            now_et = _now_et()
        cur = now_et.hour * 60 + now_et.minute
        return int(parsed["start_min"]) <= cur <= int(parsed["end_min"])
    except Exception:
        return False


def _now_et() -> dt.datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        # Last-resort: UTC. Callers in production always have zoneinfo; this keeps the
        # pure parser importable in minimal environments without failing open on time.
        return dt.datetime.now(dt.timezone.utc)


def _load_window_raw(strategy_id: str) -> tuple[bool, Any]:
    """Return ``(found, raw_or_reason)``.

    ``found=False`` means the intraday window config could not be loaded (missing file,
    YAML error, or absent ``trading_window_et`` key) — the caller MUST treat this as
    invalid/fail-closed for an intraday strategy.
    """
    p = _strategy_yaml_path(strategy_id)
    if not p.exists():
        return (False, "strategy_yaml_missing")
    try:
        import yaml
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as ex:
        return (False, f"strategy_yaml_unparsable:{ex}")
    win = ((cfg.get("intraday_execution") or {}).get("trading_window_et"))
    if win is None:
        return (False, "trading_window_et_absent")
    return (True, win)


def evaluate_intraday_window(
    strategy_id: str,
    *,
    now_et: dt.datetime | None = None,
    intraday: bool | None = None,
    window_raw: Any = None,
) -> dict:
    """Fail-closed gate result for the auto-approval fast-path.

    Returns a dict::

        {"applicable": bool, "blocked": bool, "code": str|None,
         "reason": str|None, "window": {...}|None}

    ``blocked=True`` means an autonomous/auto-approval action must NOT proceed.
    For test isolation, ``intraday`` and ``window_raw`` may be supplied directly to
    bypass class-lookup and file IO.
    """
    if intraday is None:
        try:
            from proposal_lifecycle import is_intraday
            intraday = bool(is_intraday(strategy_id))
        except Exception:
            # Class indeterminate — a non-intraday strategy must not be falsely blocked,
            # and "unknown class" is not evidence of "intraday". Treat as not-applicable.
            intraday = False

    if not intraday:
        return {"applicable": False, "blocked": False, "code": None, "reason": None, "window": None}

    if window_raw is None:
        found, raw = _load_window_raw(strategy_id)
        if not found:
            return {"applicable": True, "blocked": True, "code": INVALID_CODE,
                    "reason": f"intraday strategy {strategy_id}: {raw}", "window": None}
        window_raw = raw

    status, parsed = parse_window(window_raw)
    if status != "ok":
        return {"applicable": True, "blocked": True, "code": INVALID_CODE,
                "reason": f"intraday strategy {strategy_id}: {parsed}", "window": None}

    if not now_in_window(parsed, now_et):
        return {"applicable": True, "blocked": True, "code": OUTSIDE_CODE,
                "reason": f"{strategy_id} window {parsed['start']}-{parsed['end']} ET",
                "window": parsed}

    return {"applicable": True, "blocked": False, "code": None, "reason": None, "window": parsed}
