#!/usr/bin/env python3
"""finviz_throttle.py — GLOBAL cross-process rate limiter for ALL Finviz HTTP calls.

Why: ingestion, enrichment, news, charts and the screener runner each self-throttled, but ran as separate
processes with no shared limit — overlapping runs (e.g. continuous_runner cycle + noon orchestrator) hammered
Finviz simultaneously and tripped HTTP 429s (which then degraded scoring). This module serializes request
spacing across EVERY process via a small state file + flock.

Usage (before any Finviz HTTP request):
    from finviz_throttle import acquire, cooldown
    acquire()                      # blocks until a global slot is free (min-interval since last request)
    ...
    if resp.status_code == 429:
        cooldown(retry_after or 60)   # tell ALL processes to back off

Config (env, no hardcoding): FINVIZ_MIN_INTERVAL (default 2.5s), FINVIZ_COOLDOWN_DEFAULT (default 60s).
"""
import fcntl
import json
import os
import time
from pathlib import Path

_STATE = Path(__file__).resolve().parent.parent / "data" / "state" / "finviz_throttle.json"
_LOCK = _STATE.with_suffix(".lock")
MIN_INTERVAL = float(os.getenv("FINVIZ_MIN_INTERVAL", "2.5"))
COOLDOWN_DEFAULT = float(os.getenv("FINVIZ_COOLDOWN_DEFAULT", "60"))


def _read():
    try:
        return json.loads(_STATE.read_text())
    except Exception:
        return {}


def _write(d):
    try:
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d))
        tmp.replace(_STATE)
    except Exception:
        pass


def acquire(timeout=300):
    """Block until a global Finviz request slot is free. Returns wait time actually slept."""
    start = time.time()
    _LOCK.parent.mkdir(parents=True, exist_ok=True)
    slept = 0.0
    while True:
        with open(_LOCK, "a+") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                st = _read()
                now = time.time()
                cool_until = float(st.get("cooldown_until", 0))
                last = float(st.get("last_request", 0))
                ready_at = max(last + MIN_INTERVAL, cool_until)
                if now >= ready_at:
                    st["last_request"] = now
                    _write(st)
                    return slept
                wait = min(ready_at - now, 10.0)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
        if time.time() - start + wait > timeout:
            return slept  # fail-open after timeout: better a request than a dead pipeline
        time.sleep(wait)
        slept += wait


def cooldown(seconds=None):
    """Record a global cooldown (e.g. on HTTP 429 / Retry-After) so EVERY process backs off."""
    seconds = float(seconds or COOLDOWN_DEFAULT)
    with open(_LOCK, "a+") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            st = _read()
            st["cooldown_until"] = max(float(st.get("cooldown_until", 0)), time.time() + seconds)
            st["last_429_at"] = time.time()
            _write(st)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def status():
    st = _read()
    now = time.time()
    return {"cooling": now < float(st.get("cooldown_until", 0)),
            "cooldown_remaining_s": max(0, round(float(st.get("cooldown_until", 0)) - now, 1)),
            "last_request_age_s": round(now - float(st.get("last_request", 0)), 1) if st.get("last_request") else None,
            "min_interval_s": MIN_INTERVAL}
