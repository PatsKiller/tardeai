#!/usr/bin/env python3
"""paper_trade_logger.py — Paper trade logging module for Trade AI v12.

Handles parsing /pt commands, opening/closing PAPER TRADES,
PnL tracking, and Telegram response formatting.

PAPER ACCOUNTS ONLY. Live accounts are blocked at parse time.
Risk gate is fail-closed for all paper trade operations.
"""
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn
from risk_gate import RiskGate, RiskDecision
from market_quote_provider import get_best_quote

log = logging.getLogger(__name__)

# ── Account configuration (broker-agnostic) ────────────────────────────────
def _default_account():
    try:
        from broker_config import get_default_paper_account
        return get_default_paper_account()
    except Exception:
        import os
        return os.environ.get("DEFAULT_PAPER_ACCOUNT", "paper")

# Account normalization: map legacy names to canonical account labels
VALID_PAPER_ACCOUNTS = {}  # populated dynamically from accounts table
BLOCKED_ACCOUNTS = set()   # populated dynamically — live accounts blocked for paper
try:
    from broker_config import get_all_accounts
    for _a in get_all_accounts():
        if _a.get("mode") == "paper":
            VALID_PAPER_ACCOUNTS[_a["account_label"]] = _a["account_label"]
            VALID_PAPER_ACCOUNTS[_a.get("broker", "")] = _a["account_label"]
        elif _a.get("mode") == "live":
            BLOCKED_ACCOUNTS.add(_a["account_label"])
except Exception:
    pass
DEFAULT_ACCOUNT = _default_account()


# ─────────────────────────────────────────────────────────────────────────────
# 1. parse_pt_command
# ─────────────────────────────────────────────────────────────────────────────
def parse_pt_command(text: str) -> tuple:
    """Parse a /pt command string.

    Formats:
        SYMBOL auto [account]
        SYMBOL shares entry stop target [account]

    Returns (success, params_dict, error_message).
    params_dict keys: symbol, shares, entry, stop, target, account, auto
    """
    text = (text or "").strip()
    if not text:
        return False, {}, "Empty command. Usage: /pt SYMBOL auto  or  /pt SYMBOL shares entry stop target [account]"

    parts = text.split()
    if len(parts) < 2:
        return False, {}, "Not enough arguments. Usage: /pt SYMBOL auto  or  /pt SYMBOL shares entry stop target [account]"

    symbol = parts[0].upper()

    # Detect auto mode
    if parts[1].lower() == "auto":
        account_raw = parts[2].lower() if len(parts) >= 3 else None
        account = _resolve_account(account_raw)
        if account is None:
            if account_raw and account_raw in BLOCKED_ACCOUNTS:
                return False, {}, f"BLOCKED: '{account_raw}' is a LIVE account. PAPER TRADE accounts only."
            return False, {}, f"Unknown account '{account_raw}'. Valid: {', '.join(sorted(VALID_PAPER_ACCOUNTS.keys()))}"
        return True, {
            "symbol": symbol,
            "shares": None,
            "entry": None,
            "stop": None,
            "target": None,
            "account": account,
            "auto": True,
        }, ""

    # Manual mode: SYMBOL shares entry stop target [account]
    if len(parts) < 5:
        return False, {}, "Manual format needs 5 args: SYMBOL shares entry stop target [account]"

    try:
        shares = int(parts[1])
        entry = float(parts[2])
        stop = float(parts[3])
        target = float(parts[4])
    except ValueError:
        return False, {}, "Invalid numbers. Usage: /pt SYMBOL shares entry stop target [account]"

    account_raw = parts[5].lower() if len(parts) >= 6 else None
    account = _resolve_account(account_raw)
    if account is None:
        if account_raw and account_raw in BLOCKED_ACCOUNTS:
            return False, {}, f"BLOCKED: '{account_raw}' is a LIVE account. PAPER TRADE accounts only."
        return False, {}, f"Unknown account '{account_raw}'. Valid: {', '.join(sorted(VALID_PAPER_ACCOUNTS.keys()))}"

    return True, {
        "symbol": symbol,
        "shares": shares,
        "entry": entry,
        "stop": stop,
        "target": target,
        "account": account,
        "auto": False,
    }, ""


def _resolve_account(raw: str | None) -> str | None:
    """Map user-supplied account name to canonical paper account.
    Returns None if the account is unknown or blocked."""
    if raw is None:
        return DEFAULT_ACCOUNT
    raw = raw.lower()
    if raw in BLOCKED_ACCOUNTS:
        return None
    return VALID_PAPER_ACCOUNTS.get(raw)


# ─────────────────────────────────────────────────────────────────────────────
# 1b. Market context at trade entry
# ─────────────────────────────────────────────────────────────────────────────
def _get_entry_regime(conn) -> dict:
    """Fetch current market regime and VIX for trade entry context."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT regime_label, volatility_state, trend_state, breadth_state
            FROM market_regime_snapshots
            ORDER BY created_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        regime = row[0] if row else None

        # Try to get VIX from indicator cache or regime indicators
        vix = None
        cur.execute("""
            SELECT value FROM market_regime_indicators
            WHERE indicator_key = 'vix_close' OR indicator_key = 'vix'
            ORDER BY created_at DESC LIMIT 1
        """)
        vix_row = cur.fetchone()
        if vix_row:
            vix = float(vix_row[0])
        return {"regime": regime, "vix": vix}
    except Exception:
        return {"regime": None, "vix": None}


# ─────────────────────────────────────────────────────────────────────────────
# 2. open_paper_trade
# ─────────────────────────────────────────────────────────────────────────────
def open_paper_trade(params: dict) -> dict:
    """Open a PAPER TRADE from parsed /pt params.

    Steps:
        1. Look up trade plan if auto mode.
        2. Call risk gate (fail-closed).
        3. Insert into paper_trades.
        4. Write audit_log.

    Returns dict with success, trade_id, message.
    """
    conn = get_conn()
    try:
        symbol = params["symbol"]
        account = params["account"]
        auto = params.get("auto", False)

        # ── 1. Resolve trade details ────────────────────────────────────
        trade_plan = None
        strategy_id = None
        signal_id = None
        trade_plan_id = None

        if auto:
            plan = _lookup_trade_plan(conn, symbol)
            if plan is None:
                return {"success": False, "message": f"No recent trade plan found for {symbol}. Use manual format: /pt {symbol} shares entry stop target [account]"}
            trade_plan = plan
            params["shares"] = plan["shares"]
            params["entry"] = plan["entry"]
            params["stop"] = plan["stop"]
            params["target"] = plan["target"]
            strategy_id = plan.get("strategy_id")
            signal_id = plan.get("signal_id")
            trade_plan_id = plan.get("trade_plan_id")
        else:
            # Try to find matching trade plan for risk gate context
            trade_plan = {
                "shares": params["shares"],
                "entry": params["entry"],
                "stop": params["stop"],
                "target": params["target"],
            }

        shares = params["shares"]
        entry = params["entry"]
        stop = params["stop"]
        target = params["target"]
        dollar_size = round(shares * entry, 2)
        dollar_risk = round(abs(entry - stop) * shares, 2)

        # ── 2. Risk gate (fail-closed) ──────────────────────────────────
        try:
            rg = RiskGate(conn)
            decision = rg.check(
                symbol=symbol,
                strategy_id=strategy_id or "",
                trade_plan=trade_plan,
                account=account,
                mode="paper",
                action_context="paper_trade",
                extra={},
            )
        except Exception as e:
            log.error("Risk gate error for %s: %s", symbol, e)
            decision = RiskDecision(
                approved=False,
                result="RISK_GATE_ERROR",
                reason_codes=["risk_gate_exception"],
                reason_text=str(e),
            )

        if not decision.approved:
            _write_audit(conn, "paper_trade_blocked", symbol, {
                "reason": decision.result,
                "codes": decision.reason_codes,
                "account": account,
            })
            return {
                "success": False,
                "message": (
                    f"PAPER TRADE BLOCKED by risk gate: {decision.result}\n"
                    f"Reasons: {', '.join(decision.reason_codes)}"
                ),
            }

        # ── 3. Insert paper_trades row ──────────────────────────────────
        now = datetime.now(timezone.utc)
        entry_ctx = _get_entry_regime(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO paper_trades (
                signal_id, strategy_id, symbol, account,
                entry_price, entry_time, shares, dollar_size,
                stop_loss, target_1, dollar_risk,
                trade_plan_id, planned_entry, planned_stop,
                risk_gate_result, risk_gate_reason_codes,
                market_regime, vix_at_entry,
                status, opened_via, logged_by,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s,
                'open', 'telegram', 'paper_trade_logger',
                %s, %s
            ) RETURNING id
        """, (
            signal_id, strategy_id, symbol, account,
            entry, now, shares, dollar_size,
            stop, target, dollar_risk,
            trade_plan_id, entry, stop,
            decision.result, decision.reason_codes,
            entry_ctx["regime"], entry_ctx["vix"],
            now, now,
        ))
        trade_id = cur.fetchone()[0]

        # ── 4. Audit log ───────────────────────────────────────────────
        _write_audit(conn, "paper_trade_opened", symbol, {
            "trade_id": trade_id,
            "account": account,
            "entry": entry,
            "shares": shares,
            "stop": stop,
            "target": target,
            "dollar_size": dollar_size,
            "dollar_risk": dollar_risk,
            "risk_gate": decision.result,
            "auto": auto,
        })

        conn.commit()

        return {
            "success": True,
            "trade_id": trade_id,
            "trade": {
                "symbol": symbol,
                "shares": shares,
                "entry": entry,
                "stop": stop,
                "target": target,
                "account": account,
                "dollar_size": dollar_size,
                "dollar_risk": dollar_risk,
            },
            "message": format_open_response({
                "symbol": symbol,
                "shares": shares,
                "entry": entry,
                "stop": stop,
                "target": target,
                "account": account,
                "dollar_size": dollar_size,
                "dollar_risk": dollar_risk,
                "trade_id": trade_id,
                "auto": auto,
            }),
        }
    except Exception as e:
        conn.rollback()
        log.exception("Failed to open PAPER TRADE for %s", params.get("symbol"))
        return {"success": False, "message": f"Error opening PAPER TRADE: {e}"}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 3. close_paper_trade
