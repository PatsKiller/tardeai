"""Options execution policy — commit-only literals, default OFF (operator arms via options_pilot_arm.py).

Mirrors protective_stop_policy: standing DB unlock + per-order 2FA. Covers:
  • Single-leg: covered call (SELL_TO_OPEN call), cash-secured put, long call/put
  • Credit spread: 2-leg vertical (NET_CREDIT), max width enforced

While ENABLED=False every options submit is BLOCKED regardless of pilot standing unlock.
"""
from __future__ import annotations

ENABLED = True   # commit gate — DB approve (options_pilot_arm.py) still required for live submit
GATES_REMOVED = False
OPTIONS_ACCOUNT_ALLOWLIST: tuple[str, ...] = (
    "schwab_taxable", "schwab_roth_ira", "schwab_rollover_ira",
)
MAX_CONTRACTS_PER_ORDER = 5
MAX_NOTIONAL_USD = 25_000.0
MAX_SPREAD_WIDTH_PCT = 15.0
ALLOWED_STRATEGIES = (
    "covered_call", "cash_secured_put", "long_call", "long_put", "credit_spread",
)
ALLOWED_ORDER_TYPES = ("LIMIT", "NET_CREDIT", "NET_DEBIT", "MARKET")


def evaluate(
    *,
    account_key: str | None,
    strategy: str,
    order_type: str,
    contracts: int,
    notional_usd: float,
    spread_width_pct: float | None = None,
    symbol: str | None = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not ENABLED:
        return (False, ["Options execution policy DISABLED — run options_pilot_arm.py --approve"])
    if GATES_REMOVED:
        return (True, [])
    if (account_key or "").strip() not in OPTIONS_ACCOUNT_ALLOWLIST:
        reasons.append(f"account {account_key!r} not in options allowlist {OPTIONS_ACCOUNT_ALLOWLIST}")
    if strategy not in ALLOWED_STRATEGIES:
        reasons.append(f"strategy {strategy!r} not in {ALLOWED_STRATEGIES}")
    if (order_type or "").upper() not in ALLOWED_ORDER_TYPES:
        reasons.append(f"order_type {order_type!r} not allowed")
    if contracts < 1 or contracts > MAX_CONTRACTS_PER_ORDER:
        reasons.append(f"contracts {contracts} outside 1..{MAX_CONTRACTS_PER_ORDER}")
    if notional_usd > MAX_NOTIONAL_USD:
        reasons.append(f"notional ${notional_usd:,.0f} exceeds cap ${MAX_NOTIONAL_USD:,.0f}")
    if strategy == "credit_spread" and spread_width_pct is not None:
        if spread_width_pct > MAX_SPREAD_WIDTH_PCT:
            reasons.append(f"spread width {spread_width_pct:.1f}% exceeds {MAX_SPREAD_WIDTH_PCT}%")
    return (not reasons, reasons)