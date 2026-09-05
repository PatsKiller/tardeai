#!/usr/bin/env python3
"""search_budget.py — a per-provider search budget that cannot fail open.

Measured 2026-08-30. The Brave budget layer was correct for the callers that
used it and saw roughly 15% of the traffic:

    ledger  monthly_calls  2026-08: 150      last_call 2026-08-10
    provider dashboard     2026-08: ~1,000   trending above the prior month

Four callers held their own Brave client — their own key read, their own HTTP
call — and never imported the budgeted one. The alert path was wired, scheduled,
and reaching a channel; it reported `monthly_pct: 17.6, monthly_alert: "ok"`
while the provider hit 100% of its spend ceiling. A working alarm on an
unrepresentative sensor.

Three properties this module exists to guarantee:

  * **Per provider.** One provider exhausting itself must not silently spend
    another's allowance, and "we are at 17%" must name which provider.
  * **Never fail open.** A budget-check error DENIES. The previous
    implementation caught every exception in `_load_budget()` and returned
    `{}`, which the caller then rebuilt as a fresh zero counter — so a corrupt
    or unreadable ledger produced an *unbudgeted call*. That is backwards: the
    whole point of the check is to be conservative when it cannot be sure.
  * **Survives a process.** State is a file under the canonical state root, not
    an in-memory cache, and not a path relative to whichever release directory
    the caller happened to import from. Overnight F3 hardens the write path
    with an exclusive flock so concurrent cron invocations cannot both observe
    an under-limit counter and both spend.

Shared API for callers (including WAVE F1/F2 residual-web binding):

    check(provider)       → {allowed, reason, status}   # read-only preflight
    try_consume(provider) → same shape; atomic check+count under flock
    guard(provider)       → bool                         # try_consume convenience
    record / note         → count after the fact / validators

READ_ONLY_ADVISORY with respect to the trading system: this module counts and
denies. It never issues a request itself.
"""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA = "SearchBudget@v1"

# Per-provider daily / monthly ceilings.
#
# THE TWO CEILINGS HAVE DIFFERENT JOBS. They previously did not, and that was a
# defect rather than a belt-and-braces: brave daily 25 x 30 days = 750, against
# a monthly of 850. The daily cap was therefore a second copy of the monthly
# one, and it bound first on every burst. Measured 2026-08-31: 25 calls made,
# **3 denied**, while August's monthly counter stood at 25 of 850 — the lane was
# refused research with 97% of the month's allowance unspent.
#
#   daily    an anti-runaway circuit breaker. Its job is to bound a LOOP BUG,
#            not spend. It should sit well above a heavy legitimate day, because
#            a denial here is not a downgrade — brave_search.py returns False and
#            the research is simply lost; there is no fallback lane wired.
#   monthly  the cost bound. This is the number that maps to money.
#
# Sizing, 2026-09-05, from measured demand and observed provider capacity:
#   * Budgeted traffic is ~12/day, ~360/month run-rate (Sept: 60 calls in 5 days).
#   * The historical UNBUDGETED peak this module was built to catch was the
#     provider dashboard's ~1,000/month in 2026-08 (see the docstring above).
#   * Brave's own headers, observed 2026-09-05: 50 req/sec, and a per_month
#     window of 0 = NOT METERED. The provider imposes no monthly ceiling on this
#     key, so the monthly number below is purely OUR cost choice.
#   * 1,500/month is ~1.5 units of a thousand queries: low single-digit dollars
#     a month at any per-1k rate in the normal range, and it covers the historical
#     peak plus Hermes research headroom.
DEFAULT_LIMITS: dict[str, dict[str, int]] = {
    "brave":  {"daily": 120, "monthly": 1500},
    "tavily": {"daily": 20, "monthly": 500},
    "searxng": {"daily": 10_000, "monthly": 300_000},   # self-hosted, effectively free
}

WARN_PCT = 70
CRITICAL_PCT = 90


def _state_root() -> Path:
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root())
    except Exception:
        try:
            from lib.canonical_store_registry import production_state_root  # type: ignore
            return Path(production_state_root())
        except Exception:
            return Path.home() / "trade-ai-releases" / "persistent-state"