# ─────────────────────────────────────────────────────────────────────────────
def close_paper_trade(symbol: str, exit_price: float, reason: str = "manual") -> dict:
    """Close an open PAPER TRADE for *symbol*.

    Calculates PnL, sets verdict, updates paper_trades, inserts
    agent_recommendation_outcomes, writes audit_log.

    Returns dict with success/message.
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        symbol = symbol.upper()

        # Find open trade
        cur.execute("""
            SELECT id, entry_price, entry_time, shares, strategy_id, signal_id,
                   stop_loss, target_1, account, dollar_size, dollar_risk
            FROM paper_trades
            WHERE symbol = %s AND status = 'open'
            ORDER BY created_at DESC LIMIT 1
        """, (symbol,))
        row = cur.fetchone()
        if not row:
            return {"success": False, "message": f"No open PAPER TRADE found for {symbol}."}

        (trade_id, entry_price, entry_time, shares, strategy_id,
         signal_id, stop_loss, target_1, account, dollar_size, dollar_risk) = row

        now = datetime.now(timezone.utc)
        pnl = round((exit_price - entry_price) * shares, 2)
        pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 2) if entry_price else 0.0
        hold_time_min = round((now - entry_time).total_seconds() / 60, 1) if entry_time else None

        # R-multiple
        risk_per_share = abs(entry_price - stop_loss) if stop_loss else None
        r_multiple = round(pnl / (risk_per_share * shares), 2) if risk_per_share and risk_per_share > 0 else None

        # Verdict
        if pnl > 0:
            verdict = "CORRECT"
        elif pnl < 0:
            verdict = "WRONG"
        else:
            verdict = "NEUTRAL"

        # Update paper_trades
        cur.execute("""
            UPDATE paper_trades SET
                exit_price = %s,
                exit_time = %s,
                exit_reason = %s,
                pnl = %s,
                pnl_pct = %s,
                hold_time_min = %s,
                outcome_verdict = %s,
                status = 'closed',
                lifecycle_state = 'closed',
                closed_at = %s,
                closed_via = 'telegram',
                updated_at = %s
            WHERE id = %s
        """, (exit_price, now, reason, pnl, pnl_pct, hold_time_min,
              verdict, now, now, trade_id))

        # Insert agent_recommendation_outcomes
        hold_days = round((now - entry_time).total_seconds() / 86400, 2) if entry_time else None
        cur.execute("""
            INSERT INTO agent_recommendation_outcomes (
                agent_name, symbol, recommendation, confidence,
                strategy_type, recommendation_date,
                trade_id, entry_date, exit_date,
                entry_price, exit_price,
                realized_pnl, pnl_pct, hold_days,
                verdict, scoring_method, scored_at, notes
            ) VALUES (
                'paper_trade_logger', %s, 'BUY', NULL,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, 'paper_trade_close', %s, %s
            )
        """, (
            symbol, strategy_id, entry_time,
            trade_id, entry_time, now,
            entry_price, exit_price,
            pnl, pnl_pct, hold_days,
            verdict, now,
            f"PAPER TRADE closed via telegram. Reason: {reason}",
        ))

        # Audit log
        _write_audit(conn, "paper_trade_closed", symbol, {
            "trade_id": trade_id,
            "entry_price": float(entry_price),
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "verdict": verdict,
            "r_multiple": r_multiple,
            "hold_time_min": hold_time_min,
            "reason": reason,
        })

        conn.commit()

        # Agent curation hooks (non-blocking)
        try:
            from agent_curation_hooks import on_paper_trade_closed
            on_paper_trade_closed(conn, trade_id)
            conn.commit()
        except Exception as e:
            log.warning(f"Curation hooks failed for {symbol}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

        result = {
            "success": True,
            "trade_id": trade_id,
            "symbol": symbol,
            "entry_price": float(entry_price),
            "exit_price": exit_price,
            "shares": shares,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "verdict": verdict,
            "r_multiple": r_multiple,
            "hold_time_min": hold_time_min,
            "reason": reason,
        }
        result["message"] = format_close_response(result)
        return result

    except Exception as e:
        conn.rollback()
        log.exception("Failed to close PAPER TRADE for %s", symbol)
        return {"success": False, "message": f"Error closing PAPER TRADE: {e}"}
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 4. get_open_positions
# ─────────────────────────────────────────────────────────────────────────────
def get_open_positions() -> list:
    """Return list of open PAPER TRADE position dicts."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, symbol, account, entry_price, entry_time, shares,
                   dollar_size, stop_loss, target_1, dollar_risk, strategy_id,
                   current_price, unrealized_pnl
            FROM paper_trades
            WHERE status = 'open'
            ORDER BY entry_time DESC
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 5. get_pnl_summary
# ─────────────────────────────────────────────────────────────────────────────
def get_pnl_summary() -> dict:
    """Return PAPER TRADE PnL summary: today realized, total realized,
    open count, win/loss count, win rate."""
    conn = get_conn()
    try:
        cur = conn.cursor()

        # Today's realized PnL
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        cur.execute("""
            SELECT COALESCE(SUM(pnl), 0)
            FROM paper_trades
            WHERE status = 'closed' AND closed_at >= %s
        """, (today_start,))
        today_realized = float(cur.fetchone()[0])

        # Total realized PnL
        cur.execute("""
            SELECT COALESCE(SUM(pnl), 0)
            FROM paper_trades
            WHERE status = 'closed'
        """)
        total_realized = float(cur.fetchone()[0])

        # Open count
        cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status = 'open'")
        open_count = cur.fetchone()[0]

        # Win / loss
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE pnl > 0) AS wins,
                COUNT(*) FILTER (WHERE pnl < 0) AS losses,
                COUNT(*) FILTER (WHERE pnl = 0) AS neutral,
                COUNT(*) AS total
            FROM paper_trades
            WHERE status = 'closed'
        """)
        wins, losses, neutral, total = cur.fetchone()
        win_rate = round((wins / total) * 100, 1) if total > 0 else 0.0

        return {
            "today_realized": today_realized,
            "total_realized": total_realized,
            "open_count": open_count,
            "wins": wins,
            "losses": losses,
            "neutral": neutral,
            "total_closed": total,
            "win_rate": win_rate,
        }
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 6–9. Telegram formatters
# ─────────────────────────────────────────────────────────────────────────────
def format_open_response(trade: dict) -> str:
    """Format Telegram message for an opened PAPER TRADE."""
    mode_label = "AUTO" if trade.get("auto") else "MANUAL"
    return (
        f"PAPER TRADE OPENED ({mode_label})\n"
        f"{'='*30}\n"
        f"Symbol:  {trade['symbol']}\n"
        f"Account: {trade['account']}\n"
        f"Shares:  {trade['shares']}\n"
        f"Entry:   ${trade['entry']:.2f}\n"
        f"Stop:    ${trade['stop']:.2f}\n"
        f"Target:  ${trade['target']:.2f}\n"
        f"Size:    ${trade['dollar_size']:,.2f}\n"
        f"Risk:    ${trade['dollar_risk']:,.2f}\n"
        f"Trade #: {trade['trade_id']}"
    )


def format_close_response(result: dict) -> str:
    """Format Telegram message for a closed PAPER TRADE."""
    emoji = "+" if result["pnl"] >= 0 else ""
    r_str = f"  R: {result['r_multiple']:.1f}R" if result.get("r_multiple") is not None else ""
    return (
        f"PAPER TRADE CLOSED\n"
        f"{'='*30}\n"
        f"Symbol:  {result['symbol']}\n"
        f"Entry:   ${result['entry_price']:.2f}\n"
        f"Exit:    ${result['exit_price']:.2f}\n"
        f"Shares:  {result['shares']}\n"
        f"PnL:     {emoji}${result['pnl']:,.2f} ({emoji}{result['pnl_pct']:.1f}%){r_str}\n"
        f"Verdict: {result['verdict']}\n"
        f"Hold:    {result.get('hold_time_min', '?')} min\n"
        f"Reason:  {result['reason']}\n"
        f"Trade #: {result['trade_id']}"
    )


def format_positions_response(positions: list) -> str:
    """Format /ptopen response listing open PAPER TRADE positions."""
    if not positions:
        return "No open PAPER TRADE positions."

    lines = [f"OPEN PAPER TRADES ({len(positions)})", "=" * 30]
    for p in positions:
        entry = float(p.get("entry_price", 0))
        current = float(p["current_price"]) if p.get("current_price") else None
        unrealized = float(p["unrealized_pnl"]) if p.get("unrealized_pnl") else None
        price_str = f"${current:.2f}" if current else "N/A"
        pnl_str = f"${unrealized:+,.2f}" if unrealized is not None else "N/A"
        lines.append(
            f"  {p['symbol']}  {p['shares']}sh @ ${entry:.2f}  "
            f"now {price_str}  PnL {pnl_str}  [{p['account']}]"
        )
    return "\n".join(lines)


def format_pnl_response(summary: dict) -> str:
    """Format /ptpnl summary response."""
    return (
        f"PAPER TRADE PnL SUMMARY\n"
        f"{'='*30}\n"
        f"Today realized:  ${summary['today_realized']:+,.2f}\n"
        f"Total realized:  ${summary['total_realized']:+,.2f}\n"
        f"Open positions:  {summary['open_count']}\n"
        f"Closed trades:   {summary['total_closed']}\n"
        f"  Wins:   {summary['wins']}   Losses: {summary['losses']}   Neutral: {summary['neutral']}\n"
        f"Win rate:        {summary['win_rate']:.1f}%"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────
def _lookup_trade_plan(conn, symbol: str) -> dict | None:
    """Find the best available trade plan for auto mode.

    Search order:
        1. trade_plans (recent, not disqualified)
        2. strategy_cards (recent)
        3. trade_ai_scans (GO decisions)
    """
    cur = conn.cursor()
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)

    # 1. trade_plans
    cur.execute("""
        SELECT id, signal_id, strategy_id, symbol,
               entry_low, entry_high, stop_loss, target_1, target_2,
               shares, dollar_size, dollar_risk
        FROM trade_plans
        WHERE symbol = %s AND generated_at > %s AND NOT disqualified
        ORDER BY generated_at DESC LIMIT 1
    """, (symbol, cutoff))
    row = cur.fetchone()
    if row:
        entry = float(row[5]) if row[5] else (float(row[4]) if row[4] else None)
        if entry is None:
            entry = float(row[4]) if row[4] else 0
        return {
            "trade_plan_id": row[0],
            "signal_id": row[1],
            "strategy_id": row[2],
            "symbol": row[3],
            "entry": round(float(entry), 2),
            "stop": round(float(row[6]), 2) if row[6] else 0,
            "target": round(float(row[7]), 2) if row[7] else 0,
            "shares": int(row[9]) if row[9] else 100,
            "dollar_size": float(row[10]) if row[10] else None,
            "dollar_risk": float(row[11]) if row[11] else None,
        }

    # 2. strategy_cards
    cur.execute("""
        SELECT id, symbol, strategy_id, entry_price, stop_loss, target_price, shares
        FROM strategy_cards
        WHERE symbol = %s AND created_at > %s
        ORDER BY created_at DESC LIMIT 1
    """, (symbol, cutoff))
    row = cur.fetchone()
    if row:
        return {
            "trade_plan_id": None,
            "signal_id": None,
            "strategy_id": row[2],
            "symbol": row[1],
            "entry": round(float(row[3]), 2) if row[3] else 0,
            "stop": round(float(row[4]), 2) if row[4] else 0,
            "target": round(float(row[5]), 2) if row[5] else 0,
            "shares": int(row[6]) if row[6] else 100,
        }

    # 3. trade_ai_scans
    cur.execute("""
        SELECT symbol, price, stop_price
        FROM trade_ai_scans
        WHERE symbol = %s AND decision IN ('GO') AND scanned_at > %s
        ORDER BY scanned_at DESC LIMIT 1
    """, (symbol, cutoff))
    row = cur.fetchone()
    if row:
        price = float(row[1]) if row[1] else 0
        stop = float(row[2]) if row[2] else 0
        target = round(price * 1.10, 2) if price else 0  # default 10% target
        return {
            "trade_plan_id": None,
            "signal_id": None,
            "strategy_id": None,
            "symbol": row[0],
            "entry": round(price, 2),
            "stop": round(stop, 2),
            "target": target,
            "shares": 100,
        }

    return None


def _write_audit(conn, event: str, symbol: str, details: dict):
    """Write to audit_log table."""
    try:
        import json
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO audit_log (event_type, symbol, input_snapshot, created_at)
            VALUES (%s, %s, %s, %s)
        """, (event, symbol, json.dumps(details, default=str),
              datetime.now(timezone.utc)))
    except Exception as e:
        log.warning("Audit log write failed: %s", e)


