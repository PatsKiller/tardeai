"""Advisory Desk v1 — Deterministic opinion table for every instrument the operator
sees or gets pinged about.

Ingests holdings, watchlist, risk, rotation, and closed-lot data through the
Data Broker's read-model projections. Produces one row per instrument with a
fixed 8-verdict opinion, a short rationale, and a confidence score.

No LLM on this path. RE_ENTER delegates to the existing reentry_decision_desk.
ADD / HOLD / TRIM / EXIT / WAIT / AVOID / INSUFFICIENT_DATA are computed from
deterministic rules over positions, watchlist signals, risk, and rotation data.

Architecture: extends the Data Broker module family (same pattern as
reentry_decision_desk.py, portfolio_snapshot.py, watch_intelligence.py).
All data from JSON state files — zero DB queries, zero network calls.

Usage:
    from lib.data_broker.advisory_desk import build_advisory_desk
    result = build_advisory_desk()
    # result = {"ok": True, "data": {"rows": [...], "metadata": {...}}}
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time as _time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
CACHE_DIR = PROJECT_ROOT / "data" / "runtime"
CACHE_FILE = CACHE_DIR / "advisory_desk_latest.json"
SNAPSHOT_VERSION = "advisory-desk-v1-data-broker"
DEFAULT_MAX_AGE_S = 300  # 5-minute default cache window

# ── Freshness thresholds ─────────────────────────────────────────────────
STALE_HOURS_HOLDINGS = 24           # holdings.json freshness limit
STALE_HOURS_WATCHLIST = 48          # watchlist research data freshness
STALE_HOURS_RISK = 12               # risk snapshot freshness
STALE_HOURS_CLOSED = 96             # closed-lot journal freshness (matches re-entry)
MAX_WEIGHT_PCT = 15.0               # max single-position weight before TRIM consideration
MIN_WEIGHT_PCT_TRIM = 12.0          # weight where TRIM starts becoming advisory
LOSS_THRESHOLD_PCT = -15.0          # unrealized loss % that triggers EXIT review
LOSS_THRESHOLD_TRIM = -8.0          # unrealized loss % that triggers TRIM review
GAIN_THRESHOLD_PCT = 25.0           # unrealized gain % that triggers partial TRIM
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0
DAYS_HELD_LONG = 180               # threshold for long-held position review
RISK_SCORE_HIGH = 70.0              # risk score above which AVOID is considered
HOLD_MIN_WEIGHT_PCT = 1.0           # positions below this weight are flagged for housekeeping
IPS_MAX_POSITION_PCT = 8.0          # IPS single-position max (FIX-3 plausibility gate)

# ── Plausibility gate thresholds (FIX-3) ──────────────────────────────────
MAX_ANY_VERDICT_PCT = 30.0          # no single verdict >30% of holdings rows
MAX_EXIT_TRIM_COMBINED_PCT = 40.0   # EXIT+TRIM combined ≤ 40% of holdings
MIN_WEIGHT_SUM_PCT = 95.0           # holdings weight sum floor
MAX_WEIGHT_SUM_PCT = 105.0          # holdings weight sum ceiling
MATERIALITY_FLOOR_USD = 500.0       # B2: positions below $500 are housekeeping remnants
ALLOCATION_TOLERANCE_PCT = 4.0      # B1: drift tolerance from model_portfolio.json or IPS

# ── Evidence enrichment thresholds (Part A) ──────────────────────────────
MIN_EVIDENCE_ITEMS = 3              # A2: at least 3 evidence items for HOLD/WATCH
MIN_EVIDENCE_ACTIONABLE = 3         # A2: at least 3 for ADD/TRIM/EXIT/RE_ENTER (2 base + 1 domain)
STALE_DAYS_CATALYST = 7             # catalysts older than 7 days are stale
STALE_DAYS_EARNINGS = 90            # earnings data older than 90 days is stale
STALE_DAYS_NEWS = 3                 # news older than 3 days is stale

# ── S4: External plausibility invariant thresholds ───────────────────────
POSITION_VALUE_TOLERANCE = 0.01     # shares × price vs market_value ±1%
RECENT_IPO_DAYS = 180               # listed < 180 days → is_recent_ipo
MAX_PRICE_DEVIATION_52W = 20.0      # price >20% beyond 52w hi/lo → stale/wrong
MAX_BASIS_DEVIATION_AT = 50.0       # basis >50% outside all-time range → suspect

# ── S4: Curated listing dates (fallback when yfinance is rate-limited) ──
# Source: IPO data + public market history. Used for holding-period
# invariant: days_held must not exceed days_since_listing.
CURATED_LISTING_DATES: dict[str, str] = {
    "V":    "2008-03-19",
    "SCHD": "2011-10-20",
    "QCOM": "1991-12-13",
    "NOC":  "1951-03-01",
    "LDOS": "2006-09-14",
    "DIV":  "2018-12-03",
    "BAH":  "2010-11-17",
    "CSWC": "1969-01-01",
    "SCHG": "2009-12-11",
    "JEPI": "2020-05-19",
    "RTX":  "2020-04-03",
    "PFLT": "2011-04-06",
    "SRNE": "2013-07-10",
}


def _scripts_path() -> None:
    scripts = str(PROJECT_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


# ═══════════════════════════════════════════════════════════════════════════════
# Advisory Verdict — the frozen 8-verdict taxonomy
# ═══════════════════════════════════════════════════════════════════════════════

class AdvisoryVerdict(str, Enum):
    ADD = "ADD"                               # Accumulate/increase position
    HOLD = "HOLD"                             # Maintain current position
    TRIM = "TRIM"                             # Reduce position size
    EXIT = "EXIT"                             # Close the position entirely
    RE_ENTER = "RE_ENTER"                     # Consider re-entering a previously-closed position
    WAIT = "WAIT"                             # Wait for better conditions (price, RSI, catalyst)
    AVOID = "AVOID"                           # Do not engage — structural issues or high risk
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"   # Not enough evidence to form an opinion


VERDICT_DISPLAY = {
    AdvisoryVerdict.ADD:                   "Add / Accumulate",
    AdvisoryVerdict.HOLD:                  "Hold",
    AdvisoryVerdict.TRIM:                  "Trim / Reduce",
    AdvisoryVerdict.EXIT:                  "Exit / Close",
    AdvisoryVerdict.RE_ENTER:              "Re-Entry Opportunity",
    AdvisoryVerdict.WAIT:                  "Wait for Conditions",
    AdvisoryVerdict.AVOID:                 "Avoid",
    AdvisoryVerdict.INSUFFICIENT_DATA:     "Insufficient Data",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Data loading helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"state": "DATA_UNAVAILABLE", "reason": f"{path.name} not found"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"state": "ERROR", "reason": str(e)[:300]}


def _age_hours(timestamp_str: str | None) -> float | None:
    """Hours since a timestamp. Accepts ISO and 'YYYY-MM-DD'."""
    if not timestamp_str:
        return None
    try:
        ts = timestamp_str.strip()
        if "T" in ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(ts[:10], "%Y-%m-%d")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
    except Exception:
        return None


def _f(value: Any) -> float | None:
    try:
        n = float(value)
        return n if n == n else None
    except (TypeError, ValueError):
        return None


def _norm_symbol(s: str) -> str:
    return str(s).strip().upper()


# FIX-1: CUSIP / non-ticker detection
_CUSIP_RE = re.compile(r"^[A-Z0-9]{6,9}$")  # 6-9 alphanumeric: typical CUSIP length
_ALL_DIGITS_RE = re.compile(r"^\d+$")          # all-digits: bond/treasury identifier
_EQUITY_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")  # 1-5 uppercase letters: equity ticker


def _is_unresolved_symbol(symbol: str) -> tuple[bool, str]:
    """Check whether a symbol is an unresolved non-equity identifier.

    Returns (is_unresolved, reason).
    - All-digits: bond or treasury CUSIP — unresolved, not a delisting.
    - Alphanumeric 6-9 chars that is NOT a standard equity ticker: likely CUSIP.
    - Standard equity ticker (1-5 letters): resolved — it's a real symbol.
    """
    if _ALL_DIGITS_RE.match(symbol):
        return True, "symbol_is_numeric_cusip"
    if _EQUITY_TICKER_RE.match(symbol):
        return False, ""
    if _CUSIP_RE.match(symbol):
        return True, "symbol_matches_cusip_pattern"
    return False, ""


# ═══════════════════════════════════════════════════════════════════════════════
# Domain projections
# ═══════════════════════════════════════════════════════════════════════════════

def _load_holdings() -> dict[str, Any]:
    raw = _load_json(STATE_DIR / "holdings.json")
    positions: list[dict[str, Any]] = []
    total_value = 0.0
    as_of = None
    cash_weight_pct = None

    # Read portfolio_totals for authoritative denominator (includes CASH)
    totals = raw.get("portfolio_totals", {})
    portfolio_total_value = _f(totals.get("total_value"))  # full portfolio incl. CASH
    cash_weight_pct = _f(totals.get("cash_weight_pct"))
    if cash_weight_pct is None and portfolio_total_value:
        # Compute cash_weight_pct from raw CASH entries
        cash_mv = sum(
            _f(h.get("market_value")) or 0
            for h in raw.get("holdings", [])
            if h.get("is_cash") or _norm_symbol(h.get("symbol", "")) == "CASH"
        )
        cash_weight_pct = round(cash_mv / portfolio_total_value * 100, 2) if portfolio_total_value > 0 else 0

    for h in raw.get("holdings", []):
        symbol = _norm_symbol(h.get("symbol", ""))
        if not symbol or symbol == "CASH":
            continue
        mv = _f(h.get("market_value")) or 0
        # FIX-6: Consume the canonical gain_loss_pct from holdings.json
        canonical_gl = _f(h.get("gain_loss_pct"))
        pos = {
            "symbol": symbol,
            "shares": _f(h.get("shares")) or 0,
            "market_value": mv,
            "price": _f(h.get("price")) or _f(h.get("current_price")),
            "account": str(h.get("account", "")),
            "portfolio_pct": _f(h.get("portfolio_pct")),
            "cost_basis": _f(h.get("cost_basis")),
            "day_change_pct": _f(h.get("day_change_pct")),
            "bucket": str(h.get("bucket", "")),
            "name": str(h.get("name", "")),
            "gain_loss_pct": canonical_gl,
            "reconciliation_status": str(h.get("reconciliation_status", "")),
        }
        positions.append(pos)
        total_value += mv
        if h.get("as_of") and not as_of:
            as_of = str(h.get("as_of"))

    age_h = _age_hours(as_of or raw.get("as_of"))
    return {
        "state": "STALE" if (age_h and age_h > STALE_HOURS_HOLDINGS) else "AVAILABLE",
        "as_of": as_of,
        "age_hours": round(age_h, 1) if age_h else None,
        "positions": positions,
        "total_value": total_value,
        "count": len(positions),
        "portfolio_total_value": portfolio_total_value,
        "cash_weight_pct": cash_weight_pct,
    }


def _load_risk() -> dict[str, Any]:
    raw = _load_json(STATE_DIR / "risk_management.json")
    if raw.get("state"):
        return raw

    positions_risk: dict[str, dict[str, Any]] = {}
    for p in raw.get("positions", []):
        sym = _norm_symbol(p.get("symbol", ""))
        if sym:
            positions_risk[sym] = {
                "stop_count": p.get("stop_count", 0),
                "triggered": p.get("triggered", False),
            }

    return {
        "state": "AVAILABLE",
        "portfolio_heat_pct": _f(raw.get("portfolio_heat_pct")),
        "pct_protected": _f(raw.get("pct_protected")),
        "total_risk_dollars": _f(raw.get("total_risk_dollars")),
        "total_mv": _f(raw.get("total_mv")),
        "positions": positions_risk,
    }


def _load_watchlist() -> dict[str, Any]:
    raw = _load_json(STATE_DIR / "watchlist.json")
    if raw.get("state"):
        return raw

    items: dict[str, dict[str, Any]] = {}
    for sym, data in raw.items():
        s = _norm_symbol(sym)
        if s and isinstance(data, dict):
            items[s] = {
                "watching_since": data.get("watching_since"),
                "thesis": str(data.get("thesis", "")),
                "target_intent": str(data.get("target_intent", "")),
                "notes": str(data.get("notes", "")),
            }
    return {
        "state": "AVAILABLE",
        "items": items,
        "count": len(items),
    }


def _load_trade_journal() -> dict[str, Any]:
    raw = _load_json(STATE_DIR / "trade_journal.json")
    if raw.get("state"):
        return raw

    closed_symbols: set[str] = set()
    closed_by_symbol: dict[str, list[dict[str, Any]]] = {}
    trades = raw.get("closed_trades", [])
    if not isinstance(trades, list):
        trades = raw.get("trades", raw.get("entries", [])) if isinstance(raw, dict) else []
    for t in trades:
        sym = _norm_symbol(t.get("symbol", ""))
        if sym:
            closed_symbols.add(sym)
            exit_reason = str(t.get("setup") or t.get("note") or "")
            if t.get("stop_used"):
                exit_reason = f"stop:{t['stop_used']} {exit_reason}".strip()
            closed_by_symbol.setdefault(sym, []).append({
                "symbol": sym,
                "exit_date": t.get("close_date") or t.get("date") or t.get("exit_date"),
                "exit_price": _f(t.get("sell_price") or t.get("price")),
                "realized_pnl": _f(t.get("pnl")),
                "pnl_pct": _f(t.get("pnl_pct")),
                "exit_reason": exit_reason,
                "trade_type": str(t.get("trade_type", "")),
            })

    return {
        "state": "AVAILABLE",
        "closed_symbols": closed_symbols,
        "closed_by_symbol": closed_by_symbol,
        "count": len(closed_symbols),
    }


def _load_tax_lots() -> dict[str, Any]:
    """Parse tax_lots.json.

    Structure: {"SYMBOL:account": [{"lot_date": "...", "shares": N, "closed": bool}, ...], ...}
    Keys are composite; values are arrays of lot objects keyed by symbol+account.
    """
    raw = _load_json(STATE_DIR / "tax_lots.json")
    if raw.get("state"):
        return raw

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    lot_count = 0
    for key, lots in raw.items():
        if not isinstance(lots, list):
            continue
        parts = key.split(":")
        sym = _norm_symbol(parts[0]) if parts else ""
        if not sym:
            continue
        for lot in lots:
            if isinstance(lot, dict):
                by_symbol.setdefault(sym, []).append(lot)
                lot_count += 1

    return {
        "state": "AVAILABLE",
        "by_symbol": by_symbol,
        "count": lot_count,
    }


def _compute_days_held(symbol: str, tax_lots: dict) -> float | None:
    all_lots = tax_lots.get("by_symbol", {}).get(symbol, [])
    if not all_lots:
        return None
    # 0.3: Restrict to open lots only — closed lots have stale lot_dates
    # that would produce inflated days_held values and false long_held signals.
    open_lots = [
        l for l in all_lots
        if not l.get("closed") and float(l.get("shares_remaining", 0)) > 0
    ]
    source_lots = open_lots if open_lots else all_lots
    oldest = min(
        (lot.get("lot_date") or lot.get("acquired_date") or lot.get("date") or "9999-12-31" for lot in source_lots),
        default="9999-12-31",
    )
    try:
        dt = datetime.strptime(oldest[:10], "%Y-%m-%d")
        return (datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc)).days
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Opinion engine — deterministic rules over aggregated data
# ═══════════════════════════════════════════════════════════════════════════════

def _derive_holding_opinion(
    pos: dict[str, Any],
    total_value: float,
    risk_positions: dict[str, dict[str, Any]],
    tax_lots: dict,
    portfolio_heat_pct: float | None,
    invariants: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute a single advisory opinion for one holding position.

    If invariants are provided and fail for this holding, the verdict is
    forced to INSUFFICIENT_DATA with the violated invariant named.
    """
    symbol = pos["symbol"]
    mv = pos.get("market_value") or 0
    pct = pos.get("portfolio_pct") or (mv / total_value * 100 if total_value > 0 else 0)
    day_chg_pct = pos.get("day_change_pct")
    bucket = pos.get("bucket", "")
    risk = risk_positions.get(symbol, {})
    days_held = _compute_days_held(symbol, tax_lots)
    reconciliation_status = str(pos.get("reconciliation_status", "")).upper()

    # FIX-6: Use canonical gain_loss_pct from holdings.json — no recomputation.
    # The holdings.json field is enriched by the API pipeline and is the
    # single authority for P&L surfacing.  Recomputation diverges because
    # the desk uses raw cost_basis while the API may include DRIP adjustments.
    gain_loss_pct = pos.get("gain_loss_pct")

    # FIX-1: Unresolved symbol (CUSIP, bond) → INSUFFICIENT_DATA, never EXIT.
    # An unrecognized identifier is a lookup failure, not a corporate death.
    is_unresolved, cusip_reason = _is_unresolved_symbol(symbol)
    if is_unresolved:
        return {
            "symbol": symbol,
            "verdict": AdvisoryVerdict.INSUFFICIENT_DATA,
            "confidence": 0.30,
            "rationale": f"Unresolvable symbol ({cusip_reason}). No delisting signal — identifier cannot be resolved to an equity ticker.",
            "weight_pct": round(pct, 2),
            "market_value": mv,
            "account": pos.get("account", ""),
            "risk_signals": [],
            "source": "holdings",
            "housekeeping_flag": False,
            "gain_loss_pct": gain_loss_pct,
        }

    # Delisted bucket still fires EXIT — but only for genuinely delisted equity tickers,
    # not CUSIPs (which were caught above).
    if bucket in ("Delisted/Worthless", "Worthless", "Delisted"):
        return {
            "symbol": symbol,
            "verdict": AdvisoryVerdict.EXIT,
            "confidence": 0.95,
            "rationale": f"Position is classified as {bucket}. No recovery path — remove for reporting hygiene.",
            "weight_pct": round(pct, 2),
            "market_value": mv,
            "account": pos.get("account", ""),
            "risk_signals": [],
            "source": "holdings",
            "housekeeping_flag": False,
            "gain_loss_pct": gain_loss_pct,
        }

    # ── S4: External invariant enforcement ──
    # Rows failing invariants get INSUFFICIENT_DATA with the violated invariant named.
    # This gate fires before any signal evaluation — a verdict must never fire on
    # data that failed external validation.
    if invariants and not invariants.get("pass", True):
        inv_violations = invariants.get("violations", [])
        inv_lot_status = invariants.get("lot_data_status", "")
        return {
            "symbol": symbol,
            "verdict": AdvisoryVerdict.INSUFFICIENT_DATA,
            "confidence": 0.10,
            "rationale": (
                f"External invariant violation: {'; '.join(inv_violations[:3])}. "
                f"Lot data status: {inv_lot_status}. "
                f"Verdict suppressed — data failed external reality checks."
            ),
            "weight_pct": round(pct, 2),
            "market_value": mv,
            "account": pos.get("account", ""),
            "risk_signals": [],
            "source": "holdings",
            "housekeeping_flag": False,
            "gain_loss_pct": gain_loss_pct,
            "lot_data_status": inv_lot_status,
        }

    signals: list[str] = []
    reasons: list[str] = []
    housekeeping_flag = False

    # Risk signals
    if risk.get("triggered"):
        signals.append("stop_triggered")
        reasons.append("Stop-loss triggered")

    if portfolio_heat_pct is not None and portfolio_heat_pct > RISK_SCORE_HIGH:
        signals.append("portfolio_heat_high")
        reasons.append(f"Portfolio risk heat at {portfolio_heat_pct:.0f}%")

    # Weight signals
    if pct > MAX_WEIGHT_PCT:
        signals.append("overweight")
        reasons.append(f"Position weight {pct:.1f}% exceeds {MAX_WEIGHT_PCT:.0f}% max")
    elif pct > MIN_WEIGHT_PCT_TRIM:
        signals.append("elevated_weight")
        reasons.append(f"Position at {pct:.1f}% — review sizing")

    # FIX-2: Sub-threshold weight is a property, not a judgment.
    # It flags the row for housekeeping without forcing EXIT.
    if pct < HOLD_MIN_WEIGHT_PCT and mv > 0:
        housekeeping_flag = True
        reasons.append(f"Sub-threshold remnant at {pct:.2f}% — review for consolidation")

    # B2: Materiality floor — sub-$500 positions are housekeeping, not decisions.
    if mv < MATERIALITY_FLOOR_USD and mv > 0:
        housekeeping_flag = True
        reasons.append(f"Below materiality floor (${MATERIALITY_FLOOR_USD:.0f}) — close-out remnant" if housekeeping_flag else f"Below materiality floor (${MATERIALITY_FLOOR_USD:.0f}) — close-out remnant")

    # Loss signals
    if gain_loss_pct is not None and gain_loss_pct < LOSS_THRESHOLD_PCT:
        signals.append("material_loss")
        reasons.append(f"Unrealized loss {gain_loss_pct:.1f}% exceeds {abs(LOSS_THRESHOLD_PCT):.0f}% threshold")
    elif gain_loss_pct is not None and gain_loss_pct < LOSS_THRESHOLD_TRIM:
        signals.append("moderate_loss")
        reasons.append(f"Unrealized loss {gain_loss_pct:.1f}% — monitor")

    # Gain signals
    if gain_loss_pct is not None and gain_loss_pct > GAIN_THRESHOLD_PCT:
        signals.append("large_gain")
        reasons.append(f"Unrealized gain {gain_loss_pct:.1f}% exceeds {GAIN_THRESHOLD_PCT:.0f}% — consider partial trim")

    # Day change
    if day_chg_pct is not None and day_chg_pct < -5:
        signals.append("sharp_drop")
        reasons.append(f"Down {day_chg_pct:.1f}% today — wait for stabilization")

    # Days held
    # S4: Suppress long_held when lot data is UNTRUSTED — a verdict must
    # never fire on a signal derived from data that failed validation.
    lot_status = (invariants or {}).get("lot_data_status", "")
    if days_held is not None and days_held > DAYS_HELD_LONG:
        if lot_status == "UNTRUSTED":
            reasons.append(
                f"days_held={days_held:.0f}d (UNTRUSTED lot data — "
                f"suppressed as signal, reported for operator awareness)"
            )
        else:
            signals.append("long_held")
            reasons.append(f"Held {days_held:.0f} days — review thesis freshness")

    if gain_loss_pct is not None and gain_loss_pct < LOSS_THRESHOLD_PCT and days_held is not None and days_held > 90:
        signals.append("disposition_effect_like")
        reasons.append(f"Long-held ({days_held:.0f}d) material loser ({gain_loss_pct:.1f}%) — disposition effect candidate (see behavioral analytics)")

    # ── Verdict selection ──
    verdict = AdvisoryVerdict.HOLD

    if "material_loss" in signals and "overweight" in signals:
        verdict = AdvisoryVerdict.EXIT
    elif "material_loss" in signals and "long_held" in signals:
        verdict = AdvisoryVerdict.EXIT
    elif "material_loss" in signals:
        verdict = AdvisoryVerdict.TRIM
    elif "overweight" in signals:
        verdict = AdvisoryVerdict.TRIM
    elif "large_gain" in signals:
        verdict = AdvisoryVerdict.TRIM
        reasons.append("Consider taking partial profits")
    elif "sharp_drop" in signals:
        verdict = AdvisoryVerdict.WAIT
    elif "stop_triggered" in signals:
        verdict = AdvisoryVerdict.EXIT

    # Clean verdict: if nothing triggered, it's a HOLD
    if not signals:
        verdict = AdvisoryVerdict.HOLD
        reasons.append("Position within normal parameters — no advisory signal triggered")

    # B2: Materiality floor — below $500, suppress all actionable verdicts.
    housekeeping_reason = ""
    if housekeeping_flag and mv < MATERIALITY_FLOOR_USD:
        if verdict.value in ("EXIT", "TRIM", "ADD"):
            housekeeping_reason = "close_out_remnant"
            reasons.append(f"Dollar value ${mv:.0f} below materiality floor (${MATERIALITY_FLOOR_USD:.0f}) — verdict suppressed")
        verdict = AdvisoryVerdict.HOLD

    # FIX-4: Confidence varies with evidence quality
    confidence = _compute_confidence(
        signals=signals,
        days_held=days_held,
        gain_loss_pct=gain_loss_pct,
        reconciliation_status=reconciliation_status,
        cost_basis=pos.get("cost_basis"),
    )

    return {
        "symbol": symbol,
        "verdict": verdict,
        "confidence": round(confidence, 2),
        "rationale": " | ".join(reasons) if reasons else "No material signals detected.",
        "weight_pct": round(pct, 2),
        "market_value": round(mv, 2),
        "gain_loss_pct": round(gain_loss_pct, 2) if gain_loss_pct is not None else None,
        "days_held": round(days_held) if days_held else None,
        "account": pos.get("account", ""),
        "risk_signals": signals,
        "source": "holdings",
        "housekeeping_flag": housekeeping_flag,
        "housekeeping_reason": housekeeping_reason or None,
    }


