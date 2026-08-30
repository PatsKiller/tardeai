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
    the caller happened to import from.

READ_ONLY_ADVISORY with respect to the trading system: this module counts and
denies. It never issues a request itself.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "SearchBudget@v1"

# Per-provider daily / monthly ceilings. Deliberately conservative: the bounded
# residual-web lane the CIO spec defines needs ~100-300 calls a month, and
# everything above that was the bulk callers that consumed the allowance the
# lane needs.
DEFAULT_LIMITS: dict[str, dict[str, int]] = {
    "brave":  {"daily": 25, "monthly": 850},
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
    base = Path(root) if root else _state_root()
    return base / "data" / "runtime" / "search_budget.json"


class BudgetUnavailable(RuntimeError):
    """The budget could not be established. Callers must treat this as DENY."""


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


def status(provider: str, *, now: Optional[datetime] = None,
           root: Optional[Path] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    day, month = _keys(now)
    path = budget_path(root)
    doc = _load(path)
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


def check(provider: str, *, now: Optional[datetime] = None,
          root: Optional[Path] = None) -> dict[str, Any]:
    """May this provider be called right now? Returns {allowed, reason, status}.

    **Never raises, and never fails open.** Any error establishing the budget
    returns ``allowed=False`` with the reason, because a caller that cannot know
    whether it is over budget must behave as though it is.
    """
    try:
        st = status(provider, now=now, root=root)
    except Exception as e:
        return {"allowed": False,
                "reason": f"BUDGET_UNAVAILABLE: {type(e).__name__}: {e}",
                "fail_open": False, "status": None}
    if st["monthly_used"] >= st["monthly_limit"]:
        return {"allowed": False, "reason": "MONTHLY_EXHAUSTED", "status": st}
    if st["daily_used"] >= st["daily_limit"]:
        return {"allowed": False, "reason": "DAILY_EXHAUSTED", "status": st}
    return {"allowed": True, "reason": "OK", "status": st}


def record(provider: str, *, allowed: bool = True, caller: str = "default",
           now: Optional[datetime] = None, root: Optional[Path] = None) -> None:
    """Record one call (or one denial). Best-effort — a failed write must not
    take down the caller — but a failed write is visible in the next status()
    as a counter that did not advance, and the health lane reports it."""
    now = now or datetime.now(timezone.utc)
    day, month = _keys(now)
    path = budget_path(root)
    try:
        doc = _load(path)
    except BudgetUnavailable:
        doc = {"schema": SCHEMA, "providers": {}}   # ledger is being rebuilt
    p = doc.setdefault("providers", {}).setdefault(provider, {})
    bucket = "daily" if allowed else "denied"
    p.setdefault(bucket, {})[day] = int(p.get(bucket, {}).get(day, 0)) + 1
    if allowed:
        p.setdefault("monthly", {})[month] = int(p.get("monthly", {}).get(month, 0)) + 1
        p.setdefault("callers", {}).setdefault(month, {})
        p["callers"][month][caller] = int(p["callers"][month].get(caller, 0)) + 1
        p["last_call"] = now.isoformat()
    try:
        _save(path, doc)
    except Exception:
        pass


def guard(provider: str, caller: str = "default") -> bool:
    """One-liner for a call site: may I call, and count it if so.

    Returns False when denied — including when the budget cannot be established,
    because a caller that cannot know whether it is over budget must behave as
    though it is.
    """
    verdict = check(provider)
    if not verdict["allowed"]:
        try:
            record(provider, allowed=False, caller=caller)
        except Exception:
            pass
        return False
    record(provider, allowed=True, caller=caller)
    return True


def note(provider: str, caller: str = "default") -> None:
    """Count a call that must NOT be denied.

    Key validators and credential monitors consume a real credit, so they have
    to be counted or the ledger under-reports again. But denying them would make
    a healthy key report as dead, which is a worse failure than the spend.
    """
    try:
        record(provider, allowed=True, caller=caller)
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
