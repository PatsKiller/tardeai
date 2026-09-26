"""Plain-English explanation of one option idea, from its own numbers.

Operator 2026-09-26: "not seeing clearly profit possibilities". A cash-secured
put showed "Reward/risk 0.046" and a protective put showed "EV -$1,100" with
"Why an option: missing" -- true numbers that told the reader nothing about what
the trade is for or what the premium buys.

Deterministic arithmetic only: no model call, nothing invented. Every figure
comes from the proposal (spot, strike, premium, contracts, DTE, POP). Advisory:
it sizes nothing and recommends no order.
"""
from __future__ import annotations

from typing import Any, Optional

TOOLTIPS = {
    "pop": "Estimated chance the option expires where this trade makes money (a model estimate, not a promise).",
    "ev": "Probability-weighted average result per trade; for a hedge it is the expected cost of the insurance.",
    "reward_risk": "Most you can make divided by most you can lose; small for income trades by design.",
    "delta": "How much the option's price moves for a $1 move in the stock, and a rough odds-of-finishing-in-the-money.",
    "iv_rank": "Where today's implied volatility sits in its own range; higher means option premiums are richer.",
    "dte": "Days until the option expires.",
    "open_interest": "How many of these contracts are open; more means easier to get a fair fill.",
    "breakeven": "The stock price at expiry where this trade neither makes nor loses money.",
    "total_debit_credit": "Cash paid (debit) or received (credit) today for all contracts.",
}


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _usd(v: float) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def _payoff(strategy: str, price: float, strike: float, premium: float, long_strike: Optional[float]) -> float:
    """Option P/L per share at expiry (premium included)."""
    if strategy == "cash_secured_put":
        return premium - max(0.0, strike - price)
    if strategy == "covered_call":
        return premium - max(0.0, price - strike)
    if strategy in ("protective_put", "long_put"):
        return max(0.0, strike - price) - premium
    if strategy == "long_call":
        return max(0.0, price - strike) - premium
    if strategy == "credit_spread" and long_strike is not None:
        return premium - max(0.0, strike - price) + max(0.0, long_strike - price)
    return 0.0


