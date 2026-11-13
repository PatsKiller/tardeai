"""Provider-exhausted breaker for the in-process LLM call path (LQ-20261107-2565 ADDENDUM 2).

Operator requirement (2026-11-12): "the system must know on its own that Grok is out and reroute to the
next provider." Measured before this existed: xAI exhausted its weekly quota at 2026-11-10 10:35 ET and
answered 403 ``personal-team-blocked:spending-limit`` to every call; the grok proxy folded it into 502,
``lib.oauth_lane_status.classify_failure`` knew no quota class, and every scheduled caller retried into
the wall for 54 h — 2,284 failed rows, 324 in the last 8 h, zero successes. Each caller had its own
half-fallback (``generate_cloud`` loops grok/chatgpt; ``holding_protection_advisor`` re-derives a lane
list; ``topic_curator`` swallows; ``grok_stop_review`` gives up). Nothing shared the knowledge that a
provider was out, so nothing stopped calling it.

This module is that shared knowledge. ``lib.llm_consumption.gate_and_generate`` — the funnel every
``log_call`` caller reaches with a ``process_id`` — asks :func:`routed_lane` before it reserves anything,
so the decision is provider-level and applies to every caller at once:

* after ``consecutive_threshold`` (default 3) quota/5xx failures from one provider, that provider is
  recorded EXHAUSTED in shared state with an expiry;
* an exhausted provider is skipped and the call goes to the next provider in the configured order
  ``grok -> chatgpt -> deepseek``;
* the expiry IS the probe: after it (default 30 min) the provider is tried once more. A success clears
  the streak; another failure re-exhausts it for the same window. No caller is ever asked to guess a
  reset time — the provider's own answer is the probe;
* a DeepSeek candidate is only used as an automatic hop inside the operator's scheduled paid window
  (``lib.deepseek_offpeak.in_operator_scheduled_window_et``: weekdays 09:00-21:00 ET, weekends any hour).
  A caller that explicitly requested a DeepSeek lane is not vetoed by the window: it keeps its own
  off-peak deferral / manual-trigger decision (``lib.llm_deferral``) instead of becoming NO_PROVIDER_LEFT;
* when no provider is left the caller raises ``NO_PROVIDER_LEFT``. It never fabricates output.

State is one JSON file (``PROVIDER_BREAKER_PATH`` → ``$TRADEAI_STATE_ROOT/data/runtime/provider_breaker.json``
→ the checkout's ``data/runtime``) so every process on the host sees the same breaker. A write that fails
is not fatal: an unreachable state file degrades to the previous behaviour (every provider tried), never
to a false "everything is out".

Read-only advisory. No broker, no order, no credential: this module names providers, never tokens.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

#: The configured provider order (addendum 2, and the same walk ``generate_cloud`` already used for the
#: free OAuth pair). deepseek is last because it is the metered lane.
CANONICAL_ORDER = ("grok", "chatgpt", "deepseek")

PROVIDER_OAUTH = {"grok": "grok", "chatgpt": "chatgpt"}
_DEEPSEEK_LANES = frozenset({
    "deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro",
    "fast", "fast_think", "pro", "pro_think", "pro_max",
})
#: Lane name used when a reroute targets DeepSeek, most specific first. A lane the process's allowlist
#: does not name is never chosen (see :func:`lane_for_provider`).
_DEEPSEEK_PREFERENCE = ("deepseek-flash", "deepseek-v4-flash", "fast", "pro", "pro_think")

DEFAULT_CONSECUTIVE = 3
DEFAULT_PROBE_S = 1800.0

# A quota wall is the upstream saying "this account may not use the model now". Same vocabulary the proxy
# and lib.oauth_lane_status use; kept here so a 402/403-spending-limit/429 from ANY provider counts.
_QUOTA_MARKERS = (
    "entitlement_exhausted", "entitlement exhausted", "spending-limit", "personal-team-blocked",
    "run out of credits", "need a grok subscription", "insufficient credits", "insufficient balance",
    "quota exceeded", "quota_exceeded", "rate limit", "rate_limit", "too many requests",
    "http 402", "http 429", " 402", " 429", "payment required",
)
# 5xx / gateway text. A read TIMEOUT is deliberately NOT here: it is the caller's deadline expiring on a
# live provider (LQ-20261107-978), and exhausting a provider for it would hide a working lane.
_SERVER_MARKERS = (
    "http 500", "http 502", "http 503", "http 504", "http 529",
    " 500", " 502", " 503", " 504", " 529",
    "bad gateway", "service unavailable", "gateway time-out", "gateway timeout",
    "internal server error", "provider_5xx", "overloaded",
)


def provider_of(lane: str | None) -> str | None:
    """Provider for a lane name: grok/chatgpt/deepseek, or None for a lane this module does not route."""
    name = (lane or "").strip().lower()
    if name in PROVIDER_OAUTH:
        return name
    if name.startswith("deepseek") or name in _DEEPSEEK_LANES:
        return "deepseek"
    return None


def _threshold() -> int:
    try:
        return max(1, int(os.environ.get("PROVIDER_BREAKER_THRESHOLD", DEFAULT_CONSECUTIVE)))
    except (TypeError, ValueError):
        return DEFAULT_CONSECUTIVE


def _probe_s() -> float:
    try:
        return max(1.0, float(os.environ.get("PROVIDER_BREAKER_PROBE_SEC", DEFAULT_PROBE_S)))
    except (TypeError, ValueError):
        return DEFAULT_PROBE_S


def state_path() -> Path:
    explicit = os.environ.get("PROVIDER_BREAKER_PATH")
    if explicit:
        return Path(explicit)
    root = os.environ.get("TRADEAI_STATE_ROOT")
    if root:
        return Path(root) / "data" / "runtime" / "provider_breaker.json"
    return Path(__file__).resolve().parent.parent.parent / "data" / "runtime" / "provider_breaker.json"


def read_state(path: str | Path | None = None) -> dict:
    try:
        data = json.loads(Path(path or state_path()).read_text())
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - unreadable state means "nothing known", never "everything is out"
        return {}


def _write_state(data: dict, path: str | Path | None = None) -> None:
    target = Path(path or state_path())
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, target)
    except Exception:  # noqa: BLE001 - losing the breaker only restores the old retry-into-the-wall behaviour
        pass


def classify_for_breaker(error: str | None) -> str | None:
    """``quota`` / ``server_error`` for failures that mean "this provider is out"; None to ignore.

    None for a caller-deadline timeout, an auth lapse (the lane-availability check owns that) and every
    policy refusal — a breaker exists to stop hammering a provider, not to hide a caller's own error.
    """
    text = (error or "").lower()
    if not text:
        return None
    if any(m in text for m in _QUOTA_MARKERS):
        return "quota"
    if any(m in text for m in _SERVER_MARKERS):
        return "server_error"
    return None


def note_result(provider: str | None, *, ok: bool, error: str | None = None,
                now: float | None = None, path: str | Path | None = None) -> dict | None:
    """Record one call's outcome for ``provider``. Returns the provider's entry, or None when not counted."""
    prov = (provider or "").strip().lower()
    if prov not in CANONICAL_ORDER:
        return None
    now = time.time() if now is None else float(now)
    data = read_state(path)
    prev = data.get(prov) or {}
    if ok:
        if not prev:
            return None
        data.pop(prov, None)
        _write_state(data, path)
        return None
    kind = classify_for_breaker(error)
    if kind is None:
        return prev or None  # a timeout or a caller error neither proves the provider out nor clears it
    streak = int(prev.get("streak") or 0) + 1
    entry = {
        "provider": prov,
        "kind": kind,
        "streak": streak,
        "last_error": (error or "")[:200],
        "last_failure_at": now,
        "exhausted_until": prev.get("exhausted_until"),
    }
    if streak >= _threshold() or (isinstance(entry["exhausted_until"], (int, float))
                                  and entry["exhausted_until"] > now):
        # Still failing when the probe came due: another full window, no fresh threshold to climb.
        entry["exhausted_until"] = now + _probe_s()
        entry["exhausted_at"] = now
    data[prov] = entry
    _write_state(data, path)
    return entry


def exhausted_until(provider: str, *, now: float | None = None, path=None) -> float | None:
    """The provider's exhaustion expiry, or None when it is not exhausted (or the expiry has passed)."""
    now = time.time() if now is None else float(now)
    entry = read_state(path).get((provider or "").strip().lower()) or {}
    until = entry.get("exhausted_until")
    if isinstance(until, (int, float)) and float(until) > now:
        return float(until)
    return None


