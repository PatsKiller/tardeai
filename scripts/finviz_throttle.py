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

Config (env, no hardcoding): FINVIZ_MIN_INTERVAL (default 2.5s), FINVIZ_COOLDOWN_DEFAULT (default 60s),
FINVIZ_MAX_COOLDOWN_S (default 86400s).

Corrupt state is discarded, not obeyed (2026-10-10): ``last_request`` is only ever written as ``now`` by a
successful acquire, so a value more than FUTURE_SKEW_S ahead of the clock was written by a process with a
wrong clock, and a ``cooldown_until`` more than FINVIZ_MAX_COOLDOWN_S ahead is not a Retry-After. Obeying
either made EVERY caller sleep its whole throttle timeout before each request: on 2026-10-09 21:51:48 ET
something wrote ``last_request`` = 2026-12-25T07:26:01Z, and the finviz-view-contracts n8n dry run (two
views, 300 s throttle wait each) was killed at its 300 s lane timeout on 2026-10-10 13:11Z. The discarded
value is kept in the state file under ``discarded`` as evidence.

Where the state lives (2026-10-10, GAP 13): ``throttle_state_path()`` -> ``<state root>/data/state/
finviz_throttle.json`` under the shared persistent-state root (``canonical_store_registry.
production_state_root``), never the code checkout. It was ``Path(__file__).parent.parent / data/state``:
correct only while the checkout's ``data/state`` is a symlink into persistent-state (the dev tree, the
served release). A git worktree, a scratch release or an agent run had a private throttle -- not rate-limited
together with production, and a stale/corrupt timestamp in one copy went unnoticed beside the other (RC1).
The resolver follows the pattern of ``scripts/lib/enrichment_cache_store.state_root`` (branch
n8nmat/finviz-cache-n8n, NOT merged here; this module depends only on main): a code checkout (a tree with
``scripts/``) is never the state root while the persistent-state marker exists.
"""
import fcntl
import json
import os
import sys
import time
from pathlib import Path

_CODE_ROOT = Path(__file__).resolve().parent.parent
STATE_REL = Path("data") / "state" / "finviz_throttle.json"
#: The persistent-state marker production_state_root() also keys on.
PERSISTENT_MARKER = "PERSISTENT_STATE_ROOT.json"


def _is_code_checkout(path) -> bool:
    try:
        return (Path(path) / "scripts").is_dir()
    except OSError:
        return False


def _persistent_default():
    pref = Path.home() / "trade-ai-releases" / "persistent-state"
    return pref if (pref / PERSISTENT_MARKER).is_file() else None


def throttle_state_root():
    """The shared state root every Finviz caller on this host agrees on (cron cwd, n8n executor, worktree).

    ``production_state_root()`` (TRADEAI_STATE_ROOT -> non-release TRADEAI_ROOT -> TRADEAI_PERSISTENT_STATE_ROOT
    -> the persistent-state marker -> CURRENT -> repo). When that lands on a code checkout (TRADEAI_ROOT pointed
    at a worktree, or the repo fallback) and the persistent-state marker exists, the marker wins: a checkout's
    ``data/`` is the shared store only by symlink accident. Import failure falls back to the same marker rule.
    """
    try:
        if str(_CODE_ROOT) not in sys.path:
            sys.path.insert(0, str(_CODE_ROOT))
        from scripts.lib.canonical_store_registry import production_state_root
        root = Path(production_state_root())
    except Exception as exc:  # noqa: BLE001 - the throttle must load even when the registry cannot
        print(f"[finviz_throttle] production_state_root unavailable ({type(exc).__name__}); "
              f"using the persistent-state marker", file=sys.stderr)
        root = _persistent_default() or _CODE_ROOT
    if _is_code_checkout(root):
        root = _persistent_default() or root
    return root


def throttle_state_path():
    return throttle_state_root() / STATE_REL


_STATE = throttle_state_path()
_LOCK = _STATE.with_suffix(".lock")
MIN_INTERVAL = float(os.getenv("FINVIZ_MIN_INTERVAL", "2.5"))
COOLDOWN_DEFAULT = float(os.getenv("FINVIZ_COOLDOWN_DEFAULT", "60"))
MAX_COOLDOWN_S = float(os.getenv("FINVIZ_MAX_COOLDOWN_S", "86400"))
#: A real ``last_request`` is written as ``now``; allow this much clock step before calling it corrupt.
FUTURE_SKEW_S = 60.0


def _corrupt_fields(st, now):
    """Pure: the state fields that cannot be honest at ``now`` -> {field: value}."""
    bad = {}
    try:
        last = float(st.get("last_request", 0))
    except (TypeError, ValueError):
        last = float("inf")
    if last > now + FUTURE_SKEW_S:
        bad["last_request"] = st.get("last_request")
    try:
        cool = float(st.get("cooldown_until", 0))
    except (TypeError, ValueError):
        cool = float("inf")
    if cool > now + MAX_COOLDOWN_S:
        bad["cooldown_until"] = st.get("cooldown_until")
    return bad


def _discard_corrupt(st, now):
    """Drop corrupt fields from ``st`` in place; record them under ``discarded``. Returns what was dropped."""
    bad = _corrupt_fields(st, now)
    if bad:
        for k in bad:
            st.pop(k, None)
        st["discarded"] = {"at": now, "fields": bad}
        print(f"[finviz_throttle] discarded corrupt state {bad} (now={now:.0f})", file=sys.stderr)
    return bad


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
                if _discard_corrupt(st, now):
                    _write(st)
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
    """Read-only. Writes nothing; ``corrupt`` names fields acquire() would discard."""
    st = _read()
    now = time.time()
    bad = _corrupt_fields(st, now)
    honest = {k: v for k, v in st.items() if k not in bad}
    ready_at = max(float(honest.get("last_request", 0)) + MIN_INTERVAL, float(honest.get("cooldown_until", 0)))
    return {"corrupt": bad, "would_wait_s": round(max(0.0, ready_at - now), 1),
            "cooling": now < float(honest.get("cooldown_until", 0)),
            "cooldown_remaining_s": max(0, round(float(honest.get("cooldown_until", 0)) - now, 1)),
            "last_request_age_s": (round(now - float(honest["last_request"]), 1)
                                   if honest.get("last_request") else None),
            "min_interval_s": MIN_INTERVAL, "state_path": str(_STATE)}