def explain(p: dict[str, Any]) -> Optional[dict[str, Any]]:
    strategy = str(p.get("strategy") or "")
    spot = _f(p.get("underlying_price"))
    strike = _f(p.get("strike") if p.get("strike") is not None else p.get("short_strike"))
    premium = _f(p.get("premium"))
    if not spot or not strike or premium is None:
        return None
    n = int(_f(p.get("contracts")) or 1)
    shares = 100 * n
    exp = p.get("expiration") or f"{p.get('dte')} days"
    pop = _f(p.get("pop_pct"))
    long_strike = _f(p.get("long_strike"))
    cash = premium * shares
    sym = p.get("symbol") or ""
    odds = f" (model estimate ~{pop:.0f}%)" if pop is not None else ""

    if strategy == "cash_secured_put":
        be = strike - premium
        objective = "Income: get paid now for agreeing to buy the stock at a lower price."
        premium_line = (f"You collect {_usd(cash)} today for promising to buy {shares} {sym} at ${strike:g} "
                        f"if it is below that on {exp}.")
        cases = {
            "best": f"{sym} stays at or above ${strike:g}: you keep {_usd(cash)}{odds}.",
            "expected": f"Most often the put expires unused and the {_usd(cash)} is the whole return.",
            "worst": f"{sym} collapses: you must buy {shares} shares at ${strike:g}; effective cost ${be:.2f}/share, "
                     f"and you carry the loss below that.",
        }
        why = "A put pays you to wait for a lower entry. It is not the same as buying the shares now."
    elif strategy == "covered_call":
        be = spot - premium
        objective = "Income on shares you already own, in exchange for capping the upside."
        premium_line = (f"You collect {_usd(cash)} today for agreeing to sell {shares} {sym} at ${strike:g} "
                        f"if it is above that on {exp}.")
        cases = {
            "best": f"{sym} finishes just under ${strike:g}: you keep the shares, their gain, and {_usd(cash)}.",
            "expected": f"The call expires unused{odds}; the {_usd(cash)} adds to what the shares do.",
            "worst": f"{sym} rallies far above ${strike:g}: your shares are sold at ${strike:g} and you miss the rest.",
        }
        why = "You already hold the shares; the call sells some upside for cash. It is not a new investment."
    elif strategy in ("protective_put", "long_put"):
        be = strike - premium
        objective = ("Insurance: protect shares you own against a large drop." if strategy == "protective_put"
                     else "A bet that the stock falls below the breakeven by expiry.")
        premium_line = (f"You pay {_usd(cash)} for the right to sell {shares} {sym} at ${strike:g} until {exp}, "
                        f"however low the price goes.")
        cases = {
            "best": f"{sym} falls far below ${strike:g}: the puts gain dollar-for-dollar below ${be:.2f} and offset the share loss.",
            "expected": f"{sym} stays above ${strike:g}{odds.replace('estimate', 'odds it does not')}: the puts expire "
                        f"and {_usd(cash)} is the cost of the insurance.",
            "worst": f"You lose the {_usd(cash)} premium; that is the most this position can cost.",
        }
        why = (f"Insurance: the right to sell {shares} shares at ${strike:g} until {exp}. Negative expected value "
               f"is normal for insurance - it is the price of the floor.") if strategy == "protective_put" else \
            "Limited, known cost for downside exposure."
    elif strategy == "long_call":
        be = strike + premium
        objective = "Leveraged upside: benefit from a rise with a known maximum loss."
        premium_line = f"You pay {_usd(cash)} for the right to buy {shares} {sym} at ${strike:g} until {exp}."
        cases = {
            "best": f"{sym} rises well above ${be:.2f}: gains grow dollar-for-dollar above breakeven.",
            "expected": f"Depends on the move; below ${be:.2f} at expiry the trade loses money.",
            "worst": f"{sym} stays below ${strike:g}: you lose the full {_usd(cash)}.",
        }
        why = "Controls the shares' upside for less cash than buying them, with the loss capped at the premium."
    elif strategy == "credit_spread" and long_strike is not None:
        be = strike - premium
        width = strike - long_strike
        objective = "Income with a capped worst case: get paid if the stock stays above the short strike."
        premium_line = (f"You collect {_usd(cash)} today; the most you can lose is "
                        f"{_usd((width - premium) * shares)} if {sym} is below ${long_strike:g} on {exp}.")
        cases = {
            "best": f"{sym} stays above ${strike:g}: you keep {_usd(cash)}{odds}.",
            "expected": "Usually the spread expires and the credit is the return.",
            "worst": f"{sym} below ${long_strike:g}: loss of {_usd((width - premium) * shares)}.",
        }
        why = "Defined-risk income: the bought put caps the loss that a bare short put would carry."
    else:
        return None

    prices = sorted({round(spot * 1.10, 2), round(spot, 2), round(strike, 2), round(be, 2), round(be * 0.90, 2)},
                    reverse=True)
    scenarios = []
    for px in prices:
        pl = _payoff(strategy, px, strike, premium, long_strike) * shares
        row = {"price": px, "option_pl": round(pl, 2)}
        if strategy in ("protective_put", "covered_call"):
            row["shares_plus_option_vs_today"] = round((px - spot) * shares + pl, 2)
        scenarios.append(row)

    return {
        "schema": "OptionsPlainEnglish@v1",
        "objective": objective,
        "premium_line": premium_line,
        "why_option": why,
        "breakeven": round(be, 2),
        "breakeven_line": f"Breakeven at expiry: ${be:.2f} ({(be / spot - 1) * 100:+.1f}% from today's ${spot:,.2f}).",
        "cases": cases,
        "scenarios": scenarios,
        "tooltips": TOOLTIPS,
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }


# ── Investment-committee memo (operator 2026-09-26) ─────────────────────────
# Classify first, then say only what the house actually knows. A section with no
# research behind it says so; nothing here is written by a model.

CLASSIFICATION = {
    "covered_call": ("INCOME", "Income trade", "Collect premium on shares you own."),
    "cash_secured_put": ("INCOME", "Income trade", "Collect premium while waiting to buy lower."),
    "credit_spread": ("INCOME", "Income trade (defined risk)", "Collect premium with a capped worst case."),
    "protective_put": ("HEDGE", "Hedge / insurance", "Reduce the risk of shares you already own."),
    "long_call": ("MONEY_MAKING", "Money-making trade", "Profit if the stock rises past breakeven."),
    "long_put": ("SPECULATIVE", "Speculative trade", "Profit if the stock falls past breakeven."),
}

