"""search_spend.py — the Brave dollar budget: pools, shares, daily pacing (SearchSpend@v1).

Operator, 2026-10-10: "I have $20 maximum a month on Brave already, trying not to use it all
... prioritize the search for scalps that are about to fire". The ledger
(``lib/search_budget``) counts REQUESTS; this module turns those counts into DOLLARS with the
price in ``config/search_routing_policy.json`` and decides, per paid request, whether the
request's budget pool may spend it.

The lines (policy ``budget``; all compared to GROSS spend, before the $5 monthly credit):

  * nothing above ``local_ceiling_usd`` ($18) — headroom under the $20 account cap;
  * the operator pool (a reserve) may run to $18 and bypasses daily pacing;
  * the scalp pool has first claim and may run to ``working_target_usd`` ($15);
  * background pools (catalyst, other) stop at ``non_priority_stop_usd`` ($12) AND at their own
    share of the month and of the day, so they can never consume the scalp share or the reserve;
  * daily pacing: base = working target / NYSE trading days in the month; unspent pace carries
    forward by at most ``carry_over_max_days`` x base; an overspent pace is repaid from the next
    day, never below ``floor_fraction_of_base`` x base.

Ledger keys are UTC days and months (``search_budget._keys``); this module uses the same keys
so a decision and the counter it reads can never disagree about which day it is.

Pure: no network, no writes. ``make_gate`` returns the callable that
``search_budget.try_consume(gate=...)`` evaluates inside the ledger lock.
AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

SCHEMA = "SearchSpend@v1"
PROVIDER = "brave"
ROUTED_PREFIX = "route."
OPERATOR_POOL = "operator"


def _holidays(year: int) -> set[date]:
    try:
        from scripts.lib.cio_market_session import nyse_holidays
    except ImportError:  # pragma: no cover - dual-import shape
        from lib.cio_market_session import nyse_holidays  # type: ignore
    try:
        return set(nyse_holidays(year))
    except Exception:  # noqa: BLE001 — weekdays-only is the conservative fallback (more days, smaller base)
        return set()


def trading_days(year: int, month: int) -> list[date]:
    hol = _holidays(year)
    n = calendar.monthrange(year, month)[1]
    out = []
    for d in range(1, n + 1):
        day = date(year, month, d)
        if day.weekday() < 5 and day not in hol:
            out.append(day)
    return out


def usd_per_request(policy: dict[str, Any]) -> float:
    return float((policy.get("pricing") or {}).get("usd_per_request") or 0.0)


def pool_of_caller(caller: str, policy: dict[str, Any]) -> str:
    """``route.<pool>`` → pool; anything else is unrouted legacy spend."""
    c = str(caller or "")
    if c.startswith(ROUTED_PREFIX):
        pool = c[len(ROUTED_PREFIX):]
        if pool in ((policy.get("budget") or {}).get("pools") or {}):
            return pool
    return "unrouted"


@dataclass
class SpendSnapshot:
    month_key: str
    day_key: str
    usd_per_request: float
    month_requests: int = 0
    day_requests: int = 0
    month_by_pool: dict[str, int] = field(default_factory=dict)
    day_by_pool: dict[str, int] = field(default_factory=dict)

    def usd(self, n: int | float) -> float:
        return round(float(n) * self.usd_per_request, 6)

    @property
    def month_usd(self) -> float:
        return self.usd(self.month_requests)

    @property
    def day_usd(self) -> float:
        return self.usd(self.day_requests)

    def month_pool_usd(self, pool: str) -> float:
        return self.usd(self.month_by_pool.get(pool, 0))

    def day_pool_usd(self, pool: str) -> float:
        return self.usd(self.day_by_pool.get(pool, 0))

    @property
    def day_nonoperator_usd(self) -> float:
        return self.usd(self.day_requests - self.day_by_pool.get(OPERATOR_POOL, 0))

    @property
    def before_today_nonoperator_usd(self) -> float:
        month_nonop = self.month_requests - self.month_by_pool.get(OPERATOR_POOL, 0)
        day_nonop = self.day_requests - self.day_by_pool.get(OPERATOR_POOL, 0)
        return self.usd(max(0, month_nonop - day_nonop))


def snapshot(doc: dict[str, Any], policy: dict[str, Any], now: datetime) -> SpendSnapshot:
    """Dollar view of the ledger for ``now``'s UTC day and month (ledger key convention)."""
    day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    p = ((doc or {}).get("providers") or {}).get(PROVIDER) or {}
    snap = SpendSnapshot(month_key=month, day_key=day, usd_per_request=usd_per_request(policy))
    snap.month_requests = int((p.get("monthly") or {}).get(month, 0) or 0)
    snap.day_requests = int((p.get("daily") or {}).get(day, 0) or 0)
    for caller, n in (((p.get("callers") or {}).get(month)) or {}).items():
        pool = pool_of_caller(caller, policy)
        snap.month_by_pool[pool] = snap.month_by_pool.get(pool, 0) + int(n or 0)
    for caller, n in (((p.get("caller_daily") or {}).get(day)) or {}).items():
        pool = pool_of_caller(caller, policy)
        snap.day_by_pool[pool] = snap.day_by_pool.get(pool, 0) + int(n or 0)
    return snap


