#!/usr/bin/env python3
"""alpaca_throttle.py — GLOBAL cross-process rate limiter for Alpaca market-data (OHLCV) HTTP calls.

Why: ohlc_charts._fetch (Alpaca data API, IEX/SIP feed) had NO throttle/retry/cache. The chart UI,
the orchestrator's per-candidate scoring, the signal simulator and execution-quality analytics all hit
data.alpaca.markets independently. When a large candidate batch was scored (e.g. 547 candidates after a
screener pool rebuild), the burst tripped Alpaca's free-tier rate limit (HTTP 429) — which starved the
scoring stage of bars → 0 GO/A+ grades → 0 signals. Mirrors finviz_throttle but keyed to its OWN state
file and limits, so an Alpaca cooldown never blocks Finviz and vice-versa.

Usage (before any Alpaca data HTTP request):
    from alpaca_throttle import acquire, cooldown
    acquire()                          # blocks until a global slot is free (min-interval since last request)
    ...
    if resp.status == 429:
        cooldown(retry_after or 30)    # tell ALL processes to back off

Config (env, no hardcoding): ALPACA_MIN_INTERVAL (default 0.35s ≈ 170 req/min, under the 200/min free tier),
ALPACA_COOLDOWN_DEFAULT (default 30s).
"""
import fcntl
import json
import os
import time
from pathlib import Path

_STATE = Path(__file__).resolve().parent.parent / "data" / "state" / "alpaca_throttle.json"
_LOCK = _STATE.with_suffix(".lock")
MIN_INTERVAL = float(os.getenv("ALPACA_MIN_INTERVAL", "0.35"))
COOLDOWN_DEFAULT = float(os.getenv("ALPACA_COOLDOWN_DEFAULT", "30"))


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


def acquire(timeout=120):
    """Block until a global Alpaca request slot is free. Returns wait time actually slept.
    Fail-open after `timeout` (better a request than a wedged pipeline)."""
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
            return slept  # fail-open after timeout
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