def is_exhausted(provider: str, *, now: float | None = None, path=None) -> bool:
    return exhausted_until(provider, now=now, path=path) is not None


def clear(provider: str, *, path=None) -> None:
    data = read_state(path)
    if data.pop((provider or "").strip().lower(), None) is not None:
        _write_state(data, path)


def note_refusal(process_id: str, requested: str, reason: str, *, now: float | None = None,
                 path: str | Path | None = None) -> None:
    """Count one call refused because no provider was left, so the refusal is visible somewhere.

    A refusal writes no consumption row (nothing was sent, and a row per refused call is the noise this
    change exists to remove), so the count and the last reason live in this file for the health surfaces.
    """
    now = time.time() if now is None else float(now)
    data = read_state(path)
    ref = data.get("_refusals") if isinstance(data.get("_refusals"), dict) else {}
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    bucket = ref.get(day) if isinstance(ref.get(day), dict) else {"count": 0}
    bucket["count"] = int(bucket.get("count") or 0) + 1
    bucket["last_at"] = now
    bucket["last_process"] = str(process_id)
    bucket["last_requested"] = str(requested)
    bucket["last_reason"] = str(reason)[:300]
    ref = {day: bucket}  # one day of history is enough to see a wall; older buckets are dropped
    data["_refusals"] = ref
    _write_state(data, path)