# ─────────────────────────────────────────────────────────────────────────────
# Proposal workflow
# ─────────────────────────────────────────────────────────────────────────────
def proposal_quality_check(candidate: dict, conn=None) -> tuple:
    """Check if a proposal candidate meets quality thresholds.

    Returns (passed: bool, reason_codes: list[str]).
    """
    reasons = []
    score = candidate.get('score') or candidate.get('signal_score') or 0
    intel = candidate.get('intel_readiness') or 0
    catalyst_verified = candidate.get('catalyst_verified', False)
    rvol = float(candidate.get('rvol') or 0)
    rg_result = candidate.get('risk_gate_result', 'APPROVED')

    if score < 45:
        reasons.append('SCORE_TOO_LOW')
    if intel < 50 and intel > 0:
        reasons.append('INTEL_TOO_THIN')
    if not catalyst_verified and rvol < 8:
        reasons.append('NO_VERIFIED_CATALYST_OR_HIGH_RVOL')
    if rg_result not in ('APPROVED', 'RISK_GATE_ERROR', None, ''):
        reasons.append('RISK_GATE_REJECTED')

    # Duplicate check
    if conn:
        try:
            symbol = candidate.get('symbol', '')
            sid = candidate.get('strategy_id', '')
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM paper_trade_proposals
                WHERE symbol=%s AND strategy_id=%s AND status='PENDING'
                AND expires_at > NOW()
            """, [symbol, sid])
            if (cur.fetchone()[0] or 0) > 0:
                reasons.append('DUPLICATE_PENDING_PROPOSAL')
        except Exception:
            pass

    return (len(reasons) == 0, reasons)


def create_proposal(symbol: str, strategy_id: str = 'momentum_scalp',
                    proposed_by: str = 'system', account: str = None) -> dict:
    """Create a paper trade proposal from latest trade plan. Returns dict with success/proposal_id/message."""
    conn = get_conn()
    try:
        plan = _lookup_trade_plan(conn, symbol)
        if not plan:
            return {'success': False, 'message': f'No valid trade plan found for {symbol}. Use manual: /pt {symbol} SHARES ENTRY STOP TARGET'}

        entry = plan.get('entry_high') or plan.get('entry')
        stop = plan.get('stop_loss') or plan.get('stop')
        target = plan.get('target_1') or plan.get('target')
        shares = plan.get('shares', 0)

        if not all([entry, stop, target, shares]):
            return {'success': False, 'message': f'Incomplete plan for {symbol}'}

        entry, stop, target = float(entry), float(stop), float(target)
        shares = int(shares)
        dollar_size = round(shares * entry, 2)
        dollar_risk = round(abs(entry - stop) * shares, 2)
        stop_pct = round(abs(entry - stop) / entry, 4) if entry > 0 else 0
        rr = round((target - entry) / (entry - stop), 2) if entry > stop else 0

        # Risk gate check at proposal time
        rg_result = 'APPROVED'
        rg_codes = []
        try:
            from risk_gate import RiskGate
            gate = RiskGate(conn)
            decision = gate.check(symbol, strategy_id, {'stop_loss': stop, 'dollar_size': dollar_size},
                                  account, 'paper', 'paper_trade')
            rg_result = decision.result
            rg_codes = decision.reason_codes
        except Exception:
            rg_result = 'RISK_GATE_ERROR'

        # Quality filter check
        quality_candidate = {
            'symbol': symbol, 'strategy_id': strategy_id,
            'score': plan.get('score'), 'signal_score': plan.get('score'),
            'intel_readiness': plan.get('intel_readiness'),
            'catalyst_verified': plan.get('catalyst_verified'),
            'rvol': plan.get('rvol'),
            'risk_gate_result': rg_result,
        }
        q_pass, q_codes = proposal_quality_check(quality_candidate, conn)

        # Session 24A: Strategy-aware expiry
        try:
            from proposal_lifecycle import get_expiry_datetime
            expires = get_expiry_datetime(strategy_id)
        except Exception:
            expires = datetime.now(timezone.utc) + timedelta(hours=4)

        cur = conn.cursor()
        cur.execute("""
            INSERT INTO paper_trade_proposals (
                symbol, strategy_id, setup_type, signal_score, signal_grade, signal_decision,
                trade_plan_id, rvol, float_m, gap_pct, catalyst, catalyst_verified,
                intel_readiness, proposed_account, proposed_entry, proposed_stop,
                proposed_target1, proposed_shares, proposed_dollar_size, proposed_dollar_risk,
                proposed_stop_pct, proposed_rr, tos_order_string,
                risk_gate_result, risk_gate_codes, proposed_by, status, expires_at,
                quality_pass, quality_reason_codes, hidden_by_quality_filter
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, 'PENDING', %s,
                %s, %s, %s
            ) RETURNING id
        """, [
            symbol, strategy_id, plan.get('setup_type'), plan.get('score'), plan.get('grade'), plan.get('decision'),
            plan.get('plan_id'), plan.get('rvol'), plan.get('float_m'), plan.get('gap_pct'),
            plan.get('catalyst'), plan.get('catalyst_verified'),
            plan.get('intel_readiness'), account, entry, stop,
            target, shares, dollar_size, dollar_risk,
            stop_pct, rr, plan.get('tos_order_string'),
            rg_result, json.dumps(rg_codes), proposed_by, expires.isoformat(),
            q_pass, json.dumps(q_codes) if q_codes else None, not q_pass,
        ])
        proposal_id = cur.fetchone()[0]

        # SP-2C: Generate route audit evidence
        try:
            from proposal_route_audit_integration import ensure_route_audit_for_proposal
            ensure_route_audit_for_proposal(
                conn, proposal_id, symbol, strategy_id,
                plan, source="paper_trade_logger_scan"
            )
        except Exception:
            pass

        conn.commit()

        _write_audit(conn, 'paper_proposal_created', symbol, {
            'proposal_id': proposal_id, 'strategy_id': strategy_id,
            'entry': entry, 'stop': stop, 'target': target, 'shares': shares,
            'risk_gate': rg_result,
        })
        conn.close()

        return {
            'success': True,
            'proposal_id': proposal_id,
            'symbol': symbol,
            'strategy_id': strategy_id,
            'entry': entry, 'stop': stop, 'target': target,
            'shares': shares, 'dollar_risk': dollar_risk, 'rr': rr,
            'risk_gate_result': rg_result, 'risk_gate_codes': rg_codes,
            'account': account,
            'message': f'PAPER PROPOSAL #{proposal_id} created for {symbol}',
        }
    except Exception as e:
        conn.close()
        return {'success': False, 'message': f'Proposal creation failed: {e}'}


def _check_scan_decision(conn, symbol: str) -> dict:
    """Check latest scan decision for WAIT/DOWNGRADE guard."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT decision, critic_verdict, critic_confidence, score, grade
            FROM trade_ai_scans
            WHERE symbol = %s
            ORDER BY scanned_at DESC LIMIT 1
        """, [symbol])
        row = cur.fetchone()
        if row:
            return {
                'decision': row[0],
                'critic_verdict': row[1],
                'critic_confidence': row[2],
                'score': row[3],
                'grade': row[4],
            }
    except Exception:
        pass
    return {}


def create_manual_proposal(symbol: str, shares: int, entry: float, stop: float,
                           target: float, account: str = None, strategy_id: str = "momentum_scalp",
                           origin: str = "manual_telegram") -> dict:
    """Create a manual paper trade proposal, mapped to a chosen strategy (operator 2026-06-19 — the
    Schwab/Fidelity manual-submit form passes the strategy).

    Adds WAIT/DOWNGRADE guard: if latest scan shows WAIT/AVOID/NO GO or
    critic BLOCK/DOWNGRADE, the proposal is created but marked as
    CAUTIOUS_MANUAL_TEST with approval_allowed=false.
    """
    strategy_id = strategy_id or "momentum_scalp"
    conn = get_conn()
    try:
        dollar_size = round(shares * entry, 2)
        dollar_risk = round(abs(entry - stop) * shares, 2)
        stop_pct = round(abs(entry - stop) / entry, 4) if entry > 0 else 0
        rr = round((target - entry) / (entry - stop), 2) if entry > stop else 0

        # WAIT/DOWNGRADE guard
        scan_info = _check_scan_decision(conn, symbol)
        scan_decision = scan_info.get('decision', '')
        critic = scan_info.get('critic_verdict', '')
        proposal_warning = None
        decision_state = None

        if scan_decision in ('WAIT', 'NO GO', 'AVOID') or critic in ('BLOCK', 'DOWNGRADE'):
            proposal_warning = f"Latest scan: {scan_decision or 'unknown'}, critic: {critic or 'N/A'}. Manual override — requires dashboard confirmation."
            decision_state = 'CAUTIOUS_MANUAL_TEST'

        # Session 24A: Strategy-aware expiry
        try:
            from proposal_lifecycle import get_expiry_datetime
            _strat = strategy_id or 'momentum_scalp'
            expires = get_expiry_datetime(_strat)
        except Exception:
            expires = datetime.now(timezone.utc) + timedelta(hours=4)

        cur = conn.cursor()

        # Build columns dynamically to handle approval_allowed etc.
        cols = [
            'symbol', 'strategy_id', 'proposed_account', 'proposed_entry', 'proposed_stop',
            'proposed_target1', 'proposed_shares', 'proposed_dollar_size', 'proposed_dollar_risk',
            'proposed_stop_pct', 'proposed_rr', 'proposed_by', 'status', 'expires_at',
        ]
        vals = [
            symbol, strategy_id, account, entry, stop,
            target, shares, dollar_size, dollar_risk,
            stop_pct, rr, 'telegram_manual', 'PENDING', expires.isoformat(),
        ]

        # Unified queue stamping (operator 2026-06-19): manual submissions share the SAME queue as the
        # automated pipeline; intended_broker prepares broker-aware routing (alpaca paper now, Schwab later).
        # Default account/broker comes from config (no hardcode), not a literal.
        import account_policy as _apol
        _default_paper = _apol.default_paper_account()
        _tacct = account or _default_paper
        _broker = _default_paper if (not account or 'alpaca' in account.lower()) else account
        try:
            _qcur = conn.cursor()
            _qcur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='paper_trade_proposals' AND column_name IN ('origin','target_account','intended_broker','routing_state','sizing_basis')")
            _qcols = {row[0] for row in _qcur.fetchall()}
            for _c, _v in (('origin', origin or 'manual_telegram'), ('target_account', _tacct),
                           ('intended_broker', _broker), ('routing_state', 'queued'),
                           ('sizing_basis', json.dumps({'engine': 'manual_operator', 'shares': shares,
                                                         'account_key': _tacct}))):
                if _c in _qcols:
                    cols.append(_c)
                    vals.append(_v)
        except Exception:
            pass

        # Add scan context columns if they exist
        try:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='paper_trade_proposals' AND column_name IN ('catalyst','catalyst_verified','critic_verdict','critic_confidence','signal_score','signal_grade','approval_allowed','approval_blocked_reason')")
            existing_cols = {row[0] for row in cur.fetchall()}

            if 'catalyst' in existing_cols and scan_info.get('decision'):
                pass  # scan context populated via enrichment
            if 'signal_score' in existing_cols and scan_info.get('score'):
                cols.append('signal_score')
                vals.append(scan_info['score'])
            if 'signal_grade' in existing_cols and scan_info.get('grade'):
                cols.append('signal_grade')
                vals.append(scan_info['grade'])
            if 'critic_verdict' in existing_cols and critic:
                cols.append('critic_verdict')
                vals.append(critic)
            if 'critic_confidence' in existing_cols and scan_info.get('critic_confidence'):
                cols.append('critic_confidence')
                vals.append(scan_info['critic_confidence'])
            if 'approval_allowed' in existing_cols and decision_state:
                cols.append('approval_allowed')
                vals.append(False)
            if 'approval_blocked_reason' in existing_cols and proposal_warning:
                cols.append('approval_blocked_reason')
                vals.append(proposal_warning)
        except Exception:
            pass

        placeholders = ', '.join(['%s'] * len(vals))
        col_str = ', '.join(cols)

        cur.execute(f"""
            INSERT INTO paper_trade_proposals ({col_str})
            VALUES ({placeholders})
            RETURNING id
        """, vals)
        proposal_id = cur.fetchone()[0]

        # SP-2C: Generate route audit evidence
        try:
            from proposal_route_audit_integration import ensure_route_audit_for_proposal
            _payload = {"symbol": symbol, "price": entry, "score": 0, "decision": "MANUAL"}
            ensure_route_audit_for_proposal(
                conn, proposal_id, symbol, strategy_id,
                _payload, source="paper_trade_logger_manual"
            )
        except Exception:
            pass

        conn.commit()
        conn.close()

        msg = f'PAPER PROPOSAL #{proposal_id} created for {symbol} (manual)'
        if proposal_warning:
            msg += f'\n⚠️ {proposal_warning}'

        return {
            'success': True, 'proposal_id': proposal_id, 'symbol': symbol,
            'entry': entry, 'stop': stop, 'target': target,
            'shares': shares, 'dollar_risk': dollar_risk, 'rr': rr,
            'account': account,
            'proposal_warning': proposal_warning,
            'decision_state': decision_state,
            'message': msg,
        }
    except Exception as e:
        conn.close()
        return {'success': False, 'message': f'Manual proposal failed: {e}'}


def promote_proposal_to_broker(
    proposal_id: int,
    account: str,
    shares: int,
    entry: float,
    stop: float,
    target: float,
    *,
    risk_reward: float = None,
    operator: str = "operator",
    operator_route: bool = False,
) -> dict:
    """Promote a broker-agnostic proposal to the Schwab/Fidelity execution queue (in-place update).

    operator_route=True: operator-confirmed live size — skip P0/policy/paper-queue cap blocks.
    """
    acct = (account or "").strip()
    acct_l = acct.lower()
    if not acct or not ("schwab" in acct_l or "fidelity" in acct_l):
        return {"ok": False, "error": "account must be a Schwab or Fidelity account key"}

    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, symbol, strategy_id, status,
                      COALESCE(intended_broker, '') AS intended_broker,
                      COALESCE(origin, 'auto') AS origin
               FROM paper_trade_proposals WHERE id=%s""",
            (proposal_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": f"proposal #{proposal_id} not found"}
        _id, symbol, strategy_id, status, prev_broker, prev_origin = row
        if status not in ("PENDING", "APPROVED_FOR_PAPER_TEST"):
            return {"ok": False, "error": f"proposal #{proposal_id} status={status} — cannot promote"}

        try:
            import broker_queue_hygiene as _bqh
            other = _bqh.find_active_symbol_proposal(symbol, exclude_id=proposal_id, broker_only=True)
            if other:
                _bqh.supersede_older_broker_rows(symbol, proposal_id, dry_run=False)
            _bqh.sweep_broker_queue(dry_run=False, refresh_quotes=False)
        except Exception:
            pass

        shares = int(shares)
        entry, stop, target = float(entry), float(stop), float(target)
        if shares <= 0 or entry <= 0 or stop <= 0 or target <= 0:
            return {"ok": False, "error": "shares, entry, stop, and target must be positive"}
        if entry <= stop:
            return {"ok": False, "error": "entry must be above stop for a long trade"}

        import broker_promote_sizing as bps
        live_quote = {}
        try:
            from market_quote_provider import get_best_quote
            live_quote = get_best_quote(symbol) or {}
        except Exception:
            pass
        evaluation = bps.evaluate_broker_promote(
            acct, strategy_id, entry, stop, target, shares, quote=live_quote,
            operator_route=operator_route,
        )
        try:
            import broker_promote_oversight as bpo
            oversight = bpo.evaluate_oversight(proposal_id)
            evaluation = bpo.merge_evaluation_with_oversight(evaluation, oversight)
        except Exception:
            pass

        if not evaluation.get("allowed"):
            reasons = list(evaluation.get("violations") or [])
            mkt = evaluation.get("market") or {}
            if mkt.get("reason"):
                reasons.append(mkt["reason"])
            sizing = evaluation.get("sizing") or {}
            return {
                "ok": False,
                "error": "; ".join(reasons) or "broker promote blocked by sizing/market/oversight gates",
                "evaluation": evaluation,
                "oversight": evaluation.get("oversight"),
                "max_shares": evaluation.get("max_shares"),
                "recommended_shares": evaluation.get("recommended_shares"),
                "binding": sizing.get("binding"),
            }

        dollar_size = round(shares * entry, 2)
        dollar_risk = round(abs(entry - stop) * shares, 2)
        stop_pct = round(abs(entry - stop) / entry, 4) if entry > 0 else 0
        rr = round(float(risk_reward), 2) if risk_reward is not None else (
            round((target - entry) / (entry - stop), 2) if entry > stop else 0
        )

        sizing_basis = evaluation.get("sizing") or {}
        basis_patch = json.dumps({
            "engine": "paper_promoted_to_broker",
            "promoted_from_broker": prev_broker or os.getenv("DEFAULT_PAPER_ACCOUNT", "alpaca_paper"),  # hardcode-ok: env-backed lineage fallback when prior broker unset
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "operator": operator,
            "shares": shares,
            "account_key": acct,
            "broker_sizing": {
                "binding": sizing_basis.get("binding"),
                "max_shares": evaluation.get("max_shares"),
                "engine": sizing_basis.get("engine"),
                "equity": sizing_basis.get("equity"),
                "cash_available": sizing_basis.get("cash_available"),
                "policy_snapshot": sizing_basis.get("policy_snapshot"),
            },
            "market_status": (evaluation.get("market") or {}).get("status"),
        })

        cur.execute(
            """UPDATE paper_trade_proposals SET
                 intended_broker=%s, target_account=%s, proposed_account=%s,
                 proposed_entry=%s, proposed_stop=%s, proposed_target1=%s,
                 proposed_shares=%s, proposed_dollar_size=%s, proposed_dollar_risk=%s,
                 proposed_stop_pct=%s, proposed_rr=%s,
                 routing_state='queued',
                 origin=CASE WHEN origin='auto' THEN 'paper_promoted' ELSE origin END,
                 sizing_basis=COALESCE(sizing_basis, '{}'::jsonb) || %s::jsonb
               WHERE id=%s""",
            (acct, acct, acct, entry, stop, target, shares, dollar_size, dollar_risk,
             stop_pct, rr, basis_patch, proposal_id),
        )
        conn.commit()

        try:
            import trade_modify as _tm
            _tm.audit_decision(
                "promote_to_broker", proposal_id=proposal_id, actor=operator, channel="web",
                after={"account": acct, "symbol": symbol, "shares": shares, "entry": entry,
                       "stop": stop, "target": target, "rr": rr, "prev_broker": prev_broker,
                       "prev_origin": prev_origin},
                reason=f"Promoted #{proposal_id} {symbol} to broker queue ({acct})",
            )
        except Exception:
            pass

        broker_label = "Fidelity" if "fidelity" in acct_l else "Schwab"
        return {
            "ok": True,
            "success": True,
            "proposal_id": proposal_id,
            "symbol": symbol,
            "account": acct,
            "broker": broker_label,
            "shares": shares,
            "entry": entry,
            "stop": stop,
            "target": target,
            "rr": rr,
            "message": f"Proposal #{proposal_id} ({symbol}) queued for {broker_label} · {acct}",
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e)[:200]}
    finally:
        conn.close()