def budget_path(root: Optional[Path] = None) -> Path:
    """Durable ledger path. Always under production_state_root/data/runtime.

    Dry-run quote (2026-08-31):
      production_state_root → ~/trade-ai-releases/persistent-state
      ledger → …/persistent-state/data/runtime/search_budget.json
    """
    base = Path(root) if root else _state_root()
    return base / "data" / "runtime" / "search_budget.json"


class BudgetUnavailable(RuntimeError):
    """The budget could not be established. Callers must treat this as DENY."""


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


@contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    """Exclusive flock on a sidecar so concurrent cron processes serialize."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(path)
    if not lock.exists():
        lock.touch()
    with open(lock, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _load(path: Path) -> dict[str, Any]:
    """Read the ledger. Raises rather than returning an empty dict.

    The old code swallowed every exception here and returned `{}`; the caller
    read that as "no calls recorded yet" and proceeded. An unreadable ledger
    must never look like an empty one.
    """
    if not path.exists():
        return {"schema": SCHEMA, "providers": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise BudgetUnavailable(f"budget ledger unreadable at {path}: {e}") from e
    if not isinstance(doc, dict):
        raise BudgetUnavailable(f"budget ledger malformed at {path}")
    doc.setdefault("providers", {})
    return doc


def _save(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)                      # atomic; a torn ledger reads as unavailable


#: Monthly units held back from SCHEDULED bulk callers so an on-demand or
#: operator query is never starved by a cron job that ran first.
#:
#: The original brave_search.py comment — "Reserve 150 for P0/manual searches
#: out of 1000" — had the right instinct and a false premise: there was no 1000,
#: and no reserve was ever implemented. The instinct is kept here and made real.
#: A denied on-demand call is a question nobody answers, because there is no
#: fallback provider wired behind a refusal.
MONTHLY_RESERVE: dict[str, int] = {
    "brave": 200,
}

#: Callers answering a question someone is waiting for. These may draw on the
#: reserve; scheduled bulk jobs may not. Mirrors brave_search.ON_DEMAND_CALLERS.
ON_DEMAND_CALLERS: frozenset[str] = frozenset({
    "web_research", "intel_query", "manual", "operator",
})


def effective_monthly_limit(provider: str, caller: str, monthly_limit: int) -> int:
    """The monthly ceiling THIS caller may spend to.

    On-demand callers see the full limit. Everything else stops at the reserve
    line. An unknown caller is treated as scheduled: fail closed, consistent
    with this module's other refusals.
    """
    if caller in ON_DEMAND_CALLERS:
        return monthly_limit
    return max(0, monthly_limit - reserve_for(provider, monthly_limit))


#: A reserve may never exceed this share of the budget it is carved from.
RESERVE_MAX_SHARE = 5   # i.e. at most one fifth


def reserve_for(provider: str, monthly_limit: int) -> int:
    """How much of `monthly_limit` is held back — bounded by the limit itself.

    The reserve is a fixed count, but the limit is configurable
    (SEARCH_BUDGET_BRAVE_MONTHLY). A flat 200 against a limit of 150 yields an
    effective ceiling of ZERO: every scheduled call denied, reason
    MONTHLY_RESERVE_ONLY, while the ledger truthfully reports 0 used of 150.
    A provider silently switched off by a config value that looks conservative
    is the same failure shape as a green tile over a degraded run — it looks
    like restraint and it is an outage.

    So the reserve is capped at a fifth of whatever the budget actually is. It
    protects on-demand callers without ever being able to starve everyone.
    """
    want = MONTHLY_RESERVE.get(provider, 0)
    return min(want, max(0, monthly_limit // RESERVE_MAX_SHARE))


def _limits(provider: str) -> dict[str, int]:
    lim = dict(DEFAULT_LIMITS.get(provider, {"daily": 10, "monthly": 200}))
    for scope in ("daily", "monthly"):
        env = os.getenv(f"SEARCH_BUDGET_{provider.upper()}_{scope.upper()}")
        if env:
            try:
                lim[scope] = int(env)
            except ValueError:
                pass                       # a bad override keeps the safe default
    return lim


def _keys(now: datetime) -> tuple[str, str]:
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")


def _status_from_doc(provider: str, doc: dict[str, Any], now: datetime,
                     path: Path) -> dict[str, Any]:
    day, month = _keys(now)
    p = (doc.get("providers") or {}).get(provider) or {}
    daily = int((p.get("daily") or {}).get(day, 0))
    monthly = int((p.get("monthly") or {}).get(month, 0))
    lim = _limits(provider)
    pct = round(monthly / lim["monthly"] * 100, 1) if lim["monthly"] else 0.0
    return {
        "provider": provider, "as_of": now.replace(microsecond=0).isoformat(),
        "daily_used": daily, "daily_limit": lim["daily"],
        "monthly_used": monthly, "monthly_limit": lim["monthly"],
        "monthly_pct": pct,
        "alert": "critical" if pct >= CRITICAL_PCT else
                 "warning" if pct >= WARN_PCT else "ok",
        "denied_today": int((p.get("denied") or {}).get(day, 0)),
        "ledger_path": str(path),
    }


def _apply_record(doc: dict[str, Any], provider: str, *, allowed: bool,
                  caller: str, now: datetime) -> None:
    day, month = _keys(now)
    p = doc.setdefault("providers", {}).setdefault(provider, {})
    bucket = "daily" if allowed else "denied"
    p.setdefault(bucket, {})[day] = int(p.get(bucket, {}).get(day, 0)) + 1
    if allowed:
        p.setdefault("monthly", {})[month] = int(p.get("monthly", {}).get(month, 0)) + 1
        p.setdefault("callers", {}).setdefault(month, {})
        p["callers"][month][caller] = int(p["callers"][month].get(caller, 0)) + 1
        p["last_call"] = now.isoformat()


def status(provider: str, *, now: Optional[datetime] = None,
           root: Optional[Path] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    path = budget_path(root)
    doc = _load(path)
    return _status_from_doc(provider, doc, now, path)


def check(provider: str, *, caller: str = "default",
          now: Optional[datetime] = None,
          root: Optional[Path] = None) -> dict[str, Any]:
    """May this provider be called right now? Returns {allowed, reason, status}.

    **Never raises, and never fails open.** Any error establishing the budget
    returns ``allowed=False`` with the reason, because a caller that cannot know
    whether it is over budget must behave as though it is.

    Read-only: does not mutate the ledger. Prefer ``try_consume`` / ``guard`` at
    the call site so concurrent cron processes cannot both spend the last unit.
    """
    try:
        st = status(provider, now=now, root=root)
    except Exception as e:
        return {"allowed": False,
                "reason": f"BUDGET_UNAVAILABLE: {type(e).__name__}: {e}",
                "fail_open": False, "status": None}
    eff = effective_monthly_limit(provider, caller, st["monthly_limit"])
    if st["monthly_used"] >= st["monthly_limit"]:
        return {"allowed": False, "reason": "MONTHLY_EXHAUSTED", "status": st}
    if st["monthly_used"] >= eff:
        # The month is not exhausted — the BULK allowance is. Distinct reason so
        # an operator reading a refusal knows a manual query would still go out.
        return {"allowed": False, "reason": "MONTHLY_RESERVE_ONLY", "status": st}
    if st["daily_used"] >= st["daily_limit"]:
        return {"allowed": False, "reason": "DAILY_EXHAUSTED", "status": st}
    return {"allowed": True, "reason": "OK", "status": st}


def try_consume(provider: str, *, caller: str = "default",
                now: Optional[datetime] = None,
                root: Optional[Path] = None) -> dict[str, Any]:
    """Atomically check the budget and consume one unit when allowed.

    Holds an exclusive flock for the read-modify-write so two cron processes
    cannot both observe an under-limit counter and both spend. On any error
    establishing or writing the ledger: ``allowed=False`` (never fail open).
    """
    now = now or datetime.now(timezone.utc)
    path = budget_path(root)
    try:
        with _exclusive(path):
            try:
                doc = _load(path)
            except BudgetUnavailable as e:
                return {"allowed": False,
                        "reason": f"BUDGET_UNAVAILABLE: {type(e).__name__}: {e}",
                        "fail_open": False, "status": None}
            st = _status_from_doc(provider, doc, now, path)
            eff = effective_monthly_limit(provider, caller, st["monthly_limit"])
            if st["monthly_used"] >= eff:
                _apply_record(doc, provider, allowed=False, caller=caller, now=now)
                try:
                    _save(path, doc)
                except Exception:
                    pass
                reason = ("MONTHLY_EXHAUSTED"
                          if st["monthly_used"] >= st["monthly_limit"]
                          else "MONTHLY_RESERVE_ONLY")
                return {"allowed": False, "reason": reason, "status":
                        _status_from_doc(provider, doc, now, path)}
            if st["daily_used"] >= st["daily_limit"]:
                _apply_record(doc, provider, allowed=False, caller=caller, now=now)
                try:
                    _save(path, doc)
                except Exception:
                    pass
                return {"allowed": False, "reason": "DAILY_EXHAUSTED", "status":
                        _status_from_doc(provider, doc, now, path)}
            _apply_record(doc, provider, allowed=True, caller=caller, now=now)
            try:
                _save(path, doc)
            except Exception as e:
                # Could not persist the consume → deny rather than spend uncounted
                return {"allowed": False,
                        "reason": f"BUDGET_UNAVAILABLE: {type(e).__name__}: {e}",
                        "fail_open": False, "status": st}
            return {"allowed": True, "reason": "OK",
                    "status": _status_from_doc(provider, doc, now, path)}
    except Exception as e:
        return {"allowed": False,
                "reason": f"BUDGET_UNAVAILABLE: {type(e).__name__}: {e}",
                "fail_open": False, "status": None}


def record(provider: str, *, allowed: bool = True, caller: str = "default",
           now: Optional[datetime] = None, root: Optional[Path] = None) -> None:
    """Record one call (or one denial) under exclusive flock.

    A failed or corrupt ledger must **not** be rebuilt as a fresh zero counter
    (that was the fail-open write path). Skip the write instead; the next
    ``check`` / ``try_consume`` will DENY on the unreadable ledger.
    """
    now = now or datetime.now(timezone.utc)
    path = budget_path(root)
    try:
        with _exclusive(path):
            try:
                doc = _load(path)
            except BudgetUnavailable:
                return                       # never overwrite a corrupt ledger with zeros
            _apply_record(doc, provider, allowed=allowed, caller=caller, now=now)
            try:
                _save(path, doc)
            except Exception:
                pass
    except Exception:
        pass


def guard(provider: str, caller: str = "default", *,
          now: Optional[datetime] = None,
          root: Optional[Path] = None) -> bool:
    """One-liner for a call site: may I call, and count it if so.

    Returns False when denied — including when the budget cannot be established,
    because a caller that cannot know whether it is over budget must behave as
    though it is. Uses ``try_consume`` so the decision and the count are atomic
    across concurrent processes.
    """
    return bool(try_consume(provider, caller=caller, now=now, root=root)["allowed"])


def note(provider: str, caller: str = "default", *,
         now: Optional[datetime] = None,
         root: Optional[Path] = None) -> None:
    """Count a call that must NOT be denied.

    Key validators and credential monitors consume a real credit, so they have
    to be counted or the ledger under-reports again. But denying them would make
    a healthy key report as dead, which is a worse failure than the spend.
    """
    try:
        record(provider, allowed=True, caller=caller, now=now, root=root)
    except Exception:
        pass


def all_status(*, now: Optional[datetime] = None,
               root: Optional[Path] = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for provider in DEFAULT_LIMITS:
        try:
            out[provider] = status(provider, now=now, root=root)
        except Exception as e:
            out[provider] = {"provider": provider, "error": str(e)}
    return out
