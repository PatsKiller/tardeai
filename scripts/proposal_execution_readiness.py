#!/usr/bin/env python3
"""proposal_execution_readiness.py — Determine if a paper trade proposal is executable now.

Reads proposal data, market quotes, indicator cache, and open positions to produce
a readiness assessment with score, blockers, warnings, and an execution plan.

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

FINVIZ_CACHE_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "finviz_quote_cache.json"

READINESS_STATES = [
    "READY_FOR_PAPER_SUBMIT",
    "READY_ORB_CONFIRMED",
    "CAUTION_EXECUTABLE",
    "CAUTION_EXTENDED_ABOVE_VWAP",
    "CAUTION_ATR_TARGET_TOO_FAR",
    "CAUTION_BELOW_PREMARKET_HIGH",
    "BLOCKED_STALE_QUOTE",
    "BLOCKED_SPREAD",
    "BLOCKED_PRICE_MOVED",
    "BLOCKED_RISK_GATE",
    "BLOCKED_DUPLICATE",
    "BLOCKED_MISSING_TECHNICALS",
    "BLOCKED_MISSING_INTRADAY_REQUIRED",
    "BLOCKED_BACKTEST_INSUFFICIENT",
    "BLOCKED_LIVE_DISABLED",
]

# Strategy-specific ORB requirements
STRATEGY_REQUIRES_ORB = {"momentum_scalp"}
STRATEGY_REQUIRES_VWAP = {"momentum_scalp", "gap_and_go"}
STRATEGY_REQUIRES_DAILY_STRUCTURE = {"swing_breakout"}

LIVE_DISABLED_WARNING = "Live trading disabled pending six-month paper validation"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_finviz_cache() -> dict:
    """Load finviz_quote_cache.json and return dict keyed by symbol."""
    if not FINVIZ_CACHE_PATH.exists():
        return {}
    with open(FINVIZ_CACHE_PATH, "r") as f:
        return json.load(f)


def parse_finviz_timestamp(ts_str: str) -> datetime:
    """Parse '2026-05-07 11:15:00 ET' style timestamps into UTC-aware datetime."""
    # Strip timezone label and parse
    clean = ts_str.strip()
    for suffix in (" ET", " EST", " EDT"):
        if clean.endswith(suffix):
            clean = clean[: -len(suffix)]
            break
    dt_naive = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
    # ET is UTC-4 (EDT) or UTC-5 (EST); approximate as UTC-4 during market hours
    from datetime import timedelta
    dt_utc = dt_naive + timedelta(hours=4)
    return dt_utc.replace(tzinfo=timezone.utc)


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
    """Return True if there is an open paper trade for this symbol."""
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM paper_trades WHERE symbol = %s AND status = 'open'",
        (symbol,),
    )
    count = cur.fetchone()[0]
    cur.close()
    return count > 0


def check_indicator_confluence(conn, symbol: str) -> bool:
    """Return True if indicator_confluence_cache has a row for this symbol."""
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM indicator_confluence_cache WHERE symbol = %s",
        (symbol,),
    )
    count = cur.fetchone()[0]
    cur.close()
    return count > 0


# ---------------------------------------------------------------------------
# Core readiness assessment
# ---------------------------------------------------------------------------

def assess_proposal(conn, proposal: dict, finviz_cache: dict) -> dict:
    """Run all readiness checks for a single proposal. Return readiness record dict."""
    symbol = proposal["symbol"]
    quote = finviz_cache.get(symbol, {})

    blockers = []
    warnings = []

    # Initialize check flags
    quote_fresh = False
    price_ok = False
    spread_ok = True  # default, see below
    liquidity_ok = False
    risk_gate_ok = False
    duplicate_ok = False
    indicators_ok = False
    backtest_ok = True  # default pass — no backtest gate yet

    quote_price = quote.get("price")
    quote_age_seconds = None
    quote_timestamp = None
    bid = None
    ask = None
    spread = None
    spread_pct = None
    price_vs_entry_pct = None

    # -----------------------------------------------------------------------
    # 1. Quote freshness
    # -----------------------------------------------------------------------
    last_updated_str = quote.get("last_updated")
    if last_updated_str and quote_price is not None:
        try:
            qt = parse_finviz_timestamp(last_updated_str)
            quote_timestamp = qt.isoformat()
            now_utc = datetime.now(timezone.utc)
            quote_age_seconds = (now_utc - qt).total_seconds()

            max_age = MAX_QUOTE_AGE_SECONDS
            if not is_market_hours():
                max_age = 86400  # relax to 24 h after hours

            if quote_age_seconds <= max_age:
                quote_fresh = True
            else:
                blockers.append(
                    f"Quote age {quote_age_seconds:.0f}s exceeds max {max_age}s"
                )
        except Exception as e:
            blockers.append(f"Could not parse quote timestamp: {e}")
    else:
        blockers.append(f"No quote data found for {symbol} in finviz cache")

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
                f"(quote={quote_price}, entry={proposed_entry})"
            )
    elif proposed_entry is None:
        blockers.append("Proposal has no proposed_entry")

    # -----------------------------------------------------------------------
    # 3. Spread check (Finviz has no bid/ask)
    # -----------------------------------------------------------------------
    # spread_ok stays True; add informational warning
    warnings.append("Spread not available from Finviz — spread_ok defaulted to True")

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
    # 6. Technical snapshot present
    # -----------------------------------------------------------------------
    if check_indicator_confluence(conn, symbol):
        indicators_ok = True
    else:
        indicators_ok = False
        blockers.append(f"No indicator confluence data for {symbol}")

    # -----------------------------------------------------------------------
    # 7. Volume / liquidity
    # -----------------------------------------------------------------------
    volume = quote.get("volume")
    if volume is not None and volume > MIN_VOLUME:
        liquidity_ok = True
    else:
        liquidity_ok = False
        blockers.append(
            f"Volume {volume} below minimum {MIN_VOLUME}"
            if volume is not None
            else f"No volume data for {symbol}"
        )

    # -----------------------------------------------------------------------
    # 8. Technical snapshot gates (Session 23D)
    # -----------------------------------------------------------------------
    tech_ok = True
    strategy_id = proposal.get("strategy_id", "")
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT ema_alignment, technical_grade, opening_range_status, premarket_status,
                   vwap_distance_pct, atr_14, nearest_fib_level, nearest_fib_distance_pct,
                   ohlcv_data_status
            FROM proposal_technical_snapshots
            WHERE symbol = %s ORDER BY computed_at DESC LIMIT 1
        """, (symbol,))
        ts_row = cur.fetchone()
        cur.close()

        if ts_row:
            ts_ema_align, ts_grade, ts_orb_status, ts_pm_status, \
                ts_vwap_dist, ts_atr, ts_fib_level, ts_fib_dist, ts_ohlcv_status = ts_row

            # EMA alignment gate
            if ts_ema_align in ("BEARISH", "LONG_TERM_OVERHEAD"):
                warnings.append(f"CAUTION_EMA: EMA alignment is {ts_ema_align}")

            # ORB gate — only required for momentum_scalp
            if strategy_id in STRATEGY_REQUIRES_ORB:
                if ts_orb_status == "NO_INTRADAY_DATA":
                    blockers.append("BLOCKED_MISSING_INTRADAY_REQUIRED: momentum_scalp requires intraday data")
                    tech_ok = False
                elif ts_orb_status == "ORB_BREAKOUT_FAILED":
                    warnings.append("CAUTION_ORB_FAILED: Opening range breakout failed")

            # VWAP extension warning
            if ts_vwap_dist is not None and float(ts_vwap_dist) > 5:
                warnings.append(f"CAUTION_EXTENDED_ABOVE_VWAP: {ts_vwap_dist}% above VWAP")

            # ATR target feasibility
            proposed_target1 = float(proposal.get("proposed_target1") or 0)
            proposed_entry = float(proposal.get("proposed_entry") or 0)
            if ts_atr and proposed_entry and proposed_target1:
                target_distance = abs(proposed_target1 - proposed_entry)
                atr_val = float(ts_atr)
                if atr_val > 0 and target_distance > 3 * atr_val:
                    warnings.append(f"CAUTION_ATR_TARGET_TOO_FAR: Target {target_distance:.2f} > 3x ATR {atr_val:.2f}")

            # Fib proximity note
            if ts_fib_level and ts_fib_dist is not None and float(ts_fib_dist) < 2:
                warnings.append(f"INFO_NEAR_FIB: Near {ts_fib_level} ({ts_fib_dist}% away)")

            # Premarket status
            if ts_pm_status == "PREMARKET_HIGH_REJECTED":
                warnings.append("CAUTION_BELOW_PREMARKET_HIGH: Rejected at premarket high")

            # Technical grade
            if ts_grade == "TECH_WEAK":
                warnings.append("CAUTION_TECH_WEAK: Technical grade is WEAK")
            elif ts_grade == "TECH_INCOMPLETE":
                warnings.append("CAUTION_TECH_INCOMPLETE: Technical data incomplete")
        else:
            warnings.append("NO_TECHNICAL_SNAPSHOT: No proposal technical snapshot available")
    except Exception as e:
        warnings.append(f"TECH_GATE_ERROR: {str(e)[:100]}")

    # -----------------------------------------------------------------------
    # Paper-only warning (always)
    # -----------------------------------------------------------------------
    warnings.append(LIVE_DISABLED_WARNING)

    # -----------------------------------------------------------------------
    # Backtest gate — future placeholder, passes for now
    # -----------------------------------------------------------------------
    # backtest_ok already True; add a note
    warnings.append("Backtest gate not yet implemented — defaulted to pass")

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
        # Pick the first blocker category as primary state
        state_map = {
            "Quote age": "BLOCKED_STALE_QUOTE",
            "No quote data": "BLOCKED_STALE_QUOTE",
            "Could not parse": "BLOCKED_STALE_QUOTE",
            "Price moved": "BLOCKED_PRICE_MOVED",
            "Open paper trade": "BLOCKED_DUPLICATE",
            "Risk gate": "BLOCKED_RISK_GATE",
            "No indicator": "BLOCKED_MISSING_TECHNICALS",
            "Volume": "BLOCKED_SPREAD",  # liquidity-related
            "No volume": "BLOCKED_SPREAD",
            "Spread": "BLOCKED_SPREAD",
            "Backtest": "BLOCKED_BACKTEST_INSUFFICIENT",
        }
        readiness_state = "BLOCKED_STALE_QUOTE"  # fallback
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

    slippage_budget_pct = 0.10  # default 10 bps

    # Session 23D: Bracket validation fields
    bracket_order_supported = True  # Alpaca paper supports brackets
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
        try:
            if ts_row and ts_orb_status == "ORB_BREAKOUT_CONFIRMED":
                readiness_state = "READY_ORB_CONFIRMED"
        except NameError:
            pass

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

    # Update proposal with latest readiness state
    cur.execute(
        """
        UPDATE paper_trade_proposals
           SET latest_execution_readiness = %s
         WHERE id = %s
        """,
        (rec["readiness_state"], rec["proposal_id"]),
    )

    conn.commit()
    cur.close()


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def print_readiness(rec: dict):
    """Pretty-print a readiness record."""
    state = rec["readiness_state"]
    score = rec["readiness_score"]
    sym = rec["symbol"]

    icon = "PASS" if "READY" in state else ("WARN" if "CAUTION" in state else "BLOCK")
    print(f"\n[{icon}] {sym} (proposal #{rec['proposal_id']}): {state}  score={score}/100")

    if rec["quote_price"] is not None:
        print(f"  Quote: ${rec['quote_price']:.2f}  age={rec['quote_age_seconds']:.0f}s"
              if rec["quote_age_seconds"] is not None
              else f"  Quote: ${rec['quote_price']:.2f}  age=N/A")
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
    if rec["warnings"]:
        print("  Warnings:")
        for w in rec["warnings"]:
            print(f"    - {w}")

    print(f"  Execution plan: {json.dumps(rec['execution_plan'], indent=2)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Assess paper trade proposal execution readiness"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pending", action="store_true", help="Assess all pending proposals")
    group.add_argument("--proposal-id", type=int, help="Assess a specific proposal by ID")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Display results only, do not write to DB")
    mode.add_argument("--apply", action="store_true", help="Write results to DB")

    args = parser.parse_args()

    conn = get_conn()
    finviz_cache = load_finviz_cache()

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
        rec = assess_proposal(conn, p, finviz_cache)
        results.append(rec)
        print_readiness(rec)

        if args.apply:
            write_readiness(conn, rec)
            print(f"  -> Written to DB (proposal #{rec['proposal_id']})")

    # Summary
    ready = sum(1 for r in results if r["readiness_state"] == "READY_FOR_PAPER_SUBMIT")
    caution = sum(1 for r in results if r["readiness_state"] == "CAUTION_EXECUTABLE")
    blocked = sum(1 for r in results if "BLOCKED" in r["readiness_state"])
    print(f"\nSummary: {ready} ready, {caution} caution, {blocked} blocked out of {len(results)} proposals")

    if args.dry_run:
        print("(dry-run — no DB writes performed)")

    conn.close()


if __name__ == "__main__":
    main()