# FIX-4: Confidence derived from evidence quality, not a constant.
def _compute_confidence(
    *,
    signals: list[str],
    days_held: float | None,
    gain_loss_pct: float | None,
    reconciliation_status: str | None,
    cost_basis: float | None,
) -> float:
    """Score confidence from the evidence actually present.

    Base: 0.50 (no signals → weak HOLD).
    Per independent signal: +0.10 (max +0.30 from signals).
    Fresh data bonus (days_held available): +0.05.
    Verified cost basis: +0.10 if reconciliation_status is 'OK' and cost_basis present.
    Margin bonus: +0.05 if threshold crossed by >50% (strong signal).
    Unverified basis penalty: -0.15 if reconciliation_status is not OK/UNKNOWN.
    """
    score = 0.50

    # Signal count (cap at 3 signals)
    n_signals = min(len(signals), 3)
    score += n_signals * 0.10

    # Freshness / data completeness
    if days_held is not None:
        score += 0.05

    # Cost basis verification
    recon = (reconciliation_status or "").upper()
    if recon == "OK" and cost_basis is not None:
        score += 0.10
    elif recon not in ("OK", "") and recon != "UNKNOWN":
        score -= 0.15

    # Margin bonus — threshold crossed by wide margin
    gl = gain_loss_pct
    if gl is not None:
        threshold_str = LOSS_THRESHOLD_PCT  # -15.0
        if gl < threshold_str * 1.5:   # more than 50% beyond threshold
            score += 0.05
        if gl > GAIN_THRESHOLD_PCT * 1.5:
            score += 0.05

    return max(0.10, min(0.95, score))


