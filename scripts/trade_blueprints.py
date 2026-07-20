#!/usr/bin/env python3
"""trade_blueprints.py — turn a directional view into constructible mechanics.

WHY THIS EXISTS
---------------
"Consider a call spread" is not a recommendation. It has the grammar of advice
and none of the content: no expiration, no strikes, no debit, no maximum loss,
no breakeven, no trigger, no invalidation. An operator cannot act on it and a
reviewer cannot check it, which means it can never be wrong — the same defect as
`IGNORE`, one level down.

Every function here returns EITHER a fully specified blueprint whose arithmetic
is computed from live quotes, OR a rejection naming the precise rule that failed.
There is no third outcome and no prose-only path.

ARITHMETIC OWNERSHIP
--------------------
Every payoff number below is computed here, in Python, from quoted inputs. No
model authors a strike, a quote, a greek, a maximum loss or a breakeven. Models
explain WHY a structure fits a thesis; they never say WHAT the structure is.

A blueprint built from estimated option prices is marked research-only and can
never become an executable proposal — `bs_estimate_only` already blocks at the
enterprise gate, and this module refuses to construct one in the first place.

PURE: no network, no database, no broker. Quotes are passed in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

SHARES_PER_CONTRACT = 100

# Liquidity rails. Deliberately shared with the options desk rather than
# redefined — divergent copies are how a card renders green while a gate refuses.
MAX_SPREAD_PCT = 12.0
MIN_OPEN_INTEREST = 50


class BlueprintRejected(Exception):
    """Carries the reasons, so a refusal always states its cause."""

    def __init__(self, structure: str, reasons: list[str]):
        self.structure = structure
        self.reasons = reasons
        super().__init__(f"{structure} rejected: {'; '.join(reasons)}")


@dataclass
class Quote:
    """One option contract's live market. `source` must be a real chain —
    constructing from estimates is refused, not silently downgraded."""
    occ_symbol: str
    strike: float
    bid: float
    ask: float
    delta: float | None = None
    iv: float | None = None
    open_interest: int = 0
    volume: int = 0
    expiration: str = ""
    source: str = "chain"

    @property
    def midpoint(self) -> float:
        return round((float(self.bid) + float(self.ask)) / 2.0, 4)

    @property
    def spread_pct(self) -> float:
        mid = self.midpoint
        if mid <= 0:
            return 999.0
        return round((float(self.ask) - float(self.bid)) / mid * 100.0, 2)

    def liquidity_failures(self) -> list[str]:
        out = []
        if self.source != "chain":
            out.append(f"quote source is {self.source!r}, not a live chain — "
                       "payoff arithmetic from estimated prices is not constructible")
        if float(self.bid) <= 0:
            out.append(f"{self.occ_symbol}: no bid — cannot price")
        if self.spread_pct > MAX_SPREAD_PCT:
            out.append(f"{self.occ_symbol}: spread {self.spread_pct}% exceeds {MAX_SPREAD_PCT}% limit")
        if int(self.open_interest) < MIN_OPEN_INTEREST:
            out.append(f"{self.occ_symbol}: open interest {self.open_interest} below {MIN_OPEN_INTEREST}")
        return out


def _earnings_inside(expiration: str, earnings_date: str | None) -> bool | None:
    """None means UNKNOWN — which is NOT the same as False, and callers must not
    treat it as such. Unknown event timing fails closed everywhere else in this
    system and does so here too."""
    if not earnings_date or not expiration:
        return None
    try:
        return date.fromisoformat(str(earnings_date)[:10]) <= date.fromisoformat(str(expiration)[:10])
    except (ValueError, TypeError):
        return None


def _event_fields(expiration: str, earnings_date: str | None) -> dict:
    inside = _earnings_inside(expiration, earnings_date)
    return {
        "earnings_date": earnings_date,
        "earnings_inside_contract": inside,
        "earnings_state": ("UNKNOWN" if inside is None
                           else "INSIDE_CONTRACT" if inside else "CLEAR"),
    }


# ── Long stock ────────────────────────────────────────────────────────────────

def staged_shares(*, symbol: str, current_price: float, atr: float,
                  support: list[float], resistance: list[float],
                  thesis_state: str, timing: str,
                  account_equity: float, max_position_pct: float = 5.0,
                  earnings_date: str | None = None) -> dict:
    """A staged plan, because forcing all-in vs no-entry on a volatile long-term
    candidate is a false choice — it is what turned BETA into `IGNORE`.

    Levels are computed from ATR and real support/resistance, never hardcoded.
    """
    reasons = []
    if current_price <= 0:
        reasons.append("no current price")
    if atr <= 0:
        reasons.append("no ATR — cannot size stops or pullback zones")
    if not support:
        reasons.append("no support level identified — invalidation would be arbitrary")
    if reasons:
        raise BlueprintRejected("STAGED_SHARES", reasons)

    res = min(resistance) if resistance else current_price * 1.05
    sup = max([s for s in support if s < current_price] or [current_price - 2 * atr])

    # Pullback zone: one ATR below spot, floored at the first real support.
    pull_hi = round(current_price - 0.5 * atr, 2)
    pull_lo = round(max(current_price - 1.5 * atr, sup), 2)
    breakout = round(res * 1.005, 2)          # a close ABOVE resistance
    invalidation = round(sup - 0.5 * atr, 2)  # below support, not at it

    # Extended tape gets a smaller starter — the discipline that "do not chase"
    # is supposed to encode, expressed as an allocation rather than a refusal.
    extended = timing in ("EXTENDED", "WAIT_FOR_PULLBACK", "BREAKOUT_CONFIRMATION")
    speculative = thesis_state in ("SPECULATIVE_CONSTRUCTIVE", "NEUTRAL", "INSUFFICIENT_EVIDENCE")
    starter_pct = 25.0 if extended else 40.0
    if speculative:
        starter_pct = min(starter_pct, 25.0)

    event_reserve_pct = 25.0 if earnings_date else 0.0
    remaining = 100.0 - starter_pct - event_reserve_pct
    breakout_pct = round(remaining * 0.5, 1)
    pullback_pct = round(remaining - breakout_pct, 1)

    risk_per_share = round(current_price - invalidation, 2)
    target = round(current_price + 2.0 * (current_price - invalidation), 2)
    rr = round((target - current_price) / risk_per_share, 2) if risk_per_share > 0 else 0.0
    max_pos_value = round(account_equity * max_position_pct / 100.0, 2)

    return {
        "structure": "STAGED_SHARES", "direction": "BULLISH", "horizon": "LONG_TERM",
        "state": "ELIGIBLE",
        "entry_method": "PULLBACK" if extended else "STARTER_NOW",
        "starter_entry": {
            "price_or_zone": [pull_hi, round(current_price, 2)] if not extended else [pull_lo, pull_hi],
            "allocation_pct": starter_pct,
            "condition": ("enter now at market-adjacent limit" if not extended
                          else f"only on a pullback into {pull_lo}-{pull_hi}"),
        },
        "add_entries": [
            {"price_or_zone": [pull_lo, pull_hi], "allocation_pct": pullback_pct,
             "condition": f"pullback into {pull_lo}-{pull_hi} (0.5-1.5 ATR) holding above support {sup}"},
            {"price_or_zone": [breakout, round(breakout * 1.03, 2)], "allocation_pct": breakout_pct,
             "condition": f"daily CLOSE above resistance {res} followed by a successful retest",
             "retest_required": True},
        ],
        "event_reserve": {
            "allocation_pct": event_reserve_pct,
            "event": f"earnings {earnings_date}" if earnings_date else "",
        } if event_reserve_pct else {},
        "stop_or_invalidation": {
            "price": invalidation,
            "condition": f"daily close below {invalidation} (support {sup} less 0.5 ATR)",
            "basis": "SUPPORT",
        },
        "targets": [{"price": target, "action": "reassess thesis; trim only on thesis change"}],
        "risk_per_share": risk_per_share,
        "reward_to_risk": rr,
        "maximum_position_pct": max_position_pct,
        "maximum_position_value": max_pos_value,
        "event_plan": (f"reserve {event_reserve_pct}% through earnings {earnings_date}"
                       if earnings_date else "no scheduled event"),
        "atr_used": atr,
        "rejection_reasons": [],
    }


# ── Short stock ───────────────────────────────────────────────────────────────

def short_stock(*, symbol: str, current_price: float, atr: float,
                support: list[float], resistance: list[float],
                borrow_state: str, short_float_pct: float, rsi: float | None,
                earnings_date: str | None, dte_intent: int,
                held_long: bool) -> dict:
    """Bearish suitability is NOT the inverse of a weak thesis. A bad company can
    be a terrible short — squeeze risk, no borrow, already oversold. Those are
    checked here so nothing infers 'short it' from 'dislike it'."""
    reasons = []
    if held_long:
        reasons.append("symbol is currently held long — shorting it would offset the position")
    if str(borrow_state).upper() != "AVAILABLE":
        reasons.append(f"borrow {borrow_state} — a short with unavailable/unknown borrow is not constructible")
    if short_float_pct >= 20.0:
        reasons.append(f"short float {short_float_pct}% — squeeze risk too high")
    if rsi is not None and rsi <= 30:
        reasons.append(f"RSI {rsi} already oversold — shorting into exhaustion")
    inside = _earnings_inside("", earnings_date)
    if earnings_date and dte_intent > 0:
        reasons.append(f"earnings {earnings_date} inside the intended {dte_intent}-session hold — binary risk on unlimited-loss structure")
    if not resistance:
        reasons.append("no resistance level — buy-stop would be arbitrary")

    if reasons:
        return {
            "structure": "SHORT_STOCK", "direction": "BEARISH", "state": "REJECTED",
            "rejection_reasons": reasons,
            "compare_instead": ["PUT_DEBIT_SPREAD", "BEAR_CALL_SPREAD", "NO_TRADE"],
            "why_compare": "defined-risk bearish structures survive the constraints that "
                           "reject short stock (borrow, squeeze, unlimited loss)",
        }

    res = min(resistance)
    buy_stop = round(res + 0.5 * atr, 2)
    sup = max(support) if support else round(current_price - 3 * atr, 2)
    risk = round(buy_stop - current_price, 2)
    return {
        "structure": "SHORT_STOCK", "direction": "BEARISH", "horizon": "TACTICAL",
        "state": "ELIGIBLE", "entry_method": "FAILED_RALLY",
        "entry_zone": [round(current_price, 2), round(res, 2)],
        "confirmation": f"rejection at resistance {res} on declining volume",
        "buy_stop": buy_stop,
        "targets": [{"price": sup, "action": "cover half at first support"}],
        "risk_per_share": risk,
        "reward_to_risk": round((current_price - sup) / risk, 2) if risk > 0 else 0.0,
        "borrow_state": borrow_state, "short_float_pct": short_float_pct,
        "squeeze_risk": "LOW" if short_float_pct < 10 else "MEDIUM",
        "earnings_state": "CLEAR",
        "rejection_reasons": [],
    }


# ── Vertical debit spreads (calls and puts share the arithmetic) ───────────────

def _debit_spread(*, kind: str, long_leg: Quote, short_leg: Quote,
                  contracts: int, underlying_price: float,
                  trigger: str, invalidation: str,
                  earnings_date: str | None) -> dict:
    structure = "CALL_DEBIT_SPREAD" if kind == "call" else "PUT_DEBIT_SPREAD"
    reasons = long_leg.liquidity_failures() + short_leg.liquidity_failures()

    if long_leg.expiration != short_leg.expiration:
        reasons.append(f"expiration mismatch {long_leg.expiration} vs {short_leg.expiration} — not a vertical")
    if kind == "call" and short_leg.strike <= long_leg.strike:
        reasons.append("call debit spread requires short strike ABOVE long strike")
    if kind == "put" and short_leg.strike >= long_leg.strike:
        reasons.append("put debit spread requires short strike BELOW long strike")

    width = round(abs(float(short_leg.strike) - float(long_leg.strike)), 2)
    net_debit = round(long_leg.midpoint - short_leg.midpoint, 4)
    if net_debit <= 0:
        reasons.append(f"net debit {net_debit} is not positive — quotes are crossed or stale")
    elif net_debit >= width:
        reasons.append(f"net debit {net_debit} >= width {width} — no profit is possible at any price")

    if reasons:
        raise BlueprintRejected(structure, reasons)

    max_loss = round(net_debit * contracts * SHARES_PER_CONTRACT, 2)
    max_profit = round((width - net_debit) * contracts * SHARES_PER_CONTRACT, 2)
    breakeven = (round(long_leg.strike + net_debit, 2) if kind == "call"
                 else round(long_leg.strike - net_debit, 2))

    return {
        "structure": structure,
        "direction": "BULLISH" if kind == "call" else "BEARISH",
        "state": "ELIGIBLE",
        "expiration": long_leg.expiration,
        "long_leg": {"occ_symbol": long_leg.occ_symbol, "strike": long_leg.strike,
                     "bid": long_leg.bid, "ask": long_leg.ask, "midpoint": long_leg.midpoint,
                     "delta": long_leg.delta, "open_interest": long_leg.open_interest,
                     "volume": long_leg.volume},
        "short_leg": {"occ_symbol": short_leg.occ_symbol, "strike": short_leg.strike,
                      "bid": short_leg.bid, "ask": short_leg.ask, "midpoint": short_leg.midpoint,
                      "delta": short_leg.delta, "open_interest": short_leg.open_interest,
                      "volume": short_leg.volume},
        "net_debit_mid": net_debit,
        "proposed_limit": round(net_debit + 0.02, 2),
        "width": width,
        "contracts": contracts,
        "maximum_loss": max_loss,
        "maximum_profit": max_profit,
        "breakeven": breakeven,
        "return_on_risk_pct": round(max_profit / max_loss * 100.0, 1) if max_loss > 0 else 0.0,
        "underlying_price": underlying_price,
        "underlying_trigger": trigger,
        "underlying_invalidation": invalidation,
        "management_plan": f"close at 50-75% of max profit; exit if underlying invalidates ({invalidation})",
        **_event_fields(long_leg.expiration, earnings_date),
        "rejection_reasons": [],
    }


def call_debit_spread(**kw) -> dict:
    return _debit_spread(kind="call", **kw)


def put_debit_spread(**kw) -> dict:
    return _debit_spread(kind="put", **kw)


# ── Cash-secured put ──────────────────────────────────────────────────────────

def cash_secured_put(*, symbol: str, put: Quote, contracts: int,
                     current_price: float, available_cash: float,
                     assignment_intent: str, earnings_date: str | None) -> dict:
    """A CSP is a BUY order with a discount and a waiting period. If the operator
    would not willingly own the shares at the effective acquisition price, it is
    not an income trade — it is an unwanted position with extra steps."""
    reasons = put.liquidity_failures()

    cash_required = round(float(put.strike) * contracts * SHARES_PER_CONTRACT, 2)
    credit = round(put.midpoint * contracts * SHARES_PER_CONTRACT, 2)
    effective = round(float(put.strike) - put.midpoint, 2)

    if str(assignment_intent).upper() != "WILLING":
        reasons.append(f"assignment_intent={assignment_intent} — a CSP is only valid if the "
                       f"operator would willingly own 100 shares at {effective}")
    if available_cash < cash_required:
        reasons.append(f"cash {available_cash} below the {cash_required} required to secure {contracts} contract(s)")
    if put.strike >= current_price:
        reasons.append(f"strike {put.strike} is at or above spot {current_price} — "
                       "this is not an acquisition-at-a-discount structure")

    if reasons:
        raise BlueprintRejected("CASH_SECURED_PUT", reasons)

    ev = _event_fields(put.expiration, earnings_date)
    gap_scenarios = []
    for pct in (10, 20, 30):
        gapped = round(current_price * (1 - pct / 100.0), 2)
        gap_scenarios.append({
            "gap_pct": -pct, "underlying_after": gapped,
            "assigned": gapped < put.strike,
            "unrealised_per_share": round(gapped - effective, 2) if gapped < put.strike else 0.0,
            "unrealised_total": round((gapped - effective) * contracts * SHARES_PER_CONTRACT, 2)
                                if gapped < put.strike else 0.0,
        })

    return {
        "structure": "CASH_SECURED_PUT", "direction": "MILDLY_BULLISH",
        "state": "ELIGIBLE",
        "expiration": put.expiration, "occ_symbol": put.occ_symbol, "strike": put.strike,
        "bid": put.bid, "ask": put.ask, "midpoint": put.midpoint,
        "proposed_limit_credit": put.midpoint,
        "delta": put.delta, "iv": put.iv,
        "open_interest": put.open_interest, "volume": put.volume,
        "contracts": contracts,
        "cash_required": cash_required,
        "maximum_profit": credit,
        "effective_acquisition_price": effective,
        "discount_to_current_pct": round((current_price - effective) / current_price * 100.0, 2),
        "assignment_intent": assignment_intent,
        "negative_gap_scenarios": gap_scenarios,
        "management_plan": ("close at 50% of credit; accept assignment if the thesis holds"
                            if ev["earnings_state"] != "INSIDE_CONTRACT"
                            else "EARNINGS ASSIGNMENT RISK: a negative gap assigns shares at "
                                 f"{effective} regardless of the post-print thesis"),
        **ev,
        "rejection_reasons": [],
    }


# ── Long single options ───────────────────────────────────────────────────────

def long_option(*, kind: str, opt: Quote, contracts: int, underlying_price: float,
                trigger: str, invalidation: str, earnings_date: str | None,
                directional_setup_confirmed: bool) -> dict:
    """Buying a put is a BEARISH position or protection for shares held. It is
    never a way to 'buy into' a company — the operator asked for exactly that on
    BETA, and the system must say so rather than fill the order shape."""
    structure = "LONG_CALL" if kind == "call" else "LONG_PUT"
    reasons = opt.liquidity_failures()

    if not directional_setup_confirmed:
        reasons.append(
            f"no confirmed {'bullish' if kind == 'call' else 'bearish'} tactical setup — "
            + ("a weak long-term thesis is not a bearish entry signal"
               if kind == "put" else
               "a strong thesis is not a tactical entry signal")
        )

    ev = _event_fields(opt.expiration, earnings_date)
    if ev["earnings_state"] == "INSIDE_CONTRACT":
        reasons.append(f"earnings {earnings_date} inside the contract — a long single option "
                       "pays full IV before the print and absorbs the crush after")
    if ev["earnings_state"] == "UNKNOWN":
        reasons.append("earnings timing unknown — fails closed rather than assuming clear")

    if reasons:
        raise BlueprintRejected(structure, reasons)

    debit = round(opt.midpoint * contracts * SHARES_PER_CONTRACT, 2)
    breakeven = (round(opt.strike + opt.midpoint, 2) if kind == "call"
                 else round(opt.strike - opt.midpoint, 2))
    return {
        "structure": structure, "direction": "BULLISH" if kind == "call" else "BEARISH",
        "state": "ELIGIBLE",
        "expiration": opt.expiration, "occ_symbol": opt.occ_symbol, "strike": opt.strike,
        "bid": opt.bid, "ask": opt.ask, "midpoint": opt.midpoint,
        "proposed_limit": round(opt.midpoint + 0.05, 2),
        "delta": opt.delta, "iv": opt.iv,
        "open_interest": opt.open_interest, "volume": opt.volume,
        "contracts": contracts, "debit": debit, "maximum_loss": debit,
        "maximum_profit": None if kind == "call" else round(
            (opt.strike - opt.midpoint) * contracts * SHARES_PER_CONTRACT, 2),
        "breakeven": breakeven,
        "underlying_price": underlying_price,
        "underlying_trigger": trigger, "underlying_invalidation": invalidation,
        "profit_management": "scale at 100% gain; never let a winner round-trip to zero",
        "time_stop": "exit at 21 DTE regardless of P&L — theta dominates thereafter",
        **ev,
        "rejection_reasons": [],
    }


def puts_are_not_a_bullish_entry(symbol: str) -> dict:
    """Returned when an operator asks for 'puts to buy in'. The mismatch is
    between what was asked and what the instrument does, so the answer must
    explain the instrument, not silently substitute one."""
    return {
        "structure": "LONG_PUT", "state": "NOT_APPLICABLE",
        "rejection_reasons": [
            f"buying a put on {symbol} is a BEARISH position — it profits when the stock FALLS",
            "it is not a method of acquiring shares and does not establish long exposure",
        ],
        "what_you_probably_want": [
            {"structure": "CASH_SECURED_PUT",
             "why": "SELLING a put is the bullish put strategy — it pays you to wait "
                    "and acquires shares at a discount if assigned"},
            {"structure": "STAGED_SHARES",
             "why": "direct long exposure with no expiration, best fit for a multi-year thesis"},
            {"structure": "CALL_DEBIT_SPREAD",
             "why": "defined-risk bullish exposure that offsets part of an elevated IV"},
        ],
        "when_a_long_put_IS_right": [
            "protecting shares you already own (protective put)",
            "a confirmed bearish tactical setup you intend to trade",
        ],
    }


def comparison_matrix(*, symbol: str, directional_view: dict,
                      structures: list[dict], no_trade_is_valid: bool = True) -> dict:
    """Selection must be mechanical: the preferred structure wins on stated
    numbers, and the runner-up records why it lost. A preference with no
    comparison is just a preference."""
    evaluated = []
    for s in structures:
        evaluated.append({
            "structure": s.get("structure"),
            "state": s.get("state"),
            "capital_required": s.get("cash_required") or s.get("debit")
                                or s.get("maximum_loss") or s.get("maximum_position_value"),
            "maximum_loss": s.get("maximum_loss"),
            "maximum_profit": s.get("maximum_profit"),
            "breakeven": s.get("breakeven"),
            "earnings_state": s.get("earnings_state"),
            "rejection_reasons": s.get("rejection_reasons") or [],
        })
    eligible = [e for e in evaluated if e["state"] == "ELIGIBLE"]
    # Lowest defined maximum loss wins among eligible structures; undefined risk
    # never outranks defined risk.
    eligible.sort(key=lambda e: (e["maximum_loss"] is None, e["maximum_loss"] or 0))
    preferred = eligible[0]["structure"] if eligible else "NO_TRADE"
    runner_up = eligible[1]["structure"] if len(eligible) > 1 else None
    return {
        "symbol": symbol,
        "directional_view": directional_view,
        "evaluated_structures": evaluated,
        "preferred_structure": preferred,
        "runner_up": runner_up,
        "no_trade_is_valid": no_trade_is_valid,
    }