METRIC_GUIDE = {
    "edge": ("Desk composite score of POP, IV, premium yield, catalyst and conviction.",
             "It decides whether an idea reaches the desk; it is a model score, not a CIO decision.", "higher"),
    "pop": ("Model-estimated chance the trade finishes profitable at expiry.",
            "Shows how often this structure tends to work, not how much it makes.", "higher"),
    "ev": ("Probability-weighted average result.",
           "Negative is normal for insurance; for income trades it should be positive.", "higher"),
    "delta": ("Option price change per $1 stock move; also a rough odds of finishing in the money.",
              "Tells you how stock-like the position behaves.", "depends on the goal"),
    "gamma": ("How fast delta changes as the stock moves.",
              "High gamma means the position's risk shifts quickly near expiry.", "lower for income, higher for bets"),
    "theta": ("Value the option loses per day from time passing.",
              "Sellers earn it, buyers pay it.", "higher if you sold, lower if you bought"),
    "iv_rank": ("Where today's implied volatility sits in its own recent range.",
                "Rich premiums favour selling; cheap premiums favour buying.", "higher to sell, lower to buy"),
    "open_interest": ("Number of these contracts currently open.",
                      "More open interest usually means tighter prices and easier exits.", "higher"),
    "breakeven": ("Stock price at expiry where the trade neither makes nor loses money.",
                  "Compare it with where you think the stock is going.", "closer to spot is easier"),
    "debit": ("Cash you pay today.", "It is the most a bought option can lose.", "lower"),
    "credit": ("Cash you receive today.", "It is the most a sold option can make.", "higher"),
    "dte": ("Days until expiry.", "Longer gives the thesis time; shorter decays faster.", "depends on the goal"),
}


def _thesis_list(t: dict, key: str) -> list:
    return [str(x) for x in (t.get(key) or []) if x]


