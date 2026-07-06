"""Novice options education copy — presentation/tests only; no execution."""
from __future__ import annotations

from typing import Any

NOVICE_GLOSSARY_TERMS = (
    "Call", "Put", "Strike", "Expiration", "Premium", "Total debit", "Total credit",
    "Breakeven", "Delta", "Theta", "IV", "DTE", "OI", "Bid/ask spread", "Assignment",
)

_STRATEGY_EDU: dict[str, dict[str, Any]] = {
    "deep_itm_call": {
        "direction": "Buy call",
        "cashflow": "pay debit",
        "goal": "stock replacement",
        "max_loss": "premium paid",
        "beginner_contains": ("buy", "call", "pay", "stock-like"),
    },
    "protective_put": {
        "direction": "Buy put",
        "cashflow": "pay debit",
        "goal": "hedge",
        "beginner_contains": ("buy", "put", "pay", "insurance"),
    },
    "covered_call": {
        "direction": "Sell call",
        "cashflow": "collect credit",
        "goal": "income",
        "beginner_contains": ("sell", "call", "collect", "upside"),
    },
    "cash_secured_put": {
        "direction": "Sell put",
        "cashflow": "collect credit",
        "goal": "income",
        "beginner_contains": ("sell", "put", "collect", "buy shares"),
    },
    "credit_spread": {
        "direction": "Net short premium",
        "cashflow": "collect net credit",
        "goal": "defined-risk income",
        "beginner_contains": ("collect", "credit", "short strike"),
    },
    "atm_call": {
        "direction": "Buy call",
        "cashflow": "pay debit",
        "goal": "bullish directional",
        "beginner_contains": ("buy", "call", "pay"),
    },
    "atm_put": {
        "direction": "Buy put",
        "cashflow": "pay debit",
        "goal": "bearish",
        "beginner_contains": ("buy", "put", "pay"),
    },
    "debit_spread": {
        "direction": "Net long premium",
        "cashflow": "pay net debit",
        "goal": "directional capped risk",
        "beginner_contains": ("pay", "debit", "capped"),
    },
    "earnings_put_debit_spread": {
        "direction": "Buy put spread",
        "cashflow": "pay net debit",
        "goal": "earnings downside",
        "beginner_contains": ("pay", "debit", "earnings"),
    },
    "earnings_put_credit_spread": {
        "direction": "Sell put spread",
        "cashflow": "collect net credit",
        "goal": "stay above short put",
        "beginner_contains": ("collect", "credit", "short put"),
    },
}

_MONITOR_LONG_CALLS = (
    "Current option value", "Unrealized P/L", "Delta", "Theta", "IV",
    "Bid/ask spread", "DTE", "Breakeven",
)

_MONITOR_SHORT_PREMIUM = (
    "Stock price vs short strike", "Assignment risk", "Remaining credit", "DTE",
)

_MONITOR_SPREADS = (
    "Short strike distance", "Spread mark", "Max gain / max loss", "Breakeven", "DTE",
)


def strategy_education(strategy: str) -> dict[str, Any]:
    return _STRATEGY_EDU.get((strategy or "").lower(), _STRATEGY_EDU["atm_call"])


def build_beginner_summary(card: dict[str, Any]) -> str:
    s = (card.get("strategy") or "").lower()
    edu = strategy_education(s)
    contracts = int(card.get("contracts") or 1)
    total = card.get("premium_total")
    cash = f"${float(total):,.0f}" if total is not None else "a premium"
    templates = {
        "deep_itm_call": f"Buy {contracts} call, pay {cash}, get stock-like upside exposure, max option loss {cash}",
        "protective_put": f"Buy a put as insurance. It costs {cash} but can offset stock losses",
        "covered_call": f"Sell calls against shares you own, collect {cash}, but cap upside",
        "cash_secured_put": f"Sell a put, collect {cash}, but you may have to buy shares if the stock falls",
        "credit_spread": f"Collect {cash} with capped risk — want price to stay away from the short strike",
        "debit_spread": f"Pay {cash} for a directional bet with capped loss and capped gain",
        "atm_call": f"Buy {contracts} call, pay {cash}, profit only if the stock rises enough before time decay hurts",
        "atm_put": f"Buy {contracts} put, pay {cash}, profit if the stock falls enough before expiration",
    }
    body = templates.get(s, f"{edu['direction']} — {edu['goal']}")
    if card.get("educational_paper_model") or card.get("paper_only"):
        body += ", paper only"
    return f"Beginner view: {body}."


def monitor_checklist(strategy: str) -> tuple[str, ...]:
    s = (strategy or "").lower()
    if s in ("deep_itm_call", "atm_call", "long_call"):
        return _MONITOR_LONG_CALLS + ("Lifecycle monitor advice label",)
    if s in ("atm_put", "protective_put"):
        return ("Hedge effectiveness", "Put value", "Theta", "IV", "DTE", "Breakeven")
    if s in ("covered_call", "cash_secured_put"):
        return _MONITOR_SHORT_PREMIUM + ("Liquidity",)
    if "spread" in s:
        return _MONITOR_SPREADS + ("Assignment risk",)
    return _MONITOR_LONG_CALLS


def alpaca_paper_education_snippet() -> str:
    return (
        "Alpaca paper only. Simulated 1-contract limit order path. "
        "Does not place a live broker order."
    )


def open_options_intro() -> str:
    return (
        "Open paper options are monitored after fill. The monitor watches option value, "
        "stock price, Greeks, IV, spread, P/L, DTE, and advisory labels. "
        "It does not place live orders."
    )