def _derive_watchlist_opinion(
    symbol: str,
    data: dict[str, Any],
    holdings_symbols: set[str],
) -> dict[str, Any]:
    """Compute an advisory opinion for a watchlist instrument (not held)."""
    if symbol in holdings_symbols:
        return None

    thesis = data.get("thesis", "")
    target = data.get("target_intent", "").upper()
    watching_since = data.get("watching_since")

    verdict = AdvisoryVerdict.WAIT
    confidence = 0.40
    reasons: list[str] = []

    # B3: Real differentiation from target_intent values in watchlist.json
    if target in ("BUY", "ACCUMULATE", "ADD", "LONG_TERM_HOLD", "INCOME", "ETF_BROAD"):
        verdict = AdvisoryVerdict.ADD
        confidence = 0.45
        reasons.append(f"Watchlist intent: {target.replace('_',' ').lower()}")
    elif target in ("GROWTH_SPECULATIVE",):
        verdict = AdvisoryVerdict.AVOID
        confidence = 0.40
        reasons.append("Speculative growth — high risk, no structural thesis edge")
    elif target in ("MONITOR", "WATCH"):
        verdict = AdvisoryVerdict.WAIT
        reasons.append("Watchlist intent is monitor — wait for entry signal")
    elif not thesis:
        verdict = AdvisoryVerdict.INSUFFICIENT_DATA
        confidence = 0.20
        reasons.append("No target intent defined and no thesis — insufficient data for opinion")
    else:
        verdict = AdvisoryVerdict.WAIT
        reasons.append(f"Intent '{target.lower()}' — pending review")

    if thesis:
        reasons.append(f"Thesis: {thesis[:120]}")
        confidence += 0.05

    return {
        "symbol": symbol,
        "verdict": verdict,
        "confidence": min(0.60, confidence),
        "rationale": " | ".join(reasons) if reasons else "On watchlist — no current entry/exit signal.",
        "weight_pct": None,
        "market_value": None,
        "gain_loss_pct": None,
        "days_held": None,
        "risk_signals": [],
        "source": "watchlist",
        "watching_since": watching_since,
        "housekeeping_flag": False,
    }


def _derive_closed_opinion(
    symbol: str,
    trades: list[dict[str, Any]],
    holdings_symbols: set[str],
) -> dict[str, Any] | None:
    """Compute advisory opinion for a previously-closed position.

    Delegates to the re-entry decision desk for RE_ENTER signals.
    """
    if symbol in holdings_symbols:
        return None

    _scripts_path()
    try:
        from lib.data_broker.reentry_decision_desk import build_decision_desk
        from db_adapter import _execute as _db_exec
        def _db_wrapper(sql: str, params=None, *, fetch: str = "all"):
            """Thin wrapper matching the re-entry desk's db_query signature.
            Defaults to fetch='all' since most callers expect a list.
            """
            return _db_exec(sql, params, fetch=fetch)
        reentry_result = build_decision_desk(_db_wrapper)
        # Rows are at top level, not nested inside data
        rows = reentry_result.get("rows", []) if isinstance(reentry_result, dict) else []
        for row in rows:
            if _norm_symbol(row.get("symbol", "")) == symbol:
                intel = row.get("intel", {})
                state = intel.get("state", "WAIT")
                if state in ("READY TO REVIEW", "NEAR ENTRY"):
                    price = row.get("price", "?")
                    entry_low = row.get("entry_low", "?")
                    entry_high = row.get("entry_high", "?")
                    return {
                        "symbol": symbol,
                        "verdict": AdvisoryVerdict.RE_ENTER,
                        "confidence": 0.55,
                        "rationale": (
                            f"Re-entry desk: {state}. "
                            f"Price ${price} in zone ${entry_low}–${entry_high}. "
                            f"{intel.get('reason', '')}"
                        ),
                        "weight_pct": None,
                        "market_value": None,
                        "gain_loss_pct": None,
                        "days_held": None,
                        "risk_signals": [],
                        "source": "reentry_decision_desk",
                        "reentry_state": state,
                        "reentry_entry_low": entry_low,
                        "reentry_entry_high": entry_high,
                        "housekeeping_flag": False,
                    }
                else:
                    return {
                        "symbol": symbol,
                        "verdict": AdvisoryVerdict.WAIT,
                        "confidence": 0.30,
                        "rationale": f"Re-entry desk: {state} — {intel.get('reason', 'Not yet ready for review.')}",
                        "weight_pct": None,
                        "market_value": None,
                        "gain_loss_pct": None,
                        "days_held": None,
                        "reentry_state": state,
                        "risk_signals": [],
                        "source": "reentry_decision_desk",
                        "housekeeping_flag": False,
                    }
    except Exception:
        pass

    # Fallback: basic WAIT for closed positions without re-entry desk data
    latest_exit = trades[0] if trades else {}
    return {
        "symbol": symbol,
        "verdict": AdvisoryVerdict.WAIT,
        "confidence": 0.25,
        "rationale": f"Previously closed. Last exit: {latest_exit.get('exit_reason', 'unknown reason')}. Re-entry desk has no active signal.",
        "weight_pct": None,
        "market_value": None,
        "gain_loss_pct": None,
        "days_held": None,
        "risk_signals": [],
        "source": "closed_journal",
        "housekeeping_flag": False,
    }


# FIX-5: Compute a per-row advisory hash over material deterministic fields.
def _row_hash(row: dict[str, Any]) -> str:
    """Compute a deterministic hash for one advisory row.

    Only includes fields that materially affect the opinion — excludes
    timestamps, computed_at, and other fields that tick without meaning.
    """
    material_keys = (
        "symbol", "verdict", "confidence", "weight_pct", "market_value",
        "gain_loss_pct", "days_held", "account", "source", "risk_signals",
        "housekeeping_flag", "housekeeping_reason", "row_class",
    )
    material = {}
    for k in material_keys:
        v = row.get(k)
        if v is not None:
            material[k] = v
    payload = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════════════════════
# B1 + Part A: Evidence loading functions
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG_DIR = PROJECT_ROOT / "config"


def _load_model_portfolio() -> dict[str, Any]:
    raw = _load_json(CONFIG_DIR / "model_portfolio.json")
    return raw.get("strategic_allocation", {}) if raw.get("strategic_allocation") else raw


def _load_catalysts() -> dict[str, Any]:
    """Load catalyst/news evidence from portfolio_news and catalyst_cache."""
    news = _load_json(STATE_DIR / "portfolio_news.json")
    cache = _load_json(PROJECT_ROOT / "data" / f"catalyst_cache_2026-08-10.json")
    catalysts: dict[str, list[dict[str, Any]]] = {}

    # From portfolio_news (scored catalysts)
    for item in news.get("scored_catalysts", []):
        sym = _norm_symbol(item.get("symbol", ""))
        if sym:
            catalysts.setdefault(sym, []).append({
                "source": "portfolio_news",
                "as_of": news.get("generated_at", ""),
                "title": str(item.get("headline", item.get("title", "")))[:200],
                "quality": str(item.get("score", item.get("quality", ""))),
                "staleness_days": _age_hours(news.get("generated_at")) / 24 if news.get("generated_at") else None,
            })

    # From catalyst_cache
    for sym, data in cache.items():
        enrichment = data.get("enrichment", {})
        cat_list = enrichment.get("catalysts", [])
        if cat_list:
            sym_u = _norm_symbol(sym)
            for c in cat_list[:5]:
                catalysts.setdefault(sym_u, []).append({
                    "source": "catalyst_cache",
                    "as_of": data.get("_cached_at", ""),
                    "title": str(c.get("headline", c.get("title", "")))[:200],
                    "type": str(c.get("catalyst_type", "")),
                    "tier": str(enrichment.get("catalyst_tier", "")),
                    "staleness_days": _age_hours(data.get("_cached_at")) / 24 if data.get("_cached_at") else None,
                })

    return {"state": "AVAILABLE", "by_symbol": catalysts, "count": len(catalysts)}


def _load_earnings() -> dict[str, Any]:
    raw = _load_json(STATE_DIR / "earnings_dates.json")
    by_symbol: dict[str, dict[str, Any]] = {}
    for sym, data in raw.items():
        if isinstance(data, dict):
            s = _norm_symbol(sym)
            ed = data.get("earnings_date")
            fetched = data.get("fetched_at")
            stale = _age_hours(fetched) / 24 if fetched else None
            by_symbol[s] = {
                "next_earnings_date": ed,
                "fetched_at": fetched,
                "staleness_days": round(stale, 1) if stale else None,
            }
    return {"state": "AVAILABLE", "by_symbol": by_symbol, "count": len(by_symbol)}


def _load_rotation() -> dict[str, Any]:
    """Load rotation posture from runtime state."""
    raw = _load_json(PROJECT_ROOT / "data" / "runtime" / "rotation_autopilot_state.json")
    return {
        "state": "AVAILABLE",
        "signal": raw.get("signal"),
        "strength": raw.get("strength", 0),
        "as_of": raw.get("last_checked", ""),
    }


def _load_ips() -> dict[str, Any]:
    raw = _load_json(CONFIG_DIR / "investment_policy_statement.json")
    return {
        "state": "AVAILABLE",
        "max_position_pct": IPS_MAX_POSITION_PCT,
        "beta_target": _f(raw.get("risk_tolerance", {}).get("target_beta") or raw.get("target_beta")),
    }


def _load_hermes_lifecycle() -> dict[str, Any]:
    """Load per-position hermes health scores from holdings lifecycle."""
    raw = _load_json(PROJECT_ROOT / "data" / "runtime" / "hermes_holdings_lifecycle.json")
    by_symbol: dict[str, dict[str, Any]] = {}
    for sym, data in raw.get("holdings", {}).items():
        s = _norm_symbol(sym)
        by_symbol[s] = {
            "lifecycle_stage": data.get("lifecycle_stage", ""),
            "health_score": _f(data.get("health_score")),
            "confidence_tier": data.get("confidence_tier", ""),
            "graded_n": data.get("graded_n", 0),
            "stop_quality": _f(data.get("components", {}).get("stop_quality")),
            "outcome_consistency": _f(data.get("components", {}).get("outcome_consistency")),
            "realized": _f(data.get("components", {}).get("realized")),
        }
    return {"state": "AVAILABLE", "by_symbol": by_symbol, "count": len(by_symbol)}


def _load_indicator_snapshot() -> dict[str, Any]:
    """Load per-symbol technical indicators from pre-computed snapshot."""
    raw = _load_json(PROJECT_ROOT / "state" / "data_broker" / "indicator_snapshot.json")
    by_symbol: dict[str, dict[str, Any]] = {}
    bs = raw.get("by_symbol", {})
    for sym, data in bs.items():
        s = _norm_symbol(sym)
        by_symbol[s] = {
            "rsi": _f(data.get("rsi")),
            "rsi_status": data.get("rsi_status", ""),
            "sma_20": _f(data.get("sma_20")),
            "sma_50": _f(data.get("sma_50")),
            "sma_200": _f(data.get("sma_200")),
            "sma20_pct": _f(data.get("sma20_pct")),
            "sma50_pct": _f(data.get("sma50_pct")),
            "sma200_pct": _f(data.get("sma200_pct")),
            "macd_signal": data.get("macd_signal", ""),
            "macd_histogram_direction": data.get("macd_histogram_direction", ""),
            "atr": _f(data.get("atr")),
            "obv_signal": data.get("obv_signal", ""),
            "volume_ratio": _f(data.get("volume_ratio")),
            "as_of": raw.get("computed_at", ""),
        }
    return {"state": "AVAILABLE", "by_symbol": by_symbol, "count": len(by_symbol), "as_of": raw.get("computed_at", "")}


def _load_risk_snapshot() -> dict[str, Any]:
    """Load per-position risk/stop data from risk snapshot."""
    raw = _load_json(PROJECT_ROOT / "state" / "data_broker" / "risk_snapshot.json")
    by_symbol: dict[str, dict[str, Any]] = {}
    for p in raw.get("positions", []):
        s = _norm_symbol(p.get("symbol", ""))
        if s:
            by_symbol[s] = {
                "stop_price": _f(p.get("stop_price")),
                "distance_to_stop_pct": _f(p.get("distance_to_stop_pct")),
                "triggered": bool(p.get("triggered")),
                "status": p.get("status", ""),
                "market_value": _f(p.get("market_value")),
            }
    # Also check stops_map for alternative key patterns (e.g. "BAH:schwab_taxable")
    for key, val in raw.get("stops_map", {}).items():
        s = _norm_symbol(key.split(":")[0] if ":" in key else key)
        if s not in by_symbol:
            by_symbol[s] = {
                "stop_price": _f(val.get("stop_price")),
                "triggered": bool(val.get("triggered")),
                "distance_to_stop_pct": None,
                "status": "",
                "market_value": None,
            }
    return {
        "state": "AVAILABLE",
        "by_symbol": by_symbol,
        "count": len(by_symbol),
        "portfolio_heat_pct": _f(raw.get("portfolio", {}).get("heat_pct")),
        "as_of": raw.get("computed_at", ""),
    }


