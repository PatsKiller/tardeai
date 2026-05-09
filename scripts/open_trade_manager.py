#!/usr/bin/env python3
"""open_trade_manager.py — In-trade intelligence and order modification proposal engine.

Evaluates open paper trades, runs due diligence, creates stop/limit modification
proposals requiring admin approval. NEVER directly modifies broker orders without
explicit approved-execution mode.

PAPER ONLY. No live trading. No automatic broker modifications.

Usage:
    .venv/bin/python scripts/open_trade_manager.py --scan-open --dry-run --json
    .venv/bin/python scripts/open_trade_manager.py --scan-open --create-proposals --dry-run --json
    .venv/bin/python scripts/open_trade_manager.py --execute-approved --proposal-id MOD_001 --json
"""
import argparse, json, logging, os, sys, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn

log = logging.getLogger("open_trade_manager")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


def _f(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def _safe_div(a, b):
    if not b or b == 0:
        return None
    return a / b


# ── Safety gates ─────────────────────────────────────────────────────────────

def check_paper_mode():
    mode = os.getenv("ALPACA_MODE", "paper").lower()
    live = os.getenv("LIVE_TRADING", "false").lower()
    if mode != "paper":
        return False, f"ALPACA_MODE={mode}, expected paper"
    if live == "true":
        return False, "LIVE_TRADING=true, must be false/absent"
    return True, "paper_mode_ok"


def run_live_trading_gate():
    try:
        from live_trading_gate import evaluate
        result = evaluate()
        return result.get("allowed", True) is False, result
    except Exception as e:
        return True, {"error": str(e), "allowed": False}


# ── Data fetchers ────────────────────────────────────────────────────────────

def get_open_trades(conn, symbol=None, trade_id=None):
    cur = conn.cursor()
    conditions = ["status = 'open'"]
    params = []
    if symbol:
        conditions.append("symbol = %s")
        params.append(symbol)
    if trade_id:
        conditions.append("id = %s")
        params.append(trade_id)
    sql = f"""SELECT id, symbol, strategy_id, entry_price, entry_time, shares,
                     stop_loss, target_1, target_2, dollar_risk, account,
                     current_price, unrealized_pnl, r_multiple,
                     monitored_at, last_alert_at, stale_flag,
                     broker_order_id, broker_status, thesis_status
              FROM paper_trades WHERE {' AND '.join(conditions)}
              ORDER BY entry_time DESC"""
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_latest_price(conn, symbol):
    cur = conn.cursor()
    cur.execute("""SELECT price, scanned_at FROM trade_ai_scans
                   WHERE symbol=%s ORDER BY scanned_at DESC LIMIT 1""", [symbol])
    row = cur.fetchone()
    if row:
        return _f(row[0]), row[1]
    return None, None


def get_news_risk(conn, symbol):
    """Check for adverse news since trade entry."""
    cur = conn.cursor()
    cur.execute("""SELECT title, published_at, sentiment
                   FROM news_articles
                   WHERE symbol=%s AND published_at > NOW() - INTERVAL '48 hours'
                   ORDER BY published_at DESC LIMIT 5""", [symbol])
    articles = cur.fetchall()
    adverse = [a for a in articles if a[2] and float(a[2]) < -0.3]
    positive = [a for a in articles if a[2] and float(a[2]) > 0.3]
    return {
        "total_recent": len(articles),
        "adverse_count": len(adverse),
        "positive_count": len(positive),
        "adverse_titles": [a[0][:80] for a in adverse[:3]],
        "risk_score": min(len(adverse) * 0.3, 1.0),
    }


def get_indicator_data(conn, symbol):
    """Get cached indicator data if available."""
    cur = conn.cursor()
    cur.execute("""SELECT rsi_14, atr_14, vwap, rvol, trend_label, confluence_score
                   FROM indicator_confluence_cache
                   WHERE symbol=%s ORDER BY updated_at DESC LIMIT 1""", [symbol])
    row = cur.fetchone()
    if row:
        return {"rsi": _f(row[0]), "atr": _f(row[1]), "vwap": _f(row[2]),
                "rvol": _f(row[3]), "trend": row[4], "confluence": _f(row[5])}
    return {}


# ── Due diligence engine ─────────────────────────────────────────────────────

def run_due_diligence(conn, trade):
    """Run comprehensive due diligence on a single open trade."""
    sym = trade["symbol"]
    entry = _f(trade.get("entry_price")) or 0
    stop = _f(trade.get("stop_loss"))
    target = _f(trade.get("target_1"))
    shares = _f(trade.get("shares")) or 0

    current_price, price_time = get_latest_price(conn, sym)
    news = get_news_risk(conn, sym)
    indicators = get_indicator_data(conn, sym)

    dd_events = []
    now = datetime.now(timezone.utc)

    # Quote freshness
    quote_fresh = True
    quote_age_sec = None
    if price_time:
        quote_age_sec = (now - price_time.replace(tzinfo=timezone.utc) if price_time.tzinfo is None
                         else now - price_time).total_seconds()
        if quote_age_sec > 900:  # 15 min
            quote_fresh = False
            dd_events.append(_dd_event(trade, "stale_quote", "warning",
                                       {"age_seconds": quote_age_sec}))
    else:
        quote_fresh = False
        dd_events.append(_dd_event(trade, "stale_quote", "critical",
                                   {"message": "no_price_data"}))
        current_price = _f(trade.get("current_price")) or entry  # fallback

    risk = abs(entry - stop) if stop and entry else None

    # R multiple
    r_mult = _safe_div(current_price - entry, risk) if current_price and risk else None

    # Distance to stop/target
    dist_stop_pct = _safe_div(abs(current_price - stop), current_price) * 100 if current_price and stop else None
    dist_target_pct = _safe_div(abs(target - current_price), current_price) * 100 if current_price and target else None

    # Unrealized PnL
    unreal_pnl = (current_price - entry) * shares if current_price and entry else 0
    unreal_pnl_pct = _safe_div(current_price - entry, entry) * 100 if current_price and entry else 0

    # Near-stop check
    if dist_stop_pct is not None and dist_stop_pct < 2.0 and current_price and stop and current_price > stop:
        dd_events.append(_dd_event(trade, "stop_near", "warning",
                                   {"distance_pct": round(dist_stop_pct, 2)}))
    if current_price and stop and current_price <= stop:
        dd_events.append(_dd_event(trade, "stop_breached", "critical",
                                   {"current": current_price, "stop": float(stop)}))

    # Near-target check
    if dist_target_pct is not None and dist_target_pct < 2.0 and current_price and target and current_price < target:
        dd_events.append(_dd_event(trade, "target_near", "info",
                                   {"distance_pct": round(dist_target_pct, 2)}))
    if current_price and target and current_price >= target:
        dd_events.append(_dd_event(trade, "target_breached", "info",
                                   {"current": current_price, "target": float(target)}))

    # RSI extremes
    rsi = indicators.get("rsi")
    if rsi is not None:
        if rsi > 80:
            dd_events.append(_dd_event(trade, "rsi_extreme", "warning",
                                       {"rsi": rsi, "condition": "overbought"}))
        elif rsi < 20:
            dd_events.append(_dd_event(trade, "rsi_extreme", "warning",
                                       {"rsi": rsi, "condition": "oversold"}))

    # Volume spike
    rvol = indicators.get("rvol")
    if rvol and rvol > 3.0:
        dd_events.append(_dd_event(trade, "volume_spike", "info",
                                   {"rvol": rvol}))

    # ATR expansion
    atr = indicators.get("atr")
    if atr and risk and atr > risk * 1.5:
        dd_events.append(_dd_event(trade, "volatility_expansion", "warning",
                                   {"atr": atr, "original_risk": float(risk)}))

    # Adverse news
    if news["adverse_count"] > 0:
        dd_events.append(_dd_event(trade, "adverse_news", "warning",
                                   {"count": news["adverse_count"],
                                    "titles": news["adverse_titles"]}))
    if news["positive_count"] > 0:
        dd_events.append(_dd_event(trade, "positive_catalyst", "info",
                                   {"count": news["positive_count"]}))

    # Thesis status
    thesis = trade.get("thesis_status")
    if thesis and thesis.lower() in ("degraded", "broken", "invalidated"):
        dd_events.append(_dd_event(trade, "thesis_degraded", "critical",
                                   {"thesis_status": thesis}))

    # Time in trade
    entry_time = trade.get("entry_time")
    hold_hours = None
    if entry_time:
        et = entry_time if entry_time.tzinfo else entry_time.replace(tzinfo=timezone.utc)
        hold_hours = (now - et).total_seconds() / 3600

    # Build snapshot
    snapshot = {
        "paper_trade_id": trade["id"], "symbol": sym,
        "current_price": current_price, "entry_price": entry,
        "stop_price": float(stop) if stop else None,
        "limit_price": float(target) if target else None,
        "unrealized_pnl": round(unreal_pnl, 2),
        "unrealized_pnl_pct": round(unreal_pnl_pct, 2) if unreal_pnl_pct else None,
        "r_multiple": round(r_mult, 2) if r_mult else None,
        "distance_to_stop_pct": round(dist_stop_pct, 2) if dist_stop_pct else None,
        "distance_to_target_pct": round(dist_target_pct, 2) if dist_target_pct else None,
        "atr": atr, "rsi": rsi,
        "volume_ratio": rvol, "vwap": indicators.get("vwap"),
        "trend_state": indicators.get("trend"),
        "news_risk_score": news["risk_score"],
        "technical_risk_score": None,
        "quote_fresh": quote_fresh, "quote_age_sec": quote_age_sec,
        "hold_hours": round(hold_hours, 1) if hold_hours else None,
        "intelligence_summary": _build_summary(trade, current_price, r_mult, dist_stop_pct, news, dd_events),
    }

    return snapshot, dd_events


def _dd_event(trade, event_type, severity, payload):
    return {
        "paper_trade_id": trade["id"], "symbol": trade["symbol"],
        "event_type": event_type, "severity": severity,
        "source": "open_trade_manager", "payload": payload,
        "requires_review": severity in ("warning", "critical"),
    }


def _build_summary(trade, price, r_mult, dist_stop, news, events):
    parts = [f"{trade['symbol']}"]
    if r_mult is not None:
        parts.append(f"R={r_mult:.1f}")
    if dist_stop is not None:
        parts.append(f"stop_dist={dist_stop:.1f}%")
    criticals = [e for e in events if e["severity"] == "critical"]
    warnings = [e for e in events if e["severity"] == "warning"]
    if criticals:
        parts.append(f"CRITICAL:{len(criticals)}")
    if warnings:
        parts.append(f"WARN:{len(warnings)}")
    return " | ".join(parts)


# ── Proposal engine ──────────────────────────────────────────────────────────

def generate_proposals(conn, trade, snapshot, dd_events):
    """Generate order modification proposals if warranted."""
    proposals = []
    sym = trade["symbol"]
    entry = _f(trade.get("entry_price")) or 0
    stop = _f(trade.get("stop_loss"))
    target = _f(trade.get("target_1"))
    current = snapshot.get("current_price")
    r_mult = snapshot.get("r_multiple")

    if not current or not entry:
        return proposals  # insufficient data

    risk = abs(entry - stop) if stop else None
    critical_events = [e for e in dd_events if e["severity"] == "critical"]

    # Trailing stop: if R >= 2, propose tightening stop to lock profit
    if r_mult and r_mult >= 2.0 and stop and current > entry and risk:
        new_stop = round(entry + risk * 0.5, 2)  # lock 0.5R profit
        if new_stop > float(stop):
            proposals.append(_proposal(trade, "adjust_stop", stop, new_stop, target, target,
                                       f"R={r_mult:.1f}, trailing stop to lock 0.5R profit",
                                       snapshot, dd_events, confidence=0.7))

    # Stop breach: propose close
    if any(e["event_type"] == "stop_breached" for e in dd_events):
        proposals.append(_proposal(trade, "close_trade", stop, None, target, None,
                                   "Stop breached — close position",
                                   snapshot, dd_events, confidence=0.9))

    # Thesis degraded: propose close
    if any(e["event_type"] == "thesis_degraded" for e in dd_events):
        proposals.append(_proposal(trade, "close_trade", stop, None, target, None,
                                   "Thesis degraded/broken — close position",
                                   snapshot, dd_events, confidence=0.8))

    # Target breached: propose close to take profit
    if any(e["event_type"] == "target_breached" for e in dd_events):
        proposals.append(_proposal(trade, "close_trade", stop, None, target, None,
                                   "Target reached — take profit",
                                   snapshot, dd_events, confidence=0.75))

    # No proposals needed
    if not proposals:
        proposals.append(_proposal(trade, "hold_no_change", stop, stop, target, target,
                                   "No action needed", snapshot, dd_events,
                                   confidence=1.0, status="hold"))

    return proposals


def _proposal(trade, action, cur_stop, prop_stop, cur_limit, prop_limit,
              reason, snapshot, dd_events, confidence=0.5, status="proposed"):
    return {
        "proposal_id": f"MOD_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{trade['id']}_{uuid.uuid4().hex[:6]}",
        "paper_trade_id": trade["id"], "symbol": trade["symbol"],
        "action": action,
        "current_stop": float(cur_stop) if cur_stop else None,
        "proposed_stop": float(prop_stop) if prop_stop else None,
        "current_limit": float(cur_limit) if cur_limit else None,
        "proposed_limit": float(prop_limit) if prop_limit else None,
        "current_qty": _f(trade.get("shares")),
        "reason": reason,
        "evidence": {
            "snapshot": {k: v for k, v in snapshot.items() if k != "intelligence_summary"},
            "dd_events": [{"type": e["event_type"], "severity": e["severity"]} for e in dd_events],
        },
        "confidence": confidence,
        "status": status if action != "hold_no_change" else "hold",
        "created_by": "open_trade_manager",
        "expires_at": str(datetime.now(timezone.utc) + timedelta(hours=4)),
    }


# ── Execution (approved proposals only) ──────────────────────────────────────

def execute_approved(conn, proposal_id):
    """Execute a single approved proposal. PAPER ONLY. Full safety checks."""
    # Safety gate 1: paper mode
    safe, msg = check_paper_mode()
    if not safe:
        return {"status": "blocked", "error": msg}

    # Safety gate 2: live trading gate
    gate_blocked, gate_result = run_live_trading_gate()
    if not gate_blocked:
        return {"status": "blocked", "error": "live_trading_gate not blocking — unsafe state"}

    cur = conn.cursor()
    cur.execute("""SELECT * FROM paper_order_modification_proposals
                   WHERE proposal_id=%s""", [proposal_id])
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    if not row:
        return {"status": "error", "error": f"Proposal {proposal_id} not found"}

    proposal = dict(zip(cols, row))

    # Must be approved
    if proposal["status"] != "approved":
        return {"status": "blocked", "error": f"Proposal status is '{proposal['status']}', must be 'approved'"}

    # Must not be expired
    if proposal.get("expires_at") and datetime.now(timezone.utc) > proposal["expires_at"].replace(tzinfo=timezone.utc):
        cur.execute("UPDATE paper_order_modification_proposals SET status='expired', updated_at=now() WHERE proposal_id=%s",
                    [proposal_id])
        conn.commit()
        return {"status": "expired", "error": "Proposal expired"}

    # Run risk gate
    try:
        from risk_gate import evaluate_risk
        risk = evaluate_risk(proposal["symbol"], mode="paper", action_context="broker_submit")
        if not risk.get("approved", False):
            cur.execute("""UPDATE paper_order_modification_proposals SET status='failed',
                           risk_gate_result=%s, error_message=%s, updated_at=now()
                           WHERE proposal_id=%s""",
                        [risk.get("result"), risk.get("reason_text", "risk_gate_blocked"), proposal_id])
            conn.commit()
            return {"status": "blocked", "error": "risk_gate_blocked", "risk": risk}
    except ImportError:
        log.warning("risk_gate not available — proceeding with caution")

    # Execute via Alpaca paper adapter
    try:
        from alpaca_paper_adapter import AlpacaPaperAdapter
        adapter = AlpacaPaperAdapter(dry_run=False)
        if not adapter.enabled:
            return {"status": "blocked", "error": "alpaca_paper_not_enabled"}

        action = proposal["action"]
        result = {"action": action, "proposal_id": proposal_id}

        if action == "close_trade":
            # Close via market sell
            trade_id = proposal["paper_trade_id"]
            cur.execute("SELECT symbol, shares FROM paper_trades WHERE id=%s AND status='open'", [trade_id])
            trow = cur.fetchone()
            if not trow:
                return {"status": "error", "error": "trade_not_found_or_closed"}
            resp = adapter._api_post("/v2/orders", {
                "symbol": trow[0], "qty": str(int(trow[1])),
                "side": "sell", "type": "market", "time_in_force": "day"
            })
            result["broker_response"] = {k: v for k, v in resp.items() if k not in ("account_id",)}
        elif action in ("adjust_stop", "adjust_limit", "replace_bracket"):
            result["note"] = "Order replacement requires cancel+replace — logged for manual review"
            result["broker_response"] = {"status": "logged_for_review"}
        else:
            result["note"] = "No broker action for this proposal type"
            result["broker_response"] = None

        # Update proposal
        cur.execute("""UPDATE paper_order_modification_proposals
                       SET status='executed', executed_at=now(),
                           broker_response=%s, updated_at=now()
                       WHERE proposal_id=%s""",
                    [json.dumps(result.get("broker_response"), default=str), proposal_id])
        conn.commit()
        return {"status": "executed", **result}

    except Exception as e:
        cur.execute("""UPDATE paper_order_modification_proposals
                       SET status='failed', error_message=%s, updated_at=now()
                       WHERE proposal_id=%s""", [str(e), proposal_id])
        conn.commit()
        return {"status": "failed", "error": str(e)}


# ── DB writers ───────────────────────────────────────────────────────────────

def save_snapshot(conn, snapshot):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO open_trade_intelligence_snapshots
            (paper_trade_id, symbol, current_price, entry_price, stop_price,
             limit_price, unrealized_pnl, unrealized_pnl_pct, r_multiple,
             distance_to_stop_pct, distance_to_target_pct,
             atr, rsi, volume_ratio, vwap, trend_state,
             news_risk_score, technical_risk_score, intelligence_summary)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, [snapshot["paper_trade_id"], snapshot["symbol"],
          snapshot.get("current_price"), snapshot.get("entry_price"),
          snapshot.get("stop_price"), snapshot.get("limit_price"),
          snapshot.get("unrealized_pnl"), snapshot.get("unrealized_pnl_pct"),
          snapshot.get("r_multiple"),
          snapshot.get("distance_to_stop_pct"), snapshot.get("distance_to_target_pct"),
          snapshot.get("atr"), snapshot.get("rsi"),
          snapshot.get("volume_ratio"), snapshot.get("vwap"),
          snapshot.get("trend_state"), snapshot.get("news_risk_score"),
          snapshot.get("technical_risk_score"), snapshot.get("intelligence_summary")])
    conn.commit()


