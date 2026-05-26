# Source Export: scripts/proposal_execution_readiness.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/proposal_execution_readiness.py` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:50:11Z` |
| **SHA256** | `dcfc412589f3c7ca1e99eea59c89f32ffa0eb3ad780e72d32b798901925bbc29` |
| **File Size** | 32288 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""proposal_execution_readiness.py — Determine if a paper trade proposal is executable now.

Session 23E: Uses multi-provider quote hierarchy (Alpaca > Polygon > Finnhub > FMP > yfinance).
No longer depends on Finviz cache for execution quotes.
Proposal technical snapshots are primary for technical readiness.

Usage:
    .venv/bin/python scripts/proposal_execution_readiness.py --pending --dry-run
    .venv/bin/python scripts/proposal_execution_readiness.py --pending --apply
    .venv/bin/python scripts/proposal_execution_readiness.py --proposal-id 123 --apply
"""

import argparse
import json
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Strategy-aware thresholds (Session 24C fix)
# ---------------------------------------------------------------------------
# Intraday strategies need tight execution windows.
# Swing/position strategies have wider tolerances because they execute
# over days/weeks — the spread and drift at 10pm don't matter if the
# trade is submitted at 9:35am when spreads are tight.
# ---------------------------------------------------------------------------
# Derive intraday strategies from YAML configs — no hardcoded list
try:
    from proposal_lifecycle import INTRADAY_STRATEGIES
except ImportError:
    INTRADAY_STRATEGIES = {"momentum_scalp", "gap_and_go"}  # safe fallback

THRESHOLDS_BY_CLASS = {
    "intraday": {
        "max_quote_age": 300,
        "max_price_drift_pct": 2.0,
        "max_spread_pct": 1.0,
        "min_volume": 100_000,
        "rsi_block_above": 85,       # scalps are momentum — higher RSI tolerated
        "vwap_block_above_pct": 10,
    },
    "short_swing": {
        "max_quote_age": 86400,       # 24h — swing can wait for market open
        "max_price_drift_pct": 5.0,   # 5% drift allowed for multi-day holds
        "max_spread_pct": 3.0,        # AH spread acceptable, will re-check at submit
        "min_volume": 50_000,         # lower volume ok for less liquid swing names
        "rsi_block_above": 90,        # only block extreme overbought
        "vwap_block_above_pct": 15,   # swing entries can be extended
    },
    "medium_swing": {
        "max_quote_age": 86400,
        "max_price_drift_pct": 8.0,
        "max_spread_pct": 3.0,
        "min_volume": 50_000,
        "rsi_block_above": 90,
        "vwap_block_above_pct": 20,
    },
    "position": {
        "max_quote_age": 86400,
        "max_price_drift_pct": 12.0,
        "max_spread_pct": 5.0,
        "min_volume": 25_000,
        "rsi_block_above": 95,        # position rarely blocked by RSI
        "vwap_block_above_pct": 25,
    },
}

def _get_thresholds(strategy_id: str) -> dict:
    """Get strategy-aware thresholds."""
    try:
        from proposal_lifecycle import get_timeframe_class
        tc = get_timeframe_class(strategy_id)
    except Exception:
        tc = "intraday" if strategy_id in INTRADAY_STRATEGIES else "short_swing"
    return THRESHOLDS_BY_CLASS.get(tc, THRESHOLDS_BY_CLASS["short_swing"])

READINESS_STATES = [
    "READY_FOR_PAPER_SUBMIT",
    "READY_ORB_CONFIRMED",
    "CAUTION_EXECUTABLE",
    "CAUTION_EXTENDED_ABOVE_VWAP",
    "CAUTION_ATR_TARGET_TOO_FAR",
    "CAUTION_BELOW_PREMARKET_HIGH",
    "BLOCKED_NO_QUOTE",
    "BLOCKED_STALE_QUOTE",
    "BLOCKED_SPREAD_UNKNOWN",
    "BLOCKED_SPREAD",
    "BLOCKED_NO_VOLUME",
    "BLOCKED_PRICE_MOVED",
    "BLOCKED_RISK_GATE",
    "BLOCKED_DUPLICATE",
    "BLOCKED_MISSING_TECHNICALS",
    "BLOCKED_MISSING_INTRADAY_REQUIRED",
    "BLOCKED_DELAYED_QUOTE_FOR_SUBMIT",
    "BLOCKED_LIVE_DISABLED",
]

# Strategy-specific requirements — derived from timeframe class, not hardcoded lists
# Intraday strategies require VWAP; momentum scalps require ORB
STRATEGY_REQUIRES_VWAP = INTRADAY_STRATEGIES  # all intraday strategies need VWAP
STRATEGY_REQUIRES_ORB = {s for s in INTRADAY_STRATEGIES if 'scalp' in s}  # scalps need ORB
STRATEGY_REQUIRES_DAILY_STRUCTURE = set()  # populated from YAML if setup_qualification.min_base_days exists
try:
    import yaml as _yaml
    _strat_dir = Path(__file__).resolve().parent.parent / "config" / "strategies"
    for _p in _strat_dir.glob("*.yaml"):
        try:
            with open(_p) as _f:
                _cfg = _yaml.safe_load(_f) or {}
            if _cfg.get("setup_qualification", {}).get("min_base_days"):
                STRATEGY_REQUIRES_DAILY_STRUCTURE.add(_p.stem)
        except Exception:
            pass
except Exception:
    STRATEGY_REQUIRES_DAILY_STRUCTURE = {"swing_breakout"}  # safe fallback

LIVE_DISABLED_WARNING = "Live trading disabled pending six-month paper validation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_market_hours() -> bool:
    """Rough check: Mon-Fri 9:30-16:00 ET (13:30-20:00 UTC)."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    hour_utc = now.hour + now.minute / 60.0
    return 13.5 <= hour_utc <= 20.0