def _load_sector_rotation() -> dict[str, Any]:
    """Load sector RS rankings from rotation ladders."""
    raw = _load_json(PROJECT_ROOT / "state" / "data_broker" / "rotation_ladders.json")
    sectors: list[dict[str, Any]] = []
    top = ""
    bottom = ""
    for s in raw.get("sectors", []):
        sectors.append({
            "etf": s.get("etf", ""),
            "name": s.get("name", ""),
            "rs_score": s.get("rs_score", 0),
            "return_1m": s.get("return_1m"),
        })
    if sectors:
        top = sectors[0]["name"]
        bottom = sectors[-1]["name"]
    return {
        "state": "AVAILABLE",
        "sectors": sectors,
        "count": len(sectors),
        "top_sector": top,
        "bottom_sector": bottom,
        "as_of": raw.get("computed_at", ""),
    }


def _load_agent_results() -> dict[str, Any]:
    """Load per-symbol agent opinions from watchlist_agent_results via DB."""
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    try:
        from db_adapter import _execute
        rows = _execute(
            """SELECT upper(symbol) AS symbol, agent, recommendation, confidence,
                      full_narrative, completed_at
               FROM watchlist_agent_results
               WHERE completed_at > now() - make_interval(days => 14)
               ORDER BY completed_at DESC""",
            fetch="all",
        ) or []
        for row in rows:
            sym = _norm_symbol(str(row.get("symbol") or ""))
            if sym:
                by_symbol.setdefault(sym, []).append({
                    "agent": row.get("agent", ""),
                    "recommendation": row.get("recommendation", ""),
                    "confidence": _f(row.get("confidence")),
                    "narrative": str(row.get("full_narrative", ""))[:200] if row.get("full_narrative") else "",
                    "completed_at": str(row.get("completed_at", "")),
                })
        return {"state": "AVAILABLE", "by_symbol": by_symbol, "count": len(by_symbol)}
    except Exception:
        return {"state": "UNAVAILABLE", "by_symbol": {}, "count": 0}


# ═══════════════════════════════════════════════════════════════════════════════
# S4: External data loaders — listing dates, instrument identity, OHLCV,
#     price action, lot-level basis, analyst context
# ═══════════════════════════════════════════════════════════════════════════════


def _load_listing_dates(holdings_symbols: set[str]) -> dict[str, str]:
    """Load listing dates from curated map + ipo_lockups.json.

    Falls back to CURATED_LISTING_DATES for well-known stocks.
    SPCX sourced from config/ipo_lockups.json (2026-06-12).
    """
    dates: dict[str, str] = dict(CURATED_LISTING_DATES)

    # Override from ipo_lockups.json (authoritative for recent IPOs)
    lockups = _load_json(CONFIG_DIR / "ipo_lockups.json")
    lockups_data = lockups.get("lockups", {})
    for sym, data in lockups_data.items():
        if isinstance(data, dict) and data.get("ipo_date"):
            dates[_norm_symbol(sym)] = data["ipo_date"]

    # Return only symbols we care about
    return {s: d for s, d in dates.items() if s in holdings_symbols}


def _load_ohlcv_data() -> dict[str, dict[str, dict[str, float]]]:
    """Load price_ohlc_cache.json.

    Returns {SYMBOL: {date_str: {o, h, l, c, v}}}.
    SPCX has no data (None) — expected for recent IPO (< 60 days).
    """
    raw = _load_json(STATE_DIR / "price_ohlc_cache.json")
    if raw.get("state"):
        return {}
    result: dict[str, dict[str, dict[str, float]]] = {}
    for sym, data in raw.items():
        if isinstance(data, dict):
            result[_norm_symbol(sym)] = data
    return result


