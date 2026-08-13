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
CIO_DIR = PROJECT_ROOT / "data" / "cio"
CACHE_DIR = PROJECT_ROOT / "data" / "runtime"
CACHE_FILE = CACHE_DIR / "advisory_desk_latest.json"
OPINIONS_LATEST_FILE = CACHE_DIR / "advisory_opinions_latest.json"
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
            "cost_basis_source": str(h.get("cost_basis_source", "")),
            "basis_partial": bool(h.get("basis_partial")),
            "cost_basis_note": str(h.get("cost_basis_note", "")),
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
#
# CONVICTION RULE (Phase 1.7 — documented contract):
#   Deterministic confidence and model conviction measure *thesis confidence*
#   (evidence quality / signal strength), NOT position size or account.
#   Same instrument in two accounts may differ if gain_loss_pct / entry basis
#   differ (loss magnitude is thesis-relevant). Market value and weight_pct
#   must not enter this function.
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

    Does NOT take market_value or weight_pct — conviction ≠ size.
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
    """Compute an advisory opinion for a watchlist instrument (not held).

    A watchlist entry is an *intent*, not a position: it has no lots, no cost
    basis, and usually no live price/analyst coverage. The desk must NOT turn
    the operator's ``target_intent`` label into a directional ADD/AVOID verdict
    with a confidence number — that would masquerade human intent as
    evidence-backed analysis (the "deep hallucination" failure mode). The
    honest deterministic verdict is WAIT (on watch, awaiting an entry signal),
    or INSUFFICIENT_DATA when there is neither intent nor thesis to evaluate.
    Intent/thesis are surfaced as rationale signals, not as a verdict.
    """
    if symbol in holdings_symbols:
        return None

    thesis = (data.get("thesis") or "").strip()
    target = (data.get("target_intent") or "").strip().upper()
    watching_since = data.get("watching_since")

    reasons: list[str] = []

    if target:
        reasons.append(f"Operator watch intent: {target.replace('_', ' ').lower()}")
    if thesis:
        reasons.append(f"Thesis: {thesis[:120]}")

    if not target and not thesis:
        verdict = AdvisoryVerdict.INSUFFICIENT_DATA
        confidence = 0.20
        reasons.append("No target intent and no thesis — insufficient data for an opinion")
    else:
        verdict = AdvisoryVerdict.WAIT
        # Deliberately low confidence: a watchlist entry is an intent, not an
        # evidence-backed trade signal. Capped well below holding confidence so
        # the two are never visually conflated in the operator surface.
        confidence = 0.25
        if thesis:
            confidence += 0.05
        if target == "GROWTH_SPECULATIVE":
            reasons.append("Speculative growth — treat with caution, no structural thesis edge")
        reasons.append("On watchlist — awaiting entry signal; no active position")

    return {
        "symbol": symbol,
        "verdict": verdict,
        "confidence": min(0.35, confidence),
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


# FIX-5 / Phase 2B: per-row advisory hash over *material* fields only.
# Bucketing prevents $0.01 price ticks from busting the opinion cache.
_HASH_WEIGHT_BUCKET_PP = 0.1     # weight to 0.1 percentage points
_HASH_PNL_BUCKET_PP = 0.5        # P&L % to 0.5pp
_HASH_MV_BUCKET_PCT = 0.5        # market value to 0.5% relative buckets
_HASH_CONF_BUCKET = 0.05         # confidence to 0.05


def _bucket_float(val: float | None, step: float) -> float | None:
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if step <= 0:
        return v
    return round(round(v / step) * step, 6)


def _bucket_mv(mv: float | None, pct_step: float = _HASH_MV_BUCKET_PCT) -> float | None:
    """Bucket market value by relative percent so $0.01 ticks do not change the key.

    Uses geometric buckets of size (1 + pct_step/100) so the step is scale-free.
    """
    import math

    if mv is None:
        return None
    try:
        v = float(mv)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return 0.0
    r = 1.0 + max(pct_step, 0.01) / 100.0
    n = round(math.log(v) / math.log(r))
    return round(r ** n, 2)


def _row_hash(row: dict[str, Any]) -> str:
    """Compute a deterministic hash for one advisory row.

    Material fields only — buckets weight / P&L / MV / confidence so noise
    does not invalidate the local opinion cache (Phase 2B cost model).
    """
    verdict = row.get("verdict")
    if hasattr(verdict, "value"):
        verdict = verdict.value
    material = {
        "symbol": row.get("symbol"),
        "verdict": str(verdict) if verdict is not None else None,
        "confidence": _bucket_float(row.get("confidence"), _HASH_CONF_BUCKET),
        "weight_pct": _bucket_float(row.get("weight_pct"), _HASH_WEIGHT_BUCKET_PP),
        "market_value": _bucket_mv(row.get("market_value")),
        "gain_loss_pct": _bucket_float(row.get("gain_loss_pct"), _HASH_PNL_BUCKET_PP),
        "days_held": int(row["days_held"]) if row.get("days_held") is not None else None,
        "account": row.get("account"),
        "source": row.get("source"),
        "risk_signals": sorted(row.get("risk_signals") or []) if isinstance(row.get("risk_signals"), list) else row.get("risk_signals"),
        "housekeeping_flag": bool(row.get("housekeeping_flag")),
        "row_class": row.get("row_class"),
        "lot_data_status": row.get("lot_data_status") or "",
    }
    payload = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════════════════════
# B1 + Part A: Evidence loading functions
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG_DIR = PROJECT_ROOT / "config"


def _load_model_portfolio() -> dict[str, Any]:
    raw = _load_json(CONFIG_DIR / "model_portfolio.json")
    return raw.get("strategic_allocation", {}) if raw.get("strategic_allocation") else raw


def _latest_catalyst_cache_path() -> Path | None:
    """Resolve newest data/catalyst_cache_YYYY-MM-DD.json (never hardcode a date)."""
    data_dir = PROJECT_ROOT / "data"
    candidates = sorted(data_dir.glob("catalyst_cache_*.json"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def _load_catalysts() -> dict[str, Any]:
    """Load catalyst/news evidence from portfolio_news and latest catalyst_cache."""
    news = _load_json(STATE_DIR / "portfolio_news.json")
    cache_path = _latest_catalyst_cache_path()
    cache = _load_json(cache_path) if cache_path else {}
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

    # From catalyst_cache (date-agnostic latest file)
    if isinstance(cache, dict):
        for sym, data in cache.items():
            if not isinstance(data, dict):
                continue
            enrichment = data.get("enrichment", {})
            if not isinstance(enrichment, dict):
                enrichment = {}
            cat_list = enrichment.get("catalysts", [])
            if cat_list:
                sym_u = _norm_symbol(sym)
                for c in cat_list[:5]:
                    if not isinstance(c, dict):
                        continue
                    catalysts.setdefault(sym_u, []).append({
                        "source": "catalyst_cache",
                        "cache_file": cache_path.name if cache_path else "",
                        "as_of": data.get("_cached_at", ""),
                        "title": str(c.get("headline", c.get("title", "")))[:200],
                        "type": str(c.get("catalyst_type", "")),
                        "tier": str(enrichment.get("catalyst_tier", "")),
                        "staleness_days": _age_hours(data.get("_cached_at")) / 24 if data.get("_cached_at") else None,
                    })

    return {
        "state": "AVAILABLE" if catalysts else "EMPTY",
        "by_symbol": catalysts,
        "count": len(catalysts),
        "cache_path": str(cache_path) if cache_path else None,
    }


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
    """Load per-symbol agent opinions from watchlist_agent_results via DB.

    Deduplicated to one row per (symbol, agent) — the table accumulates
    near-identical re-runs (same agent, same recommendation, new completed_at),
    which previously surfaced as triplicated "agent_opinion · maria — HOLD"
    evidence lines. Keep only the latest completed_at per agent.
    """
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    try:
        from db_adapter import _execute
        rows = _execute(
            """SELECT DISTINCT ON (upper(symbol), agent)
                      upper(symbol) AS symbol, agent, recommendation, confidence,
                      full_narrative, completed_at
               FROM watchlist_agent_results
               WHERE completed_at > now() - make_interval(days => 14)
               ORDER BY upper(symbol), agent, completed_at DESC""",
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


def _load_external_research() -> dict[str, Any]:
    """Load latest governed DeepSeek external-research opinion per symbol from
    hermes_external_research via DB.

    2026-08-13: the external research lane migrated from free ChatGPT OAuth to
    governed DeepSeek (lane='deepseek'). This surfaces that per-symbol challenge
    as advisory `external_research` evidence — replacing the hourly raw Telegram
    "research update" spam with a desk-side evidence line the Flash/Pro opinions
    and the CIO synthesis can actually reason over.
    """
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    try:
        from db_adapter import _execute
        rows = _execute(
            """SELECT DISTINCT ON (upper(symbol))
                      upper(symbol) AS symbol, recommendation, confidence,
                      model, created_at
               FROM hermes_external_research
               WHERE lane = 'deepseek'
                 AND recommendation IS NOT NULL
                 AND recommendation NOT LIKE '[%%'
                 AND created_at > now() - make_interval(days => 14)
               ORDER BY upper(symbol), created_at DESC""",
            fetch="all",
        ) or []
        for row in rows:
            sym = _norm_symbol(str(row.get("symbol") or ""))
            if sym:
                by_symbol.setdefault(sym, []).append({
                    "recommendation": str(row.get("recommendation") or "")[:240],
                    "confidence": _f(row.get("confidence")),
                    "model": row.get("model", ""),
                    "created_at": str(row.get("created_at", "")),
                })
        return {"state": "AVAILABLE", "by_symbol": by_symbol, "count": len(by_symbol)}
    except Exception:
        return {"state": "UNAVAILABLE", "by_symbol": {}, "count": 0}


def _load_ingestion_health() -> dict[str, Any]:
    """Load topic ingestion/curation health from the desk-side projections.

    2026-08-13: topic_ingestion.py and topic_curator.py stopped texting per-run
    counts to Telegram and now write `data/runtime/topic_ingestion_latest.json`
    and `topic_curator_latest.json`. This surfaces that health as a
    portfolio-level `ingestion_health` evidence item so the desk still sees the
    freshness of the research pipeline that was previously only visible as spam.
    """
    runtime = PROJECT_ROOT / "data" / "runtime"
    ingestion = _load_json(runtime / "topic_ingestion_latest.json") or {}
    curation = _load_json(runtime / "topic_curator_latest.json") or {}

    has_ingestion = bool(ingestion.get("generated_at"))
    has_curation = bool(curation.get("generated_at"))
    if not has_ingestion and not has_curation:
        return {"state": "UNAVAILABLE"}

    return {
        "state": "AVAILABLE",
        "ingestion": ({
            "as_of": str(ingestion.get("generated_at", ""))[:19],
            "articles": ingestion.get("articles"),
            "transcripts": ingestion.get("transcripts"),
            "topics_processed": ingestion.get("topics_processed"),
            "topics_skipped": ingestion.get("topics_skipped"),
        } if has_ingestion else None),
        "curation": ({
            "as_of": str(curation.get("generated_at", ""))[:19],
            "rated": curation.get("rated"),
            "approved": curation.get("approved"),
            "blocked": curation.get("blocked"),
            "entity_links": curation.get("entity_links"),
            "agent_events": curation.get("agent_events"),
        } if has_curation else None),
    }


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

    # Iterate the *research* symbol set — held positions plus watchlist/closed
    # symbols. A watchlist ticker (e.g. MSFT, NVDA) deserves the same instrument
    # identity evidence as a holding; limiting this to positions left every
    # watchlist expand card showing "No instrument identity".
    positions = holdings.get("positions", [])
    pos_by_symbol: dict[str, dict[str, Any]] = {
        _norm_symbol(p.get("symbol", "")): p for p in positions if p.get("symbol")
    }
    symbols: set[str] = set(holdings.get("symbols") or set())
    for p in positions:
        symbols.add(_norm_symbol(p.get("symbol", "")))
    symbols.discard("")

    for sym in sorted(symbols):
        pos = pos_by_symbol.get(sym, {})
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

        # Market cap from Finviz. Despite the "_b" suffix, the field is stored
        # in MILLIONS of dollars (GD = 104,926.14 → $104.9B), not billions.
        # Multiplying by 1e9 inflated every market cap 1000×.
        mcap_m = _f(finv.get("market_cap_b"))
        mcap = mcap_m * 1_000_000 if mcap_m else None

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
            chg_1d = _f(finviz.get("change_pct"))

            # 52-week distance lives in the enrichment cache (week52_high_pct is
            # the % below the 52w high, e.g. -3.12; week52_low_pct is the % above
            # the 52w low). Semantics match the OHLCV-derived values.
            enrich_cache = _load_json(STATE_DIR / "ticker_enrichment_cache.json")
            enrich = enrich_cache.get(symbol, {}) if isinstance(enrich_cache, dict) else {}
            off_high = _f(enrich.get("week52_high_pct"))
            off_low = _f(enrich.get("week52_low_pct"))

            dist_from_basis = None
            if cost_basis and shares and shares > 0 and current_price:
                cbps = cost_basis / shares
                dist_from_basis = round((current_price / cbps - 1) * 100, 2)

            result: dict[str, Any] = {
                "price_change_pct_1d": chg_1d,
                "price_change_pct_5d": perf_week,
                "price_change_pct_20d": perf_month,
                "pct_off_52w_high": off_high,
                "pct_off_52w_low": off_low,
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
    lots_long = 0
    lots_short = 0
    as_of = datetime.now(timezone.utc).date()

    for lot in source:
        shares = float(lot.get("shares_remaining", 0) or lot.get("shares", 0))
        cps = float(lot.get("cost_per_share", 0))
        lot_dt = lot.get("lot_date") or lot.get("acquired_date") or ""
        total_shares += shares
        total_cost += shares * cps
        if cps > 0:
            basis_prices.append(cps)

        # Holding-period classification (LT ≥ 365 days held, else ST)
        lot_term = ""
        if lot_dt:
            try:
                lot_day = datetime.strptime(str(lot_dt)[:10], "%Y-%m-%d").date()
                if (as_of - lot_day).days >= 365:
                    lot_term = "LT"
                    lots_long += 1
                else:
                    lot_term = "ST"
                    lots_short += 1
            except ValueError:
                pass

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
            "holding_period": lot_term or None,
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
        "lots_long": lots_long,
        "lots_short": lots_short,
        "holding_period": (
            "MIXED" if lots_long and lots_short
            else "LONG" if lots_long
            else "SHORT" if lots_short
            else None
        ),
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

def _recommendation_mean_label(mean: float | None) -> str:
    """Map Yahoo's recommendation_mean (1=Strong Buy .. 5=Strong Sell) to a label.

    Yahoo convention: 1.0 Strong Buy, 2.0 Buy, 3.0 Hold, 4.0 Underperform,
    5.0 Sell. The ``analyst_consensus_history`` columns are unreliable — a
    percentage return has been observed stored in ``recom_score`` (e.g. 160.15),
    producing nonsense ratings like "Strong Sell" for GD. Derive the label from
    ``recommendation_mean`` (the authoritative 1–5 score) instead.
    """
    if mean is None:
        return ""
    try:
        m = float(mean)
    except (TypeError, ValueError):
        return ""
    if m <= 1.5:
        return "Strong Buy"
    if m <= 2.5:
        return "Buy"
    if m <= 3.5:
        return "Hold"
    if m <= 4.5:
        return "Underperform"
    return "Sell"


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
            rec_mean = _f(t.get("recommendation_mean"))
            result[sym] = {
                "analyst_count": t.get("number_of_analyst_opinions"),
                "price_target_mean": mean_t,
                "price_target_high": _f(t.get("target_high_price")),
                "price_target_low": _f(t.get("target_low_price")),
                "target_vs_current_pct": target_vs_current,
                "recommendation_mean": rec_mean,
                "consensus_rating": _recommendation_mean_label(rec_mean),
                "as_of": str(t.get("snapshot_date", ""))[:10],
                "source": "yahoo_analyst_targets_history",
            }

        # Latest consensus ratings — fallback only, and only when the numeric
        # score is a plausible 1–5 recommendation (guards corrupted % returns).
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
            if sym not in result:
                continue
            if not result[sym].get("consensus_rating"):
                rating = str(c.get("analyst_rating") or "")
                if rating:
                    result[sym]["consensus_rating"] = rating
            score = _f(c.get("recom_score"))
            if score is not None and 1.0 <= score <= 5.0:
                result[sym]["consensus_score"] = score
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
            # Prefer source as_of — never inject wall-clock (destroys cache/prefix stability)
            "as_of": str(hlc.get("as_of") or hermes_data.get("as_of") or "")[:19],
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
    elif row_class in ("holding", "watchlist"):
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
    elif row_class in ("holding", "watchlist"):
        gaps.append("earnings_calendar")

    # ── 4. Technical indicators (native snapshot, else price-action derived) ──
    ind = indicator_data.get("by_symbol", {}).get(symbol, {})
    if ind and any(ind.get(k) is not None for k in ("rsi", "sma_50", "macd_signal", "atr")):
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
    else:
        # Phase 2A: derive a thin technicals proxy from price_action so the gap
        # does not systematically starve evidence when indicator_snapshot lags.
        pa_for_tech = all_data.get("price_action", {}).get(symbol, {}) or {}
        derived = {}
        for src_k, dst_k in (
            ("price_change_pct_5d", "ret_5d_pct"),
            ("price_change_pct_20d", "ret_20d_pct"),
            ("trend_direction", "trend_direction"),
            ("volatility_w_pct", "volatility_w_pct"),
            ("pct_off_52w_high", "pct_off_52w_high"),
        ):
            if pa_for_tech.get(src_k) is not None:
                derived[dst_k] = pa_for_tech.get(src_k)
        if derived:
            items.append({
                "type": "technicals",
                "source": "price_action_derived",
                "as_of": str(pa_for_tech.get("as_of") or "")[:19],
                "derived": True,
                **derived,
            })
        elif row_class in ("holding", "watchlist"):
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
        "aggregate": True,  # portfolio-level, not symbol-specific
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
            "aggregate": True,  # portfolio-level, not symbol-specific
        })

    # ── 8. IPS policy (aggregate) ──
    if ips_data.get("state") == "AVAILABLE":
        items.append({
            "type": "investment_policy",
            "source": "investment_policy_statement",
            "max_position_pct": ips_data.get("max_position_pct"),
            "beta_target": ips_data.get("beta_target"),
            "aggregate": True,  # portfolio-level, not symbol-specific
        })

    # ── 8b. Research ingestion/curation health (aggregate) ──
    ingest_health = all_data.get("ingestion_health", {})
    if ingest_health.get("state") == "AVAILABLE":
        items.append({
            "type": "ingestion_health",
            "source": "topic_ingestion_latest_json",
            "ingestion": ingest_health.get("ingestion"),
            "curation": ingest_health.get("curation"),
            "aggregate": True,  # portfolio-level, not symbol-specific
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
    elif row_class in ("holding", "watchlist"):
        gaps.append("agent_opinions")

    # ── 9b. External research (governed DeepSeek challenge) ──
    external_list = all_data.get("external_research", {}).get("by_symbol", {}).get(symbol, [])
    if external_list:
        for e in external_list[:1]:
            items.append({
                "type": "external_research",
                "source": "hermes_external_research",
                "as_of": str(e.get("created_at",""))[:19],
                "model": e.get("model",""),
                "recommendation": e.get("recommendation","")[:240],
                "confidence": e.get("confidence"),
            })
    elif row_class in ("holding", "watchlist"):
        gaps.append("external_research")

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
    elif row_class in ("holding", "watchlist"):
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
    elif row_class in ("holding", "watchlist"):
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
    # Phase 2A: accept target mean OR consensus even when analyst_count is null
    if an and (
        an.get("analyst_count")
        or an.get("price_target_mean") is not None
        or an.get("consensus_rating")
        or an.get("recommendation_mean") is not None
    ):
        items.append({
            "type": "analyst_context",
            "source": an.get("source") or "yahoo_analyst_targets_history",
            "as_of": str(an.get("as_of", "") or "")[:19],
            "analyst_count": an.get("analyst_count"),
            "price_target_mean": an.get("price_target_mean"),
            "price_target_high": an.get("price_target_high"),
            "price_target_low": an.get("price_target_low"),
            "target_vs_current_pct": an.get("target_vs_current_pct"),
            "recommendation_mean": an.get("recommendation_mean"),
            "consensus_rating": an.get("consensus_rating"),
        })
    elif row_class in ("holding", "watchlist"):
        gaps.append("analyst_context")

    # Evidence count is *symbol-specific* only. Portfolio-level items (rotation,
    # sector_context, investment_policy) are context, not evidence for THIS
    # instrument — counting them would let a watchlist row with zero symbol data
    # masquerade as "sufficient" and inflate the operator-facing "ev N" badge.
    symbol_specific = [i for i in items if not i.get("aggregate")]
    sufficiency = len(symbol_specific)
    # Gap report for operators / Phase 2 telemetry
    gap_report = {
        "missing": list(gaps),
        "item_types": sorted({str(i.get("type")) for i in items if isinstance(i, dict)}),
    }
    return {
        "evidence_items": items,
        "evidence_count": sufficiency,
        "aggregate_evidence_count": len(items) - sufficiency,
        "evidence_gaps": gaps,
        "evidence_gap_report": gap_report,
        "sufficient": sufficiency >= MIN_EVIDENCE_ITEMS,
        "row_class": row_class,
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

        # Confidence must agree with the verdict's evidence basis, not be a flat
        # constant. INSUFFICIENT_DATA means we cannot measure the allocation —
        # high confidence there is logically inverted.
        if verdict == AdvisoryVerdict.INSUFFICIENT_DATA:
            conf = 0.20
        elif verdict == AdvisoryVerdict.HOLD:
            conf = 0.55
        else:  # ADD / TRIM — deterministic drift arithmetic, well-grounded
            conf = 0.65

        row = {
            "row_class": "allocation",
            "allocation_target": desk_key,
            "symbol": f"ALLOC:{desk_key}",
            "verdict": verdict,
            "confidence": conf,
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
            "confidence": 0.20,
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
# Portfolio-level analytics + performance (read-model projections, JSON only)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_portfolio_analytics(holdings: dict[str, Any]) -> dict[str, Any]:
    """Asset-weighted valuation multiples + sector concentration + top-10.

    Sources ticker_enrichment_cache.json (PE/PB/PS/PC/sector) over current
    holdings. Only *direct equity* positions (both PE and PB populated — a
    reliable common-stock signal) feed the weighted multiples and sector
    breakdown. Funds/ETFs are excluded because the cache has no look-through
    multiples and carries a generic "Financial / Exchange Traded Fund" tag for
    them; that portion is reported as a coverage percentage instead of being
    mis-attributed.
    """
    enrich = _load_json(STATE_DIR / "ticker_enrichment_cache.json")
    positions = holdings.get("positions", [])
    if not positions:
        return {"state": "DATA_UNAVAILABLE", "reason": "no positions"}

    metrics = ("pe", "pb", "ps", "pc")
    totals = {m: 0.0 for m in metrics}
    covered_mv = 0.0
    fund_mv = 0.0
    total_mv = 0.0
    sector_mv: dict[str, float] = {}
    rows_by_mv: list[tuple[float, dict]] = []
    direct_equity_symbols: list[str] = []
    unclassified: list[dict[str, Any]] = []

    for p in positions:
        sym = p.get("symbol", "")
        mv = float(p.get("market_value") or 0)
        if mv <= 0:
            continue
        total_mv += mv
        rows_by_mv.append((mv, p))
        rec = enrich.get(sym) or {}
        if not isinstance(rec, dict):
            continue
        pe = _f(rec.get("pe"))
        pb = _f(rec.get("pb"))
        is_direct_equity = pe is not None and pe > 0 and pb is not None and pb > 0
        if not is_direct_equity:
            # Funds/ETFs and data-less instruments — excluded from valuation
            # and sector (no reliable look-through at this tier).
            fund_mv += mv
            industry = rec.get("industry")
            if industry in ("Exchange Traded Fund", "Closed-End Fund", "Mutual Fund", "Index Fund"):
                reason = "fund_or_etf"
            elif not rec.get("sector") and not rec.get("industry"):
                reason = "no_enrichment_data"
            else:
                reason = "no_direct_equity_multiples"
            unclassified.append({
                "symbol": sym,
                "market_value": round(mv, 2),
                "reason": reason,
                "style_classification": "requires_lookthrough",
            })
            continue
        covered_mv += mv
        direct_equity_symbols.append(sym)
        sector = rec.get("sector")
        if sector:
            sector_mv[str(sector)] = sector_mv.get(str(sector), 0.0) + mv
        for m in metrics:
            v = _f(rec.get(m))
            if v is not None and v > 0:
                totals[m] += mv * v

    weighted = {}
    for m in metrics:
        weighted[m] = round(totals[m] / covered_mv, 2) if covered_mv > 0 else None

    coverage_pct = round(covered_mv / total_mv * 100, 1) if total_mv > 0 else 0.0
    fund_pct = round(fund_mv / total_mv * 100, 1) if total_mv > 0 else 0.0

    # Top-10 holdings by market value (Morgan Stanley "Top 10")
    rows_by_mv.sort(key=lambda x: x[0], reverse=True)
    top_10 = []
    for mv, p in rows_by_mv[:10]:
        top_10.append({
            "symbol": p.get("symbol", ""),
            "account": p.get("account", ""),
            "market_value": round(mv, 2),
            "weight_pct": round(mv / total_mv * 100, 2) if total_mv > 0 else None,
        })

    sector_sorted = sorted(sector_mv.items(), key=lambda kv: kv[1], reverse=True)
    sector_breakdown = [
        {"sector": s, "market_value": round(v, 2),
         "weight_pct": round(v / total_mv * 100, 2) if total_mv > 0 else None}
        for s, v in sector_sorted
    ]

    return {
        "state": "AVAILABLE",
        "weighted_pe": weighted["pe"],
        "weighted_pb": weighted["pb"],
        "weighted_ps": weighted["ps"],
        "weighted_pcf": weighted["pc"],
        "valuation_coverage_pct": coverage_pct,
        "fund_etf_pct": fund_pct,
        "valuation_coverage_note": (
            "Multiples and sector weights are over direct equity holdings only; "
            f"{fund_pct:.1f}% of market value is in funds/ETFs and requires "
            "look-through (not yet wired)."
        ) if fund_pct > 0 else None,
        "sector_breakdown": sector_breakdown,
        "top_10": top_10,
        "style_classification": {
            "style_box_available": False,
            "style_method": (
                "Direct-equity multiples only (no Morningstar-style 3x3 "
                "value/blend/growth look-through)."
            ),
            "direct_equity_symbols": sorted(set(direct_equity_symbols)),
            "unclassified": unclassified,
            "unclassified_count": len(unclassified),
            "hermes_research_recommended": bool(unclassified),
        },
    }


def _load_performance() -> dict[str, Any]:
    """Performance returns + attribution from precomputed caches.

    performance_history.json supplies period returns (1D..1Y); the desk uses a
    money-weighted CAGR from performance_attribution.json (a true time-weighted
    return is a documented non-goal — see ROADMAP_GAPS.md).
    """
    hist = _load_json(STATE_DIR / "performance_history.json")
    attr = _load_json(STATE_DIR / "performance_attribution.json")

    periods_raw = hist.get("periods", {}) if isinstance(hist, dict) else {}
    period_returns: dict[str, Any] = {}
    for pname in ("1D", "1W", "1M", "3M", "6M", "YTD", "1Y"):
        pr = periods_raw.get(pname) or {}
        period_returns[pname] = {
            "change_pct": _f(pr.get("change_pct")),
            "source": pr.get("source"),
        }

    return {
        "state": "AVAILABLE" if hist.get("has_data") else "DATA_UNAVAILABLE",
        "period_returns": period_returns,
        "ytd_return": _f(periods_raw.get("YTD", {}).get("change_pct")),
        "building": hist.get("building", []) if isinstance(hist, dict) else [],
        "reconstructed": hist.get("reconstructed", []) if isinstance(hist, dict) else [],
        "current_value": _f(hist.get("current_value")),
        # Money-weighted attribution (not TWR)
        "inception_return": _f(attr.get("inception_return")),
        "port_cagr": _f(attr.get("port_cagr")),
        "bench_cagr": _f(attr.get("bench_cagr")),
        "alpha_annualized": _f(attr.get("alpha_annualized")),
        "bench_3yr_return": _f(attr.get("bench_3yr_return")),
        "sharpe": _f(attr.get("port_sharpe")),
        "sortino": _f(attr.get("port_sortino")),
        "max_drawdown": _f(attr.get("port_maxdd")),
        "benchmark_label": attr.get("benchmark_label"),
    }


def _load_living_thesis() -> dict[str, Any]:
    """Current desk governing thesis from the CIO versioned thesis store.

    Reads the rebuildable projection directly (JSON only — no store
    instantiation, no writes). Surfaces the desk@vN pin + governing context so
    the desk's output can state fit/tension with the live thesis.
    """
    proj = _load_json(CIO_DIR / "cio_theses_projection.json")
    cur = (proj.get("current") or {}) if isinstance(proj, dict) else {}
    desk = cur.get("desk")
    if not isinstance(desk, dict):
        return {"state": "DATA_UNAVAILABLE", "reason": "no desk thesis published"}

    return {
        "state": "AVAILABLE",
        "thesis_id": desk.get("thesis_id"),
        "thesis_version": desk.get("thesis_version"),
        "version": desk.get("version"),
        "stance": desk.get("stance"),
        "status": desk.get("status"),
        "summary": (desk.get("summary") or "")[:1200],
        "risk_posture": desk.get("risk_posture") or "",
        "principles": list(desk.get("principles") or [])[:12],
        "escalation_rules": list(desk.get("escalation_rules") or [])[:12],
        "linked_symbols": list(desk.get("linked_symbols") or [])[:20],
        "watch_symbols": list(desk.get("watch_symbols") or desk.get("linked_symbols") or [])[:20],
        "published_ts": desk.get("published_ts"),
        "owner_agent": desk.get("owner_agent"),
        "authority": "READ_ONLY_ADVISORY",
    }


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
    analytics = _load_portfolio_analytics(holdings)
    performance = _load_performance()
    living_thesis = _load_living_thesis()

    total_value = holdings.get("total_value") or 0
    holdings_symbols = {p["symbol"] for p in holdings.get("positions", [])}
    watchlist_symbols = set(watchlist.get("items", {}).keys())
    closed_symbols = set(closed.get("closed_by_symbol", {}).keys())
    research_symbols = holdings_symbols | watchlist_symbols | closed_symbols
    portfolio_heat_pct = risk.get("portfolio_heat_pct")

    # ── S4: Load external data sources ──
    # Scope to *research* symbols, not just held positions, so watchlist and
    # closed-journal rows also receive price action, analyst, and instrument
    # evidence (the data exists for liquid tickers like MSFT/NVDA/GD).
    listing_dates = _load_listing_dates(research_symbols)
    ohlcv_data = _load_ohlcv_data()
    instrument_data = _load_instrument_identity(
        {"positions": holdings.get("positions", []), "symbols": research_symbols},
        listing_dates,
    )
    analyst_data = _load_analyst_context(research_symbols)

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

    # Watchlist + closed symbols also get price action (OHLCV or Finviz fallback).
    # No cost basis / shares — these are not held positions, so the
    # distance-from-basis metric is intentionally absent.
    for sym in research_symbols - holdings_symbols:
        inst = instrument_data.get(sym, {})
        ld_str = inst.get("listing_date")
        price_actions[sym] = _load_price_action(sym, None, None, None, ohlcv_data, ld_str)

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
            # Tax truth: broker-adjusted cost basis + provenance + holding period
            opinion["adjusted_cost"] = _f(pos.get("cost_basis"))
            opinion["cost_basis_source"] = pos.get("cost_basis_source", "")
            opinion["basis_partial"] = bool(pos.get("basis_partial"))
            opinion["holding_period"] = lot_basis_data.get(sym, {}).get("holding_period")

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

    # S4: Attach price action + instrument identity to non-holding security rows
    # (watchlist + closed). Holdings carry these from the loop above; allocation
    # rows have synthetic symbols (ALLOC:...) with no price action by design.
    for row in rows:
        sym = row.get("symbol", "")
        if not sym:
            continue
        if not row.get("price_action") and sym in price_actions:
            row["price_action"] = price_actions[sym]
        if not row.get("instrument") and sym in instrument_data:
            row["instrument"] = instrument_data[sym]

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
        ("external_research", _load_external_research),
        ("ingestion_health", _load_ingestion_health),
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
        # Applies to security-like rows (holding + watchlist). Allocation rows
        # are exempt: their evidence is the target/actual drift arithmetic in
        # the row fields, not the symbol evidence bundle.
        if rcls in ("holding", "watchlist"):
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
                    "external_research": "lib.data_broker.advisory_desk._load_external_research",
                    "ingestion_health": "lib.data_broker.advisory_desk._load_ingestion_health",
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
                "invariant_violation_count": sum(
                    1 for r in rows
                    if r.get("invariant_violations") and len(r.get("invariant_violations", [])) > 0
                ),
                "untrusted_lot_count": sum(
                    1 for r in rows
                    if r.get("lot_data_status") == "UNTRUSTED"
                ),
                "listing_date_coverage": len(listing_dates),
                "instrument_identity_coverage": len(instrument_data),
                "portfolio_analytics": analytics,
                "performance": performance,
                "living_thesis": living_thesis,
                "catalyst_cache_path": (evidence_data.get("catalysts") or {}).get("cache_path"),
            },
            "rows": rows,
        },
    }

    # ── Plausibility / contract validation on every build (Phase 1.4) ──
    # Soft-fail: never raise; surface in metadata for delivery hard-fail later.
    try:
        validation_errors = validate_advisory_output(result)
    except Exception as e:
        validation_errors = [f"validator_exception: {type(e).__name__}: {e}"]
    result["data"]["metadata"]["validation_errors"] = validation_errors
    result["data"]["metadata"]["validation_ok"] = len(validation_errors) == 0
    result["data"]["metadata"]["plausibility_gate"] = (
        "PASS" if not any("PLAUSIBILITY_FAIL" in e for e in validation_errors) else "FAIL"
    )
    if validation_errors:
        result["data"]["metadata"]["validation_error_count"] = len(validation_errors)

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

def _advisory_desk_v1_enabled(config: dict[str, Any] | None = None) -> bool:
    """Feature flag ADVISORY_DESK_V1 — default OFF. Env overrides yaml."""
    import os

    env = (os.environ.get("ADVISORY_DESK_V1") or "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    if config is None:
        try:
            from lib.advisory.advisory_opinion_engine import _load_config
            config = _load_config()
        except Exception:
            config = {}
    return bool((config or {}).get("ADVISORY_DESK_V1"))


def enrich_advisory_with_opinions(
    desk_result: dict[str, Any],
    *,
    max_rows: int | None = None,
    force: bool = False,
    dry_run: bool | None = None,
    include_synthesis: bool = True,
) -> dict[str, Any]:
    """Enrich advisory desk rows with LLM-generated opinions (S3 / Phase 2).

    Phase 2 coverage rule: **all actionable rows above materiality** are
    model-covered first (Flash). Remaining budget may fill high-MV HOLDs.
    Local hash cache makes a second identical run = 0 model calls.
    One Pro synthesis (dollars-first) when not dry_run and include_synthesis.
    """
    try:
        from lib.advisory.advisory_opinion_engine import (
            generate_row_opinion,
            generate_desk_synthesis,
            estimate_cost_usd,
            _append_telemetry,
            _load_config,
        )
        from lib.advisory.advisory_memory import (
            append_run_history,
            apply_thrash_penalty,
            build_memory_for_row,
            load_calibration,
        )
    except ImportError:
        desk_result.setdefault("opinions", {})["error"] = "opinion engine unavailable"
        return desk_result

    try:
        config = _load_config()
    except Exception:
        config = {}

    try:
        calibration = load_calibration()
    except Exception:
        calibration = {}

    flag_on = _advisory_desk_v1_enabled(config)
    if dry_run is None:
        dry_run = not flag_on
    if not flag_on:
        dry_run = True

    cost_cfg = (config.get("routing") or {}).get("cost") or {}
    if max_rows is None:
        max_rows = int(cost_cfg.get("max_model_rows_per_run") or 20)
    max_rows = max(0, int(max_rows))
    max_watchlist_rows = max(0, int(cost_cfg.get("max_watchlist_rows_per_run") or 12))

    rows = desk_result.get("data", {}).get("rows", [])
    if not rows:
        desk_result.setdefault("opinions", {})["error"] = "no rows"
        return desk_result

    meta = (desk_result.get("data") or {}).get("metadata") or {}
    if meta.get("validation_ok") is False:
        desk_result.setdefault("opinions", {})["validation_warning"] = (
            "desk failed validation; opinions may be unreliable"
        )

    ACTIONABLE = frozenset({"EXIT", "TRIM", "ADD", "RE_ENTER"})
    VERDICT_SEVERITY = {
        "EXIT": 5, "TRIM": 4, "ADD": 3, "RE_ENTER": 2,
        "HOLD": 1, "WAIT": 0, "AVOID": 0, "INSUFFICIENT_DATA": 0,
    }

    def _vstr(row: dict[str, Any]) -> str:
        v = row.get("verdict")
        if hasattr(v, "value"):
            return str(v.value)
        return str(v or "HOLD")

    def _is_actionable(row: dict[str, Any]) -> bool:
        mv = float(row.get("market_value") or 0)
        if mv < MATERIALITY_FLOOR_USD and row.get("row_class") in ("holding", "allocation", None):
            # allocation cash gaps often have large MV — allow if MV high
            if row.get("row_class") != "allocation":
                return False
        return _vstr(row) in ACTIONABLE and mv >= MATERIALITY_FLOOR_USD

    def _eligible(row: dict[str, Any]) -> tuple[bool, str]:
        if not row.get("advisory_row_hash"):
            return False, "no_hash"
        if row.get("lot_data_status") == "UNTRUSTED" and _vstr(row) in ("EXIT", "TRIM"):
            return False, "untrusted"
        mv = float(row.get("market_value") or 0)
        if row.get("row_class") == "holding" and mv < MATERIALITY_FLOOR_USD:
            return False, "materiality"
        return True, "ok"

    # Partition: actionable first (must cover), then other eligible by $ × severity.
    # Watchlist rows get their own bucket — they are non-held (WAIT, no MV) and
    # would otherwise be starved by the dollars-first queue.
    actionable: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    watchlist_rows: list[dict[str, Any]] = []
    skipped_untrusted = skipped_materiality = 0
    for row in rows:
        ok, why = _eligible(row)
        if not ok:
            if why == "untrusted":
                skipped_untrusted += 1
            elif why == "materiality":
                skipped_materiality += 1
            continue
        if row.get("row_class") == "watchlist":
            watchlist_rows.append(row)
        elif _is_actionable(row):
            actionable.append(row)
        else:
            rest.append(row)

    actionable.sort(
        key=lambda r: float(r.get("market_value") or 0) * VERDICT_SEVERITY.get(_vstr(r), 1),
        reverse=True,
    )
    rest.sort(
        key=lambda r: float(r.get("market_value") or 0) * VERDICT_SEVERITY.get(_vstr(r), 0),
        reverse=True,
    )
    # Watchlist: cover the most-evidenced names first. A watchlist entry with
    # thin evidence (ev < MIN_EVIDENCE_ACTIONABLE) still gets a Flash WAIT but is
    # deprioritized behind names that carry real price/analyst/agent context.
    watchlist_rows.sort(
        key=lambda r: (
            (r.get("evidence_bundle") or {}).get("evidence_count", 0),
            r.get("symbol", ""),
        ),
        reverse=True,
    )
    # Actionable always first; then fill remainder of max_rows from rest
    # All actionable first (hard cover), then optional HOLDs up to max_rows.
    ordered = list(actionable)
    for r in rest:
        if len(ordered) >= max(max_rows, len(actionable)):
            break
        ordered.append(r)

    # Watchlist coverage is independent of the holdings budget.
    watchlist_covered: list[dict[str, Any]] = []
    for r in watchlist_rows:
        if len(watchlist_covered) >= max_watchlist_rows:
            break
        watchlist_covered.append(r)
    ordered.extend(watchlist_covered)

    opinions: dict[str, dict[str, Any]] = {}
    rows_model_called = 0
    rows_cache_hit = 0
    rows_enriched = 0
    input_tokens = output_tokens = cached_tokens = 0
    cost_usd = 0.0
    rejection_count = 0
    actionable_total = len(actionable)
    actionable_covered = 0

    memory_hits = 0
    thrash_applied_n = 0
    disagree_surfaced_n = 0

    for row in ordered:
        row_hash = row["advisory_row_hash"]
        det_verdict = _vstr(row)
        evidence = row.get("evidence_bundle") or {}
        sym = row.get("symbol", "?")

        # Phase 3: load L4 memory (prior + feedback + thrash) for this row
        try:
            mem = build_memory_for_row(row, calibration=calibration)
        except Exception:
            mem = {"memory_block": "", "prior": {}, "thrash_penalty": 0, "disagree_thesis": None}
        memory_block = mem.get("memory_block") or ""
        if mem.get("prior", {}).get("has_prior"):
            memory_hits += 1
        if mem.get("disagree_thesis"):
            disagree_surfaced_n += 1
        # Attach compact memory onto the row for surface/API later
        row["memory"] = {
            "prior": mem.get("prior"),
            "thrash_penalty": mem.get("thrash_penalty"),
            "has_disagree_thesis": bool(mem.get("disagree_thesis")),
        }

        if dry_run:
            base_conv = int((row.get("confidence") or 0.5) * 100)
            adj, pen = apply_thrash_penalty(base_conv, int((mem.get("prior") or {}).get("verdict_changes_90d") or 0))
            if pen:
                thrash_applied_n += 1
            rationale = row.get("rationale", f"Deterministic opinion for {sym}.")
            if mem.get("disagree_thesis"):
                d = mem["disagree_thesis"]
                rationale = (
                    f"{rationale} | Operator DISAGREE_THESIS on "
                    f"{(d.get('ts') or '')[:10]}: held through prior call."
                )
            # Dry-run: still record lesson applications when injected
            try:
                from lib.advisory.kb_lessons import record_application
                for L in (mem.get("lessons") or []):
                    lid = str(L.get("id") or "")
                    if lid:
                        record_application(lid, symbol=str(sym), hit=None, cited_in_rationale=False)
            except Exception:
                pass
            opinion = {
                "verdict": det_verdict,
                "conviction": adj,
                "conviction_pre_thrash": base_conv,
                "thrash_penalty": pen,
                "what_changed": "Dry run — model not called.",
                "rationale": rationale,
                "key_risk": (
                    f"No counter-argument analysis (dry run). "
                    f"Evidence gaps: {evidence.get('evidence_gaps', [])}"
                ),
                "evidence_cited": [
                    item.get("title", "")
                    for item in (evidence.get("evidence_items") or [])[:3]
                    if isinstance(item, dict)
                ],
                "advisory_row_hash": row_hash,
                "model_deterministic_disagreement": False,
                "llm_rejected": False,
                "model": "deterministic (dry_run)",
                "cache_hit": False,
                "memory_injected": bool(memory_block),
                "lessons_injected": [L.get("id") for L in (mem.get("lessons") or [])],
            }
        else:
            opinion = generate_row_opinion(
                row, evidence, det_verdict,
                config=config, force=force,
                memory_block=memory_block,
            )
            # Thrash penalty on conviction (deterministic post-process)
            base_conv = opinion.get("conviction")
            adj, pen = apply_thrash_penalty(
                base_conv,
                int((mem.get("prior") or {}).get("verdict_changes_90d") or 0),
            )
            if pen:
                thrash_applied_n += 1
                opinion["conviction_pre_thrash"] = base_conv
                opinion["conviction"] = adj
                opinion["thrash_penalty"] = pen
            if mem.get("disagree_thesis") and opinion.get("rationale"):
                d = mem["disagree_thesis"]
                opinion["rationale"] = (
                    f"{opinion['rationale']} | Operator DISAGREE_THESIS on "
                    f"{(d.get('ts') or '')[:10]}: held through prior call."
                )
                opinion["operator_disagree_thesis"] = True
            # Phase 6: record lesson applications; mark citations in rationale
            try:
                from lib.advisory.kb_lessons import record_application
                rat = str(opinion.get("rationale") or "")
                cited_ids = []
                for L in (mem.get("lessons") or []):
                    title = str(L.get("title") or "")
                    lid = str(L.get("id") or "")
                    if not lid:
                        continue
                    cited = bool((title and title[:40] in rat) or (lid and lid in rat))
                    if cited:
                        cited_ids.append(lid)
                    record_application(
                        lid,
                        symbol=str(row.get("symbol") or ""),
                        hit=None,
                        cited_in_rationale=cited,
                    )
                if cited_ids:
                    opinion["lessons_cited"] = cited_ids
            except Exception:
                pass
            opinion["memory_injected"] = bool(memory_block)
            opinion["lessons_injected"] = [L.get("id") for L in (mem.get("lessons") or [])]
            usage = opinion.get("usage") or {}
            if opinion.get("cache_hit"):
                rows_cache_hit += 1
            else:
                rows_model_called += 1
                input_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                output_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
                cached_tokens += int(
                    usage.get("prompt_cache_hit_tokens") or usage.get("cached_tokens") or 0
                )
                cost_usd += estimate_cost_usd(usage, model=str(opinion.get("model") or ""))
            if opinion.get("llm_rejected"):
                rejection_count += 1

        # Watchlist guard: a non-held name must never receive a directional
        # ADD/TRIM/EXIT/RE_ENTER call. The deterministic verdict is WAIT, and the
        # model may reason about the watch thesis, but cannot recommend a buy/sell
        # on something the operator does not own. Coerce any actionable verdict
        # back to WAIT (mirrors the deterministic A2 gate philosophy).
        if row.get("row_class") == "watchlist":
            wv = str(opinion.get("verdict") or "").upper()
            if wv in ACTIONABLE:
                opinion["verdict"] = "WAIT"
                opinion["model_deterministic_disagreement"] = True
                opinion["what_changed"] = (
                    f"Model returned {wv}; overridden to WAIT — watchlist rows "
                    "are non-held and cannot carry a directional call."
                )
                if opinion.get("rationale"):
                    opinion["rationale"] = (
                        f"{opinion['rationale']} [watchlist override: {wv}→WAIT]"
                    )

        opinions[row_hash] = opinion
        rows_enriched += 1
        if _is_actionable(row):
            actionable_covered += 1

    # Pro synthesis — one call, dollars-first (Phase 2C)
    synthesis_meta: dict[str, Any]
    if dry_run or not include_synthesis:
        synthesis_meta = {
            "text": (
                f"Desk synthesis preview — opinion layer is not enabled for this run "
                f"(ADVISORY_DESK_V1={flag_on}). "
                f"{len(rows)} rows, {len(opinions)} opinions. "
                f"Actionable covered {actionable_covered}/{actionable_total}."
            ),
            "cache_hit": False,
            "degraded": True,
            "model": "dry_run",
        }
    else:
        synthesis_meta = generate_desk_synthesis(rows, config=config, force=force)
        usage = synthesis_meta.get("usage") or {}
        if not synthesis_meta.get("cache_hit"):
            input_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            cached_tokens += int(
                usage.get("prompt_cache_hit_tokens") or usage.get("cached_tokens") or 0
            )
            cost_usd += estimate_cost_usd(
                usage, model=str(synthesis_meta.get("model") or "deepseek-v4-pro")
            )

    total_for_hit = rows_model_called + rows_cache_hit
    cache_hit_rate = (rows_cache_hit / total_for_hit) if total_for_hit else 1.0

    telemetry = {
        "event": "advisory_opinion_run",
        "dry_run": dry_run,
        "ADVISORY_DESK_V1": flag_on,
        "rows_enriched": rows_enriched,
        "rows_called": rows_model_called,
        "rows_cache_hit": rows_cache_hit,
        "cache_hit_rate": round(cache_hit_rate, 4),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "cost_usd": round(cost_usd, 6),
        "actionable_total": actionable_total,
        "actionable_covered": actionable_covered,
        "actionable_coverage_pct": (
            round(100.0 * actionable_covered / actionable_total, 1)
            if actionable_total else 100.0
        ),
        "watchlist_total": len(watchlist_rows),
        "watchlist_covered": len(watchlist_covered),
        "rejection_count": rejection_count,
        "synthesis_cache_hit": bool(synthesis_meta.get("cache_hit")),
        "synthesis_lead_symbol": synthesis_meta.get("lead_symbol"),
        "synthesis_lead_dollars": synthesis_meta.get("lead_dollars"),
        "skipped_untrusted": skipped_untrusted,
        "skipped_materiality": skipped_materiality,
        "memory_prior_hits": memory_hits,
        "memory_prior_hit_pct": (
            round(100.0 * memory_hits / rows_enriched, 1) if rows_enriched else 0.0
        ),
        "thrash_applied_n": thrash_applied_n,
        "disagree_thesis_surfaced_n": disagree_surfaced_n,
    }
    try:
        _append_telemetry(telemetry)
    except Exception:
        pass

    # Phase 3A: append-only verdict history for this run
    history_n = 0
    try:
        history_n = append_run_history(
            ordered if ordered else rows,
            opinions=opinions,
            source="enrich_advisory_with_opinions",
        )
    except Exception:
        history_n = 0
    telemetry["history_rows_appended"] = history_n

    desk_result.setdefault("opinions", {})
    desk_result["opinions"]["rows"] = opinions
    desk_result["opinions"]["synthesis"] = synthesis_meta.get("text") or ""
    desk_result["opinions"]["synthesis_meta"] = {
        k: v for k, v in synthesis_meta.items() if k != "text"
    }
    desk_result["opinions"]["rows_enriched"] = rows_enriched
    desk_result["opinions"]["dry_run"] = dry_run
    desk_result["opinions"]["ADVISORY_DESK_V1"] = flag_on
    desk_result["opinions"]["max_rows"] = max_rows
    desk_result["opinions"]["skipped_untrusted"] = skipped_untrusted
    desk_result["opinions"]["skipped_materiality"] = skipped_materiality
    desk_result["opinions"]["telemetry"] = telemetry
    desk_result["opinions"]["memory"] = {
        "prior_hits": memory_hits,
        "thrash_applied_n": thrash_applied_n,
        "disagree_thesis_surfaced_n": disagree_surfaced_n,
        "history_rows_appended": history_n,
    }
    if not dry_run:
        desk_result["data"]["llm_in_path"] = True
        desk_result["data"]["deterministic"] = True
        _persist_opinions_latest(
            opinions=opinions,
            synthesis=synthesis_meta.get("text") or "",
            synthesis_meta={k: v for k, v in synthesis_meta.items() if k != "text"},
        )

    return desk_result


def _persist_opinions_latest(
    *,
    opinions: dict[str, dict[str, Any]],
    synthesis: str,
    synthesis_meta: dict[str, Any],
) -> None:
    """Write the live enrichment result to the served read path.

    The deterministic desk snapshot (advisory_desk_latest.json) is produced by a
    different process than the shadow-session enrichment, so get_advisory_desk
    would otherwise never see Flash/Pro output. This artifact bridges the two.
    """
    from datetime import datetime, timezone

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        OPINIONS_LATEST_FILE.write_text(
            json.dumps(
                {
                    "rows": opinions,
                    "synthesis": synthesis,
                    "synthesis_meta": synthesis_meta,
                    "llm_in_path": True,
                    "computed_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
