#!/usr/bin/env python3
"""proposal_paper_submitter.py — Gated paper-only Alpaca submission.

Validates all gates before submitting a proposal to Alpaca paper trading.
SAFETY: This script ONLY submits to paper trading. Live trading is permanently blocked.

Usage:
    .venv/bin/python scripts/proposal_paper_submitter.py --proposal-id 123 --dry-run
    .venv/bin/python scripts/proposal_paper_submitter.py --proposal-id 123 --submit-paper
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from session13_db import get_conn

log = logging.getLogger("paper_submitter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# Hard safety locks
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
ALPACA_MODE = os.getenv("ALPACA_MODE", "paper").lower()
REQUIRE_SIX_MONTH_PAPER_VALIDATION = True


def _log_event(conn, proposal_id, symbol, event_type, payload):
    """Write to proposal_event_log."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO proposal_event_log (proposal_id, symbol, event_type, event_source, payload)
            VALUES (%s, %s, %s, 'paper_submitter', %s)
        """, [proposal_id, symbol, event_type, json.dumps(payload, default=str)])
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


_CANCEL_LABELS = {
    "broker_risk_gate": "Broker risk gate",
    "broker_rejected": "Broker rejected order",
    "revalidation_blocked": "Execution revalidation blocked",
    "revalidation_reapproval": "Revalidation requires re-approval",
    "submit_error": "Submission error",
    "never_submitted_timeout": "Never submitted (timeout)",
}


def _format_block_detail(raw) -> str:
    """Normalize blocker payloads (list/dict/str) into operator-readable text."""
    if raw is None:
        return "unknown"
    if isinstance(raw, dict):
        raw = raw.get("reason") or raw.get("error") or raw.get("blockers") or raw
    if isinstance(raw, list):
        parts = [str(x).strip() for x in raw if x]
        return "; ".join(parts) if parts else "unknown"
    text = str(raw).strip()
    return text or "unknown"


def _notify_trade_cancelled(
    symbol: str,
    proposal_id: int,
    trade_ids: list,
    cancel_code: str,
    detail: str,
    strategy_id: str | None = None,
) -> None:
    """Operator alert — specific cancel reason, not a generic phantom/sync message."""
    label = _CANCEL_LABELS.get(cancel_code, cancel_code.replace("_", " ").title())
    strat = f" ({strategy_id.replace('_', ' ')})" if strategy_id else ""
    tid = f"\nTrade record: #{trade_ids[0]}" if trade_ids else ""
    if len(trade_ids) > 1:
        tid += f" (+{len(trade_ids) - 1} more)"
    msg = (
        f"🚫 *TRADE CANCELLED — {symbol}{strat}*\n\n"
        f"Proposal #{proposal_id}{tid}\n"
        f"*Reason:* {label}\n"
        f"*Detail:* {detail}\n\n"
        f"No Alpaca order was submitted. DB record marked `cancelled`."
    )
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception as e:
        log.warning(f"[submitter] cancel notify failed for {symbol}: {e}")


def _cancel_never_submitted_pending(
    conn,
    proposal_id: int,
    *,
    cancel_code: str,
    detail,
    closed_via: str,
    symbol: str | None = None,
    strategy_id: str | None = None,
    notify: bool = True,
) -> int:
    """Cancel pre-created pending paper_trades rows that never received a broker order."""
    detail_text = _format_block_detail(detail)
    exit_reason = f"cancelled_{cancel_code}"
    note = f"CANCELLED — {_CANCEL_LABELS.get(cancel_code, cancel_code)}: {detail_text}"
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, symbol, strategy_id FROM paper_trades
               WHERE proposal_id=%s AND status='pending'
                 AND COALESCE(broker_order_id,'')='' AND filled_at IS NULL""",
            (proposal_id,),
        )
        rows = cur.fetchall()
        if not rows:
            return 0
        trade_ids = [r[0] for r in rows]
        sym = symbol or (rows[0][1] if rows else "?")
        strat = strategy_id or (rows[0][2] if rows else None)
        cur.execute(
            """UPDATE paper_trades
               SET status='cancelled', lifecycle_state='cancelled',
                   exit_reason=%s, close_reason=%s,
                   notes=COALESCE(notes,'') || CASE WHEN COALESCE(notes,'')='' THEN %s ELSE ' | ' || %s END,
                   closed_via=%s, closed_at=NOW(),
                   outcome_verdict='CANCELLED', pnl=0, pnl_pct=0, r_multiple=0, unrealized_pnl=0
               WHERE proposal_id=%s AND status='pending'
                 AND COALESCE(broker_order_id,'')='' AND filled_at IS NULL""",
            (exit_reason, exit_reason, note, note, closed_via, proposal_id),
        )
        n = cur.rowcount
        if n:
            conn.commit()
            _log_event(conn, proposal_id, sym, "TRADE_CANCELLED",
                       {"cancel_code": cancel_code, "detail": detail_text,
                        "trade_ids": trade_ids, "exit_reason": exit_reason})
            log.warning(f"[submitter] CANCELLED {sym} proposal #{proposal_id} "
                        f"({cancel_code}): {detail_text}")
            if notify:
                _notify_trade_cancelled(sym, proposal_id, trade_ids, cancel_code, detail_text, strat)
        return n
    except Exception as e:
        log.warning(f"[submitter] pending-row cleanup failed for proposal {proposal_id}: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 0


def _create_evidence_snapshot(conn, proposal_id, symbol, strategy_id):
    """Capture point-in-time evidence snapshot before submission."""
    cur = conn.cursor()
    snapshot = {}

    # Scan data
    cur.execute("""
        SELECT row_to_json(s) FROM (
            SELECT symbol, price, rvol, float_m, gap_pct, change_pct,
                   catalyst, catalyst_verified, sector, industry,
                   vs_sector_pct, scanned_at
            FROM trade_ai_scans WHERE symbol=%s ORDER BY scanned_at DESC LIMIT 1
        ) s
    """, [symbol])
    row = cur.fetchone()
    snapshot["scan"] = row[0] if row else None

    # Indicator data
    cur.execute("""
        SELECT row_to_json(i) FROM (
            SELECT symbol, confluence_score, confluence_tier, atr, adx_regime,
                   entry_quality, computed_at
            FROM indicator_confluence_cache WHERE symbol=%s ORDER BY computed_at DESC LIMIT 1
        ) i
    """, [symbol])
    row = cur.fetchone()
    snapshot["indicators"] = row[0] if row else None

    # Agent reviews
    cur.execute("""
        SELECT json_agg(row_to_json(r)) FROM (
            SELECT agent_name, vote, confidence, summary
            FROM proposal_agent_reviews WHERE proposal_id=%s
        ) r
    """, [proposal_id])
    row = cur.fetchone()
    snapshot["agent_reviews"] = row[0] if row else None

    # LLM analysis
    cur.execute("""
        SELECT row_to_json(a) FROM (
            SELECT model_used, narrative_source, summary, confidence
            FROM paper_proposal_analysis WHERE proposal_id=%s
            ORDER BY created_at DESC LIMIT 1
        ) a
    """, [proposal_id])
    row = cur.fetchone()
    snapshot["llm_analysis"] = row[0] if row else None

    # Quality review
    cur.execute("""
        SELECT row_to_json(q) FROM (
            SELECT review_state, quality_score
            FROM proposal_quality_reviews WHERE proposal_id=%s
            ORDER BY created_at DESC LIMIT 1
        ) q
    """, [proposal_id])
    row = cur.fetchone()
    snapshot["quality_review"] = row[0] if row else None

    # Backtest
    cur.execute("""
        SELECT row_to_json(b) FROM (
            SELECT backtest_quality, sample_size, win_rate, profit_factor, expectancy
            FROM proposal_backtest_snapshots WHERE proposal_id=%s
            ORDER BY id DESC LIMIT 1
        ) b
    """, [proposal_id])
    row = cur.fetchone()
    snapshot["backtest"] = row[0] if row else None

    # Session 23D: Fetch technical snapshot + execution readiness for thesis
    tech_snapshot_id = None
    exec_readiness_id = None
    fib_ctx = None
    orb_status = None
    try:
        cur.execute("""
            SELECT id, fib_context, opening_range_status
            FROM proposal_technical_snapshots
            WHERE proposal_id = %s ORDER BY computed_at DESC LIMIT 1
        """, [proposal_id])
        ts = cur.fetchone()
        if ts:
            tech_snapshot_id = ts[0]
            fib_ctx = ts[1]
            orb_status = ts[2]
    except Exception:
        pass

    try:
        cur.execute("""
            SELECT id FROM proposal_execution_readiness
            WHERE proposal_id = %s ORDER BY created_at DESC LIMIT 1
        """, [proposal_id])
        er = cur.fetchone()
        if er:
            exec_readiness_id = er[0]
    except Exception:
        pass

    # Write evidence snapshot with thesis fields
    cur.execute("""
        INSERT INTO proposal_evidence_snapshots
            (proposal_id, symbol, strategy_id, snapshot_type,
             scan_snapshot, indicator_snapshot, agent_snapshot,
             llm_snapshot, quality_snapshot, backtest_snapshot,
             technical_snapshot_id, execution_readiness_id,
             fib_context, opening_range_status)
        VALUES (%s, %s, %s, 'pre_submit', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, [
        proposal_id, symbol, strategy_id,
        json.dumps(snapshot.get("scan"), default=str),
        json.dumps(snapshot.get("indicators"), default=str),
        json.dumps(snapshot.get("agent_reviews"), default=str),
        json.dumps(snapshot.get("llm_analysis"), default=str),
        json.dumps(snapshot.get("quality_review"), default=str),
        json.dumps(snapshot.get("backtest"), default=str),
        tech_snapshot_id, exec_readiness_id,
        json.dumps(fib_ctx, default=str) if fib_ctx else None,
        orb_status,
    ])
    snapshot_id = cur.fetchone()[0]
    conn.commit()

    # Session 23D: Log THESIS_SNAPSHOT_READY event
    _log_event(conn, proposal_id, symbol, "THESIS_SNAPSHOT_READY", {
        "evidence_snapshot_id": snapshot_id,
        "technical_snapshot_id": tech_snapshot_id,
        "execution_readiness_id": exec_readiness_id,
        "has_fib": fib_ctx is not None,
        "has_orb": orb_status is not None,
    })

    return snapshot_id


def check_gates(conn, proposal_id: int) -> dict:
    """Run all pre-submission gate checks. Returns {passed, blockers, warnings}."""
    cur = conn.cursor()

    # Load proposal
    cur.execute("""
        SELECT id, symbol, strategy_id, status, proposed_entry, proposed_stop,
               proposed_target1, proposed_shares, proposed_dollar_risk, proposed_rr,
               risk_gate_result, approval_allowed, intel_readiness,
               created_at, approved_at, recommendation_created_at, signal_grade, signal_score,
               paper_submit_state
        FROM paper_trade_proposals WHERE id = %s
    """, [proposal_id])
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    if not row:
        return {"passed": False, "blockers": [f"Proposal {proposal_id} not found"], "warnings": []}

    p = dict(zip(cols, row))
    blockers = []
    warnings = []

    # Gate 0: ALREADY EXECUTED — prevents duplicate trades from same proposal
    if p.get("paper_submit_state") == "EXECUTED":
        blockers.append("BLOCKED_ALREADY_EXECUTED: Proposal already produced a paper trade")
        log.warning(f"[gate0] Proposal {proposal_id} ({p['symbol']}) blocked — already EXECUTED")
        return {"passed": False, "blockers": blockers, "warnings": warnings}

    # Gate 1: LIVE TRADING BLOCK
    if LIVE_TRADING_ENABLED:
        blockers.append("BLOCKED_LIVE_ENABLED: Live trading is enabled — this submitter is paper-only")
    if ALPACA_MODE != "paper":
        blockers.append(f"BLOCKED_LIVE_MODE: ALPACA_MODE={ALPACA_MODE}, must be 'paper'")

    # Gate 2: Proposal status must be submittable
    SUBMITTABLE_STATUSES = ('PENDING', 'APPROVED', 'APPROVED_FOR_PAPER_TEST')
    if p["status"] not in SUBMITTABLE_STATUSES:
        blockers.append(f"BLOCKED_STATUS: Proposal status is {p['status']}, must be one of {SUBMITTABLE_STATUSES}")

    # Gate 3: Risk gate
    if p.get("risk_gate_result") not in ("APPROVED", None):
        blockers.append(f"BLOCKED_RISK_GATE: Risk gate result is {p['risk_gate_result']}")

    # Gate 4: Trade plan exists
    if not p.get("proposed_entry") or not p.get("proposed_stop") or not p.get("proposed_shares"):
        blockers.append("BLOCKED_NO_TRADE_PLAN: Missing entry, stop, or shares")

    # Gate 5: Duplicate open paper trade
    cur.execute("""
        SELECT COUNT(*) FROM paper_trades
        WHERE symbol = %s AND status = 'open'
    """, [p["symbol"]])
    open_count = cur.fetchone()[0] or 0
    if open_count > 0:
        blockers.append(f"BLOCKED_DUPLICATE: {open_count} open paper trade(s) for {p['symbol']}")

    # Gate 6: Duplicate active order (idempotency)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    client_order_id = f"tradeai-paper-{proposal_id}-{p['symbol']}-{today}"
    cur.execute("""
        SELECT COUNT(*) FROM paper_trades
        WHERE broker_order_id LIKE %s OR broker_order_id = %s
    """, [f"%{client_order_id}%", client_order_id])
    dup_order = cur.fetchone()[0] or 0
    if dup_order > 0:
        blockers.append(f"BLOCKED_DUPLICATE_ORDER: Order {client_order_id} already exists")

    # Gate 7: Quality review not rejected
    cur.execute("""
        SELECT review_state FROM proposal_quality_reviews
        WHERE proposal_id = %s ORDER BY created_at DESC LIMIT 1
    """, [proposal_id])
    qr = cur.fetchone()
    if qr and qr[0] in ("BLOCKED_BY_RISK_GATE", "REJECT_RECOMMENDED"):
        blockers.append(f"BLOCKED_QUALITY: Quality review state is {qr[0]}")

    # Gate 8: Intel readiness
    intel = int(p.get("intel_readiness") or 0)
    if intel < 50:
        warnings.append(f"LOW_INTEL: Intelligence readiness {intel}/100")

    # Gate 9: Technical snapshot present
    cur.execute("""
        SELECT COUNT(*) FROM indicator_confluence_cache WHERE symbol = %s
    """, [p["symbol"]])
    tech_count = cur.fetchone()[0] or 0
    if tech_count == 0:
        warnings.append("NO_TECHNICALS: No indicator data available")

    # Gate 10: Six-month paper validation requirement
    warnings.append("PAPER_ONLY: Live trading disabled pending six-month paper validation")

    # Execution plan
    _entry = float(p["proposed_entry"]) if p.get("proposed_entry") else None
    _stop = float(p["proposed_stop"]) if p.get("proposed_stop") else None
    _target = float(p["proposed_target1"]) if p.get("proposed_target1") else None

    # Stop quality guards
    if _entry and _stop:
        if _stop >= _entry:
            blockers.append(f"STOP_AT_OR_ABOVE_ENTRY: stop ${_stop:.2f} >= entry ${_entry:.2f}")
        elif _stop > _entry * 0.995:
            warnings.append(f"STOP_VERY_TIGHT: stop ${_stop:.2f} is within 0.5% of entry ${_entry:.2f}")
    if _entry and _target and _stop:
        if _stop > _target:
            blockers.append(f"STOP_ABOVE_TARGET: stop ${_stop:.2f} > target ${_target:.2f} — likely swapped")

    execution_plan = {
        "order_type": "limit_bracket",
        "limit_price": _entry,
        "stop_price": _stop,
        "take_profit_price": _target,
        "time_in_force": "day",
        "shares": int(p["proposed_shares"]) if p.get("proposed_shares") else None,
        "client_order_id": client_order_id,
    }

    passed = len(blockers) == 0
    return {
        "passed": passed,
        "blockers": blockers,
        "warnings": warnings,
        "proposal": p,
        "execution_plan": execution_plan,
        "client_order_id": client_order_id,
    }


def dry_run_bracket(conn, proposal_id: int) -> dict:
    """Construct and validate bracket payload without submitting. Session 23D."""
    gates = check_gates(conn, proposal_id)
    p = gates.get("proposal", {})
    plan = gates.get("execution_plan", {})

    # Hard paper checks
    hard_blockers = []
    if ALPACA_MODE != "paper":
        hard_blockers.append(f"BLOCKED_LIVE_MODE: ALPACA_MODE={ALPACA_MODE}")
    if LIVE_TRADING_ENABLED:
        hard_blockers.append("BLOCKED_LIVE_ENABLED: LIVE_TRADING_ENABLED=true")

    alpaca_base = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    if "paper-api" not in alpaca_base:
        hard_blockers.append(f"BLOCKED_LIVE_ENDPOINT: {alpaca_base}")

    if hard_blockers:
        return {
            "status": "blocked",
            "proposal_id": proposal_id,
            "hard_blockers": hard_blockers,
            "message": "ABORT — live endpoint detected",
        }

    # Construct bracket payload
    bracket_payload = {
        "symbol": p.get("symbol", ""),
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": str(plan.get("limit_price", "")),
        "qty": str(plan.get("shares", "")),
        "order_class": "bracket",
        "take_profit": {"limit_price": str(plan.get("take_profit_price", ""))},
        "stop_loss": {"stop_price": str(plan.get("stop_price", ""))},
        "client_order_id": gates.get("client_order_id", ""),
    }

    # Check bracket order support via adapter
    bracket_supported = True
    try:
        from alpaca_paper_adapter import AlpacaPaperAdapter
        adapter = AlpacaPaperAdapter(dry_run=True)
        acct = adapter.get_account()
        if acct.get("status") == "disabled":
            bracket_supported = False
    except Exception:
        bracket_supported = False

    # Market hours check
    now_utc = datetime.now(timezone.utc)
    is_mkt = now_utc.weekday() < 5 and 13.5 <= (now_utc.hour + now_utc.minute / 60.0) <= 20.0

    return {
        "status": "dry_run_bracket",
        "proposal_id": proposal_id,
        "symbol": p.get("symbol"),
        "gates_passed": gates["passed"],
        "gate_blockers": gates["blockers"],
        "gate_warnings": gates["warnings"],
        "bracket_payload": bracket_payload,
        "bracket_order_supported": bracket_supported,
        "alpaca_mode": ALPACA_MODE,
        "alpaca_base_url_type": "paper" if "paper-api" in alpaca_base else "LIVE_BLOCKED",
        "market_hours": is_mkt,
        "client_order_id": gates.get("client_order_id"),
        "can_submit": gates["passed"] and bracket_supported and is_mkt,
    }


def submit_paper_bracket(conn, proposal_id: int, allow_after_hours: bool = False) -> dict:
    """Submit bracket order to Alpaca paper with full validation. Session 23D."""
    # Run dry-run first to validate everything
    dry = dry_run_bracket(conn, proposal_id)
    if dry.get("hard_blockers"):
        return dry

    if not dry.get("gates_passed"):
        _log_event(conn, proposal_id, dry.get("symbol", ""),
                   "ALPACA_PAPER_BRACKET_BLOCKED",
                   {"blockers": dry["gate_blockers"]})
        return {
            "status": "blocked",
            "proposal_id": proposal_id,
            "blockers": dry["gate_blockers"],
            "warnings": dry["gate_warnings"],
        }

    if not dry.get("market_hours") and not allow_after_hours:
        return {
            "status": "blocked_after_hours",
            "proposal_id": proposal_id,
            "message": "Market closed. Use --allow-after-hours-paper to queue.",
        }

    if not dry.get("bracket_order_supported"):
        return {
            "status": "bracket_unsupported",
            "proposal_id": proposal_id,
            "message": "Alpaca adapter cannot submit bracket orders",
        }

    # All clear — delegate to existing submit flow
    return submit_paper(conn, proposal_id, dry_run=False)


def submit_paper(conn, proposal_id: int, dry_run: bool = False) -> dict:
    """Submit proposal to Alpaca paper after gates pass."""
    gates = check_gates(conn, proposal_id)

    if not gates["passed"]:
        _log_event(conn, proposal_id, gates["proposal"]["symbol"],
                   "ALPACA_PAPER_SUBMIT_BLOCKED",
                   {"blockers": gates["blockers"], "warnings": gates["warnings"]})
        return {
            "status": "blocked",
            "proposal_id": proposal_id,
            "blockers": gates["blockers"],
            "warnings": gates["warnings"],
        }

    p = gates["proposal"]
    plan = gates["execution_plan"]

    if dry_run:
        log.info(f"[dry-run] Would submit {p['symbol']} {plan['shares']}sh "
                 f"@ ${plan['limit_price']} stop=${plan['stop_price']} "
                 f"target=${plan['take_profit_price']}")
        return {
            "status": "dry_run",
            "proposal_id": proposal_id,
            "symbol": p["symbol"],
            "execution_plan": plan,
            "warnings": gates["warnings"],
        }

    # ── Lifecycle: VALIDATING ──
    cur = conn.cursor()
    cur.execute("UPDATE paper_trade_proposals SET paper_submit_state='VALIDATING', updated_at=NOW() WHERE id=%s", [proposal_id])
    conn.commit()
    _log_event(conn, proposal_id, p["symbol"], "LIFECYCLE_VALIDATING", {})

    # ── Execution-time revalidation (Session 27B) ──
    recheck_live_price = None
    try:
        from paper_execution_revalidator import revalidate
        recheck = revalidate(conn, {
            "id": proposal_id, "symbol": p["symbol"],
            "strategy_id": p.get("strategy_id"),
            "proposed_entry": plan.get("limit_price"),
            "proposed_stop": plan.get("stop_price"),
            "proposed_target1": plan.get("take_profit_price"),
            "proposed_shares": plan.get("shares"),
            "created_at": p.get("created_at"),
            "approved_at": p.get("approved_at"),
            "execution_recheck_required": True,
            "approved_pending_recheck": False,
            "last_recheck_id": None,
            "execution_validated_at": None,
            "material_change_pending_approval": False,
            "proposed_dollar_risk": None, "signal_grade": None,
            "signal_score": None, "status": p.get("status"),
            "paper_submitted_at": None,
        })
        rck_status = recheck.get("status", "unknown")
        recheck_live_price = recheck.get("current_price")

        # Persist eligibility to proposals table
        _elig_status = recheck.get("eligibility_status", "INELIGIBLE" if rck_status != "valid_original" else "ELIGIBLE")
        _elig_reason = recheck.get("reason", "unknown")
        cur = conn.cursor()
        cur.execute("""
            UPDATE paper_trade_proposals
            SET execution_eligibility_status = %s,
                execution_eligibility_reason = %s,
                live_price_at_execution = %s,
                live_price_timestamp = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """, [_elig_status, _elig_reason[:500] if _elig_reason else None, recheck_live_price, proposal_id])
        conn.commit()

        if rck_status in ("blocked_safety", "cancelled"):
            cur.execute("UPDATE paper_trade_proposals SET paper_submit_state='BLOCKED', updated_at=NOW() WHERE id=%s", [proposal_id])
            conn.commit()
            _log_event(conn, proposal_id, p["symbol"],
                       "EXECUTION_REVALIDATION_BLOCKED",
                       {"recheck_status": rck_status, "reason": recheck.get("reason"),
                        "eligibility": _elig_status, "live_price": recheck_live_price})
            _cancel_never_submitted_pending(
                conn, proposal_id,
                cancel_code="revalidation_blocked",
                detail=recheck.get("reason") or rck_status,
                closed_via="revalidation_block",
                symbol=p["symbol"],
                strategy_id=p.get("strategy_id"),
            )
            return {"status": "blocked", "proposal_id": proposal_id,
                    "recheck_status": rck_status,
                    "reason": recheck.get("reason"),
                    "blockers": [recheck.get("reason")]}
        if rck_status == "updated_plan_requires_reapproval":
            _log_event(conn, proposal_id, p["symbol"],
                       "EXECUTION_REVALIDATION_REQUIRES_REAPPROVAL",
                       {"recheck_status": rck_status, "changes": recheck.get("material_change_reasons")})
            # ATOS phantom fix (2026-06-11): the approval flow pre-creates a 'pending' paper_trades row;
            # when revalidation BLOCKS submission, cancel that row immediately instead of leaving it for
            # phantom detection 16 minutes later (it was polluting closed-trade reviews as $0 'F' trades).
            _reap_detail = recheck.get("reason") or ", ".join(recheck.get("material_change_reasons") or []) or "requires_reapproval"
            _cancel_never_submitted_pending(
                conn, proposal_id,
                cancel_code="revalidation_reapproval",
                detail=_reap_detail,
                closed_via="revalidation_block",
                symbol=p["symbol"],
                strategy_id=p.get("strategy_id"),
            )
            # ── Gap 6: Telegram alert for NEEDS_REVALIDATION ──
            try:
                from telegram_alert import send_telegram
                orig = recheck.get("original_plan", {})
                recal = recheck.get("recalibrated_plan", {})
                drift = recheck.get("price_drift_pct", 0)
                score = recheck.get("execution_readiness_score", "?")
                changes = recheck.get("material_change_reasons", [])
                live_px = recheck.get("current_price", "?")
                orig_entry = orig.get("entry", plan.get("limit_price", "?"))
                new_shares = recal.get("shares", plan.get("shares", "?"))
                orig_shares = orig.get("shares", plan.get("shares", "?"))
                msg = (
                    f"⚠️ *REVALIDATION REQUIRED: {p['symbol']}*\n\n"
                    f"Proposal #{proposal_id} needs re-approval.\n"
                    f"Original entry: ${orig_entry}\n"
                    f"Current price: ${live_px} ({drift:+.1f}% drift)\n"
                    f"Shares: {orig_shares} → {new_shares}\n"
                    f"Score: {score}/100\n"
                    f"Changes: {', '.join(changes[:3]) if changes else 'price_drift'}\n\n"
                    f"Approve: /approve updated paper entry {proposal_id}\n"
                    f"Reject:  /reject updated paper entry {proposal_id}"
                )
                send_telegram(msg)
            except Exception as tg_err:
                log.warning(f"[revalidation] Telegram alert failed: {tg_err}")
            return {"status": "requires_reapproval", "proposal_id": proposal_id,
                    "recheck_status": rck_status,
                    "material_changes": recheck.get("material_change_reasons"),
                    "warnings": [recheck.get("reason")]}
        if rck_status == "delayed":
            _log_event(conn, proposal_id, p["symbol"],
                       "EXECUTION_REVALIDATION_DELAYED",
                       {"recheck_status": rck_status, "reason": recheck.get("reason")})
            return {"status": "delayed", "proposal_id": proposal_id,
                    "recheck_status": rck_status,
                    "reason": recheck.get("reason"),
                    "warnings": gates.get("warnings", [])}
        if rck_status == "downgraded_to_wait":
            _log_event(conn, proposal_id, p["symbol"],
                       "EXECUTION_REVALIDATION_DOWNGRADED",
                       {"recheck_status": rck_status})
            return {"status": "downgraded", "proposal_id": proposal_id,
                    "recheck_status": rck_status,
                    "reason": recheck.get("reason")}
        # valid_original or acceptable → continue to submission
        log.info(f"[revalidation] {p['symbol']} passed: score={recheck.get('execution_readiness_score')} eligibility={_elig_status}")
        # ── Lifecycle: VALIDATED ──
        cur = conn.cursor()
        cur.execute("UPDATE paper_trade_proposals SET paper_submit_state='VALIDATED', updated_at=NOW() WHERE id=%s", [proposal_id])
        conn.commit()
        _log_event(conn, proposal_id, p["symbol"], "LIFECYCLE_VALIDATED",
                   {"score": recheck.get("execution_readiness_score"), "live_price": recheck_live_price})
    except Exception as e:
        log.warning(f"[revalidation] Non-fatal error for {p['symbol']}: {e} — proceeding with gates-only")

    # Create evidence snapshot
    snapshot_id = _create_evidence_snapshot(
        conn, proposal_id, p["symbol"], p["strategy_id"])

    # Update proposal
    cur = conn.cursor()
    cur.execute("""
        UPDATE paper_trade_proposals
        SET latest_evidence_snapshot_id = %s,
            alpaca_paper_submit_enabled = true,
            updated_at = NOW()
        WHERE id = %s
    """, [snapshot_id, proposal_id])
    conn.commit()

    _log_event(conn, proposal_id, p["symbol"],
               "ALPACA_PAPER_SUBMIT_ATTEMPTED",
               {"execution_plan": plan, "evidence_snapshot_id": snapshot_id})

    # Submit via adapter
    try:
        from alpaca_paper_adapter import AlpacaPaperAdapter
        adapter = AlpacaPaperAdapter()
        result = adapter.submit_entry(
            symbol=p["symbol"],
            shares=int(plan["shares"]),
            entry_price=float(plan["limit_price"]),
            stop_price=float(plan["stop_price"]),
            target_price=float(plan["take_profit_price"]),
            strategy_id=p["strategy_id"],
            conn=conn,
            proposal_id=proposal_id,
            validated_price=float(recheck_live_price) if recheck_live_price else None,
            revalidation_snapshot=recheck if recheck else None,
        )

        event_type = ("ALPACA_PAPER_ORDER_SUBMITTED"
                      if result.get("status") in ("submitted", "simulation", "dry_run")
                      else "ALPACA_PAPER_SUBMIT_BLOCKED")
        _log_event(conn, proposal_id, p["symbol"], event_type,
                   {"result": result, "execution_plan": plan})

        # ── Lifecycle: EXECUTED or BLOCKED ──
        _new_state = "EXECUTED" if event_type == "ALPACA_PAPER_ORDER_SUBMITTED" else "BLOCKED"
        cur = conn.cursor()
        cur.execute("""UPDATE paper_trade_proposals
            SET paper_submit_state=%s, executed_at=CASE WHEN %s='EXECUTED' THEN NOW() ELSE executed_at END,
                updated_at=NOW()
            WHERE id=%s""",
            [_new_state, _new_state, proposal_id])
        conn.commit()

        if event_type == "ALPACA_PAPER_SUBMIT_BLOCKED":
            _block_detail = _format_block_detail(result)
            _cancel_code = "broker_risk_gate" if result.get("status") == "rejected" else "broker_rejected"
            _cancel_never_submitted_pending(
                conn, proposal_id,
                cancel_code=_cancel_code,
                detail=_block_detail,
                closed_via="broker_submit_block",
                symbol=p["symbol"],
                strategy_id=p.get("strategy_id"),
            )

        return {
            "status": result.get("status"),
            "reason": result.get("reason"),
            "block_detail": _format_block_detail(result) if event_type == "ALPACA_PAPER_SUBMIT_BLOCKED" else None,
            "proposal_id": proposal_id,
            "symbol": p["symbol"],
            "order_id": result.get("order_id"),
            "execution_plan": plan,
            "evidence_snapshot_id": snapshot_id,
            "warnings": gates["warnings"],
        }
    except Exception as e:
        log.error(f"Alpaca submission failed: {e}")
        _log_event(conn, proposal_id, p["symbol"],
                   "ALPACA_PAPER_SUBMIT_BLOCKED",
                   {"error": str(e)})
        _cancel_never_submitted_pending(
            conn, proposal_id,
            cancel_code="submit_error",
            detail=str(e),
            closed_via="broker_submit_block",
            symbol=p.get("symbol"),
            strategy_id=p.get("strategy_id"),
        )
        return {
            "status": "error",
            "proposal_id": proposal_id,
            "error": str(e),
            "block_detail": str(e),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Proposal paper submitter")
    parser.add_argument("--proposal-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--submit-paper", action="store_true")
    parser.add_argument("--check-only", action="store_true", help="Only check gates, don't submit")
    parser.add_argument("--dry-run-bracket", action="store_true",
                        help="Session 23D: Validate bracket payload without submitting")
    parser.add_argument("--submit-paper-bracket", action="store_true",
                        help="Session 23D: Submit bracket order to Alpaca paper")
    parser.add_argument("--allow-after-hours-paper", action="store_true",
                        help="Allow paper bracket submit after market hours")
    args = parser.parse_args()

    conn = get_conn()
    try:
        if args.dry_run_bracket:
            result = dry_run_bracket(conn, args.proposal_id)
            print(json.dumps(result, indent=2, default=str))
        elif args.submit_paper_bracket:
            result = submit_paper_bracket(conn, args.proposal_id,
                                          allow_after_hours=args.allow_after_hours_paper)
            print(json.dumps(result, indent=2, default=str))
        elif args.check_only:
            result = check_gates(conn, args.proposal_id)
            print(json.dumps(result, indent=2, default=str))
        elif args.submit_paper:
            result = submit_paper(conn, args.proposal_id, dry_run=False)
            print(json.dumps(result, indent=2, default=str))
        else:
            result = submit_paper(conn, args.proposal_id, dry_run=True)
            print(json.dumps(result, indent=2, default=str))
    finally:
        conn.close()