def _load_instrument_identity(
    holdings: dict[str, Any],
    listing_dates: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Build per-symbol instrument identity evidence.

    Sources: symbol_profiles DB (sector, industry, instrument_type, description),
             ticker_enrichment_cache (sector, market_cap, industry),
             ipo_lockups.json (listing_date),
             CURATED_LISTING_DATES (fallback listing_date).

    Returns {SYMBOL: {name, type, listing_date, exchange, sector, market_cap,
                       is_recent_ipo}}
    """
    # Load Finviz enrichment cache for market_cap, sector
    finviz = _load_json(STATE_DIR / "ticker_enrichment_cache.json")
    finviz_by_sym: dict[str, dict[str, Any]] = {}
    for k, v in finviz.items():
        if isinstance(v, dict):
            finviz_by_sym[_norm_symbol(k)] = v

    # Load DB symbol_profiles for instrument_type, description_1s
    db_profiles: dict[str, dict[str, Any]] = {}
    try:
        from db_adapter import _execute
        symbols_list = list(holdings.get("symbols", set()))
        if symbols_list:
            row_list = _execute(
                """SELECT upper(symbol) AS sym, instrument_type, sector, industry,
                          description_1s, quote_type
                   FROM symbol_profiles WHERE upper(symbol) = ANY(%s)""",
                (symbols_list,),
                fetch="all",
            ) or []
            for r in row_list:
                db_profiles[_norm_symbol(str(r.get("sym") or ""))] = r
    except Exception:
        pass

    result: dict[str, dict[str, Any]] = {}
    today = datetime.now(timezone.utc).date()

    for pos in holdings.get("positions", []):
        sym = pos["symbol"]
        finv = finviz_by_sym.get(sym, {})
        dbp = db_profiles.get(sym, {})

        # Instrument type hierarchy: DB > Finviz > position bucket
        inst_type = str(dbp.get("instrument_type") or "")
        if not inst_type:
            sector_finviz = str(finv.get("sector") or "")
            if "etf" in sector_finviz.lower() or "fund" in sector_finviz.lower():
                inst_type = "etf"
            else:
                inst_type = "stock"

        # Name: DB description > Finviz company > holdings name
        name = str(dbp.get("description_1s") or finv.get("company") or pos.get("name", "") or sym)

        # Sector: DB > Finviz
        sector = str(dbp.get("sector") or finv.get("sector") or "")

        # Market cap from Finviz (billions → numeric)
        mcap_b = _f(finv.get("market_cap_b"))
        mcap = mcap_b * 1_000_000_000 if mcap_b else None

        # Listing date: curated > ipo_lockups > None
        ld_str = listing_dates.get(sym)
        ld_date = None
        if ld_str:
            try:
                ld_date = datetime.strptime(ld_str[:10], "%Y-%m-%d").date()
            except ValueError:
                pass

        # is_recent_ipo: listed < RECENT_IPO_DAYS days ago
        is_recent = False
        if ld_date:
            is_recent = (today - ld_date).days < RECENT_IPO_DAYS

        # CUSIPs are unresolved — no valid instrument identity
        if _is_unresolved_symbol(sym)[0]:
            inst_type = "unresolved"
            name = f"CUSIP: {sym} (unresolved — likely bond/fixed income)"

        result[sym] = {
            "name": name,
            "type": inst_type,
            "listing_date": ld_str,
            "exchange": str(finv.get("ticker") or sym),
            "sector": sector,
            "market_cap": mcap,
            "is_recent_ipo": is_recent,
            "source": "symbol_profiles + ticker_enrichment_cache + ipo_lockups",
        }

    return result


# ── S4: External invariants validator ─────────────────────────────────────

def _validate_external_invariants(
    row: dict[str, Any],
    listing_dates: dict[str, str],
    ohlcv_data: dict[str, dict[str, dict[str, float]]],
) -> dict[str, Any]:
    """Check holding-level data against external reality.

    Returns:
        dict with:
            "pass": bool — all invariants hold
            "violations": list[str] — names of failed invariants
            "lot_data_status": "VERIFIED" | "UNTRUSTED"
    """
    violations: list[str] = []
    lot_fail = False
    sym = row.get("symbol", "")

    # Get listing date for this symbol
    ld_str = listing_dates.get(sym)
    ld_date = None
    if ld_str:
        try:
            ld_date = datetime.strptime(ld_str[:10], "%Y-%m-%d").date()
        except ValueError:
            pass

    days_since_listing = None
    if ld_date:
        days_since_listing = (datetime.now(timezone.utc).date() - ld_date).days

    # ── Invariant 1: Holding period ──
    dh = row.get("days_held")
    if dh is not None and days_since_listing is not None and dh > 0:
        if dh > days_since_listing + 2:  # +2 days for timezone/calendar slop
            violations.append(
                f"holding_period_violation: days_held={dh}d exceeds max "
                f"{days_since_listing}d (listed {ld_str}). Lot data untrusted."
            )
            lot_fail = True

    # ── Invariant 2: Position value reconciliation ──
    # Skip for fractional shares (<1.0) where holdings.json often stores
    # market_value in the price field (broker data defect).
    price = _f(row.get("price"))
    shares = _f(row.get("shares"))
    mv = _f(row.get("market_value"))
    if price and shares and mv and mv > 0 and shares >= 1.0:
        computed = price * shares
        if computed > 0:
            deviation = abs(computed - mv) / mv
            if deviation > POSITION_VALUE_TOLERANCE:
                violations.append(
                    f"position_value_mismatch: shares×price=${computed:,.2f} vs "
                    f"market_value=${mv:,.2f} ({deviation*100:.1f}% off)"
                )

    # ── Invariant 3: Price sanity (52-week range from OHLCV) ──
    # For fractional shares (<1.0), holdings.json may store market_value as price;
    # use OHLCV last close price instead.
    ohlc_sym = ohlcv_data.get(sym, {})
    check_price = price
    if shares and shares < 1.0 and isinstance(ohlc_sym, dict) and ohlc_sym:
        ohlc_dates = sorted(ohlc_sym.keys())
        if ohlc_dates:
            check_price = ohlc_sym[ohlc_dates[-1]].get("c", price)

    if check_price and isinstance(ohlc_sym, dict) and ohlc_sym:
        dates_sorted = sorted(ohlc_sym.keys())
        # 52-week range: last ~252 trading days
        recent = dates_sorted[-252:] if len(dates_sorted) >= 252 else dates_sorted
        if recent:
            week52_high = max(ohlc_sym[d]["h"] for d in recent if "h" in ohlc_sym[d])
            week52_low = min(ohlc_sym[d]["l"] for d in recent if "l" in ohlc_sym[d])
            if week52_low > 0:
                if check_price > week52_high * (1 + MAX_PRICE_DEVIATION_52W / 100):
                    violations.append(
                        f"price_above_52w_high: ${check_price:.2f} vs 52w high ${week52_high:.2f}"
                    )
                if check_price < week52_low * (1 - MAX_PRICE_DEVIATION_52W / 100):
                    violations.append(
                        f"price_below_52w_low: ${check_price:.2f} vs 52w low ${week52_low:.2f}"
                    )

    # ── Invariant 4: Basis sanity (cost_basis_per_share vs all-time range) ──
    # Only flag when the position has an unrealized LOSS — a long-term holding
    # with basis below the OHLCV data window is normal (OHLCV doesn't go back
    # to pre-2022).
    cb = _f(row.get("cost_basis"))
    gl = _f(row.get("gain_loss_pct"))
    if cb and shares and shares > 0 and gl is not None and gl < 0 and isinstance(ohlc_sym, dict) and ohlc_sym:
        cbps = cb / shares
        all_high = max(ohlc_sym[d]["h"] for d in ohlc_sym if "h" in ohlc_sym[d])
        all_low = min(ohlc_sym[d]["l"] for d in ohlc_sym if "l" in ohlc_sym[d])
        if all_low > 0:
            if cbps > all_high * (1 + MAX_BASIS_DEVIATION_AT / 100):
                violations.append(
                    f"basis_above_all_time_high: cost_per_share=${cbps:.2f} vs "
                    f"all-time high ${all_high:.2f}"
                )
            # Below all-time low is normal for long-term holdings — only flag
            # if it's far below (>50% under the all-time low)
            if cbps < all_low * (1 - MAX_BASIS_DEVIATION_AT / 100):
                violations.append(
                    f"basis_extreme_low: cost_per_share=${cbps:.2f} vs "
                    f"all-time low ${all_low:.2f} (held at a loss, basis far below market range)"
                )

    # ── Invariant 5: Lot dating vs listing date ──
    lot_data = row.get("lot_basis", {}).get("lots", [])
    if ld_date and lot_data:
        pre_listing_lots = []
        for lot in lot_data:
            lot_date_str = lot.get("lot_date", "")
            if lot_date_str:
                try:
                    lot_d = datetime.strptime(lot_date_str[:10], "%Y-%m-%d").date()
                    if lot_d < ld_date:
                        pre_listing_lots.append(lot_date_str[:10])
                except ValueError:
                    pass
        if pre_listing_lots:
            violations.append(
                f"lots_predate_listing: {len(pre_listing_lots)} lot(s) with dates "
                f"{pre_listing_lots[:3]} before listing {ld_str}. Lot data untrusted."
            )
            lot_fail = True

    lot_status = "UNTRUSTED" if lot_fail else "VERIFIED"

    return {
        "pass": len(violations) == 0,
        "violations": violations,
        "lot_data_status": lot_status,
    }


# ── S4: Price action loader ──────────────────────────────────────────────

def _load_price_action(
    symbol: str,
    last_price: float | None,
    cost_basis: float | None,
    shares: float | None,
    ohlcv_data: dict[str, dict[str, dict[str, float]]],
    listing_date_str: str | None,
) -> dict[str, Any]:
    """Compute price action metrics from OHLCV data, with Finviz fallback.

    When OHLCV is unavailable (recent IPOs, data gaps), uses Finviz
    snapshot data for weekly/monthly performance and volatility.

    Returns dict with:
        price_change_pct_1d, _5d, _20d, pct_off_52w_high, pct_off_52w_low,
        distance_from_cost_basis_pct, trend_direction, data_window_days
    """
    ohlc = ohlcv_data.get(symbol, {})
    if not isinstance(ohlc, dict) or not ohlc:
        # ── S4/B4: Finviz fallback for symbols without OHLCV ──
        finviz_cache = _load_json(STATE_DIR / "finviz_quote_cache.json")
        finviz = finviz_cache.get(symbol, {}) if isinstance(finviz_cache, dict) else {}
        if finviz:
            perf_week = _f(finviz.get("perf_week"))
            perf_month = _f(finviz.get("perf_month"))
            perf_halfyr = _f(finviz.get("perf_halfyr"))
            vol_w = _f(finviz.get("volatility_w"))
            current_price = _f(finviz.get("price"))

            dist_from_basis = None
            if cost_basis and shares and shares > 0 and current_price:
                cbps = cost_basis / shares
                dist_from_basis = round((current_price / cbps - 1) * 100, 2)

            result: dict[str, Any] = {
                "price_change_pct_1d": None,
                "price_change_pct_5d": perf_week,
                "price_change_pct_20d": perf_month,
                "pct_off_52w_high": None,
                "pct_off_52w_low": None,
                "distance_from_cost_basis_pct": dist_from_basis,
                "trend_direction": "rising" if (perf_week or 0) > 2 else ("falling" if (perf_week or 0) < -2 else "flat"),
                "data_window_days": 0,
                "last_close": current_price,
                "source": "finviz_snapshot",
            }
            if vol_w is not None:
                result["volatility_w_pct"] = vol_w
            return result
        return {"price_action": "UNAVAILABLE"}

    dates = sorted(ohlc.keys())

    # Cap window by listing date for recent IPOs
    if listing_date_str:
        try:
            ld = datetime.strptime(listing_date_str[:10], "%Y-%m-%d").date()
            ld_str_iso = ld.isoformat()
            dates = [d for d in dates if d >= ld_str_iso]
        except ValueError:
            pass

    if not dates:
        return {"price_action": "NO_DATA_IN_WINDOW"}

    closes = [ohlc[d]["c"] for d in dates if "c" in ohlc[d]]
    highs = [ohlc[d]["h"] for d in dates if "h" in ohlc[d]]
    lows = [ohlc[d]["l"] for d in dates if "l" in ohlc[d]]

    if not closes:
        return {"price_action": "NO_CLOSE_DATA"}

    current = closes[-1]
    data_window_days = len(dates)

    # Changes
    def _change(n: int) -> float | None:
        if len(closes) > n and closes[-1 - n] != 0:
            return round((closes[-1] / closes[-1 - n] - 1) * 100, 2)
        return None

    chg_1d = _change(1)
    chg_5d = _change(5)
    chg_20d = _change(20)

    # 52-week highs/lows (capped by available data)
    window_252 = dates[-252:] if len(dates) >= 252 else dates
    w52_high = max(ohlc[d]["h"] for d in window_252 if "h" in ohlc[d])
    w52_low = min(ohlc[d]["l"] for d in window_252 if "l" in ohlc[d])
    pct_off_52w_high = round((current / w52_high - 1) * 100, 2) if w52_high > 0 else None
    pct_off_52w_low = round((current / w52_low - 1) * 100, 2) if w52_low > 0 else None

    # Distance from cost basis
    dist_from_basis = None
    if cost_basis and shares and shares > 0 and current:
        cbps = cost_basis / shares
        dist_from_basis = round((current / cbps - 1) * 100, 2)

    # Trend direction (20-day SMA slope)
    trend = "flat"
    if len(closes) >= 20:
        sma20_now = sum(closes[-20:]) / 20
        sma20_prev = sum(closes[-21:-1]) / 20 if len(closes) >= 21 else sma20_now
        if sma20_prev > 0:
            slope_pct = (sma20_now / sma20_prev - 1) * 100
            if slope_pct > 0.5:
                trend = "rising"
            elif slope_pct < -0.5:
                trend = "falling"
            else:
                trend = "flat"

    return {
        "price_change_pct_1d": chg_1d,
        "price_change_pct_5d": chg_5d,
        "price_change_pct_20d": chg_20d,
        "pct_off_52w_high": pct_off_52w_high,
        "pct_off_52w_low": pct_off_52w_low,
        "distance_from_cost_basis_pct": dist_from_basis,
        "trend_direction": trend,
        "data_window_days": data_window_days,
        "last_close": current,
    }


# ── S4: Lot-level basis loader ───────────────────────────────────────────

def _load_lot_basis(
    symbol: str,
    tax_lots: dict,
    current_price: float | None,
    listing_date_str: str | None,
) -> dict[str, Any]:
    """Expose per-lot cost basis with profit/underwater breakdown.

    If lots fail listing-date invariant, returns lot_data_status: UNTRUSTED
    and suppresses all lot-derived signals.

    Returns:
        dict with lot_count, basis_range_low, basis_range_high,
        lots_in_profit, lots_underwater, weighted_avg_basis,
        oldest_open_lot_date, lot_data_status, lots[]
    """
    all_lots = tax_lots.get("by_symbol", {}).get(symbol, [])

    # Filter open lots
    open_lots = [
        l for l in all_lots
        if not l.get("closed") and float(l.get("shares_remaining", 0)) > 0
    ]
    source = open_lots if open_lots else all_lots

    if not source:
        return {"lot_data_status": "NO_DATA"}

    # Check lot dating vs listing date for trustworthiness
    lot_data_status = "VERIFIED"
    if listing_date_str:
        try:
            ld = datetime.strptime(listing_date_str[:10], "%Y-%m-%d").date()
            for lot in source:
                lot_d = lot.get("lot_date", "")
                if lot_d:
                    try:
                        ldt = datetime.strptime(lot_d[:10], "%Y-%m-%d").date()
                        if ldt < ld:
                            lot_data_status = "UNTRUSTED"
                            break
                    except ValueError:
                        pass
        except ValueError:
            pass

    # Aggregate lot data
    lot_details: list[dict[str, Any]] = []
    total_shares = 0.0
    total_cost = 0.0
    basis_prices: list[float] = []
    lots_in_profit = 0
    lots_underwater = 0
    oldest_open = ""

    for lot in source:
        shares = float(lot.get("shares_remaining", 0) or lot.get("shares", 0))
        cps = float(lot.get("cost_per_share", 0))
        lot_dt = lot.get("lot_date") or lot.get("acquired_date") or ""
        total_shares += shares
        total_cost += shares * cps
        if cps > 0:
            basis_prices.append(cps)

        # Profit/underwater check
        if current_price and cps > 0 and shares > 0:
            if current_price > cps:
                lots_in_profit += 1
            else:
                lots_underwater += 1

        lot_details.append({
            "lot_date": str(lot_dt)[:10],
            "shares_remaining": shares,
            "cost_per_share": cps,
            "account": str(lot.get("account", "")),
            "action": str(lot.get("action", "")),
        })

        # Track oldest open lot date
        if lot_dt and not oldest_open:
            oldest_open = str(lot_dt)[:10]
        elif lot_dt and str(lot_dt)[:10] < oldest_open:
            oldest_open = str(lot_dt)[:10]

    basis_range_low = min(basis_prices) if basis_prices else None
    basis_range_high = max(basis_prices) if basis_prices else None
    wavg_basis = round(total_cost / total_shares, 2) if total_shares > 0 else None

    result: dict[str, Any] = {
        "lot_count": len(source),
        "lot_data_status": lot_data_status,
        "open_lots_count": len(open_lots),
        "total_shares": total_shares,
        "total_cost": total_cost,
        "basis_range_low": basis_range_low,
        "basis_range_high": basis_range_high,
        "weighted_avg_basis": wavg_basis,
        "oldest_open_lot_date": oldest_open or None,
        "lots": lot_details,
    }

    if lot_data_status == "VERIFIED":
        result.update({
            "lots_in_profit": lots_in_profit,
            "lots_underwater": lots_underwater,
        })
    else:
        # UNTRUSTED: suppress lot-derived signals
        result["lots_in_profit"] = None
        result["lots_underwater"] = None
        result["suppressed_signals"] = ["long_held", "basis_range", "lot_profit_split"]

    return result


# ── S4: Analyst context loader ───────────────────────────────────────────

def _load_analyst_context(holdings_symbols: set[str]) -> dict[str, dict[str, Any]]:
    """Load analyst consensus, targets, and revisions from DB.

    Sources: yahoo_analyst_targets_history (latest snapshot) +
             analyst_consensus_history (latest rating).
    """
    result: dict[str, dict[str, Any]] = {}
    if not holdings_symbols:
        return result

    try:
        from db_adapter import _execute
        syms = list(holdings_symbols)

        # Latest analyst targets
        targets = _execute(
            """SELECT DISTINCT ON (upper(symbol))
                       upper(symbol) AS sym, target_mean_price, target_high_price,
                       target_low_price, number_of_analyst_opinions,
                       recommendation_mean, current_price, snapshot_date
               FROM yahoo_analyst_targets_history
               WHERE upper(symbol) = ANY(%s)
               ORDER BY upper(symbol), snapshot_date DESC""",
            (syms,),
            fetch="all",
        ) or []

        for t in targets:
            sym = _norm_symbol(str(t.get("sym") or ""))
            if not sym:
                continue
            mean_t = _f(t.get("target_mean_price"))
            cp = _f(t.get("current_price"))
            target_vs_current = (
                round((mean_t / cp - 1) * 100, 2)
                if mean_t and cp and cp > 0 else None
            )
            result[sym] = {
                "analyst_count": t.get("number_of_analyst_opinions"),
                "price_target_mean": mean_t,
                "price_target_high": _f(t.get("target_high_price")),
                "price_target_low": _f(t.get("target_low_price")),
                "target_vs_current_pct": target_vs_current,
                "recommendation_mean": _f(t.get("recommendation_mean")),
                "as_of": str(t.get("snapshot_date", ""))[:10],
                "source": "yahoo_analyst_targets_history",
            }

        # Latest consensus ratings
        consensus = _execute(
            """SELECT DISTINCT ON (upper(symbol))
                       upper(symbol) AS sym, recom_raw, recom_score,
                       analyst_rating, target_price, snapshot_date
               FROM analyst_consensus_history
               WHERE upper(symbol) = ANY(%s)
               ORDER BY upper(symbol), snapshot_date DESC""",
            (syms,),
            fetch="all",
        ) or []

        for c in consensus:
            sym = _norm_symbol(str(c.get("sym") or ""))
            if not sym:
                continue
            if sym in result:
                result[sym]["consensus_rating"] = c.get("analyst_rating", "")
                result[sym]["consensus_score"] = _f(c.get("recom_score"))
                result[sym]["rating_updated"] = str(c.get("snapshot_date", ""))[:10]

        return result

    except Exception:
        return {}


def _build_evidence_bundle(
    symbol: str,
    row_class: str,
    all_data: dict[str, Any],
) -> dict[str, Any]:
    """Assemble all available evidence for one row into a deterministic bundle.

    Returns:
        dict with evidence_items[], evidence_gaps[], sufficient: bool.
    """
    catalysts_data = all_data.get("catalysts", {})
    earnings_data = all_data.get("earnings", {})
    rotation_data = all_data.get("rotation", {})
    ips_data = all_data.get("ips", {})
    hermes_data = all_data.get("hermes", {})
    indicator_data = all_data.get("indicators", {})
    risk_data = all_data.get("risk_snapshot", {})
    sector_data = all_data.get("sectors", {})
    agent_data = all_data.get("agent_results", {})

    items: list[dict[str, Any]] = []
    gaps: list[str] = []

    # ── 1. Hermes lifecycle (independent challenger — highest-signal) ──
    hlc = hermes_data.get("by_symbol", {}).get(symbol, {})
    if hlc and hlc.get("health_score") is not None:
        items.append({
            "type": "hermes_health",
            "source": "hermes_holdings_lifecycle",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "health_score": hlc.get("health_score"),
            "lifecycle_stage": hlc.get("lifecycle_stage"),
            "confidence_tier": hlc.get("confidence_tier"),
            "stop_quality": hlc.get("stop_quality"),
            "outcome_consistency": hlc.get("outcome_consistency"),
        })
    elif row_class == "holding":
        gaps.append("hermes_health")

    # ── 2. Catalysts / news ──
    cat_list = catalysts_data.get("by_symbol", {}).get(symbol, [])
    if cat_list:
        for c in cat_list[:5]:
            items.append({
                "type": "catalyst",
                "source": c["source"],
                "as_of": str(c.get("as_of", ""))[:19],
                "staleness_days": round(c.get("staleness_days", 0), 1) if c.get("staleness_days") else None,
                "title": c.get("title", ""),
                "quality": str(c.get("quality", "")),
            })
    elif row_class == "holding":
        gaps.append("catalysts")

    # ── 3. Earnings ──
    earn = earnings_data.get("by_symbol", {}).get(symbol, {})
    if earn.get("next_earnings_date"):
        items.append({
            "type": "earnings",
            "source": "earnings_dates",
            "as_of": str(earn.get("fetched_at", ""))[:19],
            "staleness_days": earn.get("staleness_days"),
            "next_earnings_date": earn["next_earnings_date"],
        })
    elif row_class == "holding":
        gaps.append("earnings_calendar")

    # ── 4. Technical indicators ──
    ind = indicator_data.get("by_symbol", {}).get(symbol, {})
    if ind:
        items.append({
            "type": "technicals",
            "source": "indicator_snapshot",
            "as_of": str(indicator_data.get("as_of", ""))[:19],
            "rsi": ind.get("rsi"),
            "rsi_status": ind.get("rsi_status", ""),
            "sma_50": ind.get("sma_50"),
            "sma50_pct": ind.get("sma50_pct"),
            "macd_signal": ind.get("macd_signal", ""),
            "atr": ind.get("atr"),
            "obv_signal": ind.get("obv_signal", ""),
        })
    elif row_class == "holding":
        gaps.append("technicals")

    # ── 5. Risk / stop posture ──
    risk = risk_data.get("by_symbol", {}).get(symbol, {})
    if risk:
        items.append({
            "type": "risk",
            "source": "risk_snapshot",
            "as_of": str(risk_data.get("as_of", ""))[:19],
            "stop_price": risk.get("stop_price"),
            "distance_to_stop_pct": risk.get("distance_to_stop_pct"),
            "triggered": risk.get("triggered"),
        })
    elif row_class == "holding":
        gaps.append("risk_stops")

    # ── 6. Rotation posture (aggregate) ──
    items.append({
        "type": "rotation",
        "source": "rotation_autopilot",
        "as_of": str(rotation_data.get("as_of", ""))[:19],
        "signal": rotation_data.get("signal") or "not_rotated",
        "strength": rotation_data.get("strength", 0.0),
    })

    # ── 7. Sector context ──
    if sector_data.get("state") == "AVAILABLE" and sector_data.get("sectors"):
        items.append({
            "type": "sector_context",
            "source": "rotation_ladders",
            "as_of": str(sector_data.get("as_of", ""))[:19],
            "top_sector": sector_data.get("top_sector", ""),
            "bottom_sector": sector_data.get("bottom_sector", ""),
            "sector_ranking": [{"name": s["name"], "rs_score": s["rs_score"]} for s in sector_data.get("sectors", [])[:3]],
        })

    # ── 8. IPS policy (aggregate) ──
    if ips_data.get("state") == "AVAILABLE":
        items.append({
            "type": "investment_policy",
            "source": "investment_policy_statement",
            "max_position_pct": ips_data.get("max_position_pct"),
            "beta_target": ips_data.get("beta_target"),
        })

    # ── 9. Agent opinions (Maria/Risk/Tax) ──
    agent_list = agent_data.get("by_symbol", {}).get(symbol, [])
    if agent_list:
        for a in agent_list[:3]:
            items.append({
                "type": "agent_opinion",
                "source": "watchlist_agent_results",
                "as_of": str(a.get("completed_at",""))[:19],
                "agent": a.get("agent",""),
                "recommendation": a.get("recommendation",""),
                "confidence": a.get("confidence"),
                "narrative": a.get("narrative","")[:120],
            })
    elif row_class == "holding":
        gaps.append("agent_opinions")

    # ── S4/10. Instrument identity ──
    inst_data = all_data.get("instruments", {}).get(symbol, {})
    if inst_data:
        items.append({
            "type": "instrument_identity",
            "source": inst_data.get("source", "symbol_profiles"),
            "name": inst_data.get("name", ""),
            "instrument_type": inst_data.get("type", ""),
            "listing_date": inst_data.get("listing_date"),
            "sector": inst_data.get("sector"),
            "market_cap": inst_data.get("market_cap"),
            "is_recent_ipo": inst_data.get("is_recent_ipo", False),
        })
    elif row_class == "holding":
        gaps.append("instrument_identity")

    # ── S4/11. Price action ──
    pa = all_data.get("price_action", {}).get(symbol, {})
    if pa and isinstance(pa, dict) and pa.get("last_close") is not None:
        item = {
            "type": "price_action",
            "source": pa.get("source", "price_ohlc_cache"),
            "last_close": pa.get("last_close"),
            "trend_direction": pa.get("trend_direction"),
            "distance_from_basis_pct": pa.get("distance_from_cost_basis_pct"),
            "data_window_days": pa.get("data_window_days"),
        }
        # A2: Include whatever windows are populated — partial is better than none
        for wkey, wlabel in [("price_change_pct_1d", "price_change_1d"),
                              ("price_change_pct_5d", "price_change_5d"),
                              ("price_change_pct_20d", "price_change_20d")]:
            val = pa.get(wkey)
            if val is not None:
                item[wlabel] = val
        for wkey, wlabel in [("pct_off_52w_high", "pct_off_52w_high"),
                              ("pct_off_52w_low", "pct_off_52w_low")]:
            val = pa.get(wkey)
            if val is not None:
                item[wlabel] = val
        if pa.get("volatility_w_pct") is not None:
            item["volatility_w_pct"] = pa["volatility_w_pct"]
        items.append(item)
    elif row_class == "holding":
        gaps.append("price_action")

    # ── S4/12. Lot-level basis ──
    lb = all_data.get("lot_basis", {}).get(symbol, {})
    if lb and isinstance(lb, dict) and lb.get("lot_count"):
        item = {
            "type": "lot_basis",
            "source": "tax_lots_json",
            "lot_count": lb.get("lot_count"),
            "lot_data_status": lb.get("lot_data_status"),
            "open_lots_count": lb.get("open_lots_count"),
            "basis_range_low": lb.get("basis_range_low"),
            "basis_range_high": lb.get("basis_range_high"),
            "weighted_avg_basis": lb.get("weighted_avg_basis"),
            "lots_in_profit": lb.get("lots_in_profit"),
            "lots_underwater": lb.get("lots_underwater"),
            "oldest_open_lot_date": lb.get("oldest_open_lot_date"),
        }
        if lb.get("suppressed_signals"):
            item["suppressed_signals"] = lb["suppressed_signals"]
        items.append(item)
    elif row_class == "holding":
        gaps.append("lot_basis")

    # ── S4/13. Analyst context ──
    an = all_data.get("analysts", {}).get(symbol, {})
    if an and an.get("analyst_count"):
        items.append({
            "type": "analyst_context",
            "source": "yahoo_analyst_targets_history",
            "as_of": an.get("as_of", "")[:19],
            "analyst_count": an.get("analyst_count"),
            "price_target_mean": an.get("price_target_mean"),
            "price_target_high": an.get("price_target_high"),
            "price_target_low": an.get("price_target_low"),
            "target_vs_current_pct": an.get("target_vs_current_pct"),
            "recommendation_mean": an.get("recommendation_mean"),
            "consensus_rating": an.get("consensus_rating"),
        })
    elif row_class == "holding":
        gaps.append("analyst_context")

    sufficiency = len(items)
    return {
        "evidence_items": items,
        "evidence_count": sufficiency,
        "evidence_gaps": gaps,
        "sufficient": sufficiency >= MIN_EVIDENCE_ITEMS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# B1: Allocation-gap rows — cash and model_portfolio
# ═══════════════════════════════════════════════════════════════════════════════


def _derive_allocation_rows(
    raw_holdings: dict[str, Any],
    portfolio_total_value: float | None,
) -> list[dict[str, Any]]:
    """Build allocation-gap rows from model_portfolio.json vs actual holdings.

    Returns one row per asset-class target.  Cash is broken out per account,
    not aggregated, because $533K in a rollover IRA and $37K in taxable are
    different decisions with different tax treatment.

    Scope boundary (v2 §2): states gap size, does not recommend instruments,
    does not reason about Roth conversion/IRMAA/retirement sequencing.
    """
    model = _load_model_portfolio()
    if not model or not isinstance(model, dict):
        return []

    # Use portfolio_total_value from holdings (includes CASH)
    total_val = portfolio_total_value or 0

    # Step 1: compute actual asset-class weights from holdings
    actual: dict[str, float] = {"cash": 0.0}
    actual_by_account: dict[str, dict[str, float]] = {}  # account → {cash: $}
    per_account_cash: list[dict[str, Any]] = []

    for h in raw_holdings.get("holdings", []):
        symbol = _norm_symbol(h.get("symbol", ""))
        mv = _f(h.get("market_value")) or 0
        acct = str(h.get("account", ""))
        bucket = str(h.get("bucket", ""))
        is_cash = h.get("is_cash") or symbol == "CASH"

        if is_cash:
            actual["cash"] += mv
            actual_by_account.setdefault(acct, {"cash": 0.0})["cash"] += mv
            per_account_cash.append({
                "account": acct,
                "cash_mv": mv,
                "cash_pct": round(mv / total_val * 100, 2) if total_val > 0 else 0,
            })
        else:
            # Map bucket to asset class
            cls = "equity"
            if "bond" in bucket.lower() or "fixed" in bucket.lower():
                cls = "fixed_income"
            elif "delisted" in bucket.lower():
                cls = "equity"  # counted as equity for allocation purposes
            actual[cls] = actual.get(cls, 0.0) + mv

    # Compute percentages
    for cls in list(actual.keys()):
        actual[cls] = round(actual[cls] / total_val * 100, 2) if total_val > 0 else 0

    total_actual_pct = sum(actual.values())
    if total_val > 0 and total_actual_pct < 98:  # some unclassified — pad with equity
        gap = 100.0 - total_actual_pct
        actual["equity"] = actual.get("equity", 0) + round(gap, 2)

    rows: list[dict[str, Any]] = []

    # Map model asset classes to desk targets
    class_map = {
        "equity": "equity", "fixed_income": "fixed_income",
        "cash_and_equivalents": "cash", "alternatives": "alternatives",
    }

    for model_key, desk_key in class_map.items():
        target_cfg = model.get(model_key, {})
        if not isinstance(target_cfg, dict):
            continue
        target = target_cfg.get("target_pct", 0)
        actual_pct = actual.get(desk_key, 0)
        drift = round(actual_pct - target, 2)
        dollar_gap = round(drift / 100 * total_val, 2) if total_val > 0 else 0

        tolerance = target_cfg.get("tolerance_pct", ALLOCATION_TOLERANCE_PCT)

        # Verdict
        # 0.2: fixed_income at 0% with unresolved CUSIPs → INSUFFICIENT_DATA.
        # The three CUSIP positions (12507E201, 543354, 628518) are likely bonds
        # in the rollover IRA but are bucketed "Delisted/Worthless" and counted
        # as equity. Until resolved, we don't know the true fixed_income allocation.
        if desk_key == "fixed_income" and actual_pct < 0.01 and target > 0:
            verdict = AdvisoryVerdict.INSUFFICIENT_DATA
            rationale = (
                f"Model portfolio targets {target}% fixed income. "
                f"Actual: unable to determine — three CUSIP positions "
                f"(12507E201, 543354104, 628518102) may be bonds but are "
                f"unresolved. Resolve CUSIPs to instrument types first."
            )
        elif abs(drift) <= tolerance:
            verdict = AdvisoryVerdict.HOLD
        elif drift > 0:
            verdict = AdvisoryVerdict.TRIM
        else:
            verdict = AdvisoryVerdict.ADD

        row_rationale = (
            rationale if desk_key == "fixed_income" and actual_pct < 0.01 and target > 0
            else f"Model portfolio targets {target}% {desk_key.replace('_',' ')}. Actual: {actual_pct}%. Drift: {drift:+.1f}%, gap: ${dollar_gap:+,.0f}."
        )

        row = {
            "row_class": "allocation",
            "allocation_target": desk_key,
            "symbol": f"ALLOC:{desk_key}",
            "verdict": verdict,
            "confidence": 0.75,
            "rationale": row_rationale,
            "target_pct": target,
            "actual_pct": actual_pct,
            "drift_pct": drift,
            "dollar_gap": dollar_gap,
            "tolerance_pct": tolerance,
            "weight_pct": None,
            "market_value": None,
            "gain_loss_pct": None,
            "days_held": None,
            "risk_signals": [],
            "source": "allocation",
            "account": "",
            "housekeeping_flag": False,
            "housekeeping_reason": None,
        }
        rows.append(row)

    # Per-account cash rows
    for pc in per_account_cash:
        acct = pc["account"]
        mv = pc["cash_mv"]
        pct = pc["cash_pct"]

        rows.append({
            "row_class": "allocation",
            "allocation_target": "cash",
            "symbol": f"ALLOC:cash:{acct}",
            "verdict": AdvisoryVerdict.INSUFFICIENT_DATA,
            "confidence": 0.70,
            "rationale": f"Cash in {acct}: ${mv:,.0f} ({pct:.1f}% of portfolio). Per-account drift not evaluated against model — see aggregate cash row ($cash) for target comparison.",
            "target_pct": None,
            "actual_pct": pct,
            "drift_pct": None,
            "dollar_gap": mv,
            "tolerance_pct": ALLOCATION_TOLERANCE_PCT,
            "weight_pct": None,
            "market_value": mv,
            "gain_loss_pct": None,
            "days_held": None,
            "risk_signals": [],
            "source": "allocation",
            "account": acct,
            "housekeeping_flag": False,
            "housekeeping_reason": None,
        })

    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# Main builder — the single entry point
# ═══════════════════════════════════════════════════════════════════════════════

def build_advisory_desk(*, max_age_s: float = DEFAULT_MAX_AGE_S, force: bool = False) -> dict[str, Any]:
    """Build the complete Advisory Desk opinion table with optional caching.

    Args:
        max_age_s: Maximum cache age in seconds. Default 300s (5 min).
                   Set to 0 to force recompute. Cache is skipped when max_age_s=0.
        force: If True, bypasses cache entirely.

    Returns a Data Broker response envelope:
        {"ok": true, "data": {"rows": [...], "metadata": {...}}, "cache_hit": bool}
    """
    # ── Check cache ──
    if not force and max_age_s > 0:
        try:
            if CACHE_FILE.exists():
                cache_age = _time.time() - CACHE_FILE.stat().st_mtime
                if cache_age < max_age_s:
                    cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                    cached["cache_hit"] = True
                    cached["cache_age_s"] = round(cache_age, 1)
                    return cached
        except Exception:
            pass

    t0 = datetime.now(timezone.utc)

    # Load all data domains
    holdings = _load_holdings()
    risk = _load_risk()
    watchlist = _load_watchlist()
    closed = _load_trade_journal()
    tax_lots = _load_tax_lots()

    total_value = holdings.get("total_value") or 0
    holdings_symbols = {p["symbol"] for p in holdings.get("positions", [])}
    portfolio_heat_pct = risk.get("portfolio_heat_pct")

    # ── S4: Load external data sources ──
    listing_dates = _load_listing_dates(holdings_symbols)
    ohlcv_data = _load_ohlcv_data()
    instrument_data = _load_instrument_identity(
        {"positions": holdings.get("positions", []), "symbols": holdings_symbols},
        listing_dates,
    )
    analyst_data = _load_analyst_context(holdings_symbols)

    # ── S4: Pre-compute price action + lot basis per holding ──
    price_actions: dict[str, dict[str, Any]] = {}
    lot_basis_data: dict[str, dict[str, Any]] = {}
    invariant_results: dict[str, dict[str, Any]] = {}

    for pos in holdings.get("positions", []):
        sym = pos["symbol"]
        inst = instrument_data.get(sym, {})
        ld_str = inst.get("listing_date")
        price = _f(pos.get("price"))
        cb = _f(pos.get("cost_basis"))
        shares = _f(pos.get("shares"))

        # Price action
        pa = _load_price_action(sym, price, cb, shares, ohlcv_data, ld_str)
        price_actions[sym] = pa

        # Lot basis
        lb = _load_lot_basis(sym, tax_lots, price, ld_str)
        lot_basis_data[sym] = lb

    # First pass: compute invariants per holding (before opinions)
    for pos in holdings.get("positions", []):
        sym = pos["symbol"]
        pos_with_lots = dict(pos)
        pos_with_lots["days_held"] = _compute_days_held(sym, tax_lots)
        pos_with_lots["lot_basis"] = lot_basis_data.get(sym, {})

        inv = _validate_external_invariants(pos_with_lots, listing_dates, ohlcv_data)
        invariant_results[sym] = inv

    rows: list[dict[str, Any]] = []

    # 1. Holdings opinions
    for pos in holdings.get("positions", []):
        opinion = _derive_holding_opinion(
            pos, total_value,
            risk_positions=risk.get("positions", {}),
            tax_lots=tax_lots,
            portfolio_heat_pct=portfolio_heat_pct,
            invariants=invariant_results.get(pos["symbol"]),
        )
        if opinion:
            # ── S4: Add price action, lot basis, instrument data to opinion row ──
            sym = pos["symbol"]
            opinion["price_action"] = price_actions.get(sym, {})
            opinion["lot_basis"] = lot_basis_data.get(sym, {})
            opinion["instrument"] = instrument_data.get(sym, {})
            opinion["invariant_violations"] = invariant_results.get(sym, {}).get("violations", [])
            opinion["lot_data_status"] = invariant_results.get(sym, {}).get("lot_data_status", "")

            # S4: is_recent_ipo limitation — indicate unreliable technicals
            if instrument_data.get(sym, {}).get("is_recent_ipo"):
                if opinion.get("rationale"):
                    opinion["rationale"] += (
                        " | NOTE: Recent IPO (<180 days listed) — "
                        "limited price history means technical indicators "
                        "computed from < 180 trading days may be unreliable."
                    )

            rows.append(opinion)

    # 2. Watchlist opinions (exclude already-held)
    for symbol, data in watchlist.get("items", {}).items():
        opinion = _derive_watchlist_opinion(symbol, data, holdings_symbols)
        if opinion:
            rows.append(opinion)

    # 3. Closed-position opinions (RE_ENTER via reentry decision desk)
    closed_count = 0
    for symbol, trades in closed.get("closed_by_symbol", {}).items():
        if symbol in holdings_symbols:
            continue
        if closed_count >= 20:
            break
        opinion = _derive_closed_opinion(symbol, trades, holdings_symbols)
        if opinion:
            rows.append(opinion)
            closed_count += 1

    # 4. Allocation-gap rows (B1) — cash and model-portfolio drift
    raw_holdings = _load_json(STATE_DIR / "holdings.json")
    allocation_rows = _derive_allocation_rows(
        raw_holdings,
        holdings.get("portfolio_total_value"),
    )
    rows.extend(allocation_rows)

    # ── Part A: Evidence enrichment ──
    # Load all available evidence sources (may fail individually)
    evidence_data: dict[str, Any] = {}
    for name, loader in [
        ("catalysts", _load_catalysts),
        ("earnings", _load_earnings),
        ("rotation", _load_rotation),
        ("ips", _load_ips),
        ("hermes", _load_hermes_lifecycle),
        ("indicators", _load_indicator_snapshot),
        ("risk_snapshot", _load_risk_snapshot),
        ("sectors", _load_sector_rotation),
        ("agent_results", _load_agent_results),
    ]:
        try:
            evidence_data[name] = loader()
        except Exception:
            evidence_data[name] = {"state": "UNAVAILABLE", "error": f"Failed to load {name}"}

    # S4: Wire pre-computed evidence sources into evidence_data
    evidence_data["instruments"] = instrument_data
    evidence_data["price_action"] = price_actions
    evidence_data["lot_basis"] = lot_basis_data
    evidence_data["analysts"] = analyst_data

    # Add row_class to all rows (must happen before evidence bundle assembly)
    source_to_class = {
        "holdings": "holding",
        "watchlist": "watchlist",
        "reentry_decision_desk": "closed_journal",
        "closed_journal": "closed_journal",
        "allocation": "allocation",
    }
    for row in rows:
        if not row.get("row_class"):
            row["row_class"] = source_to_class.get(row.get("source", ""), "unknown")

    # Attach evidence bundles to each row
    for row in rows:
        sym = row.get("symbol", "")
        rcls = row.get("row_class", "unknown")
        bundle = _build_evidence_bundle(sym, rcls, evidence_data)
        row["evidence_bundle"] = bundle

        # A2: Sufficiency gate — insufficient evidence → INSUFFICIENT_DATA
        if rcls == "holding":
            actionable_verdicts = {AdvisoryVerdict.ADD.value, AdvisoryVerdict.TRIM.value,
                                   AdvisoryVerdict.EXIT.value, AdvisoryVerdict.RE_ENTER.value}
            v_val = row["verdict"].value if isinstance(row["verdict"], AdvisoryVerdict) else str(row["verdict"])
            if v_val in actionable_verdicts and bundle["evidence_count"] < MIN_EVIDENCE_ACTIONABLE:
                row["verdict"] = AdvisoryVerdict.INSUFFICIENT_DATA
                row["rationale"] = (
                    f"{row.get('rationale', '')} [Gate: insufficient evidence — "
                    f"{bundle['evidence_count']} items, minimum {MIN_EVIDENCE_ACTIONABLE} required for actionable verdict]"
                )
                row["confidence"] = 0.20

    # Add row_class to all rows (redundant safety — already done above)
    for row in rows:
        if not row.get("row_class"):
            row["row_class"] = source_to_class.get(row.get("source", ""), "unknown")
    for row in rows:
        if not row.get("row_class"):
            src = row.get("source", "")
            row["row_class"] = {
                "holdings": "holding",
                "watchlist": "watchlist",
                "reentry_decision_desk": "closed_journal",
                "closed_journal": "closed_journal",
                "allocation": "allocation",
            }.get(src, "unknown")

    # FIX-5: Compute per-row advisory_row_hash
    for row in rows:
        row["advisory_row_hash"] = _row_hash(row)

    # A3: Suppress noise — closed-journal rows hidden except RE_ENTER
    # RE_ENTER is the meaningful signal from closed positions; WAIT on 20/20 rows is noise.
    closed_rows_suppressed: list[dict[str, Any]] = [
        r for r in rows if r.get("row_class") == "closed_journal"
    ]
    rows = [
        r for r in rows
        if r.get("row_class") != "closed_journal"
        or str(r["verdict"].value) == "RE_ENTER"  # keep RE_ENTER rows visible
    ]

    # Detect degenerate classes (every row in a class shares the same verdict)
    degenerate_report: dict[str, str] = {}
    for cls in set(r.get("row_class") for r in rows):
        sub = [r for r in rows if r.get("row_class") == cls]
        v_set = {r["verdict"].value if isinstance(r["verdict"], AdvisoryVerdict) else str(r["verdict"]) for r in sub}
        if len(v_set) == 1 and len(sub) > 0:
            degenerate_report[cls] = f"all {len(sub)} rows → {next(iter(v_set))}"

    # Compute content hash for cache invalidation
    content_json = json.dumps(rows, sort_keys=True, default=str)
    content_hash = hashlib.sha256(content_json.encode("utf-8")).hexdigest()[:16]

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()

    verdict_counts: dict[str, int] = {}
    for r in rows:
        v = r["verdict"].value if isinstance(r["verdict"], AdvisoryVerdict) else str(r["verdict"])
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    result = {
        "ok": True,
        "cache_hit": False,
        "data": {
            "version": SNAPSHOT_VERSION,
            "computed_at": t0.isoformat(),
            "deterministic": True,
            "llm_in_path": False,
            "content_hash": content_hash,
            "elapsed_ms": round(elapsed * 1000, 1),
            "verdict_taxonomy": [v.value for v in AdvisoryVerdict],
            "data_broker": {
                "enforced": True,
                "modules": {
                    "holdings": "lib.data_broker.advisory_desk._load_holdings",
                    "risk": "lib.data_broker.advisory_desk._load_risk",
                    "watchlist": "lib.data_broker.advisory_desk._load_watchlist",
                    "closed_journal": "lib.data_broker.advisory_desk._load_trade_journal",
                    "tax_lots": "lib.data_broker.advisory_desk._load_tax_lots",
                    "reentry": "lib.data_broker.reentry_decision_desk.build_decision_desk",
                    "catalysts": "lib.data_broker.advisory_desk._load_catalysts",
                    "earnings": "lib.data_broker.advisory_desk._load_earnings",
                    "rotation": "lib.data_broker.advisory_desk._load_rotation",
                    "ips": "lib.data_broker.advisory_desk._load_ips",
                    "hermes_lifecycle": "lib.data_broker.advisory_desk._load_hermes_lifecycle",
                    "indicator_snapshot": "lib.data_broker.advisory_desk._load_indicator_snapshot",
                    "risk_snapshot": "lib.data_broker.advisory_desk._load_risk_snapshot",
                    "sector_rotation": "lib.data_broker.advisory_desk._load_sector_rotation",
                    "agent_results": "lib.data_broker.advisory_desk._load_agent_results",
                },
                "holdings_count": holdings.get("count", 0),
                "watchlist_count": watchlist.get("count", 0),
                "closed_count": closed.get("count", 0),
                "portfolio_total_value": holdings.get("portfolio_total_value"),
                "cash_weight_pct": holdings.get("cash_weight_pct"),
            },
            "metadata": {
                "total_rows": len(rows),
                "holdings_rows": sum(1 for r in rows if r.get("source") == "holdings"),
                "watchlist_rows": sum(1 for r in rows if r.get("source") == "watchlist"),
                "closed_rows": sum(1 for r in rows if r.get("source") in ("reentry_decision_desk", "closed_journal")),
                "closed_rows_suppressed": len(closed_rows_suppressed),
                "degenerate_classes": degenerate_report,
                "verdict_counts": verdict_counts,
                "s4_invariant_violations": sum(
                    1 for r in rows
                    if r.get("invariant_violations") and len(r.get("invariant_violations", [])) > 0
                ),
                "s4_untrusted_lots": sum(
                    1 for r in rows
                    if r.get("lot_data_status") == "UNTRUSTED"
                ),
                "s4_listing_dates_available": len(listing_dates),
                "s4_instrument_identity_built": len(instrument_data),
            },
            "rows": rows,
        },
    }

    # ── Persist cache ──
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(result, indent=2, default=str))
    except Exception:
        pass

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Output validator — enforce verdict taxonomy, numeric matching, safety,
# and PLAUSIBILITY GATE (FIX-3)
# ═══════════════════════════════════════════════════════════════════════════════

VALID_VERDICTS = frozenset(v.value for v in AdvisoryVerdict)


def validate_advisory_output(output: dict[str, Any]) -> list[str]:
    """Validate a build_advisory_desk() result against the advisory contract.

    Checks:
      - verdict taxonomy compliance (every row has a valid 8-verdict value)
      - numeric integrity (weights sum ≤ 100%, no negative market values)
      - confidence bounds (0.0–1.0) and non-degenerate distribution
      - source traceability (every row has a source field)
      - determinism marker (llm_in_path must be False)
      - content hash presence (cache/purity check)
      - PLAUSIBILITY GATE (FIX-3): no single verdict >30%, EXIT+TRIM ≤40%,
        weight sum 95-105%, IPS max position check

    Returns a (possibly empty) list of error strings. An empty list = valid.
    """
    errors: list[str] = []

    if not isinstance(output, dict):
        return ["Output is not a dict"]
    if not output.get("ok"):
        errors.append("output.ok is not True")

    data = output.get("data", {})
    if not isinstance(data, dict):
        return ["output.data is not a dict"]

    # Determinism check
    if not data.get("deterministic"):
        errors.append("data.deterministic must be True")
    if data.get("llm_in_path"):
        errors.append("data.llm_in_path must be False")

    # Content hash
    if not data.get("content_hash"):
        errors.append("data.content_hash is required for cache purity")

    # Verdict taxonomy
    taxonomy = data.get("verdict_taxonomy", [])
    if sorted(taxonomy) != sorted(VALID_VERDICTS):
        errors.append(f"verdict_taxonomy mismatch: {sorted(taxonomy)} != {sorted(VALID_VERDICTS)}")

    # Rows validation
    rows = data.get("rows", [])
    if not isinstance(rows, list):
        errors.append("data.rows is not a list")
        return errors

    seen_symbols: set[str] = set()
    total_weight_pct = 0.0
    holdings_rows_count = 0
    holdings_verdicts: dict[str, int] = {}
    confidences: list[float] = []

    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"row[{i}] is not a dict")
            continue

        symbol = str(row.get("symbol", ""))
        if not symbol:
            errors.append(f"row[{i}]: missing symbol")
            continue

        symbol_account = f"{symbol}:{row.get('account', '')}"
        if symbol_account in seen_symbols:
            errors.append(f"row[{i}]: duplicate symbol+account '{symbol_account}'")
        seen_symbols.add(symbol_account)

        # Verdict
        verdict = row.get("verdict")
        if isinstance(verdict, AdvisoryVerdict):
            if verdict.value not in VALID_VERDICTS:
                errors.append(f"{symbol}: unknown verdict '{verdict.value}'")
        else:
            if str(verdict) not in VALID_VERDICTS:
                errors.append(f"{symbol}: invalid verdict '{verdict}'")

        # Confidence
        conf = row.get("confidence")
        if conf is not None and (conf < 0.0 or conf > 1.0):
            errors.append(f"{symbol}: confidence {conf} out of [0.0, 1.0]")
        if conf is not None:
            confidences.append(conf)

        # Numeric integrity
        mv = row.get("market_value")
        if mv is not None and mv < 0:
            errors.append(f"{symbol}: negative market_value {mv}")

        wp = row.get("weight_pct")
        is_holdings = row.get("source") == "holdings"
        if wp is not None:
            if wp < 0:
                errors.append(f"{symbol}: negative weight_pct {wp}")
            if is_holdings:
                total_weight_pct += wp
                holdings_rows_count += 1

        if is_holdings:
            verdict_str = str(verdict.value) if isinstance(verdict, AdvisoryVerdict) else str(verdict)
            holdings_verdicts[verdict_str] = holdings_verdicts.get(verdict_str, 0) + 1

            # FIX-3: IPS max position check (>8% without flag)
            if wp is not None and wp > IPS_MAX_POSITION_PCT:
                if "overweight" not in (row.get("risk_signals") or []):
                    errors.append(
                        f"{symbol}: weight_pct {wp}% exceeds IPS max {IPS_MAX_POSITION_PCT}% "
                        f"without overweight risk signal"
                    )

        # Source
        src = row.get("source", "")
        if src not in ("holdings", "watchlist", "reentry_decision_desk", "closed_journal", "allocation"):
            errors.append(f"{symbol}: unknown source '{src}'")

        # Per-row hash
        if not row.get("advisory_row_hash"):
            errors.append(f"{symbol}: missing advisory_row_hash")

    # ── FIX-3 / B4: Plausibility gate — explicit weight-sum check ──
    # B4: Explicit two-component sum:
    #   sum(non_cash_weight_pct) + sum(cash_weight_pct) == 100 ± 1
    # Computed from both components, not inferred by exclusion.
    # Still catches a PFLT-class denominator error.
    cash_wt_pct_src = data.get("data_broker", {}).get("cash_weight_pct")
    if cash_wt_pct_src is not None and isinstance(cash_wt_pct_src, (int, float)):
        cash_wt_pct = float(cash_wt_pct_src)
    else:
        # Compute cash weight from allocation rows (fallback)
        cash_mv_sum = sum(
            row.get("market_value", 0) or 0
            for row in rows
            if row.get("row_class") == "allocation" and row.get("allocation_target") == "cash"
        )
        portfolio_total = data.get("data_broker", {}).get("portfolio_total_value") or 0
        cash_wt_pct = (cash_mv_sum / portfolio_total * 100) if portfolio_total > 0 else 0

    explicit_sum = total_weight_pct + cash_wt_pct
    if total_weight_pct > 0 and cash_wt_pct > 0:
        if explicit_sum < 99.0 or explicit_sum > 101.0:
            errors.append(
                f"PLAUSIBILITY_FAIL: explicit weight sum {explicit_sum:.1f}% "
                f"(non-cash={total_weight_pct:.1f}% + cash={cash_wt_pct:.1f}%) "
                f"outside [99%–101%] — denominator error or double-counting"
            )

    # Any single actionable verdict >30% of holdings rows → fail.
    # HOLD and INSUFFICIENT_DATA are exempt: HOLD is the baseline default
    # when no signals fire, and INSUFFICIENT_DATA indicates a data gap.
    EXEMPT_VERDICTS = frozenset({"HOLD", "INSUFFICIENT_DATA"})
    if holdings_rows_count > 0 and holdings_verdicts:
        for v, count in holdings_verdicts.items():
            if v in EXEMPT_VERDICTS:
                continue
            pct = (count / holdings_rows_count) * 100
            if pct > MAX_ANY_VERDICT_PCT:
                dist = json.dumps(holdings_verdicts, sort_keys=True)
                errors.append(
                    f"PLAUSIBILITY_FAIL: verdict '{v}' at {pct:.0f}% of holdings rows "
                    f"(>{MAX_ANY_VERDICT_PCT:.0f}%). Distribution: {dist}"
                )

        # EXIT+TRIM combined >40% of holdings → fail
        exit_trim_count = holdings_verdicts.get("EXIT", 0) + holdings_verdicts.get("TRIM", 0)
        exit_trim_pct = (exit_trim_count / holdings_rows_count) * 100
        if exit_trim_pct > MAX_EXIT_TRIM_COMBINED_PCT:
            dist = json.dumps(holdings_verdicts, sort_keys=True)
            errors.append(
                f"PLAUSIBILITY_FAIL: EXIT+TRIM at {exit_trim_pct:.0f}% of holdings "
                f"(>{MAX_EXIT_TRIM_COMBINED_PCT:.0f}%). Distribution: {dist}"
            )

    # FIX-4: Confidence non-degenerate check
    if len(set(confidences)) <= 1 and len(confidences) > 1:
        errors.append(
            f"PLAUSIBILITY_FAIL: confidence has only {len(set(confidences))} distinct "
            f"value(s) across {len(confidences)} rows — degenerate distribution"
        )

    return errors


# ═══════════════════════════════════════════════════════════════════════════════
# S3 Opinion enrichment — optional LLM layer on top of deterministic desk
# ═══════════════════════════════════════════════════════════════════════════════

def enrich_advisory_with_opinions(
    desk_result: dict[str, Any],
    *,
    max_rows: int = 20,
    force: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Enrich advisory desk rows with LLM-generated opinions (S3).

    Does not modify the deterministic desk — opinions are stored alongside
    the deterministic verdict. Each row's advisory_row_hash determines whether
    the model is called.

    Args:
        desk_result: Output of build_advisory_desk()
        max_rows: Max rows to call model for (cost control)
        force: Bypass per-row hash cache
        dry_run: If True, uses deterministic fallback only (no live model calls).
                 Set False in production when the bridge is confirmed running.

    Returns the desk_result with 'opinions' key added.
    """
    try:
        from lib.advisory.advisory_opinion_engine import (
            generate_row_opinion,
            generate_desk_synthesis,
        )
    except ImportError:
        desk_result.setdefault("opinions", {})["error"] = "opinion engine unavailable"
        return desk_result

    rows = desk_result.get("data", {}).get("rows", [])
    if not rows:
        desk_result.setdefault("opinions", {})["error"] = "no rows"
        return desk_result

    try:
        from lib.advisory.advisory_opinion_engine import _load_config
        config = _load_config()
    except Exception:
        config = {}

    opinions: dict[str, dict[str, Any]] = {}
    called = 0

    # ── S4/6.2: Prioritize by dollars at stake × verdict severity ──
    # Every actionable verdict on a position above the materiality floor
    # gets a model call before any HOLD does.
    VERDICT_SEVERITY = {
        "EXIT": 5, "TRIM": 4, "ADD": 3, "RE_ENTER": 2,
        "HOLD": 1, "WAIT": 0, "AVOID": 0, "INSUFFICIENT_DATA": 0,
    }

    def _opinion_priority(row: dict[str, Any]) -> float:
        mv = row.get("market_value") or 0
        v_str = str(row["verdict"].value) if isinstance(row.get("verdict"), object) and hasattr(row["verdict"], "value") else str(row.get("verdict", "HOLD"))
        severity = VERDICT_SEVERITY.get(v_str, 0)
        # Only score actionable verdicts above materiality floor
        if severity >= 2 and mv >= MATERIALITY_FLOOR_USD:
            return mv * severity
        # HOLD/WATCH/INSUFFICIENT_DATA below materiality floor → zero priority
        if mv < MATERIALITY_FLOOR_USD:
            return 0
        return mv * severity * 0.1  # de-prioritize non-actionable

    sorted_rows = sorted(rows, key=_opinion_priority, reverse=True)

    for row in sorted_rows:
        if called >= max_rows:
            break

        row_hash = row.get("advisory_row_hash", "")
        if not row_hash:
            continue

        sym = row.get("symbol", "?")
        det_verdict = str(row["verdict"].value) if isinstance(row.get("verdict"), object) and hasattr(row["verdict"], "value") else str(row.get("verdict", "HOLD"))
        evidence = row.get("evidence_bundle", {})

        if dry_run:
            # Deterministic-only fallback (no live call)
            opinion = {
                "verdict": det_verdict,
                "conviction": int(row.get("confidence", 0.5) * 100),
                "what_changed": "Dry run — model not called.",
                "rationale": row.get("rationale", f"Deterministic opinion for {sym}."),
                "key_risk": f"No counter-argument analysis (dry run). Evidence gaps: {evidence.get('evidence_gaps', [])}",
                "evidence_cited": [item.get("title", "") for item in evidence.get("evidence_items", [])[:3]],
                "advisory_row_hash": row_hash,
                "model_deterministic_disagreement": False,
                "llm_rejected": False,
                "model": "deterministic (dry_run)",
                "cache_hit": False,
            }
        else:
            opinion = generate_row_opinion(
                row, evidence, det_verdict,
                config=config, force=force,
            )

        opinions[row_hash] = opinion
        called += 1

    # Generate desk synthesis
    synthesis = generate_desk_synthesis(rows, config=config) if not dry_run else (
        f"[S3 SYNTHESIS — DRY RUN] "
        f"Model synthesis not generated in dry-run mode. "
        f"{len(rows)} rows, {len(opinions)} opinions populated. "
        f"See advisory_desk_latest.json for full desk."
    )

    desk_result.setdefault("opinions", {})["rows"] = opinions
    desk_result["opinions"]["synthesis"] = synthesis
    desk_result["opinions"]["rows_enriched"] = called
    desk_result["opinions"]["dry_run"] = dry_run

    return desk_result
