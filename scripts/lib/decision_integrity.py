"""DecisionIntegrity@v1 — one deterministic validation result before an
actionable (or actionable-looking) plan reaches Telegram, CIO synthesis, Watch,
an entry ticket, an alert, or a downstream recommendation.

Why (SCHD, 2026-09-25 10:48 ET): the re-entry card rendered "Plan: buy-limit in
zone · stop $33.55 · target $35.30" at a price of $33.12 — already below the
plan's own stop — because the card built that line from the mere existence of
stop/target and nothing on the path compared price to the stop. The
"fresh ✓ (0h)" gate passed under a 96-hour TTL with the age rounded to whole
hours; "wash blocked until Oct 8" was a house 30-day hold on ANY taxable sell
(the sale was a gain, so no wash-sale rule applied); the held note showed one
account of two; and "Want me to watch it?" armed nothing.

This module does not build a competing decision engine. It composes the
validators the repository already has:
  * `cio_entry_state.evaluate`          — BLOCKED reasons incl. price ≤ stop
  * `watch_canonical_quote.derive_freshness` — market-session-aware quote age
  * `holdings_universe` dust policy where available
and adds the joins that were missing (plan age/version, tax evidence class,
alert arming, order semantics). States are machine-readable; a state that is
not VALID_CURRENT suppresses actionable mechanics (sizing, R:R, order language)
and keeps historical levels visibly historical.

Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0 — nothing here sizes, orders,
sets stops or touches a broker; it only decides what may be SHOWN as current.
Architecture: v3.3 §9.3 kernel invariants ("current price coherent with entry",
"blocked state has no current mechanics", "previous plan is not current plan"),
§3 law 18 (research availability ≠ financial authorization), §20.3 (no silent
degradation).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

SCHEMA = "DecisionIntegrity@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

# ── states (severity order: first match wins as the primary state) ───────────
MISSING_EVIDENCE = "MISSING_EVIDENCE"
STALE_OR_CONFLICTING_QUOTE = "STALE_OR_CONFLICTING_QUOTE"
INVALIDATED_BY_PRICE_OR_STOP = "INVALIDATED_BY_PRICE_OR_STOP"
STALE_PLAN = "STALE_PLAN"
HELD_POLICY_BLOCK = "HELD_POLICY_BLOCK"
HOUSE_WASH_HOLD = "HOUSE_WASH_HOLD"
TAX_STATUS_UNVERIFIED = "TAX_STATUS_UNVERIFIED"
WAIT_FOR_CONFIRMATION = "WAIT_FOR_CONFIRMATION"
VALID_CURRENT = "VALID_CURRENT"
ALERT_NOT_ARMED = "ALERT_NOT_ARMED"          # alert_state, never the primary state

# Severity order. Invalidation outranks a quote conflict: when the desk print
# AND the operator's print both sit below the stop, the decision-critical fact
# is the invalidation; the conflict is still listed and disclosed.
STATES = (
    MISSING_EVIDENCE, INVALIDATED_BY_PRICE_OR_STOP, STALE_OR_CONFLICTING_QUOTE,
    STALE_PLAN, HELD_POLICY_BLOCK, HOUSE_WASH_HOLD, TAX_STATUS_UNVERIFIED,
    WAIT_FOR_CONFIRMATION, VALID_CURRENT,
)
SEVERITY = {s: i for i, s in enumerate(STATES)}

# Plan freshness: a watchlist entry plan is a snapshot of structure at a price.
# Older than this, or minted at a price that no longer brackets the current
# quote, it is history until re-validated. Env-overridable, never hardcoded in
# callers.
PLAN_MAX_AGE_DAYS = float(os.environ.get("TRADEAI_PLAN_MAX_AGE_DAYS", "14"))
# Operator-quoted price vs desk price: beyond this the two quotes CONFLICT and
# must be reconciled/disclosed, not silently overridden either way.
QUOTE_CONFLICT_PCT = float(os.environ.get("TRADEAI_QUOTE_CONFLICT_PCT", "0.75"))
HOUSE_WASH_HOLD_DAYS = int(os.environ.get("TRADEAI_HOUSE_WASH_HOLD_DAYS", "30"))
DUST_SHARES = float(os.environ.get("TRADEAI_HELD_DUST_SHARES", "1.0"))
WEEKEND_HOLD_HOURS = float(os.environ.get("TRADEAI_QUOTE_WEEKEND_HOLD_HOURS", "72"))

WASH_NONE = "NONE"
WASH_HOUSE_HOLD_GAIN = "HOUSE_HOLD_NO_LOSS"        # taxable sell at a GAIN: house hold only
WASH_SALE_RISK = "WASH_SALE_RISK_LOSS"             # taxable sell at a LOSS inside ±30d
WASH_UNVERIFIED = "UNVERIFIED"                     # a taxable sell exists, lots unknown


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _dt(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def quote_age_label(as_of: Any, *, now: Optional[datetime] = None) -> str:
    """Exact quote age: minutes under an hour, else hours with one decimal.

    "0h old" hid an 18-minute age and would hide a 59-minute one. Never round
    away up to an hour.
    """
    dt = _dt(as_of)
    if dt is None:
        return "age unknown"
    ref = now or datetime.now(timezone.utc)
    secs = max(0.0, (ref - dt).total_seconds())
    if secs < 3600:
        return f"{int(round(secs / 60.0))}m old"
    return f"{secs / 3600.0:.1f}h old"


# ── tax evidence ─────────────────────────────────────────────────────────────

def fifo_realized_gain(transactions: Iterable[Mapping[str, Any]], *, sell_date: Any = None) -> dict[str, Any]:
    """FIFO realized gain for the LAST sell (or the sell on ``sell_date``) in one
    account/symbol series of trade_transactions rows.

    Rows: trade_date, action (Buy/Sell…), quantity, price, amount (signed),
    fees. Deterministic; abstains (``evidence="INSUFFICIENT_LOTS"``) when the
    sold quantity exceeds the lots the rows can account for.
    """
    rows = sorted(
        (dict(r) for r in transactions if r),
        key=lambda r: (str(r.get("trade_date") or ""), str(r.get("trade_time") or "")),
    )
    lots: list[list[float]] = []          # [qty, price]
    last: Optional[dict[str, Any]] = None
    for r in rows:
        act = str(r.get("action") or "").lower()
        qty = _f(r.get("quantity")) or 0.0
        px = _f(r.get("price"))
        if act.startswith("buy") and qty > 0 and px is not None:
            lots.append([qty, px])
            continue
        if not (act.startswith("sell") or act in ("sold",)) or qty <= 0 or px is None:
            continue
        if sell_date is not None and str(r.get("trade_date") or "")[:10] != str(sell_date)[:10]:
            # consume lots for earlier sells so later ones see the right basis
            remaining = qty
            while remaining > 1e-9 and lots:
                take = min(remaining, lots[0][0])
                lots[0][0] -= take
                remaining -= take
                if lots[0][0] <= 1e-9:
                    lots.pop(0)
            continue
        remaining = qty
        basis = 0.0
        matched = 0.0
        while remaining > 1e-9 and lots:
            take = min(remaining, lots[0][0])
            basis += take * lots[0][1]
            lots[0][0] -= take
            remaining -= take
            matched += take
            if lots[0][0] <= 1e-9:
                lots.pop(0)
        proceeds = qty * px - (_f(r.get("fees")) or 0.0)
        last = {
            "trade_date": str(r.get("trade_date") or "")[:10],
            "quantity": qty,
            "price": px,
            "proceeds": round(proceeds, 2),
            "matched_quantity": round(matched, 4),
            "basis": round(basis, 2),
            "realized_gain": round(proceeds - basis, 2) if remaining <= 1e-9 else None,
            "evidence": "FIFO_FROM_TRADE_TRANSACTIONS" if remaining <= 1e-9 else "INSUFFICIENT_LOTS",
            "unmatched_quantity": round(remaining, 4),
        }
        if sell_date is not None:
            break
    return last or {"evidence": "NO_SELL", "realized_gain": None}


def classify_wash(
    *,
    last_taxable_sell_date: Any,
    realized_gain: Optional[float],
    evidence: str = "",
    acquisitions_within_30d: Iterable[Mapping[str, Any]] = (),
    today: Optional[date] = None,
    hold_days: int = HOUSE_WASH_HOLD_DAYS,
) -> dict[str, Any]:
    """Label a recent taxable sell honestly.

    * No taxable sell inside the hold window → NONE.
    * Sell at a verified GAIN → HOUSE_HOLD_NO_LOSS: the house's 30-day re-entry
      hold applies as policy; the wash-sale rule (which only disallows LOSSES)
      does not. Never phrase this as "wash blocked".
    * Sell at a verified LOSS → WASH_SALE_RISK_LOSS: any acquisition of the same
      or substantially identical security within 30 days before/after — in ANY
      account, IRA included (Rev. Rul. 2008-5: an IRA repurchase disallows the
      loss permanently) — is a wash-sale risk. Named acquisitions are listed.
    * Sell exists but lots/gain unknown → UNVERIFIED: conservative review state;
      no legal conclusion is asserted either way.
    """
    today = today or datetime.now(timezone.utc).date()
    sell_dt = _dt(last_taxable_sell_date)
    if sell_dt is None:
        return {"kind": WASH_NONE, "hold_until": None, "realized_gain": None,
                "label": "no taxable sell in window", "legal_conclusion": None}
    hold_until = (sell_dt.date() + timedelta(days=hold_days)).isoformat()
    in_window = sell_dt.date() + timedelta(days=hold_days) >= today
    if not in_window:
        return {"kind": WASH_NONE, "hold_until": hold_until, "realized_gain": realized_gain,
                "label": "taxable sell outside the hold window", "legal_conclusion": None}
    acq = [dict(a) for a in acquisitions_within_30d if a]
    base = {"hold_until": hold_until, "sell_date": sell_dt.date().isoformat(),
            "realized_gain": realized_gain, "evidence": evidence or None,
            "acquisitions_within_30d": acq}
    if realized_gain is None:
        return {**base, "kind": WASH_UNVERIFIED,
                "label": f"taxable sell {sell_dt.date().isoformat()}; lot basis not on file — "
                         f"house hold to {hold_until}; wash-sale status UNVERIFIED",
                "legal_conclusion": None}
    if realized_gain >= 0:
        return {**base, "kind": WASH_HOUSE_HOLD_GAIN,
                "label": f"house 30-day re-entry hold to {hold_until} after a taxable sell at a "
                         f"GAIN (+${realized_gain:,.2f}); no wash-sale rule applies to a gain",
                "legal_conclusion": "NOT_A_WASH_SALE"}
    return {**base, "kind": WASH_SALE_RISK,
            "label": f"taxable LOSS sale {sell_dt.date().isoformat()} (${realized_gain:,.2f}); a repurchase "
                     f"before {hold_until} in any account (IRA included) risks permanent disallowance"
                     + (f"; {len(acq)} acquisition(s) already inside the window" if acq else ""),
            "legal_conclusion": "WASH_SALE_RISK"}


# ── order semantics ──────────────────────────────────────────────────────────

def order_semantics(*, price: Optional[float], entry_low: Optional[float], entry_high: Optional[float]) -> dict[str, Any]:
    """What "buy-limit in zone" would actually do at the current price.

    A buy LIMIT at or above the market is marketable: it fills at once at or
    below the limit. When price is BELOW the zone, "buy limit in zone" is not a
    wait-for-reclaim instruction — it is an immediate fill. The reclaim intent
    is a conditional alert (price cross above zone low), never an order.
    """
    if price is None or entry_low is None or entry_high is None:
        return {"buy_limit_in_zone": "UNKNOWN", "advisory": None}
    if price < entry_low:
        return {
            "buy_limit_in_zone": "MARKETABLE_IMMEDIATE_FILL",
            "advisory": (f"price ${price:,.2f} is below the zone; a buy limit at ${entry_low:,.2f}–${entry_high:,.2f} "
                         f"would fill immediately near ${price:,.2f}. A reclaim is a conditional alert "
                         f"(price cross above ${entry_low:,.2f}), not an order."),
        }
    if price > entry_high:
        return {"buy_limit_in_zone": "RESTING_BELOW_MARKET",
                "advisory": f"price ${price:,.2f} is above the zone; a buy limit in zone rests until price falls into it."}
    return {"buy_limit_in_zone": "AT_MARKET_INSIDE_ZONE",
            "advisory": f"price ${price:,.2f} is inside the zone; a buy limit at the top of the zone is marketable."}


# ── the validator ────────────────────────────────────────────────────────────

@dataclass
class Evidence:
    symbol: str
    price: Optional[float] = None
    price_as_of: Any = None
    price_source: Optional[str] = None
    operator_quoted_price: Optional[float] = None
    operator_quote_as_of: Any = None
    entry_low: Optional[float] = None
    entry_high: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    plan_id: Any = None
    plan_created_at: Any = None
    price_at_plan: Optional[float] = None
    plan_invalidation_text: Optional[str] = None
    rsi: Optional[float] = None
    atr: Optional[float] = None
    positions: list[dict[str, Any]] = field(default_factory=list)   # [{account, qty}]
    wash: Optional[dict[str, Any]] = None                            # classify_wash() result
    confirmations_complete: Optional[bool] = None
    confirmation_gaps: list[str] = field(default_factory=list)
    alert: Optional[dict[str, Any]] = None                           # {armed, alert_id, condition, delivery_receipt}
    cio_action: Optional[str] = None
    earnings_date: Any = None


def validate(ev: Evidence | Mapping[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Return the DecisionIntegrity@v1 result for one symbol's presentation."""
    if isinstance(ev, Mapping):
        ev = Evidence(**{k: v for k, v in ev.items() if k in Evidence.__dataclass_fields__})
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    reasons: list[dict[str, Any]] = []

    def add(code: str, state: str, detail: str, **extra: Any) -> None:
        reasons.append({"code": code, "state": state, "detail": detail, **extra})

    price = _f(ev.price)
    lo, hi, stop, target = _f(ev.entry_low), _f(ev.entry_high), _f(ev.stop), _f(ev.target)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo

    # 1. quote freshness (market-session aware) — reuse watch_canonical_quote
    quote = {"as_of": ev.price_as_of, "age_label": quote_age_label(ev.price_as_of, now=now),
             "freshness": None, "session": None, "source": ev.price_source}
    if price is None:
        add("NO_PRICE", MISSING_EVIDENCE, "no current price")
    else:
        try:
            from scripts.lib.watch_canonical_quote import derive_freshness
        except ImportError:  # pragma: no cover
            from lib.watch_canonical_quote import derive_freshness  # type: ignore
        fresh, session = derive_freshness(ev.price_as_of, now=now)
        # Weekend / closed-market hold: the last regular or after-hours print
        # within WEEKEND_HOLD_HOURS is the operative quote when nothing newer
        # can exist. derive_freshness judges by the print's own session, so a
        # Friday-close print reads STALE on Saturday; we label it explicitly.
        try:
            from scripts.lib.watch_canonical_quote import market_session_for
        except ImportError:  # pragma: no cover
            from lib.watch_canonical_quote import market_session_for  # type: ignore
        qdt0 = _dt(ev.price_as_of)
        now_session = market_session_for(now)
        if (fresh == "STALE" and now_session == "closed" and qdt0 is not None
                and session in ("regular", "afterhours")
                and (now - qdt0).total_seconds() <= WEEKEND_HOLD_HOURS * 3600):
            fresh = "LAST_SESSION_HELD"
        quote["freshness"], quote["session"] = fresh, session
        quote["now_session"] = now_session
        if fresh in ("STALE", "DATA_UNAVAILABLE"):
            add("QUOTE_STALE", STALE_OR_CONFLICTING_QUOTE,
                f"quote {quote['age_label']} is {fresh} for session {session}", freshness=fresh)
    # 1b. operator-quoted price vs desk price: reconcile or disclose
    op = _f(ev.operator_quoted_price)
    if op is not None and price is not None:
        diff_pct = (op - price) / price * 100.0
        quote["operator_quoted_price"] = op
        quote["operator_vs_desk_pct"] = round(diff_pct, 2)
        if abs(diff_pct) > QUOTE_CONFLICT_PCT:
            add("QUOTE_CONFLICT", STALE_OR_CONFLICTING_QUOTE,
                f"operator quoted ${op:,.2f} vs desk ${price:,.2f} ({diff_pct:+.2f}%); "
                f"the two prints are from different times — disclose both, act on neither until reconciled",
                operator_quoted_price=op, desk_price=price)

    # 2. plan presence / age / invalidation
    plan_age_days = None
    if lo is None and hi is None:
        add("NO_PLAN", MISSING_EVIDENCE, "no entry zone on file")
    else:
        pc = _dt(ev.plan_created_at)
        if pc is None:
            add("PLAN_UNDATED", STALE_PLAN, "plan carries no created_at/version; age cannot be verified")
        else:
            plan_age_days = round((now - pc).total_seconds() / 86400.0, 1)
            if plan_age_days > PLAN_MAX_AGE_DAYS:
                add("PLAN_OLD", STALE_PLAN, f"plan is {plan_age_days} days old (> {PLAN_MAX_AGE_DAYS:g}d)",
                    plan_age_days=plan_age_days)
        if price is not None and stop is not None and price <= stop:
            add("PRICE_AT_OR_BELOW_STOP", INVALIDATED_BY_PRICE_OR_STOP,
                f"price ${price:,.2f} is at/below the plan stop ${stop:,.2f}; the long plan is invalidated",
                price=price, stop=stop)
        # reuse the entry-state evaluator for the remaining hard reasons
        try:
            try:
                from scripts.lib import cio_entry_state as ces
            except ImportError:  # pragma: no cover
                from lib import cio_entry_state as ces  # type: ignore
            age_h = None
            qdt = _dt(ev.price_as_of)
            if qdt is not None:
                age_h = (now - qdt).total_seconds() / 3600.0
            es = ces.evaluate({
                "symbol": ev.symbol, "price": price, "quote_age_h": age_h,
                "entry_low": lo, "entry_high": hi, "stop": stop, "target": target,
                "atr": ev.atr, "cio_action": ev.cio_action, "earnings_date": ev.earnings_date,
                "wash_blocked": False, "held": False,
            }, today=now.date())
            for r in es.get("reasons") or []:
                if "below the plan stop" in r or "quote is" in r:
                    continue           # already stated above with codes
                add("ENTRY_STATE_BLOCKED", WAIT_FOR_CONFIRMATION if "R:R" in r or "stop/target" in r
                    else STALE_OR_CONFLICTING_QUOTE if "price" in r and "no current" in r else WAIT_FOR_CONFIRMATION, r)
            entry_state = es.get("state")
            rr = es.get("rr")
            distance_pct = es.get("distance_pct")
        except Exception as exc:  # noqa: BLE001 — never lose the validation to a helper
            entry_state, rr, distance_pct = None, None, None
            add("ENTRY_STATE_UNAVAILABLE", MISSING_EVIDENCE, f"cio_entry_state unavailable: {type(exc).__name__}")
        if entry_state == "NOT_YET":
            add("PRICE_OUTSIDE_ZONE", WAIT_FOR_CONFIRMATION,
                f"price is outside the entry zone ({distance_pct:+.2f}% vs zone)" if distance_pct is not None
                else "price is outside the entry zone", distance_pct=distance_pct)
        elif entry_state == "ENTRY_NEAR":
            add("PRICE_NEAR_ZONE", WAIT_FOR_CONFIRMATION, f"price is near the zone ({distance_pct:+.2f}%)",
                distance_pct=distance_pct)
        if ev.confirmations_complete is False:
            add("CONFIRMATIONS_INCOMPLETE", WAIT_FOR_CONFIRMATION,
                "confirmations incomplete: " + ", ".join(ev.confirmation_gaps or []) if ev.confirmation_gaps
                else "confirmations incomplete")

    # 3. held policy (every account, dust named separately)
    held_rows = [p for p in (ev.positions or []) if (_f(p.get("qty")) or 0.0) > 0]
    held_total = sum(_f(p.get("qty")) or 0.0 for p in held_rows)
    dust_only = bool(held_rows) and all((_f(p.get("qty")) or 0.0) < DUST_SHARES for p in held_rows)
    if held_rows:
        accounts = ", ".join(f"{p.get('account') or 'account'} {(_f(p.get('qty')) or 0.0):g} sh" for p in held_rows)
        add("HELD", HELD_POLICY_BLOCK,
            f"held in {len(held_rows)} account(s): {accounts}"
            + (" — residual (dust) lots; the flat-position re-entry policy does not apply, "
               "the add-to-position policy does" if dust_only else
               " — add-to-position policy applies, not the flat re-entry policy"),
            accounts=[{"account": p.get("account"), "qty": _f(p.get("qty"))} for p in held_rows],
            dust_only=dust_only, total_qty=round(held_total, 4))

    # 4. tax evidence
    wash = dict(ev.wash or {})
    if wash.get("kind") == WASH_SALE_RISK:
        add("WASH_SALE_RISK", HOUSE_WASH_HOLD, wash.get("label") or "taxable loss sale inside 30d",
            legal_conclusion="WASH_SALE_RISK")
    elif wash.get("kind") == WASH_HOUSE_HOLD_GAIN:
        add("HOUSE_WASH_HOLD", HOUSE_WASH_HOLD, wash.get("label") or "house 30-day hold after a taxable sell at a gain",
            legal_conclusion="NOT_A_WASH_SALE")
    elif wash.get("kind") == WASH_UNVERIFIED:
        add("TAX_UNVERIFIED", TAX_STATUS_UNVERIFIED, wash.get("label") or "taxable sell in window; lots unverified")

    # 5. alert arming — reported, never promised
    alert = dict(ev.alert or {})
    if alert.get("armed"):
        alert_state = "ARMED_DELIVERY_RECEIPTED" if alert.get("delivery_receipt") else "ARMED_NO_DELIVERY_RECEIPT"
    else:
        alert_state = ALERT_NOT_ARMED

    # primary state = most severe reason; VALID_CURRENT only when nothing blocks
    primary = VALID_CURRENT
    for r in reasons:
        if SEVERITY.get(r["state"], 99) < SEVERITY.get(primary, 99):
            primary = r["state"]
    actionable = primary == VALID_CURRENT
    levels_as = "current" if actionable else ("conditional" if primary == WAIT_FOR_CONFIRMATION else "historical")
    sem = order_semantics(price=price, entry_low=lo, entry_high=hi)

    plan = {
        "plan_id": ev.plan_id, "created_at": str(ev.plan_created_at) if ev.plan_created_at else None,
        "age_days": plan_age_days, "entry_low": lo, "entry_high": hi, "stop": stop, "target": target,
        "price_at_plan": _f(ev.price_at_plan), "invalidation_text": ev.plan_invalidation_text,
        "shown_as": levels_as,
    }
    next_obs = []
    if primary == INVALIDATED_BY_PRICE_OR_STOP:
        next_obs.append(f"a new validated setup (fresh plan version) — the ${stop:,.2f}-stop plan is history"
                        if stop is not None else "a new validated setup")
        if lo is not None:
            next_obs.append(f"reclaim above ${lo:,.2f} with RSI in band would re-open review, via a fresh plan")
    elif primary == WAIT_FOR_CONFIRMATION and lo is not None:
        next_obs.append(f"price entering ${lo:,.2f}–${hi:,.2f} with confirmations green")
    if wash.get("hold_until") and primary in (HOUSE_WASH_HOLD, TAX_STATUS_UNVERIFIED):
        next_obs.append(f"house hold lifts {wash['hold_until']}")
    return {
        "schema": SCHEMA, "authority": AUTHORITY, "mbi_behavior": 0,
        "symbol": str(ev.symbol or "").upper(),
        "state": primary,
        "actionable_mechanics": actionable,
        "reasons": reasons,
        "reason_codes": [r["code"] for r in reasons],
        "quote": quote,
        "plan": plan,
        "order_semantics": sem,
        "held": {"held": bool(held_rows), "total_qty": round(held_total, 4), "dust_only": dust_only,
                 "accounts": [{"account": p.get("account"), "qty": _f(p.get("qty"))} for p in held_rows]},
        "wash": wash or {"kind": WASH_NONE},
        "alert_state": alert_state,
        "alert": alert or None,
        "next_observation": next_obs,
        "evaluated_at": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def suppress_mechanics(advisory: Mapping[str, Any], integrity: Mapping[str, Any]) -> dict[str, Any]:
    """Strip actionable mechanics from a desk advisory when integrity says so.

    Sizing, R:R and reward/risk numbers are removed (not zeroed) and the plan
    levels are relabelled historical; ``action`` becomes "Monitor / No Action".
    The original block is kept under ``historical_plan`` so nothing is lost.
    """
    if integrity.get("actionable_mechanics"):
        return dict(advisory)
    out = dict(advisory)
    hist = {k: out.get(k) for k in ("reentry_range_low", "reentry_range_high", "stop_loss", "target",
                                     "risk_per_share_low", "risk_per_share_high", "reward_low", "reward_high", "rr")}
    hist["shown_as"] = integrity.get("plan", {}).get("shown_as", "historical")
    hist["invalidated_by"] = [r["code"] for r in integrity.get("reasons", [])
                              if r["state"] == INVALIDATED_BY_PRICE_OR_STOP]
    out["historical_plan"] = hist
    for k in ("risk_per_share_low", "risk_per_share_high", "reward_low", "reward_high", "rr"):
        out[k] = None
    if isinstance(out.get("sizing"), dict):
        out["sizing"] = {"shares": None, "allocation": None,
                         "note": f"suppressed: {integrity.get('state')} — no actionable mechanics"}
    out["action"] = "Monitor / No Action"
    out["decision_integrity"] = {"state": integrity.get("state"), "reason_codes": integrity.get("reason_codes")}
    return out


def render_operator_summary(integrity: Mapping[str, Any]) -> list[str]:
    """Concise lines for a Telegram/CC card: state, why, what next, alert truth."""
    st = integrity.get("state")
    q = integrity.get("quote") or {}
    plan = integrity.get("plan") or {}
    lines = [f"Decision integrity: *{st}*" + (" — no actionable mechanics" if not integrity.get("actionable_mechanics") else "")]
    if q.get("operator_quoted_price") is not None:
        lines.append(f"Two prints: you quoted ${q['operator_quoted_price']:,.2f}; desk has ${(integrity.get('plan') or {}).get('_desk_price', '') or ''}".rstrip())
    for r in (integrity.get("reasons") or [])[:5]:
        lines.append(f"  – {r['detail']}")
    if plan.get("shown_as") == "historical" and plan.get("stop") is not None:
        lines.append(f"Historical plan (not current): zone ${plan.get('entry_low') or 0:,.2f}–${plan.get('entry_high') or 0:,.2f} · "
                     f"stop ${plan['stop']:,.2f} · target ${(plan.get('target') or 0):,.2f}"
                     + (f" · created {str(plan.get('created_at'))[:10]}" if plan.get("created_at") else " · undated"))
    for n in integrity.get("next_observation") or []:
        lines.append(f"Next: {n}")
    al = integrity.get("alert_state")
    lines.append("Watch alert: none armed — ask to arm one (nothing is monitored from this chat)"
                 if al == ALERT_NOT_ARMED else f"Watch alert: {al}")
    return lines


__all__ = [
    "SCHEMA", "STATES", "Evidence", "validate", "suppress_mechanics", "render_operator_summary",
    "quote_age_label", "fifo_realized_gain", "classify_wash", "order_semantics",
    "MISSING_EVIDENCE", "STALE_OR_CONFLICTING_QUOTE", "INVALIDATED_BY_PRICE_OR_STOP", "STALE_PLAN",
    "HELD_POLICY_BLOCK", "HOUSE_WASH_HOLD", "TAX_STATUS_UNVERIFIED", "WAIT_FOR_CONFIRMATION",
    "VALID_CURRENT", "ALERT_NOT_ARMED",
]
