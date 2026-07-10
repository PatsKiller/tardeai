#!/usr/bin/env python3
"""proposal_execution_readiness.py — Execution readiness assessment + funnel dashboard metrics.

Assessment (Session 23E): multi-provider quote hierarchy; proposal technical snapshots primary.
Dashboard (Jun 2026+): collect_execution_readiness / link audit / quote refresh for health API.

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
# Constants / thresholds
# ---------------------------------------------------------------------------
MAX_QUOTE_AGE_SECONDS = 300
MAX_PRICE_MOVE_FROM_ENTRY_PCT = 2.0
MIN_VOLUME = 100_000
MAX_SPREAD_PCT = 1.0  # 1% max spread for execution eligibility

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

# Strategy-specific requirements
STRATEGY_REQUIRES_ORB = {"momentum_scalp"}
STRATEGY_REQUIRES_VWAP = {"momentum_scalp", "gap_and_go"}
STRATEGY_REQUIRES_DAILY_STRUCTURE = {"swing_breakout"}

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
    if rg and str(rg).upper() in ("PASS", "TRUE", "APPROVED", "PASSED", "ADVISORY"):
        risk_gate_ok = True
    else:
        risk_gate_ok = False
        blockers.append(f"Risk gate result is '{rg}' — must be pass/approved/advisory")

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
    # 8. Technical snapshot gates (Session 23D)
    # -----------------------------------------------------------------------
    strategy_id = proposal.get("strategy_id", "")
    ts_orb_status = None
    if ts_row:
        ts_ema_align, ts_grade, ts_orb_status, ts_pm_status, \
            ts_vwap_dist, ts_atr, ts_fib_level, ts_fib_dist, ts_ohlcv_status, ts_computed = ts_row

        if ts_ema_align in ("BEARISH", "LONG_TERM_OVERHEAD"):
            warnings.append(f"CAUTION_EMA: EMA alignment is {ts_ema_align}")

        if strategy_id in STRATEGY_REQUIRES_ORB:
            if ts_orb_status == "NO_INTRADAY_DATA":
                blockers.append("BLOCKED_MISSING_INTRADAY_REQUIRED: momentum_scalp requires intraday data")
            elif ts_orb_status == "ORB_BREAKOUT_FAILED":
                warnings.append("CAUTION_ORB_FAILED: Opening range breakout failed")

        if ts_vwap_dist is not None and float(ts_vwap_dist) > 5:
            warnings.append(f"CAUTION_EXTENDED_ABOVE_VWAP: {ts_vwap_dist}% above VWAP")

        proposed_target1_val = float(proposal.get("proposed_target1") or 0)
        proposed_entry_val = float(proposal.get("proposed_entry") or 0)
        if ts_atr and proposed_entry_val and proposed_target1_val:
            target_distance = abs(proposed_target1_val - proposed_entry_val)
            atr_val = float(ts_atr)
            if atr_val > 0 and target_distance > 3 * atr_val:
                warnings.append(f"CAUTION_ATR_TARGET_TOO_FAR: Target {target_distance:.2f} > 3x ATR {atr_val:.2f}")

        if ts_fib_level and ts_fib_dist is not None and float(ts_fib_dist) < 2:
            warnings.append(f"INFO_NEAR_FIB: Near {ts_fib_level} ({ts_fib_dist}% away)")

        if ts_pm_status == "PREMARKET_HIGH_REJECTED":
            warnings.append("CAUTION_BELOW_PREMARKET_HIGH: Rejected at premarket high")

        if ts_grade == "TECH_WEAK":
            warnings.append("CAUTION_TECH_WEAK: Technical grade is WEAK")
        elif ts_grade == "TECH_INCOMPLETE":
            warnings.append("CAUTION_TECH_INCOMPLETE: Technical data incomplete")

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

    state = rec["readiness_state"]
    if state.startswith("READY"):
        action_state = "READY"
    elif state.startswith("CAUTION"):
        action_state = "CAUTION"
    elif state.startswith("BLOCKED"):
        action_state = "BLOCKED"
    else:
        action_state = state
    cur.execute(
        """UPDATE paper_trade_proposals
           SET latest_execution_readiness = %s,
               action_state = %s,
               action_label = %s,
               updated_at = NOW()
           WHERE id = %s""",
        (state, action_state, state[:500], rec["proposal_id"]),
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


# ---------------------------------------------------------------------------
# Dashboard / funnel metrics (health API — Jun 2026+)
# ---------------------------------------------------------------------------

from typing import Any


def _dash_conn():
    from db_adapter import _get_conn
    return _get_conn()


def _dash_rows(sql: str, params=None) -> list[dict]:
    conn = _dash_conn()
    if not conn:
        return []
    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or [])
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []


def collect_execution_readiness(*, since_days: int = 7) -> dict[str, Any]:
    """Dashboard payload: block reasons, revalidation mix, timing, link rate."""
    interval = f"{since_days} days"
    block_rows = _dash_rows(
        f"""SELECT COALESCE(NULLIF(TRIM(risk_gate_result), ''), 'UNKNOWN') AS gate,
                   COUNT(*) AS n
            FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}'
            GROUP BY 1 ORDER BY n DESC LIMIT 20"""
    )
    action_rows = _dash_rows(
        f"""SELECT COALESCE(NULLIF(TRIM(action_state), ''), 'none') AS action_state,
                   COUNT(*) AS n
            FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}'
              AND status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST', 'APPROVED')
            GROUP BY 1 ORDER BY n DESC"""
    )
    created = _dash_rows(
        f"SELECT COUNT(*) AS n FROM paper_trade_proposals WHERE created_at > NOW() - INTERVAL '{interval}'"
    )
    linked = _dash_rows(
        f"""SELECT COUNT(*) AS n FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}' AND paper_trade_id IS NOT NULL"""
    )
    approved = _dash_rows(
        f"""SELECT COUNT(*) AS n FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}'
              AND status IN ('APPROVED_FOR_PAPER_TEST', 'APPROVED')"""
    )
    pending = _dash_rows(
        """SELECT COUNT(*) AS n FROM paper_trade_proposals
           WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST', 'APPROVED')"""
    )
    broker_unrouted = _dash_rows(
        """SELECT COUNT(*) AS n FROM paper_trade_proposals
           WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST')
             AND (intended_broker ILIKE 'schwab%%' OR intended_broker ILIKE 'fidelity%%')
             AND live_submit_path IS NULL
             AND created_at < NOW() - INTERVAL '48 hours'"""
    )
    timing = _dash_rows(
        f"""SELECT
              ROUND(AVG(EXTRACT(EPOCH FROM (updated_at - created_at)) / 3600.0)
                    FILTER (WHERE status IN ('APPROVED_FOR_PAPER_TEST','APPROVED'))::numeric, 2) AS avg_hours_to_approve,
              ROUND(AVG(EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600.0)
                    FILTER (WHERE status IN ('PENDING','APPROVED_FOR_PAPER_TEST'))::numeric, 2) AS avg_pending_age_h
            FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}'"""
    )
    n_created = int((created[0] or {}).get("n") or 0)
    n_linked = int((linked[0] or {}).get("n") or 0)
    link_pct = round(100.0 * n_linked / max(n_created, 1), 1)
    blocks = {r["gate"]: int(r["n"]) for r in block_rows}
    price_dominated = sum(
        n for k, n in blocks.items()
        if k and any(x in str(k).upper() for x in ("PRICE", "DRIFT", "STALE", "MOVED"))
    )
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "since_days": since_days,
        "created": n_created,
        "approved": int((approved[0] or {}).get("n") or 0),
        "linked_to_execution": n_linked,
        "link_rate_pct": link_pct,
        "pending_now": int((pending[0] or {}).get("n") or 0),
        "broker_unrouted_48h": int((broker_unrouted[0] or {}).get("n") or 0),
        "risk_gate_blocks": blocks,
        "action_state_counts": {r["action_state"]: int(r["n"]) for r in action_rows},
        "avg_hours_to_approve": float((timing[0] or {}).get("avg_hours_to_approve") or 0),
        "avg_pending_age_h": float((timing[0] or {}).get("avg_pending_age_h") or 0),
        "price_block_dominant": price_dominated > sum(blocks.values()) * 0.25 if blocks else False,
        "target_link_rate_pct": float(os.getenv("PROPOSAL_TARGET_LINK_RATE_PCT", "15")),
    }