def validate_paper_proposal_live_market(
    symbol: str,
    entry: float,
    stop: float,
    target: float,
    shares: int,
    live_quote: dict,
    now: datetime = None,
    max_quote_age_minutes: float = 15,
    max_block_drift_pct: float = 3.0,
    warn_drift_pct: float = 1.5,
    max_spread_pct: float = 1.5,
    min_rr: float = 1.2,
) -> dict:
    """Pure market revalidation — no side effects, fully unit-testable.

    Args:
        symbol: Ticker symbol.
        entry: Proposed entry price.
        stop: Proposed stop loss.
        target: Proposed target price.
        shares: Proposed share count.
        live_quote: Quote dict from get_best_quote() or equivalent.
        now: Current UTC datetime (defaults to utcnow).
        max_quote_age_minutes: Block if quote older than this.
        max_block_drift_pct: Block if price drift exceeds this.
        warn_drift_pct: Warn and adjust entry if drift exceeds this.
        max_spread_pct: Block if spread exceeds this.
        min_rr: Block if risk/reward below this.

    Returns:
        dict with ok, blocked, warnings, reason, checks, original/adjusted values.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    result = {
        "ok": False,
        "blocked": True,
        "warnings": [],
        "reason": "",
        "checks": {
            "quote_available": False,
            "quote_age_minutes": None,
            "quote_fresh": False,
            "entry_drift_pct": None,
            "stop_breached": False,
            "spread_pct": None,
            "rr": None,
        },
        "original_entry": entry,
        "adjusted_entry": None,
        "live_price": None,
        "bid": None,
        "ask": None,
        "timestamp": now.isoformat(),
    }

    # ── Guard: valid proposal parameters ──
    if not entry or entry <= 0:
        result["reason"] = f"Cannot approve: proposal for {symbol} has no valid entry price."
        return result
    if not stop or stop <= 0:
        result["reason"] = f"Cannot approve: proposal for {symbol} has no valid stop loss."
        return result
    if not target or target <= 0:
        result["reason"] = f"Cannot approve: proposal for {symbol} has no valid target."
        return result

    # ── Check: quote available ──
    live_price = live_quote.get("last_price") if live_quote else None
    if not live_price or live_price <= 0:
        result["reason"] = f"Cannot approve: no live price available for {symbol}. Stale data cannot be trusted."
        return result

    result["checks"]["quote_available"] = True
    result["live_price"] = live_price
    result["bid"] = live_quote.get("bid")
    result["ask"] = live_quote.get("ask")

    # ── Check: quote freshness ──
    qt = live_quote.get("quote_timestamp")
    if qt:
        if isinstance(qt, str):
            try:
                qt = datetime.fromisoformat(qt.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                qt = None
        if qt and hasattr(qt, 'tzinfo') and qt.tzinfo is None:
            qt = qt.replace(tzinfo=timezone.utc)
        elif qt and isinstance(qt, (int, float)):
            qt = datetime.fromtimestamp(qt, tz=timezone.utc)
        try:
            age_sec = (now - qt).total_seconds()
            age_min = round(age_sec / 60, 1)
            result["checks"]["quote_age_minutes"] = age_min
            max_age_sec = max_quote_age_minutes * 60
            if age_sec > max_age_sec:
                result["checks"]["quote_fresh"] = False
                result["reason"] = f"Cannot approve: quote for {symbol} is {age_min}min old. Need fresh market data."
                return result
            result["checks"]["quote_fresh"] = True
        except Exception as e:
            result["reason"] = f"Cannot approve: unable to determine quote freshness for {symbol}. Failing closed."
            return result
    else:
        result["checks"]["quote_fresh"] = True  # No timestamp = trust provider (Alpaca real-time)

    # ── Check: stop already breached (long) ──
    if live_price <= stop:
        result["checks"]["stop_breached"] = True
        result["reason"] = (f"Not a good trade under current conditions: {symbol} is at ${live_price:.2f}, "
                            f"already at or below stop loss ${stop:.2f}. Would immediately stop out.")
        return result

    # ── Check: price drift ──
    drift_pct = abs(live_price - entry) / entry * 100
    result["checks"]["entry_drift_pct"] = round(drift_pct, 2)

    if drift_pct > max_block_drift_pct:
        direction = "above" if live_price > entry else "below"
        result["reason"] = (f"Not a good trade under current conditions: {symbol} is now ${live_price:.2f}, "
                            f"{drift_pct:.1f}% {direction} proposed entry ${entry:.2f}. "
                            f"Trade parameters are stale — resubmit with fresh analysis.")
        return result

    # ── Check: spread ──
    spread_pct = live_quote.get("spread_pct")
    result["checks"]["spread_pct"] = spread_pct
    if spread_pct and spread_pct > max_spread_pct:
        result["reason"] = (f"Not a good trade under current conditions: {symbol} spread is {spread_pct:.2f}%, "
                            f"too wide for safe execution. Wait for tighter liquidity.")
        return result

    # ── Check: R:R at current price ──
    current_risk = abs(live_price - stop)
    current_reward = abs(target - live_price)
    live_rr = round(current_reward / current_risk, 2) if current_risk > 0 else 0
    result["checks"]["rr"] = live_rr

    if live_rr < min_rr:
        orig_risk = abs(entry - stop)
        orig_rr = round(abs(target - entry) / orig_risk, 2) if orig_risk > 0 else 0
        result["reason"] = (f"Not a good trade under current conditions: {symbol} R:R has degraded from "
                            f"{orig_rr}:1 to {live_rr}:1 at current price ${live_price:.2f}. "
                            f"Reward no longer justifies the risk.")
        return result

    # ── All checks passed ──
    result["ok"] = True
    result["blocked"] = False
    adjusted_entry = live_price if drift_pct > warn_drift_pct else entry
    result["adjusted_entry"] = adjusted_entry

    if drift_pct > warn_drift_pct:
        direction = "above" if live_price > entry else "below"
        result["warnings"].append(f"price_adjusted: {drift_pct:.1f}% {direction}, entry recalibrated to ${live_price:.2f}")
        result["reason"] = (f"Approved with adjustment: {symbol} moved {drift_pct:.1f}% {direction} proposed entry. "
                            f"Entry recalibrated from ${entry:.2f} to ${live_price:.2f}. R:R={live_rr}:1.")
    else:
        result["adjusted_entry"] = entry
        result["reason"] = (f"Market conditions confirmed: {symbol} at ${live_price:.2f} "
                            f"(drift {drift_pct:.1f}%), R:R={live_rr}:1. Approved.")

    return result


def _revalidate_market_conditions(symbol: str, entry: float, stop: float, target: float, shares: int) -> dict:
    """Fetch live quote and run market revalidation. Wrapper around validate_paper_proposal_live_market().

    This function handles the side effect (quote fetching) then delegates
    to the pure validation function. Used by approve_proposal().
    """
    result = {
        "passed": False,
        "symbol": symbol,
        "proposed_entry": entry,
        "proposed_stop": stop,
        "proposed_target": target,
        "proposed_shares": shares,
        "live_price": None,
        "provider": None,
        "quote_age_seconds": None,
        "price_drift_pct": None,
        "live_rr": None,
        "live_spread_pct": None,
        "adjusted_entry": None,
        "adjusted_shares": None,
        "adjusted_dollar_risk": None,
        "blockers": [],
        "warnings": [],
        "message": "",
    }

    # ── Fetch live quote (side effect) ──
    try:
        quote = get_best_quote(symbol)
    except Exception as e:
        result["blockers"].append(f"quote_fetch_error: {e}")
        result["message"] = f"Cannot approve: failed to fetch live market data for {symbol}"
        return result

    if not quote or not quote.get("last_price"):
        result["blockers"].append("no_live_quote")
        result["message"] = f"Cannot approve: no live price available for {symbol}. Stale data cannot be trusted."
        return result

    # ── Delegate to pure validation ──
    check = validate_paper_proposal_live_market(
        symbol=symbol, entry=entry, stop=stop, target=target,
        shares=shares, live_quote=quote)

    # ── Map pure result to legacy format ──
    result["live_price"] = check.get("live_price")
    result["provider"] = quote.get("provider", "unknown")
    result["live_spread_pct"] = check["checks"].get("spread_pct")
    result["price_drift_pct"] = check["checks"].get("entry_drift_pct")
    result["live_rr"] = check["checks"].get("rr")
    age_min = check["checks"].get("quote_age_minutes")
    result["quote_age_seconds"] = round(age_min * 60) if age_min is not None else None
    result["message"] = check.get("reason", "")

    if check["ok"]:
        result["passed"] = True
        result["warnings"] = check.get("warnings", [])
        adjusted = check.get("adjusted_entry", entry)
        result["adjusted_entry"] = adjusted
        result["adjusted_shares"] = shares
        result["adjusted_dollar_risk"] = round(abs(adjusted - stop) * int(shares), 2)
    else:
        result["blockers"].append(check.get("reason", "blocked"))

    return result


def approve_proposal(proposal_id: int, override_shares: int = None,
                     override_entry: float = None, override_stop: float = None,
                     override_target: float = None) -> dict:
    """Approve a proposal, create paper trade, optionally submit to Alpaca.

    Runs real-time market revalidation BEFORE creating the paper trade.
    If current market conditions make the trade unfavorable, approval is blocked.
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM paper_trade_proposals WHERE id = %s", [proposal_id])
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        if not row:
            conn.close()
            return {'success': False, 'message': f'Proposal #{proposal_id} not found'}
        prop = dict(zip(cols, row))

        if prop['status'] != 'PENDING':
            conn.close()
            return {'success': False, 'message': f'Proposal #{proposal_id} is {prop["status"]}, not PENDING'}

        try:
            from proposal_routing import is_broker_routed
            if is_broker_routed(prop):
                conn.close()
                return {
                    'success': False,
                    'message': (
                        f'Proposal #{proposal_id} is routed for live broker execution (Path B). '
                        'Use Broker Proposals — not paper approve.'
                    ),
                    'routing_required': True,
                }
        except Exception:
            pass

        # Apply overrides
        entry = override_entry or prop['proposed_entry']
        stop = override_stop or prop['proposed_stop']
        target = override_target or prop['proposed_target1']
        shares = override_shares or prop['proposed_shares']

        # ── REAL-TIME MARKET REVALIDATION (must pass before anything else) ──
        market_check = _revalidate_market_conditions(
            prop['symbol'], float(entry), float(stop), float(target), int(shares))

        if not market_check["passed"]:
            # Block approval — update proposal with rejection reason
            cur.execute("""
                UPDATE paper_trade_proposals
                SET action_state = 'BLOCKED',
                    action_label = %s,
                    latest_execution_readiness = 'BLOCKED_MARKET_CONDITIONS',
                    updated_at = NOW()
                WHERE id = %s
            """, [market_check["message"][:500], proposal_id])
            conn.commit()
            conn.close()
            return {
                'success': False,
                'message': market_check["message"],
                'market_revalidation': market_check,
                'blockers': market_check["blockers"],
            }

        # If market check adjusted the entry, use the recalibrated values
        if market_check.get("adjusted_entry") and market_check["adjusted_entry"] != float(entry):
            log.info(f"Proposal #{proposal_id}: entry recalibrated from {entry} to {market_check['adjusted_entry']}")
            entry = market_check["adjusted_entry"]

        dollar_size = round(float(shares) * float(entry), 2)
        dollar_risk = round(abs(float(entry) - float(stop)) * int(shares), 2)

        # Risk gate re-check at approval
        rg_result = 'APPROVED'
        rg_codes = []
        try:
            from risk_gate import RiskGate
            gate = RiskGate(conn)
            decision = gate.check(prop['symbol'], prop['strategy_id'],
                {'stop_loss': float(stop), 'dollar_size': dollar_size},
                prop.get('proposed_account') or _default_account(), 'paper', 'paper_trade')
            rg_result = decision.result
            rg_codes = decision.reason_codes
            if not decision.approved:
                cur.execute("UPDATE paper_trade_proposals SET status='RISK_BLOCKED', risk_gate_result=%s, risk_gate_codes=%s, updated_at=NOW() WHERE id=%s",
                    [rg_result, json.dumps(rg_codes), proposal_id])
                conn.commit(); conn.close()
                return {'success': False, 'message': f'Risk gate BLOCKED: {rg_codes}', 'risk_gate': rg_result}
        except Exception as e:
            conn.close()
            return {'success': False, 'message': f'Risk gate error (fail-closed): {e}'}

        now = datetime.now(timezone.utc)
        entry_ctx = _get_entry_regime(conn)

        # ── Execution lineage (broker/account-neutral; sourced from the proposal, not hardcoded) ──
        try:
            from trade_lineage import extract_lineage_from_proposal
            _lin = extract_lineage_from_proposal(conn, proposal_id)
        except Exception as _e:
            _lin = {"signal_id": None, "source_signal_id": None, "strategy_card_id": None, "candidate_id": None,
                    "execution_account": None, "execution_broker": None, "execution_environment": None,
                    "lineage_confidence": "missing", "lineage_source": "missing", "lineage_notes": {}}

        # Insert paper trade — status=pending (not yet submitted to broker)
        # broker is NULL until an actual Alpaca order is submitted via proposal_paper_submitter
        cur.execute("""
            INSERT INTO paper_trades (
                strategy_id, symbol, account, entry_price, entry_time, shares, dollar_size,
                stop_loss, target_1, dollar_risk, planned_entry, planned_stop,
                score_at_entry, rvol_at_entry, float_m_at_entry, catalyst_at_entry, catalyst_verified,
                intel_readiness, trade_plan_id, proposal_id, setup_type, signal_grade,
                risk_gate_result, risk_gate_reason_codes,
                market_regime, vix_at_entry,
                signal_id, source_signal_id, source_strategy_card_id, strategy_card_id, candidate_id,
                source_proposal_id, execution_account, execution_broker, execution_environment,
                lineage_source, lineage_stamped_at, lineage_confidence, lineage_notes,
                status, lifecycle_state, broker, opened_via, logged_by, automation_source
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, NOW(), %s, %s,
                'pending', 'pending', NULL, 'proposal_approved', 'dashboard', 'proposal'
            ) RETURNING id
        """, [
            prop['strategy_id'], prop['symbol'],
            prop.get('target_account') or prop.get('proposed_account') or _default_account(),
            float(entry), now, int(shares), dollar_size,
            float(stop), float(target), dollar_risk, float(entry), float(stop),
            prop.get('signal_score'), prop.get('rvol'), prop.get('float_m'),
            prop.get('catalyst'), prop.get('catalyst_verified'),
            prop.get('intel_readiness'), prop.get('trade_plan_id'), proposal_id,
            prop.get('setup_type'), prop.get('signal_grade'),
            rg_result, json.dumps(rg_codes),
            entry_ctx["regime"], entry_ctx["vix"],
            _lin.get('signal_id'), _lin.get('source_signal_id'), _lin.get('strategy_card_id'),
            _lin.get('strategy_card_id'), _lin.get('candidate_id'),
            str(proposal_id), _lin.get('execution_account'), _lin.get('execution_broker'), _lin.get('execution_environment'),
            _lin.get('lineage_source'), _lin.get('lineage_confidence'), json.dumps(_lin.get('lineage_notes') or {}),
        ])
        paper_trade_id = cur.fetchone()[0]

        # Update proposal
        cur.execute("""
            UPDATE paper_trade_proposals
            SET status='APPROVED_FOR_PAPER_TEST', paper_trade_id=%s, approved_at=NOW(),
                final_entry=%s, final_stop=%s, final_target1=%s, final_shares=%s,
                final_account=%s, final_dollar_risk=%s, updated_at=NOW()
            WHERE id=%s
        """, [paper_trade_id, float(entry), float(stop), float(target), int(shares),
              prop.get('target_account') or prop.get('proposed_account') or _default_account(), dollar_risk, proposal_id])
        conn.commit()

        _write_audit(conn, 'paper_proposal_approved', prop['symbol'], {
            'proposal_id': proposal_id, 'paper_trade_id': paper_trade_id,
            'entry': float(entry), 'stop': float(stop), 'shares': int(shares),
            'live_price': market_check.get('live_price'),
            'price_drift_pct': market_check.get('price_drift_pct'),
            'live_rr': market_check.get('live_rr'),
            'quote_provider': market_check.get('provider'),
        })
        conn.close()

        return {
            'success': True, 'proposal_id': proposal_id, 'paper_trade_id': paper_trade_id,
            'symbol': prop['symbol'], 'strategy_id': prop['strategy_id'],
            'entry': float(entry), 'stop': float(stop), 'target': float(target),
            'shares': int(shares), 'dollar_risk': dollar_risk,
            'account': prop.get('proposed_account') or _default_account(),
            'risk_gate': rg_result,
            'market_revalidation': market_check,
            'message': f'PAPER TRADE #{paper_trade_id} opened from proposal #{proposal_id}. {market_check["message"]}',
        }
    except Exception as e:
        try: conn.close()
        except: pass
        return {'success': False, 'message': f'Approval failed: {e}'}