def deepseek_in_window(now=None) -> bool:
    """True inside the operator's scheduled paid window (weekdays 09:00-21:00 ET; weekends any hour).

    Delegates to the canonical policy helper instead of restating its hours — the same window
    ``lib.llm_deferral`` and the DeepSeek wrappers use. A ``now`` epoch float is accepted so callers
    holding ``time.time()`` need not convert. ``TRADEAI_OFFPEAK_NOW_UTC`` pins it for tests.
    """
    when = now
    if isinstance(now, (int, float)) and not isinstance(now, bool):
        from datetime import datetime, timezone

        when = datetime.fromtimestamp(float(now), tz=timezone.utc)
    try:
        try:
            from lib.deepseek_offpeak import in_operator_scheduled_window_et as _in_window
        except ImportError:
            from .deepseek_offpeak import in_operator_scheduled_window_et as _in_window
        return bool(_in_window(when))
    except Exception:  # noqa: BLE001 - an unreadable clock must not authorise a paid fallback
        return False


def lane_for_provider(provider: str, allowed_lanes) -> str | None:
    """The lane name to use for ``provider`` given a process allowlist, or None when it is not allowed."""
    allowed = [str(x).strip().lower() for x in (allowed_lanes or [])]
    if provider in PROVIDER_OAUTH:
        return provider if provider in allowed else None
    if provider == "deepseek":
        for name in _DEEPSEEK_PREFERENCE:
            if name in allowed:
                return name
        return None
    return None


def _oauth_available(lane: str) -> bool:
    try:
        try:
            from lib.oauth_lane_status import lane_available as _available
        except ImportError:
            from .oauth_lane_status import lane_available as _available
        return bool(_available(lane))
    except Exception:  # noqa: BLE001 - an unreadable probe is not evidence the lane is down
        return True