def collect_execution_link_audit(*, since_days: int = 5) -> dict[str, Any]:
    """Closed-loop: created → approved → execution-linked → closed."""
    interval = f"{since_days} days"
    funnel = _dash_rows(
        f"""SELECT
              COUNT(*) AS created,
              COUNT(*) FILTER (WHERE status IN ('APPROVED_FOR_PAPER_TEST','APPROVED')) AS approved,
              COUNT(*) FILTER (WHERE paper_trade_id IS NOT NULL) AS execution_linked,
              COUNT(*) FILTER (WHERE live_submit_path IS NOT NULL) AS live_submit_tagged,
              COUNT(*) FILTER (WHERE status = 'EXPIRED') AS expired,
              COUNT(*) FILTER (WHERE status = 'REJECTED') AS rejected
            FROM paper_trade_proposals
            WHERE created_at > NOW() - INTERVAL '{interval}'"""
    )
    closed = _dash_rows(
        f"""SELECT COUNT(DISTINCT p.id) AS n
            FROM paper_trade_proposals p
            JOIN paper_trades t ON t.proposal_id = p.id
            WHERE p.created_at > NOW() - INTERVAL '{interval}'
              AND t.lifecycle_state = 'closed'"""
    )
    f = funnel[0] if funnel else {}
    created = int(f.get("created") or 0)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_days": since_days,
        "created": created,
        "approved": int(f.get("approved") or 0),
        "execution_linked": int(f.get("execution_linked") or 0),
        "live_submit_tagged": int(f.get("live_submit_tagged") or 0),
        "closed_trades": int((closed[0] or {}).get("n") or 0),
        "expired": int(f.get("expired") or 0),
        "rejected": int(f.get("rejected") or 0),
        "approval_rate_pct": round(100 * int(f.get("approved") or 0) / max(created, 1), 1),
        "execution_link_rate_pct": round(100 * int(f.get("execution_linked") or 0) / max(created, 1), 1),
        "close_rate_pct": round(100 * int((closed[0] or {}).get("n") or 0) / max(created, 1), 1),
    }


def refresh_stale_proposal_quotes(*, limit: int = 25) -> dict[str, Any]:
    """Refresh live quotes for active proposals before revalidation (no orders)."""
    props = _dash_rows(
        """SELECT id, symbol FROM paper_trade_proposals
           WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST', 'APPROVED')
           ORDER BY updated_at ASC NULLS FIRST LIMIT %s""",
        [limit],
    )
    refreshed, errors = 0, []
    for p in props:
        try:
            from market_quote_provider import check_fresh_quote
            fq = check_fresh_quote(p["symbol"])
            if fq.get("ok") and fq.get("last_price"):
                conn = _dash_conn()
                cur = conn.cursor()
                cur.execute(
                    """UPDATE paper_trade_proposals
                       SET current_price=%s, last_price_source=%s, last_price_checked_at=NOW(), updated_at=NOW()
                       WHERE id=%s""",
                    (fq["last_price"], fq.get("provider") or "refresh", p["id"]),
                )
                conn.commit()
                refreshed += 1
        except Exception as e:
            errors.append(f"{p.get('symbol')}: {e}")
    return {"refreshed": refreshed, "checked": len(props), "errors": errors[:5]}


if __name__ == "__main__":
    main()