def save_dd_events(conn, events):
    cur = conn.cursor()
    for ev in events:
        cur.execute("""
            INSERT INTO open_trade_due_diligence_events
                (paper_trade_id, symbol, event_type, severity, source, payload, requires_review)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, [ev["paper_trade_id"], ev["symbol"], ev["event_type"],
              ev["severity"], ev.get("source"),
              json.dumps(ev.get("payload"), default=str) if ev.get("payload") else None,
              ev.get("requires_review", True)])
    conn.commit()


def save_proposals(conn, proposals):
    cur = conn.cursor()
    saved = []
    for p in proposals:
        if p["status"] == "hold":
            continue  # don't persist hold_no_change
        cur.execute("""
            INSERT INTO paper_order_modification_proposals
                (proposal_id, paper_trade_id, symbol, action,
                 current_stop, proposed_stop, current_limit, proposed_limit,
                 current_qty, reason, evidence, confidence,
                 created_by, status, expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, [p["proposal_id"], p["paper_trade_id"], p["symbol"], p["action"],
              p.get("current_stop"), p.get("proposed_stop"),
              p.get("current_limit"), p.get("proposed_limit"),
              p.get("current_qty"), p["reason"],
              json.dumps(p.get("evidence"), default=str) if p.get("evidence") else None,
              p.get("confidence"), p.get("created_by"), p["status"], p.get("expires_at")])
        saved.append(p["proposal_id"])
    conn.commit()
    return saved


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Open trade intelligence & modification proposals")
    parser.add_argument("--scan-open", action="store_true", help="Scan all open trades")
    parser.add_argument("--symbol", help="Filter to single symbol")
    parser.add_argument("--trade-id", type=int, help="Single trade ID")
    parser.add_argument("--dry-run", action="store_true", help="Compute only, no DB writes")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--create-proposals", action="store_true", help="Create modification proposals")
    parser.add_argument("--execute-approved", action="store_true", help="Execute approved proposals")
    parser.add_argument("--proposal-id", help="Specific proposal to execute")
    args = parser.parse_args()

    # Safety check
    safe, msg = check_paper_mode()
    if not safe:
        print(json.dumps({"status": "blocked", "error": msg}) if args.json else f"BLOCKED: {msg}")
        sys.exit(1)

    conn = get_conn()
    try:
        # Execute-approved mode
        if args.execute_approved and args.proposal_id:
            result = execute_approved(conn, args.proposal_id)
            if args.json:
                print(json.dumps(result, indent=2, default=str))
            else:
                print(f"[execute] {result.get('status')}: {result.get('error', 'ok')}")
            return

        # Scan mode
        trades = get_open_trades(conn, symbol=args.symbol, trade_id=args.trade_id)

        all_snapshots = []
        all_dd_events = []
        all_proposals = []

        for trade in trades:
            snapshot, dd_events = run_due_diligence(conn, trade)
            all_snapshots.append(snapshot)
            all_dd_events.extend(dd_events)

            if args.create_proposals:
                proposals = generate_proposals(conn, trade, snapshot, dd_events)
                all_proposals.extend(proposals)

        # Save if not dry-run
        saved_proposal_ids = []
        if not args.dry_run:
            for s in all_snapshots:
                save_snapshot(conn, s)
            save_dd_events(conn, all_dd_events)
            if args.create_proposals:
                saved_proposal_ids = save_proposals(conn, all_proposals)
            log.info(f"Saved {len(all_snapshots)} snapshots, {len(all_dd_events)} DD events, "
                     f"{len(saved_proposal_ids)} proposals")

        out = {
            "mode": "dry_run" if args.dry_run else "applied",
            "trades_scanned": len(trades),
            "snapshots": len(all_snapshots),
            "dd_events": len(all_dd_events),
            "dd_by_type": {},
            "proposals": len([p for p in all_proposals if p["status"] != "hold"]),
            "holds": len([p for p in all_proposals if p["status"] == "hold"]),
            "saved_proposal_ids": saved_proposal_ids,
        }
        for ev in all_dd_events:
            out["dd_by_type"][ev["event_type"]] = out["dd_by_type"].get(ev["event_type"], 0) + 1

        if args.json:
            out["snapshot_summaries"] = [
                {"symbol": s["symbol"], "r": s.get("r_multiple"), "pnl_pct": s.get("unrealized_pnl_pct"),
                 "summary": s.get("intelligence_summary")}
                for s in all_snapshots
            ]
            out["proposal_details"] = [
                {"id": p["proposal_id"], "symbol": p["symbol"], "action": p["action"],
                 "reason": p["reason"], "confidence": p["confidence"], "status": p["status"]}
                for p in all_proposals if p["status"] != "hold"
            ]
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"[otm] {out['mode']}: {out['trades_scanned']} trades, "
                  f"{out['dd_events']} DD events, {out['proposals']} proposals, {out['holds']} holds")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