def reject_proposal(proposal_id: int, reason: str = 'manual') -> dict:
    """Reject a pending proposal."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE paper_trade_proposals
            SET status='REJECTED', rejected_at=NOW(), rejection_reason=%s, updated_at=NOW()
            WHERE id=%s AND status='PENDING'
            RETURNING symbol
        """, [reason, proposal_id])
        row = cur.fetchone()
        conn.commit()
        if not row:
            conn.close()
            return {'success': False, 'message': f'Proposal #{proposal_id} not found or not PENDING'}
        conn.close()
        return {'success': True, 'message': f'Proposal #{proposal_id} ({row[0]}) REJECTED: {reason}'}
    except Exception as e:
        conn.close()
        return {'success': False, 'message': f'Reject failed: {e}'}


def get_pending_proposals() -> list:
    """Get all pending proposals."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, symbol, strategy_id, setup_type, signal_grade, signal_score,
                   proposed_account, proposed_entry, proposed_stop, proposed_target1,
                   proposed_shares, proposed_dollar_risk, proposed_rr, tos_order_string,
                   risk_gate_result, risk_gate_codes, catalyst, catalyst_verified,
                   rvol, float_m, gap_pct, created_at, expires_at
            FROM paper_trade_proposals
            WHERE status = 'PENDING'
            AND expires_at > NOW()
            ORDER BY created_at DESC
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        conn.close()
        return []


def expire_old_proposals():
    """Expire proposals past their expiry time. Session 24A: strategy-aware."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        # Intraday: expire at EOD / past expires_at
        cur.execute("""
            UPDATE paper_trade_proposals
            SET status='EXPIRED', lifecycle_status='EXPIRED_INTRADAY', updated_at=NOW()
            WHERE status='PENDING' AND expires_at < NOW()
            AND proposal_timeframe_class = 'intraday'
        """)
        intraday_expired = cur.rowcount

        # Overnight: only expire if past max_expires_at (or expires_at if no max set)
        cur.execute("""
            UPDATE paper_trade_proposals
            SET status='EXPIRED', lifecycle_status='EXPIRED_MAX_WINDOW', updated_at=NOW()
            WHERE status='PENDING'
            AND strategy_id NOT IN ('momentum_scalp', 'gap_and_go')
            AND COALESCE(max_expires_at, expires_at) < NOW()
        """)
        overnight_expired = cur.rowcount

        conn.commit(); conn.close()
        return intraday_expired + overnight_expired
    except Exception:
        conn.close()
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# CLI test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        ("FTCI auto", True),
        ("FTCI auto tos", True),
        ("FTCI auto alpaca", True),
        ("FTCI 300 4.96 4.61 5.31", True),
        ("FTCI 300 4.96 4.61 5.31 tos", True),
        ("FTCI auto live", False),
        ("FTCI auto taxable", False),
        ("", False),
        ("FTCI", False),
    ]
    print("=== Paper Trade Logger Tests ===")
    for cmd, expected in tests:
        ok, params, err = parse_pt_command(cmd)
        status = "PASS" if ok == expected else "FAIL"
        print(f"  {status}: '{cmd}' -> ok={ok} {'params='+str(params) if ok else 'err='+err}")
    print("All parser tests done")