def committee_memo(p: dict[str, Any], t: dict[str, Any], record: Optional[dict[str, Any]],
                   exit_rules: Optional[dict[str, Any]] = None,
                   queue_status: Optional[str] = None) -> dict[str, Any]:
    strategy = str(p.get("strategy") or "")
    ckey, clabel, cpurpose = CLASSIFICATION.get(strategy, ("OTHER", "Other", "Not classified."))
    state = str(t.get("thesis_state") or "INSUFFICIENT_DATA").upper()
    rc = p.get("research_context") or {}
    has_thesis = bool(t.get("symbol_thesis_version")) and state not in ("INSUFFICIENT_DATA",)
    evidence = _thesis_list(t, "evidence_for")
    if has_thesis and evidence and state == "CURRENT":
        research, conf = "FULLY_RESEARCHED", "High" if (t.get("thesis_confidence") or 0) >= 0.7 else "Medium"
    elif has_thesis:
        research, conf = "PARTIALLY_RESEARCHED", "Medium" if state == "CURRENT" else "Low"
    else:
        research, conf = "SCREENING_ONLY", "Low"
    missing = (record or {}).get("missing_required") or []
    dec = p.get("cio_decision") or {}
    view = p.get("cio_view") or {}
    latest = view.get("latest_decision") or {}
    if queue_status == "approved":
        cio = ("CIO_APPROVED", "CIO approved")
    elif queue_status == "rejected":
        cio = ("NOT_APPROVED", "Not approved")
    elif dec.get("outcome"):
        o = str(dec["outcome"])
        cio = ({"APPROVE": "CIO_APPROVED", "REJECT": "NOT_APPROVED"}.get(o, "CIO_" + o),
               f"CIO review: {o.lower().replace('_', ' ')} ({str(dec.get('confidence') or '').lower()} confidence)")
    elif latest:
        cio = ("CIO_VIEW_ON_FILE", f"CIO view on file: {latest.get('recommendation')} ({latest.get('source')})")
    elif missing or research != "FULLY_RESEARCHED":
        cio = ("RESEARCH_PENDING", "Research pending")
    else:
        cio = ("AWAITING_CIO", "Awaiting CIO review")
    not_researched = "Not researched - generated from screening only." if research == "SCREENING_ONLY" else "Not on file."
    rules = (exit_rules or {}).get(strategy) or {}
    exit_plan = {
        "thesis_invalid_when": _thesis_list(t, "invalidation_conditions") or [not_researched],
        "take_profit": rules.get("take_profit"),
        "cut_loss": rules.get("cut_loss"),
        "time_exit": rules.get("time_exit"),
    }
    return {
        "schema": "OptionsCommitteeMemo@v1",
        "classification": ckey,
        "classification_label": clabel,
        "purpose": cpurpose,
        "investment_thesis": (t.get("thesis_summary") or "").strip() or not_researched,
        "market_thesis": rc.get("summary") or not_researched,
        "contrarian_view": "; ".join(_thesis_list(t, "counter_evidence")) or not_researched,
        "why_now": p.get("catalyst") or rc.get("catalyst") or not_researched,
        "research_status": research,
        "confidence": conf,
        "cio_status": cio[0],
        "cio_status_label": cio[1],
        "missing_for_approval": missing,
        "living_thesis": {
            "thesis_pin": t.get("symbol_thesis_version"),
            "last_reviewed": t.get("last_reviewed"),
            "next_review_at": t.get("next_review_at"),
            "remembered": "Every version of this options thesis is stored append-only by strategy GUID, with your approval decisions.",
            "withdrawn_when": ["symbol thesis turns BROKEN or INVALIDATED", "liquidity or enterprise block appears",
                               "you reject it in the approval queue", "the contract expires"],
        },
        "exit_plan": exit_plan,
        "evidence_ladder": [
            {"key": "AI_IDEA", "label": "AI-generated idea", "done": True,
             "detail": "The engine built this from screens and scores. It is a starting point, not a recommendation."},
            {"key": "RESEARCH_COMPLETED", "label": "Research completed", "done": research == "FULLY_RESEARCHED",
             "detail": f"Research status: {research.lower().replace('_', ' ')}."},
            {"key": "CIO_REVIEWED", "label": "CIO-reviewed thesis",
             "done": queue_status in ("approved", "rejected") or bool(dec.get("outcome")),
             "detail": "A CIO decision with its own Decision ID, not inferred from a model score."},
            {"key": "APPROVED", "label": "Approved recommendation",
             "done": queue_status == "approved" or dec.get("outcome") == "APPROVE",
             "detail": "Approved in the queue. Sizing and the per-order 2FA remain yours."},
        ],
        "intent_answer": {"INCOME": "Generate income", "HEDGE": "Act as insurance",
                          "MONEY_MAKING": "Make money", "SPECULATIVE": "Speculate"}.get(ckey, "Not classified"),
        "plain_summary": _plain_summary(p, ckey, cpurpose),
        "continuous_research": {
            "thesis_review_scheduled": bool(t.get("next_review_at")),
            "next_review_at": t.get("next_review_at"),
            "last_reviewed": t.get("last_reviewed"),
            "status": ("Living thesis: a next review is scheduled." if t.get("next_review_at") else
                       "One-time: no thesis review is scheduled for this name."),
            "per_symbol_monitors": "Earnings, analyst, macro, option-flow and news/filing monitors are not yet "
                                   "reported per symbol on this card; do not assume they are watching it.",
        },
        "metric_guide": {k: {"means": a, "why": b, "better": c} for k, (a, b, c) in METRIC_GUIDE.items()},
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }


def _plain_summary(p: dict[str, Any], ckey: str, purpose: str) -> str:
    pe = explain(p) or {}
    sym = p.get("symbol") or "this stock"
    head = {"INCOME": f"This is an income trade on {sym}.", "HEDGE": f"This is insurance on your {sym} shares.",
            "MONEY_MAKING": f"This is a bet that {sym} rises.", "SPECULATIVE": f"This is a speculative bet on {sym}."}
    parts = [head.get(ckey, f"This is an options trade on {sym}."), purpose]
    if pe.get("premium_line"):
        parts.append(pe["premium_line"])
    if pe.get("breakeven_line"):
        parts.append(pe["breakeven_line"])
    return " ".join(parts)