def daily_allowance(policy: dict[str, Any], snap: SpendSnapshot, today: date) -> dict[str, float]:
    """Today's pace in dollars for the non-operator pools, with the arithmetic shown."""
    b = policy.get("budget") or {}
    pacing = b.get("pacing") or {}
    target = float(b.get("working_target_usd") or 0.0)
    days = trading_days(today.year, today.month)
    n = max(1, len(days))
    base = target / n
    floor = float(pacing.get("floor_fraction_of_base", 0.25)) * base
    if today not in days:
        allowance = float(pacing.get("non_trading_day_fraction_of_base", 0.25)) * base
        return {"base": round(base, 6), "trading_days": n, "elapsed_trading_days": sum(1 for d in days if d < today),
                "carry": 0.0, "allowance": round(allowance, 6), "trading_day": False}
    elapsed = sum(1 for d in days if d < today)
    carry = base * elapsed - snap.before_today_nonoperator_usd
    carry = min(carry, float(pacing.get("carry_over_max_days", 1.0)) * base)
    allowance = max(floor, base + carry)
    return {"base": round(base, 6), "trading_days": n, "elapsed_trading_days": elapsed,
            "carry": round(carry, 6), "allowance": round(allowance, 6), "trading_day": True}


@dataclass
class SpendDecision:
    allowed: bool
    reason: str
    pool: str
    est_usd: float
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decide(policy: dict[str, Any], snap: SpendSnapshot, pool: str, *, today: date,
           units: int = 1) -> SpendDecision:
    """May ``pool`` spend ``units`` paid requests now? Reasons, first that applies:

    UNKNOWN_POOL · LOCAL_CEILING · MONTH_LINE:<line> · POOL_MONTH_SHARE · DAILY_PACE · POOL_DAY_SHARE · OK
    """
    b = policy.get("budget") or {}
    pools = b.get("pools") or {}
    est = snap.usd(units)
    detail: dict[str, Any] = {"month_usd": snap.month_usd, "day_usd": snap.day_usd}
    if pool not in pools:
        return SpendDecision(False, "UNKNOWN_POOL", pool, est, detail)
    cfg = pools[pool] or {}
    after = snap.month_usd + est
    ceiling = float(b["local_ceiling_usd"])
    if after > ceiling + 1e-9:
        return SpendDecision(False, "LOCAL_CEILING", pool, est, {**detail, "line_usd": ceiling})
    line_name = cfg.get("month_line") or "non_priority_stop_usd"
    line = float(b.get(line_name) or 0.0)
    if after > line + 1e-9:
        return SpendDecision(False, f"MONTH_LINE:{line_name}", pool, est, {**detail, "line_usd": line})
    target = float(b["working_target_usd"])
    share = float(cfg.get("share") or 0.0)
    background = not cfg.get("reserve") and not cfg.get("first_claim")
    if background and snap.month_pool_usd(pool) + est > share * target + 1e-9:
        return SpendDecision(False, "POOL_MONTH_SHARE", pool, est,
                             {**detail, "pool_month_usd": snap.month_pool_usd(pool), "share_usd": round(share * target, 6)})
    if cfg.get("bypass_daily_pacing"):
        return SpendDecision(True, "OK", pool, est, detail)
    pace = daily_allowance(policy, snap, today)
    detail["pace"] = pace
    allowance = pace["allowance"]
    if snap.day_nonoperator_usd + est > allowance + 1e-9:
        return SpendDecision(False, "DAILY_PACE", pool, est, detail)
    if background and snap.day_pool_usd(pool) + est > share * allowance + 1e-9:
        return SpendDecision(False, "POOL_DAY_SHARE", pool, est,
                             {**detail, "pool_day_usd": snap.day_pool_usd(pool), "share_usd": round(share * allowance, 6)})
    return SpendDecision(True, "OK", pool, est, detail)


