#!/usr/bin/env python3
"""paper_execution_revalidator.py — Universal execution-time revalidation engine.

Revalidates ANY approved/pending paper trade before Alpaca paper order submission.
Catches stale recommendations, price drift, spread changes, market session issues,
and requires reapproval for material plan changes.

PAPER ONLY. No live trading. No automatic broker submission.

Usage:
    .venv/bin/python scripts/paper_execution_revalidator.py --all-pending --dry-run --json
    .venv/bin/python scripts/paper_execution_revalidator.py --proposal-id 123 --dry-run --json
    .venv/bin/python scripts/paper_execution_revalidator.py --symbol AAPL --simulate-delay-minutes 240 --dry-run --json
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
from market_session import (current_market_session, is_market_open, is_recommendation_stale,
                            is_approval_stale, should_delay_execution, get_freshness_threshold,
                            next_regular_session_open)

log = logging.getLogger("paper_execution_revalidator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Material change thresholds (global defaults; strategy/curated sources may use wider bands)
PRICE_DRIFT_WARN_PCT = 1.5
PRICE_DRIFT_BLOCK_PCT = 3.0
ENTRY_CHANGE_BLOCK_BPS = 200  # 2%
SPREAD_MAX_BPS = 100
RISK_INCREASE_BLOCK_PCT = 20  # stop loosening >20% of original risk

_CURATED_DISCOVERY = frozenset({"pullback_macd", "watchlist", "screener", "incubator"})


def _price_drift_block_pct(strategy_id: str | None, discovery_source: str | None = None) -> float:
    """Strategy-aware drift block — aligns submit-time revalidation with proposal_lifecycle monitor."""
    try:
        from proposal_lifecycle import get_price_drift_threshold
        strategy_pct = float(get_price_drift_threshold(strategy_id or ""))
    except Exception:
        strategy_pct = PRICE_DRIFT_BLOCK_PCT
    ds = str(discovery_source or "").lower()
    if ds in _CURATED_DISCOVERY:
        return max(PRICE_DRIFT_BLOCK_PCT, strategy_pct)
    return PRICE_DRIFT_BLOCK_PCT


def _price_drift_warn_pct(block_pct: float) -> float:
    return min(PRICE_DRIFT_WARN_PCT, max(1.0, block_pct * 0.5))


def _f(v):
    return float(v) if isinstance(v, Decimal) else v


def _safe_pct(a, b):
    if not a or not b or b == 0:
        return None
    return ((a - b) / abs(b)) * 100


# ── Safety gates ─────────────────────────────────────────────────────────────

def check_safety():
    """Verify paper mode and trading gate."""
    mode = os.getenv("ALPACA_MODE", "paper").lower()
    live = os.getenv("LIVE_TRADING", "false").lower()
    errors = []
    if mode != "paper":
        errors.append(f"ALPACA_MODE={mode}")
    if live == "true":
        errors.append("LIVE_TRADING=true")
    try:
        from live_trading_gate import evaluate
        gate = evaluate()
        if gate.get("allowed", True):
            errors.append("live_trading_gate_not_blocking")
    except Exception:
        pass  # gate unavailable is acceptable
    return len(errors) == 0, errors


# ── Data fetchers ────────────────────────────────────────────────────────────

def get_pending_proposals(conn, proposal_id=None, symbol=None):
    """Get approved/pending proposals eligible for execution."""
    cur = conn.cursor()
    conditions = ["status IN ('APPROVED', 'APPROVED_FOR_PAPER_TEST', 'PENDING')"]
    params = []
    if proposal_id:
        conditions.append("id = %s")
        params.append(proposal_id)
    if symbol:
        conditions.append("symbol = %s")
        params.append(symbol)
    sql = f"""SELECT id, symbol, strategy_id, discovery_source, proposed_entry, proposed_stop, proposed_target1,
                     proposed_shares, proposed_dollar_risk, status, signal_grade, signal_score,
                     created_at, approved_at, paper_submitted_at,
                     COALESCE(execution_recheck_required, true) as execution_recheck_required,
                     COALESCE(approved_pending_recheck, false) as approved_pending_recheck,
                     last_recheck_id, execution_validated_at,
                     COALESCE(material_change_pending_approval, false) as material_change_pending_approval
              FROM paper_trade_proposals WHERE {' AND '.join(conditions)}
              ORDER BY created_at DESC"""
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_current_quote(conn, symbol):
    """Get latest price data for symbol. Tries live Alpaca quote first, falls back to DB."""
    # Try live quote from Alpaca for freshest price
    try:
        from market_quote_provider import fetch_alpaca_quote
        live = fetch_alpaca_quote(symbol)
        if live and live.get("price") and live["price"] > 0:
            return {"price": _f(live["price"]), "time": datetime.now(timezone.utc), "source": "alpaca_live"}
    except Exception as e:
        log.debug(f"Live quote failed for {symbol}: {e}")
    # Fallback to trade_ai_scans
    cur = conn.cursor()
    cur.execute("""SELECT price, scanned_at FROM trade_ai_scans
                   WHERE symbol=%s ORDER BY scanned_at DESC LIMIT 1""", [symbol])
    row = cur.fetchone()
    if row:
        return {"price": _f(row[0]), "time": row[1], "source": "trade_ai_scans"}
    return None


def get_indicator_snapshot(conn, symbol):
    """Get latest indicator data from confluence cache."""
    cur = conn.cursor()
    try:
        cur.execute("""SELECT atr, confluence_score, adx_regime, entry_quality, full_result
                       FROM indicator_confluence_cache
                       WHERE symbol=%s ORDER BY computed_at DESC LIMIT 1""", [symbol])
        row = cur.fetchone()
        if row:
            full = row[4] or {}
            return {"atr": _f(row[0]), "confluence_score": row[1],
                    "adx_regime": row[2], "entry_quality": row[3],
                    "rsi": _f(full.get("rsi")), "rvol": _f(full.get("rvol")),
                    "vwap": _f(full.get("vwap")), "trend": full.get("trend_label")}
    except Exception:
        pass
    return {}


def check_duplicate_order(conn, symbol):
    """Check for existing open trade or pending order for symbol."""
    cur = conn.cursor()
    cur.execute("""SELECT id, status FROM paper_trades
                   WHERE symbol=%s AND status IN ('open', 'pending')
                   AND account='ALPACA_PAPER'""", [symbol])
    existing = cur.fetchone()
    if existing:
        return True, f"existing_trade_id={existing[0]}_status={existing[1]}"
    return False, None


def check_broker_reconciliation(conn, symbol):
    """Check if latest broker reconciliation is clean for symbol."""
    cur = conn.cursor()
    cur.execute("""SELECT item_type, severity FROM paper_broker_reconciliation_items
                   WHERE symbol=%s AND status='open' AND severity IN ('warning', 'critical')
                   ORDER BY created_at DESC LIMIT 5""", [symbol])
    issues = cur.fetchall()
    if issues:
        return False, [{"type": r[0], "severity": r[1]} for r in issues]
    return True, []


# ── Core revalidation ────────────────────────────────────────────────────────

def revalidate(conn, proposal, simulate_delay_min=None, simulate_session=None, simulate_drift_pct=None):
    """Run full execution-time revalidation on a single proposal."""
    now = datetime.now(timezone.utc)
    sym = proposal["symbol"]
    strategy = proposal.get("strategy_id") or "default"
    discovery_source = proposal.get("discovery_source")
    drift_block_pct = _price_drift_block_pct(strategy, discovery_source)
    drift_warn_pct = _price_drift_warn_pct(drift_block_pct)
    recheck_id = f"RCK_{now.strftime('%Y%m%d_%H%M%S')}_{proposal['id']}_{uuid.uuid4().hex[:6]}"

    # Timestamps — use approved_at for staleness (when user acted), not created_at
    approved_at = proposal.get("approved_at")
    if approved_at and approved_at.tzinfo is None:
        approved_at = approved_at.replace(tzinfo=timezone.utc)
    rec_created = approved_at or proposal.get("created_at")
    if rec_created and rec_created.tzinfo is None:
        rec_created = rec_created.replace(tzinfo=timezone.utc)

    # Simulate delay
    effective_now = now
    if simulate_delay_min:
        rec_created = now - timedelta(minutes=simulate_delay_min)

    elapsed_rec = (effective_now - rec_created).total_seconds() if rec_created else None
    elapsed_appr = (effective_now - approved_at).total_seconds() if approved_at else None

    # Original plan
    entry = _f(proposal.get("proposed_entry"))
    stop = _f(proposal.get("proposed_stop"))
    target = _f(proposal.get("proposed_target1"))
    shares = _f(proposal.get("proposed_shares"))
    original_plan = {"entry": entry, "stop": stop, "target": target, "shares": shares}

    # Current data
    quote = get_current_quote(conn, sym)
    indicators = get_indicator_snapshot(conn, sym)
    current_price = quote["price"] if quote else None

    if simulate_drift_pct and entry:
        current_price = entry * (1 + simulate_drift_pct / 100)

    # Market session
    session = simulate_session or current_market_session()

    # Initialize result
    events = []
    material_changes = []
    blockers = []
    status = "pending"
    score = 100  # start at 100, deduct for issues

    # ── Check 1: Market session ──
    delay, delay_reason = should_delay_execution(strategy)
    if simulate_session:
        delay = simulate_session not in ("regular",)
        delay_reason = f"simulated_{simulate_session}"

    if delay:
        events.append(_event(sym, proposal["id"], "market_closed", "normal",
                             {"session": session, "reason": delay_reason}))
        status = "delayed"
        score -= 50

    # ── Check 2: Recommendation staleness ──
    rec_stale, rec_msg = is_recommendation_stale(rec_created, strategy) if rec_created else (True, "no_created_at")
    if rec_stale:
        events.append(_event(sym, proposal["id"], "stale_recommendation_detected", "warning",
                             {"message": rec_msg, "elapsed_sec": elapsed_rec}))
        score -= 20
        material_changes.append(f"stale_recommendation: {rec_msg}")

    # ── Check 3: Approval staleness ──
    if approved_at:
        appr_stale, appr_msg = is_approval_stale(approved_at, strategy)
        if appr_stale:
            events.append(_event(sym, proposal["id"], "stale_approval", "warning",
                                 {"message": appr_msg, "elapsed_sec": elapsed_appr}))
            score -= 10

    # ── Check 4: Quote freshness ──
    if not quote:
        events.append(_event(sym, proposal["id"], "no_quote_data", "critical", {}))
        blockers.append("no_quote_data")
        score -= 40
    elif quote.get("time"):
        qt = quote["time"]
        if qt.tzinfo is None:
            qt = qt.replace(tzinfo=timezone.utc)
        quote_age = (effective_now - qt).total_seconds()
        if quote_age > 900:
            events.append(_event(sym, proposal["id"], "stale_quote", "warning",
                                 {"age_seconds": quote_age}))
            score -= 15

    # ── Check 4b: Stop already breached — instant block ──
    if current_price and stop and current_price <= stop:
        events.append(_event(sym, proposal["id"], "stop_already_breached", "critical",
                             {"current_price": current_price, "stop": stop,
                              "message": f"Current price ${current_price:.2f} is at or below stop ${stop:.2f} — trade would immediately stop out"}))
        blockers.append(f"stop_breached: price ${current_price:.2f} <= stop ${stop:.2f}")
        score -= 100

    # ── Check 5: Price drift ──
    drift_pct = None
    if current_price and entry and entry > 0:
        drift_pct = abs(current_price - entry) / entry * 100
        if drift_pct >= drift_block_pct:
            events.append(_event(sym, proposal["id"], "price_drift_detected", "critical",
                                 {"drift_pct": round(drift_pct, 2), "entry": entry, "current": current_price,
                                  "block_threshold_pct": drift_block_pct}))
            material_changes.append(f"price_drift={drift_pct:.1f}%")
            score -= 30
        elif drift_pct >= drift_warn_pct:
            events.append(_event(sym, proposal["id"], "price_drift_detected", "warning",
                                 {"drift_pct": round(drift_pct, 2), "warn_threshold_pct": drift_warn_pct}))
            score -= 10

    # ── Check 6: Risk/reward change ──
    if current_price and stop and target and entry:
        orig_risk = abs(entry - stop) if stop else 0
        new_risk = abs(current_price - stop) if stop else 0
        if orig_risk > 0 and new_risk > orig_risk * (1 + RISK_INCREASE_BLOCK_PCT / 100):
            material_changes.append(f"risk_increased: orig={orig_risk:.2f} new={new_risk:.2f}")
            score -= 15

        orig_rr = abs(target - entry) / orig_risk if orig_risk else 0
        new_rr = abs(target - current_price) / new_risk if new_risk else 0
        if orig_rr > 0 and new_rr < orig_rr * 0.5:
            material_changes.append(f"rr_degraded: orig={orig_rr:.1f} new={new_rr:.1f}")
            score -= 15

    # ── Check 7: Duplicate order ──
    has_dup, dup_msg = check_duplicate_order(conn, sym)
    if has_dup:
        events.append(_event(sym, proposal["id"], "duplicate_order_risk", "critical",
                             {"message": dup_msg}))
        blockers.append(f"duplicate: {dup_msg}")
        score -= 40

    # ── Check 8: Broker reconciliation ──
    recon_clean, recon_issues = check_broker_reconciliation(conn, sym)
    if not recon_clean:
        events.append(_event(sym, proposal["id"], "broker_mismatch", "warning",
                             {"issues": recon_issues}))
        score -= 10

    # ── Check 9: Risk gate ──
    risk_result = None
    try:
        from risk_gate import evaluate_risk
        risk = evaluate_risk(sym, mode="paper", action_context="broker_submit")
        risk_result = risk.get("result", "unknown")
        if not risk.get("approved", False):
            events.append(_event(sym, proposal["id"], "risk_gate_blocked", "critical",
                                 {"result": risk_result}))
            blockers.append(f"risk_gate: {risk_result}")
            score -= 30
    except Exception:
        pass

    # ── Check 10: RSI extreme ──
    rsi = indicators.get("rsi")
    if rsi and rsi > 80:
        events.append(_event(sym, proposal["id"], "rsi_overbought", "warning", {"rsi": rsi}))
        score -= 5

    # ── Determine outcome ──
    score = max(0, score)
    requires_reapproval = len(material_changes) > 0 and any(
        "price_drift" in m or "risk_increased" in m or "rr_degraded" in m for m in material_changes
    )

    if blockers:
        status = "blocked_safety"
    elif status == "delayed":
        pass  # already set
    elif requires_reapproval:
        status = "updated_plan_requires_reapproval"
    elif rec_stale and score < 60:
        status = "downgraded_to_wait"
    elif score >= 70:
        status = "valid_original"
    elif score >= 50:
        status = "delayed"
    else:
        status = "cancelled"

    recalibrated = None
    if current_price and entry:
        recalibrated = {
            "entry": current_price,
            "stop": stop,
            "target": target,
            "shares": shares,
            "note": "recalibrated to current price" if drift_pct and drift_pct > PRICE_DRIFT_WARN_PCT else "original plan"
        }

    # Map status to eligibility for downstream consumers
    eligibility_map = {
        "valid_original": "ELIGIBLE",
        "blocked_safety": "INELIGIBLE",
        "cancelled": "INELIGIBLE",
        "downgraded_to_wait": "INELIGIBLE",
        "updated_plan_requires_reapproval": "NEEDS_REVALIDATION",
        "delayed": "NEEDS_REVALIDATION",
    }
    eligibility_status = eligibility_map.get(status, "INELIGIBLE")

    result = {
        "recheck_id": recheck_id,
        "paper_trade_proposal_id": proposal["id"],
        "symbol": sym,
        "eligibility_status": eligibility_status,
        "trigger_type": _determine_trigger(session, rec_stale, drift_pct),
        "recommendation_created_at": str(rec_created) if rec_created else None,
        "approval_created_at": str(approved_at) if approved_at else None,
        "elapsed_since_recommendation_seconds": round(elapsed_rec) if elapsed_rec else None,
        "elapsed_since_approval_seconds": round(elapsed_appr) if elapsed_appr else None,
        "status": status,
        "original_plan": original_plan,
        "recalibrated_plan": recalibrated,
        "quote_snapshot": {k: str(v) for k, v in quote.items()} if quote else None,
        "market_session": session,
        "price_at_recommendation": entry,
        "current_price": current_price,
        "price_drift_pct": round(drift_pct, 2) if drift_pct else None,
        "atr": indicators.get("atr"),
        "rsi": rsi,
        "risk_gate_result": risk_result,
        "execution_readiness_score": score,
        "material_change_detected": len(material_changes) > 0,
        "material_change_reasons": material_changes,
        "recommendation": status,
        "reason": "; ".join(blockers) if blockers else (
            "; ".join(material_changes) if material_changes else "plan_valid"),
        "requires_reapproval": requires_reapproval,
        "events": events,
    }
    return result


def _determine_trigger(session, rec_stale, drift_pct):
    if session in ("weekend", "holiday"):
        return "weekend_approval"
    if session in ("closed", "afterhours"):
        return "after_hours_approval"
    if session == "premarket":
        return "premarket_recheck"
    if rec_stale:
        return "stale_recommendation"
    if drift_pct and drift_pct > PRICE_DRIFT_WARN_PCT:
        return "price_drift_recheck"
    return "pre_execution_required"


def _event(symbol, proposal_id, event_type, severity, payload):
    return {"symbol": symbol, "proposal_id": proposal_id,
            "event_type": event_type, "severity": severity, "payload": payload}


# ── DB writers ───────────────────────────────────────────────────────────────

def save_recheck(conn, result):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO paper_trade_execution_rechecks
            (recheck_id, paper_trade_proposal_id, symbol, trigger_type,
             recommendation_created_at, approval_created_at,
             elapsed_since_recommendation_seconds, elapsed_since_approval_seconds,
             status, original_plan, recalibrated_plan, quote_snapshot,
             market_session, price_at_recommendation, current_price,
             price_drift_pct, atr, rsi, risk_gate_result,
             execution_readiness_score, material_change_detected,
             material_change_reasons, recommendation, reason,
             requires_reapproval, started_at, finished_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now())
    """, [result["recheck_id"], result["paper_trade_proposal_id"], result["symbol"],
          result["trigger_type"], result.get("recommendation_created_at"),
          result.get("approval_created_at"),
          result.get("elapsed_since_recommendation_seconds"),
          result.get("elapsed_since_approval_seconds"),
          result["status"],
          json.dumps(result.get("original_plan"), default=str),
          json.dumps(result.get("recalibrated_plan"), default=str),
          json.dumps(result.get("quote_snapshot"), default=str),
          result.get("market_session"), result.get("price_at_recommendation"),
          result.get("current_price"), result.get("price_drift_pct"),
          result.get("atr"), result.get("rsi"), result.get("risk_gate_result"),
          result["execution_readiness_score"], result["material_change_detected"],
          json.dumps(result.get("material_change_reasons"), default=str),
          result["recommendation"], result["reason"], result["requires_reapproval"]])

    # Save events
    for ev in result.get("events", []):
        cur.execute("""
            INSERT INTO paper_trade_pre_execution_events
                (symbol, proposal_id, event_type, severity, payload)
            VALUES (%s,%s,%s,%s,%s)
        """, [ev["symbol"], ev.get("proposal_id"), ev["event_type"],
              ev["severity"], json.dumps(ev.get("payload"), default=str)])

    # Update proposal columns
    cur.execute("""
        UPDATE paper_trade_proposals
        SET last_recheck_id=%s, execution_readiness_score=%s,
            execution_recheck_required=%s,
            approved_pending_recheck=%s,
            material_change_pending_approval=%s,
            execution_recheck_reason=%s,
            execution_validated_at=CASE WHEN %s='valid_original' THEN now() ELSE execution_validated_at END
        WHERE id=%s
    """, [result["recheck_id"], result["execution_readiness_score"],
          result["status"] != "valid_original",
          result["status"] in ("delayed", "updated_plan_requires_reapproval"),
          result["requires_reapproval"],
          result["reason"][:200],
          result["status"], result["paper_trade_proposal_id"]])

    conn.commit()
    return result["recheck_id"]


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Paper execution-time revalidation engine")
    parser.add_argument("--proposal-id", type=int, help="Specific proposal ID")
    parser.add_argument("--symbol", help="Filter by symbol")
    parser.add_argument("--all-pending", action="store_true", help="All pending/approved proposals")
    parser.add_argument("--dry-run", action="store_true", help="Compute only")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--simulate-delay-minutes", type=int, help="Simulate recommendation age")
    parser.add_argument("--simulate-market-session", help="Simulate market session")
    parser.add_argument("--simulate-price-drift-pct", type=float, help="Simulate price drift %")
    args = parser.parse_args()

    safe, errors = check_safety()
    if not safe:
        out = {"status": "blocked_safety", "errors": errors}
        print(json.dumps(out, indent=2) if args.json else f"BLOCKED: {errors}")
        sys.exit(1)

    conn = get_conn()
    try:
        proposals = get_pending_proposals(conn, proposal_id=args.proposal_id, symbol=args.symbol)
        if not proposals and not args.all_pending:
            proposals = get_pending_proposals(conn)

        results = []
        for p in proposals:
            result = revalidate(conn, p,
                                simulate_delay_min=args.simulate_delay_minutes,
                                simulate_session=args.simulate_market_session,
                                simulate_drift_pct=args.simulate_price_drift_pct)
            if not args.dry_run:
                save_recheck(conn, result)
            results.append(result)

        out = {
            "mode": "dry_run" if args.dry_run else "applied",
            "proposals_checked": len(results),
            "by_status": {},
        }
        for r in results:
            out["by_status"][r["status"]] = out["by_status"].get(r["status"], 0) + 1

        if args.json:
            out["results"] = [{k: v for k, v in r.items() if k != "events"} for r in results]
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"[revalidate] {out['mode']}: {out['proposals_checked']} checked, "
                  f"statuses={out['by_status']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