def _skip_reason(lane: str, *, allowed_lanes, now: float | None, path,
                 window_applies: bool = True) -> str | None:
    """Why ``lane`` must not be used now, or None when it can be.

    ``window_applies`` is False for the *requested* lane: the operator's paid window exists to stop an
    automatic reroute spending the metered lane at peak, not to veto a caller that explicitly asked for
    DeepSeek — that caller already has the off-peak deferral / manual-trigger decision in
    ``lib.llm_deferral`` (LQ-20261107-2565 F2). Exhaustion still applies to a requested lane.
    """
    provider = provider_of(lane)
    if provider is None:
        return "not a routed provider"
    if lane_for_provider(provider, allowed_lanes) is None:
        return "not in the process allowlist"
    until = exhausted_until(provider, now=now, path=path)
    if until is not None:
        left = int(until - (time.time() if now is None else float(now)))
        return f"provider exhausted ({left}s left before the probe)"
    if provider in PROVIDER_OAUTH and not _oauth_available(lane):
        return "OAuth lane unavailable"
    if window_applies and provider == "deepseek" and not deepseek_in_window(now):
        return "outside the 09:00-21:00 ET scheduled paid window"
    return None


class NoProviderLeft(RuntimeError):
    """Every permitted provider is exhausted, unavailable, or outside its window. Fail closed."""


def routed_lane(process_id: str, requested_lane: str, *, allowed_lanes, now: float | None = None,
                path: str | Path | None = None) -> dict:
    """Decide which lane actually serves this call.

    Returns ``{"lane": <lane>, "requested": <lane>, "reroute": <dict|None>, "skipped": [...]}``.
    ``reroute`` is None only when the requested lane itself is usable. Raises :class:`NoProviderLeft`
    when nothing is — the caller then raises on to its own caller; it never invents an answer.
    """
    requested = (requested_lane or "").strip().lower()
    skipped: list[dict] = []
    # A caller that explicitly asked for a DeepSeek lane off the paid window is NOT skipped here: it keeps
    # its pre-existing off-peak deferral / manual-trigger path (lib.llm_deferral) instead of being turned
    # into NO_PROVIDER_LEFT by the breaker (LQ-20261107-2565 F2). The window still gates every *hop*.
    why = _skip_reason(requested, allowed_lanes=allowed_lanes, now=now, path=path, window_applies=False)
    if why is None:
        return {"lane": requested, "requested": requested, "reroute": None, "skipped": []}
    skipped.append({"provider": provider_of(requested), "lane": requested, "why": why})

    for provider in CANONICAL_ORDER:
        if provider == provider_of(requested):
            continue
        lane = lane_for_provider(provider, allowed_lanes)
        if lane is None:
            skipped.append({"provider": provider, "lane": None, "why": "not in the process allowlist"})
            continue
        why = _skip_reason(lane, allowed_lanes=allowed_lanes, now=now, path=path)
        if why is not None:
            skipped.append({"provider": provider, "lane": lane, "why": why})
            continue
        return {
            "lane": lane,
            "requested": requested,
            "reroute": {
                "requested": requested,
                "executed": lane,
                "requested_provider": provider_of(requested),
                "executed_provider": provider,
                "reason": skipped[0]["why"],
                "skipped": skipped[1:],
                # Never silent: the row carries which providers were passed over and why.
                "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            "skipped": skipped,
        }

    detail = "; ".join(f"{s['provider'] or s['lane'] or '?'}: {s['why']}" for s in skipped)
    raise NoProviderLeft(
        f"CLOUD_GENERATION_FAILED_CLOSED: {process_id}: NO_PROVIDER_LEFT on {requested} — {detail}. "
        "Nothing was sent and nothing is fabricated; the call must surface UNKNOWN."
    )
