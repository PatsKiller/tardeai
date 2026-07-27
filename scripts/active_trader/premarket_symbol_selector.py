"""Stage 5 harness — representative-symbol selector (PURE, read-only, informational).

Selects at most ONE strategy-representative U.S. common stock from normalized premarket-rank
rows, to sit alongside the always-present baseline US.AAPL. This creates NO trade candidate,
authorization, or recommendation — it only widens the DATA-observation surface so Level 2
momentum suitability can be judged on a symbol that actually moves premarket.

Deterministic: same rows -> same result. No network, no SDK, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional

SELECTOR_VERSION = "premarket-selector-1"
BASELINE_SYMBOL = "US.AAPL"

# Filters (controller §11) — observation-surface filters, not trade thresholds.
PRICE_MIN, PRICE_MAX = 1.00, 50.00
MIN_ABS_CHANGE_PCT = 5.0
MIN_PREMARKET_VOLUME = 100_000

_EXCLUDED_TYPES = {
    "OTC", "WARRANT", "WARRANTS", "RIGHT", "RIGHTS", "UNIT", "UNITS", "OPTION", "OPTIONS",
    "ETF", "ETN", "FUND", "PREFERRED", "PREFERRED_STOCK", "PFD", "ADR_PREFERRED",
    "LEVERAGED", "INVERSE",
}
_COMMON_TYPES = {"COMMON", "COMMON_STOCK", "CS", "STOCK", "ORDINARY", "ORD"}
_LEV_INV_KEYWORDS = ("2X", "3X", "-1X", "ULTRAPRO", "ULTRASHORT", "LEVERAGED", "INVERSE",
                     " BULL", " BEAR", "DAILY BULL", "DAILY BEAR")


class SelectionStatus(str, Enum):
    SELECTED = "SELECTED"
    NO_QUALIFYING_CANDIDATE = "NO_QUALIFYING_CANDIDATE"
    RANK_UNAVAILABLE = "RANK_UNAVAILABLE"
    INVALID_SOURCE_DATA = "INVALID_SOURCE_DATA"


@dataclass(frozen=True)
class SelectionResult:
    status: str
    representative: Optional[str]
    baseline: str
    considered: int
    qualified: int
    reason: str
    selector_version: str = SELECTOR_VERSION

    def as_dict(self) -> dict:
        return asdict(self)


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").replace("%", "").strip())
        except ValueError:
            return None
    return None


def _is_common(row: dict) -> bool:
    st = str(row.get("security_type", "")).strip().upper().replace("-", "_")
    name = str(row.get("name", "")).upper()
    if row.get("is_otc") is True:
        return False
    if st in _EXCLUDED_TYPES:
        return False
    if any(k in name for k in _LEV_INV_KEYWORDS):
        return False
    # must be positively identified as common (fail closed on unknown types)
    return st in _COMMON_TYPES


def _normalize(row) -> Optional[dict]:
    if not isinstance(row, dict):
        return None
    sym = row.get("symbol") or row.get("code")
    price = _num(row.get("price") or row.get("last") or row.get("premarket_price"))
    chg = _num(row.get("premarket_change_pct") or row.get("change_pct") or row.get("change_rate"))
    vol = _num(row.get("premarket_volume") or row.get("volume"))
    turn = _num(row.get("premarket_turnover") or row.get("turnover") or row.get("amount"))
    if not sym or price is None or chg is None or vol is None:
        return None                       # malformed / insufficient -> skip
    return {"symbol": str(sym), "price": price, "chg": chg, "vol": vol,
            "turnover": turn if turn is not None else price * vol,
            "security_type": row.get("security_type"), "name": row.get("name"),
            "is_otc": row.get("is_otc"), "raw": row}


def select_representative(rows) -> SelectionResult:
    """Return at most one representative symbol. Baseline US.AAPL is always retained."""
    if rows is None:
        return SelectionResult(SelectionStatus.RANK_UNAVAILABLE.value, None, BASELINE_SYMBOL,
                               0, 0, "premarket rank endpoint unavailable")
    if not isinstance(rows, (list, tuple)):
        return SelectionResult(SelectionStatus.INVALID_SOURCE_DATA.value, None, BASELINE_SYMBOL,
                               0, 0, "rank payload is not a list")
    normalized = [n for n in (_normalize(r) for r in rows) if n is not None]
    if rows and not normalized:
        return SelectionResult(SelectionStatus.INVALID_SOURCE_DATA.value, None, BASELINE_SYMBOL,
                               len(rows), 0, "no row could be parsed (all malformed)")

    qualified = []
    for n in normalized:
        row = n["raw"] if isinstance(n["raw"], dict) else n
        if not _is_common(n["raw"] if isinstance(n["raw"], dict) else {}):
            continue
        if not (PRICE_MIN <= n["price"] <= PRICE_MAX):
            continue
        if abs(n["chg"]) < MIN_ABS_CHANGE_PCT:
            continue
        if n["vol"] < MIN_PREMARKET_VOLUME:
            continue
        if n["symbol"].upper() in (BASELINE_SYMBOL.upper(), "AAPL"):
            continue                       # baseline is separate; never the "representative"
        qualified.append(n)

    if not qualified:
        return SelectionResult(SelectionStatus.NO_QUALIFYING_CANDIDATE.value, None, BASELINE_SYMBOL,
                               len(normalized), 0,
                               "no U.S. common stock met price/change/volume filters")

    # order: turnover desc, volume desc, symbol asc  (deterministic tie-break)
    qualified.sort(key=lambda n: (-n["turnover"], -n["vol"], n["symbol"]))
    winner = qualified[0]["symbol"]
    return SelectionResult(SelectionStatus.SELECTED.value, winner, BASELINE_SYMBOL,
                           len(normalized), len(qualified),
                           f"top by premarket turnover, then volume, then symbol")