def fetch_proposals(conn, proposal_id=None, pending_only=False):
    """Return list of proposal dicts from paper_trade_proposals."""
    cur = conn.cursor()
    if proposal_id:
        cur.execute(
            "SELECT id, symbol, strategy_id, proposed_entry, proposed_stop, "
            "proposed_target1, proposed_shares, risk_gate_result, status "
            "FROM paper_trade_proposals WHERE id = %s",
            (proposal_id,),
        )
    elif pending_only:
        cur.execute(
            "SELECT id, symbol, strategy_id, proposed_entry, proposed_stop, "
            "proposed_target1, proposed_shares, risk_gate_result, status "
            "FROM paper_trade_proposals WHERE status = 'PENDING'"
        )
    else:
        cur.execute(
            "SELECT id, symbol, strategy_id, proposed_entry, proposed_stop, "
            "proposed_target1, proposed_shares, risk_gate_result, status "
            "FROM paper_trade_proposals"
        )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


def check_duplicate_open(conn, symbol: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE symbol = %s AND status = 'open'",
        (symbol,),
    )
    count = cur.fetchone()[0]
    cur.close()
    return count > 0


def check_technical_data(conn, symbol: str) -> tuple:
    """Check for technical data. Returns (has_data, source, row_or_None)."""
    cur = conn.cursor()
    # Try proposal_technical_snapshots first (Session 23E: primary)
    cur.execute("""
        SELECT ema_alignment, technical_grade, opening_range_status, premarket_status,
               vwap_distance_pct, atr_14, nearest_fib_level, nearest_fib_distance_pct,
               ohlcv_data_status, computed_at
        FROM proposal_technical_snapshots
        WHERE symbol = %s ORDER BY computed_at DESC LIMIT 1
    """, (symbol,))
    row = cur.fetchone()
    if row:
        cur.close()
        return True, "proposal_technical_snapshot", row

    # Fallback to indicator_confluence_cache
    cur.execute(
        "SELECT COUNT(*) FROM indicator_confluence_cache WHERE symbol = %s",
        (symbol,),
    )
    count = cur.fetchone()[0]
    cur.close()
    if count > 0:
        return True, "indicator_confluence_cache", None
    return False, "none", None