def make_gate(policy: dict[str, Any], pool: str,
              on_decision: Optional[Callable[[SpendDecision], None]] = None) -> Callable[..., Optional[str]]:
    """The ``search_budget.try_consume(gate=...)`` callable for one paid request from ``pool``."""

    def gate(doc: dict[str, Any], _status: dict[str, Any], provider: str, _caller: str, now: datetime) -> Optional[str]:
        if provider != PROVIDER:
            return None
        snap = snapshot(doc, policy, now)
        d = decide(policy, snap, pool, today=now.date())
        if on_decision is not None:
            try:
                on_decision(d)
            except Exception:  # noqa: BLE001
                pass
        return None if d.allowed else f"DOLLAR_BUDGET:{d.reason}"

    return gate


def report(policy: dict[str, Any], doc: dict[str, Any], now: Optional[datetime] = None) -> dict[str, Any]:
    """Month-to-date spend in dollars, per pool, against every line; with the alert level."""
    now = now or datetime.now(timezone.utc)
    snap = snapshot(doc, policy, now)
    b = policy.get("budget") or {}
    pricing = policy.get("pricing") or {}
    credit = float(pricing.get("free_credit_usd_per_month") or 0.0)
    target = float(b.get("working_target_usd") or 0.0)
    gross = snap.month_usd
    pct = round(100.0 * gross / target, 1) if target else 0.0
    alert_pct = float(b.get("alert_at_pct_of_target") or 80)
    if gross >= float(b.get("local_ceiling_usd") or 0):
        level = "critical"
    elif pct >= alert_pct:
        level = "warning"
    else:
        level = "ok"
    days = trading_days(now.year, now.month)
    elapsed = sum(1 for d in days if d <= now.date())
    run_rate = round(gross / elapsed * len(days), 4) if elapsed else 0.0
    pools = {}
    for name, cfg in (b.get("pools") or {}).items():
        pools[name] = {"month_usd": snap.month_pool_usd(name), "day_usd": snap.day_pool_usd(name),
                       "share": cfg.get("share"), "share_usd": round(float(cfg.get("share") or 0) * target, 4),
                       "month_line": cfg.get("month_line")}
    pools["unrouted"] = {"month_usd": snap.month_pool_usd("unrouted"), "day_usd": snap.day_pool_usd("unrouted"),
                         "note": "Brave requests from callers not routed through the engine (legacy paths)"}
    return {
        "schema": SCHEMA,
        "as_of": now.replace(microsecond=0).isoformat(),
        "month": snap.month_key,
        "day": snap.day_key,
        "usd_per_request": snap.usd_per_request,
        "month_requests": snap.month_requests,
        "day_requests": snap.day_requests,
        "gross_usd": round(gross, 4),
        "free_credit_usd": credit,
        "net_billed_usd": round(max(0.0, gross - credit), 4),
        "caps_basis": b.get("caps_basis"),
        "lines": {k: b.get(k) for k in ("non_priority_stop_usd", "working_target_usd", "local_ceiling_usd", "account_cap_usd")},
        "pct_of_target": pct,
        "alert_at_pct_of_target": alert_pct,
        "alert": level,
        "run_rate_month_usd": run_rate,
        "today_pace": daily_allowance(policy, snap, now.date()),
        "pools": pools,
    }


__all__ = ["SCHEMA", "SpendSnapshot", "SpendDecision", "trading_days", "snapshot", "daily_allowance",
           "decide", "make_gate", "report", "pool_of_caller", "usd_per_request"]