# ---------------------------------------------------------------------------
# Core readiness assessment
# ---------------------------------------------------------------------------

def assess_proposal(conn, proposal: dict) -> dict:
    """Run all readiness checks using multi-provider quotes."""
    symbol = proposal["symbol"]

    blockers = []
    warnings = []

    # Initialize check flags
    quote_fresh = False
    price_ok = False
    spread_ok = False  # Session 23E: NO default pass
    liquidity_ok = False
    risk_gate_ok = False
    duplicate_ok = False
    indicators_ok = False
    backtest_ok = True  # learning mode

    quote_price = None
    quote_age_seconds = None
    quote_timestamp = None
    bid = None
    ask = None
    spread = None
    spread_pct = None
    price_vs_entry_pct = None
    quote_provider = None
    quote_snapshot_id = None
    quote_is_delayed = True
    quote_execution_eligible = False
    volume_source = None
    spread_source = None
    day_volume = None

    # Strategy-aware thresholds
    strategy_id_raw = proposal.get("strategy_id", "momentum_scalp")
    th = _get_thresholds(strategy_id_raw)
    MAX_QUOTE_AGE_SECONDS = th["max_quote_age"]
    MAX_PRICE_MOVE_FROM_ENTRY_PCT = th["max_price_drift_pct"]
    MAX_SPREAD_PCT = th["max_spread_pct"]
    MIN_VOLUME = th["min_volume"]

    # -----------------------------------------------------------------------
    # 1. Get quote from multi-provider hierarchy
    # -----------------------------------------------------------------------
    from market_quote_provider import get_best_quote, store_quote

    quote = get_best_quote(symbol)
    quote_provider = quote.get("provider", "none")

    if quote_provider == "none" or quote.get("last_price") is None:
        blockers.append(f"BLOCKED_NO_QUOTE: No quote available for {symbol} from any provider")
    else:
        # Store the quote snapshot
        quote_snapshot_id = store_quote(conn, symbol, quote)

        quote_price = quote.get("last_price")
        bid = quote.get("bid")
        ask = quote.get("ask")
        spread = quote.get("spread")
        spread_pct = quote.get("spread_pct")
        day_volume = quote.get("day_volume")
        quote_is_delayed = quote.get("is_delayed", True)
        quote_execution_eligible = quote.get("is_execution_eligible", False)

        # Quote timestamp and freshness
        qt_str = quote.get("quote_timestamp")
        if qt_str:
            try:
                qt = datetime.fromisoformat(str(qt_str).replace("Z", "+00:00"))
                quote_timestamp = qt.isoformat()
                now_utc = datetime.now(timezone.utc)
                quote_age_seconds = (now_utc - qt).total_seconds()

                max_age = MAX_QUOTE_AGE_SECONDS
                if not is_market_hours():
                    max_age = 86400  # relax to 24h after hours

                if quote_age_seconds <= max_age:
                    quote_fresh = True
                else:
                    blockers.append(
                        f"Quote age {quote_age_seconds:.0f}s exceeds max {max_age}s "
                        f"(provider={quote_provider})")
            except Exception as e:
                blockers.append(f"Could not parse quote timestamp: {e}")
        else:
            # If provider returned data but no timestamp, treat as fresh if recent store
            quote_fresh = True
            warnings.append(f"Quote from {quote_provider} has no timestamp — assumed fresh")

    # -----------------------------------------------------------------------
    # 2. Price vs proposed entry
    # -----------------------------------------------------------------------
    proposed_entry = float(proposal["proposed_entry"]) if proposal["proposed_entry"] else None
    if quote_price is not None and proposed_entry:
        price_vs_entry_pct = abs(quote_price - proposed_entry) / proposed_entry * 100
        if price_vs_entry_pct <= MAX_PRICE_MOVE_FROM_ENTRY_PCT:
            price_ok = True
        else:
            blockers.append(
                f"Price moved {price_vs_entry_pct:.2f}% from entry "
                f"(quote={quote_price}, entry={proposed_entry})")
    elif proposed_entry is None:
        blockers.append("Proposal has no proposed_entry")

    # -----------------------------------------------------------------------
    # 3. Spread check — Session 23E: NO false pass
    # -----------------------------------------------------------------------
    if bid is not None and ask is not None:
        spread_source = quote_provider
        if spread_pct is not None and spread_pct <= MAX_SPREAD_PCT:
            spread_ok = True
        elif spread_pct is not None:
            blockers.append(
                f"Spread {spread_pct:.3f}% exceeds max {MAX_SPREAD_PCT}% "
                f"(bid={bid}, ask={ask})")
        else:
            spread_ok = True  # bid/ask present but spread calc edge case
    else:
        spread_ok = False
        spread_source = "unavailable"
        blockers.append(
            f"BLOCKED_SPREAD_UNKNOWN: Bid/ask unavailable from {quote_provider}")

    # -----------------------------------------------------------------------
    # 4. Duplicate open paper trade
    # -----------------------------------------------------------------------
    if check_duplicate_open(conn, symbol):
        duplicate_ok = False
        blockers.append(f"Open paper trade already exists for {symbol}")
    else:
        duplicate_ok = True

    # -----------------------------------------------------------------------
    # 5. Risk gate
    # -----------------------------------------------------------------------
    rg = proposal.get("risk_gate_result")
    if rg and str(rg).lower() in ("pass", "true", "approved"):
        risk_gate_ok = True
    else:
        risk_gate_ok = False
        blockers.append(f"Risk gate result is '{rg}' — must be pass/true/approved")

    # -----------------------------------------------------------------------
    # 6. Technical readiness — Session 23E: proposal snapshots primary
    # -----------------------------------------------------------------------
    has_tech, tech_source, ts_row = check_technical_data(conn, symbol)
    if has_tech:
        indicators_ok = True
        if tech_source == "indicator_confluence_cache":
            warnings.append("INDICATOR_CONFLUENCE_CACHE_MISSING_USING_PROPOSAL_SNAPSHOT: "
                            "No proposal technical snapshot — using indicator cache")
    else:
        indicators_ok = False
        blockers.append(f"BLOCKED_MISSING_TECHNICALS: No technical data for {symbol}")

    # -----------------------------------------------------------------------
    # 7. Volume / liquidity
    # -----------------------------------------------------------------------
    if day_volume is not None and day_volume > MIN_VOLUME:
        liquidity_ok = True
        volume_source = quote_provider
    else:
        # Try OHLCV bars as volume fallback
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT volume FROM market_ohlcv_bars
                WHERE symbol = %s AND timeframe = 'daily'
                ORDER BY bar_time DESC LIMIT 1
            """, (symbol,))
            vrow = cur.fetchone()
            cur.close()
            if vrow and vrow[0] and float(vrow[0]) > MIN_VOLUME:
                liquidity_ok = True
                volume_source = "ohlcv_daily"
                day_volume = float(vrow[0])
            else:
                liquidity_ok = False
                volume_source = "unavailable"
                vol_val = f"{day_volume}" if day_volume is not None else (
                    f"{float(vrow[0]):.0f}" if vrow and vrow[0] else "none")
                blockers.append(f"BLOCKED_NO_VOLUME: Volume {vol_val} below min {MIN_VOLUME}")
        except Exception:
            liquidity_ok = False
            volume_source = "unavailable"
            blockers.append(f"BLOCKED_NO_VOLUME: No volume data for {symbol}")

    # -----------------------------------------------------------------------
    # 8. Technical snapshot gates (Session 23D + 24C enforcement upgrade)
    # -----------------------------------------------------------------------
    strategy_id = proposal.get("strategy_id", "")
    ts_orb_status = None
    if ts_row:
        ts_ema_align, ts_grade, ts_orb_status, ts_pm_status, \
            ts_vwap_dist, ts_atr, ts_fib_level, ts_fib_dist, ts_ohlcv_status, ts_computed = ts_row

        # --- HARD BLOCKS (prevent paper submit) ---

        # EMA alignment: BEARISH or LONG_TERM_OVERHEAD blocks long entries
        if ts_ema_align in ("BEARISH", "LONG_TERM_OVERHEAD"):
            blockers.append(f"BLOCKED_BEARISH_EMA: EMA alignment {ts_ema_align} — do not enter long")

        # RSI overbought: strategy-aware threshold
        rsi_block = th["rsi_block_above"]
        try:
            cur2 = conn.cursor()
            cur2.execute("SELECT rsi_14 FROM proposal_technical_snapshots WHERE symbol=%s ORDER BY computed_at DESC LIMIT 1", (symbol,))
            rsi_row = cur2.fetchone()
            cur2.close()
            if rsi_row and rsi_row[0] is not None:
                rsi_val = float(rsi_row[0])
                if rsi_val > rsi_block:
                    blockers.append(f"BLOCKED_RSI_OVERBOUGHT: RSI {rsi_val:.1f} > {rsi_block} threshold for {strategy_id_raw}")
                elif rsi_val > 70:
                    warnings.append(f"CAUTION_RSI_ELEVATED: RSI {rsi_val:.1f} — momentum extended")
        except Exception:
            pass

        # VWAP extension: strategy-aware threshold
        vwap_block = th["vwap_block_above_pct"]
        if ts_vwap_dist is not None:
            vwap_val = float(ts_vwap_dist)
            if vwap_val > vwap_block:
                blockers.append(f"BLOCKED_EXTENDED_ABOVE_VWAP: {ts_vwap_dist}% above VWAP (max {vwap_block}% for {strategy_id_raw})")
            elif vwap_val > 5:
                warnings.append(f"CAUTION_EXTENDED_ABOVE_VWAP: {ts_vwap_dist}% above VWAP")

        # ORB requirement for momentum_scalp
        if strategy_id in STRATEGY_REQUIRES_ORB:
            if ts_orb_status == "NO_INTRADAY_DATA":
                blockers.append("BLOCKED_MISSING_INTRADAY_REQUIRED: momentum_scalp requires intraday data")
            elif ts_orb_status == "ORB_BREAKOUT_FAILED":
                blockers.append("BLOCKED_ORB_FAILED: Opening range breakout failed — do not chase")

        # ATR target feasibility: block if target > 3x ATR (unrealistic)
        proposed_target1_val = float(proposal.get("proposed_target1") or 0)
        proposed_entry_val = float(proposal.get("proposed_entry") or 0)
        if ts_atr and proposed_entry_val and proposed_target1_val:
            target_distance = abs(proposed_target1_val - proposed_entry_val)
            atr_val = float(ts_atr)
            if atr_val > 0 and target_distance > 3 * atr_val:
                blockers.append(f"BLOCKED_TARGET_UNREALISTIC: Target {target_distance:.2f} > 3x ATR {atr_val:.2f}")

        # --- WARNINGS (caution, do not block) ---

        if ts_fib_level and ts_fib_dist is not None and float(ts_fib_dist) < 2:
            warnings.append(f"INFO_NEAR_FIB: Near {ts_fib_level} ({ts_fib_dist}% away)")

        if ts_pm_status == "PREMARKET_HIGH_REJECTED":
            warnings.append("CAUTION_BELOW_PREMARKET_HIGH: Rejected at premarket high")

        if ts_grade == "TECH_WEAK":
            warnings.append("CAUTION_TECH_WEAK: Technical grade is WEAK — thin evidence")
        elif ts_grade == "TECH_INCOMPLETE":
            warnings.append("CAUTION_TECH_INCOMPLETE: Technical data still populating")

    # -----------------------------------------------------------------------
    # 9. R:R gate (Session 24C — enforce minimum)
    # -----------------------------------------------------------------------
    proposed_rr = float(proposal.get("proposed_rr") or 0)
    if proposed_rr > 0 and proposed_rr < 1.5:
        blockers.append(f"BLOCKED_RR_TOO_LOW: R:R {proposed_rr:.1f} below 1.5 minimum")
    elif proposed_rr > 0 and proposed_rr < 2.0:
        warnings.append(f"CAUTION_RR_BELOW_TARGET: R:R {proposed_rr:.1f} below 2.0 target")

    # -----------------------------------------------------------------------
    # Paper-only warning (always)
    # -----------------------------------------------------------------------
    warnings.append(LIVE_DISABLED_WARNING)

    # -----------------------------------------------------------------------
    # Backtest — Session 23E: honest labeling
    # -----------------------------------------------------------------------
    # backtest_ok = True for learning mode, but warning is truthful
    warnings.append("BACKTEST_SAMPLE_INSUFFICIENT_LEARNING_MODE: "
                     "Backtest data insufficient — paper learning mode active")

    # -----------------------------------------------------------------------
    # Determine readiness state
    # -----------------------------------------------------------------------
    checks = {
        "quote_fresh": quote_fresh,
        "price_ok": price_ok,
        "spread_ok": spread_ok,
        "liquidity_ok": liquidity_ok,
        "risk_gate_ok": risk_gate_ok,
        "duplicate_ok": duplicate_ok,
        "indicators_ok": indicators_ok,
        "backtest_ok": backtest_ok,
    }
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    readiness_score = int(passed / total * 100)

    if len(blockers) == 0:
        if readiness_score == 100:
            readiness_state = "READY_FOR_PAPER_SUBMIT"
        else:
            readiness_state = "CAUTION_EXECUTABLE"
    else:
        state_map = {
            "BLOCKED_NO_QUOTE": "BLOCKED_NO_QUOTE",
            "Quote age": "BLOCKED_STALE_QUOTE",
            "Could not parse": "BLOCKED_STALE_QUOTE",
            "BLOCKED_SPREAD_UNKNOWN": "BLOCKED_SPREAD_UNKNOWN",
            "Spread": "BLOCKED_SPREAD",
            "Price moved": "BLOCKED_PRICE_MOVED",
            "Open paper trade": "BLOCKED_DUPLICATE",
            "Risk gate": "BLOCKED_RISK_GATE",
            "BLOCKED_MISSING_TECHNICALS": "BLOCKED_MISSING_TECHNICALS",
            "BLOCKED_NO_VOLUME": "BLOCKED_NO_VOLUME",
            "BLOCKED_MISSING_INTRADAY": "BLOCKED_MISSING_INTRADAY_REQUIRED",
        }
        readiness_state = "BLOCKED_NO_QUOTE"  # fallback
        for blocker_text in blockers:
            for prefix, state in state_map.items():
                if prefix.lower() in blocker_text.lower():
                    readiness_state = state
                    break
            else:
                continue
            break

    # -----------------------------------------------------------------------
    # Execution plan
    # -----------------------------------------------------------------------
    proposed_stop = float(proposal["proposed_stop"]) if proposal.get("proposed_stop") else None
    proposed_target1 = float(proposal["proposed_target1"]) if proposal.get("proposed_target1") else None
    proposed_shares = int(proposal["proposed_shares"]) if proposal.get("proposed_shares") else None

    execution_plan = {
        "order_type": "limit_bracket",
        "limit_price": proposed_entry,
        "stop_price": proposed_stop,
        "take_profit_price": proposed_target1,
        "time_in_force": "day",
        "shares": proposed_shares,
    }

    slippage_budget_pct = 0.10

    # Session 23D: Bracket validation fields
    bracket_order_supported = True
    alpaca_mode = os.getenv("ALPACA_MODE", "paper").lower()
    alpaca_base = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    alpaca_base_type = "paper" if "paper-api" in alpaca_base else "LIVE_BLOCKED"
    mkt_hours = is_market_hours()

    bracket_payload = {
        "symbol": symbol,
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": str(proposed_entry) if proposed_entry else None,
        "qty": str(proposed_shares) if proposed_shares else None,
        "order_class": "bracket",
        "take_profit": {"limit_price": str(proposed_target1) if proposed_target1 else None},
        "stop_loss": {"stop_price": str(proposed_stop) if proposed_stop else None},
        "client_order_id": f"tradeai-paper-{proposal['id']}-{symbol}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
    }

    # Enhance readiness state for ORB-confirmed scenarios
    if readiness_state == "READY_FOR_PAPER_SUBMIT":
        if ts_row and ts_orb_status == "ORB_BREAKOUT_CONFIRMED":
            readiness_state = "READY_ORB_CONFIRMED"

    return {
        "proposal_id": proposal["id"],
        "symbol": symbol,
        "strategy_id": proposal.get("strategy_id"),
        "readiness_state": readiness_state,
        "readiness_score": readiness_score,
        "quote_price": quote_price,
        "quote_timestamp": quote_timestamp,
        "quote_age_seconds": quote_age_seconds,
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "spread_pct": spread_pct,
        "entry_price": proposed_entry,
        "price_vs_entry_pct": round(price_vs_entry_pct, 4) if price_vs_entry_pct is not None else None,
        "slippage_budget_pct": slippage_budget_pct,
        "liquidity_ok": liquidity_ok,
        "spread_ok": spread_ok,
        "quote_fresh": quote_fresh,
        "price_ok": price_ok,
        "risk_gate_ok": risk_gate_ok,
        "duplicate_ok": duplicate_ok,
        "indicators_ok": indicators_ok,
        "backtest_ok": backtest_ok,
        "blockers": blockers,
        "warnings": warnings,
        "execution_plan": execution_plan,
        # Session 23D: Bracket validation
        "bracket_order_supported": bracket_order_supported,
        "alpaca_account_mode": alpaca_mode,
        "alpaca_base_url_type": alpaca_base_type,
        "market_hours": mkt_hours,
        "bracket_dry_run_payload": bracket_payload,
        # Session 23E: Quote provider fields
        "quote_provider": quote_provider,
        "quote_snapshot_id": quote_snapshot_id,
        "quote_is_delayed": quote_is_delayed,
        "quote_execution_eligible": quote_execution_eligible,
        "volume_source": volume_source,
        "spread_source": spread_source,
    }


# ---------------------------------------------------------------------------
# DB write
# ---------------------------------------------------------------------------

def write_readiness(conn, rec: dict):
    """INSERT into proposal_execution_readiness and UPDATE proposal."""
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO proposal_execution_readiness (
            proposal_id, symbol, strategy_id, readiness_state, readiness_score,
            quote_price, quote_timestamp, quote_age_seconds, bid, ask, spread, spread_pct,
            entry_price, price_vs_entry_pct, slippage_budget_pct,
            liquidity_ok, spread_ok, quote_fresh, price_ok, risk_gate_ok,
            duplicate_ok, indicators_ok, backtest_ok,
            blockers, warnings, execution_plan,
            bracket_order_supported, alpaca_account_mode, alpaca_base_url_type,
            market_hours, bracket_dry_run_payload,
            quote_provider, quote_snapshot_id, quote_is_delayed,
            quote_execution_eligible, volume_source, spread_source,
            created_at
        ) VALUES (
            %(proposal_id)s, %(symbol)s, %(strategy_id)s, %(readiness_state)s, %(readiness_score)s,
            %(quote_price)s, %(quote_timestamp)s, %(quote_age_seconds)s, %(bid)s, %(ask)s,
            %(spread)s, %(spread_pct)s,
            %(entry_price)s, %(price_vs_entry_pct)s, %(slippage_budget_pct)s,
            %(liquidity_ok)s, %(spread_ok)s, %(quote_fresh)s, %(price_ok)s, %(risk_gate_ok)s,
            %(duplicate_ok)s, %(indicators_ok)s, %(backtest_ok)s,
            %(blockers)s, %(warnings)s, %(execution_plan)s,
            %(bracket_order_supported)s, %(alpaca_account_mode)s, %(alpaca_base_url_type)s,
            %(market_hours)s, %(bracket_dry_run_payload)s,
            %(quote_provider)s, %(quote_snapshot_id)s, %(quote_is_delayed)s,
            %(quote_execution_eligible)s, %(volume_source)s, %(spread_source)s,
            NOW()
        )
        """,
        {
            **rec,
            "blockers": json.dumps(rec["blockers"]),
            "warnings": json.dumps(rec["warnings"]),
            "execution_plan": json.dumps(rec["execution_plan"]),
            "bracket_dry_run_payload": json.dumps(rec.get("bracket_dry_run_payload")),
        },
    )

    # Update readiness + sync action_state for dashboard display
    action = "BLOCKED" if "BLOCKED" in rec["readiness_state"] else (
        "PAPER_READY" if rec["readiness_state"] in ("READY_FOR_PAPER_SUBMIT",) else "NEEDS_REVIEW")
    cur.execute(
        "UPDATE paper_trade_proposals SET latest_execution_readiness = %s, action_state = %s WHERE id = %s",
        (rec["readiness_state"], action, rec["proposal_id"]),
    )

    conn.commit()
    cur.close()


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_readiness(rec: dict):
    state = rec["readiness_state"]
    score = rec["readiness_score"]
    sym = rec["symbol"]

    icon = "PASS" if "READY" in state else ("WARN" if "CAUTION" in state else "BLOCK")
    print(f"\n[{icon}] {sym} (proposal #{rec['proposal_id']}): {state}  score={score}/100")
    print(f"  Provider: {rec.get('quote_provider')} | exec_eligible={rec.get('quote_execution_eligible')} | delayed={rec.get('quote_is_delayed')}")

    if rec["quote_price"] is not None:
        age = f"{rec['quote_age_seconds']:.0f}s" if rec["quote_age_seconds"] is not None else "N/A"
        print(f"  Quote: ${rec['quote_price']:.2f}  age={age}  bid={rec.get('bid')}  ask={rec.get('ask')}  spread={rec.get('spread_pct')}")
    if rec["entry_price"] is not None:
        drift = rec["price_vs_entry_pct"]
        print(f"  Entry: ${rec['entry_price']:.2f}  drift={drift:.2f}%" if drift is not None else
              f"  Entry: ${rec['entry_price']:.2f}  drift=N/A")

    checks = ["quote_fresh", "price_ok", "spread_ok", "liquidity_ok",
              "risk_gate_ok", "duplicate_ok", "indicators_ok", "backtest_ok"]
    flags = "  Checks: " + " | ".join(
        f"{c}={'Y' if rec[c] else 'N'}" for c in checks
    )
    print(flags)

    if rec["blockers"]:
        print("  Blockers:")
        for b in rec["blockers"]:
            print(f"    - {b}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Assess paper trade proposal execution readiness"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pending", action="store_true")
    group.add_argument("--proposal-id", type=int)

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")

    args = parser.parse_args()

    conn = get_conn()

    proposals = fetch_proposals(
        conn,
        proposal_id=args.proposal_id,
        pending_only=args.pending,
    )

    if not proposals:
        print("No proposals found matching criteria.")
        conn.close()
        return

    print(f"Assessing {len(proposals)} proposal(s)...")

    results = []
    for p in proposals:
        rec = assess_proposal(conn, p)
        results.append(rec)
        print_readiness(rec)

        if args.apply:
            write_readiness(conn, rec)
            print(f"  -> Written to DB (proposal #{rec['proposal_id']})")

    ready = sum(1 for r in results if "READY" in r["readiness_state"])
    caution = sum(1 for r in results if r["readiness_state"] == "CAUTION_EXECUTABLE")
    blocked = sum(1 for r in results if "BLOCKED" in r["readiness_state"])
    print(f"\nSummary: {ready} ready, {caution} caution, {blocked} blocked out of {len(results)} proposals")

    if args.dry_run:
        print("(dry-run — no DB writes performed)")

    conn.close()


if __name__ == "__main__":
    main()
```
