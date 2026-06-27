#!/usr/bin/env python3
"""auto_enrichment_runner.py — Auto-enrich pending proposals for ATM.

Runs enrichment pipeline (price refresh → technical → AI review → risk gate
→ execution readiness) on proposals lacking fresh data. Cron: */5 9-15.

Idempotent, rate-limited, with per-proposal failure tracking.
"""
import json, logging, os, sys, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [enrich] %(message)s")
log = logging.getLogger("auto_enrichment")

MAX_FAILURES = 3
MAX_WORKERS = 3
QUOTE_MAX_AGE_SECONDS = 600        # 10 min
TECHNICAL_MAX_AGE_SECONDS = 3600   # 1 hour
AI_REVIEW_MAX_AGE_SECONDS = 86400  # 24 hours
AI_REVIEW_TIMEOUT = 120            # seconds (analyzer does DB queries + LLM call)


def _get_conn():
    from db_adapter import get_connection
    return get_connection()


def _routing_lane(proposal: dict) -> str:
    basis = proposal.get("sizing_basis")
    if isinstance(basis, str):
        try:
            basis = json.loads(basis)
        except Exception:
            basis = {}
    if isinstance(basis, dict) and basis.get("routing_lane"):
        return str(basis["routing_lane"])
    acct = str(proposal.get("target_account") or proposal.get("proposed_account") or "")
    try:
        from automated_account import is_automated_account
        return "paper_atm" if is_automated_account(acct) else "live_2fa"
    except Exception:
        return ""


def _curated_light_eligible(proposal: dict) -> bool:
    """Paper ATM curated rows with complete levels — skip heavy technical/LLM steps."""
    from atm_proposal_source_policy import is_curated_proposal
    lane = _routing_lane(proposal)
    if lane != "paper_atm":
        return False
    if not is_curated_proposal(proposal):
        return False
    try:
        entry = float(proposal.get("proposed_entry") or 0)
        stop = float(proposal.get("proposed_stop") or 0)
        target = float(proposal.get("proposed_target1") or 0)
    except (TypeError, ValueError):
        return False
    return entry > 0 and stop > 0 and target > 0 and entry > stop and target > entry


def _fetch_proposals(conn, force_all=False):
    """Return PENDING proposals needing enrichment (live 2FA lane first)."""
    cur = conn.cursor()
    base_cols = """
            SELECT id, symbol, strategy_id, proposed_entry, proposed_stop,
                   proposed_target1, proposed_shares, risk_gate_result,
                   enrichment_failures, enrichment_status,
                   discovery_source, origin, sizing_basis,
                   target_account, proposed_account
    """
    order = """
            ORDER BY
                CASE WHEN COALESCE(sizing_basis->>'routing_lane','') = 'live_2fa' THEN 0
                     WHEN COALESCE(target_account, proposed_account,'') LIKE 'schwab%' THEN 0
                     ELSE 1 END,
                created_at ASC
    """
    if force_all:
        cur.execute(f"{base_cols} FROM paper_trade_proposals WHERE status = 'PENDING' {order}")
    else:
        cur.execute(f"""
            {base_cols}
            FROM paper_trade_proposals
            WHERE status = 'PENDING'
              AND COALESCE(enrichment_status, 'PENDING') != 'FAILED'
              AND (enrichment_status IS NULL
                   OR enrichment_status != 'COMPLETE'
                   OR enrichment_last_attempt_at < NOW() - INTERVAL '10 minutes')
            {order}
        """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _log_step(conn, proposal_id, step, success, duration, error=None, output=None):
    """Write to enrichment_log."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO enrichment_log (proposal_id, step, success, duration_seconds, error_message, output, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, [proposal_id, step, success, round(duration, 2), error, json.dumps(output) if output else None])
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _update_enrichment_status(conn, proposal_id, status, error=None):
    """Update enrichment tracking columns on the proposal."""
    try:
        cur = conn.cursor()
        if status == 'FAILED':
            cur.execute("""
                UPDATE paper_trade_proposals
                SET enrichment_status = 'FAILED',
                    enrichment_failures = enrichment_failures + 1,
                    enrichment_last_attempt_at = NOW(),
                    enrichment_last_error = %s
                WHERE id = %s
            """, [error, proposal_id])
        elif status == 'COMPLETE':
            cur.execute("""
                UPDATE paper_trade_proposals
                SET enrichment_status = 'COMPLETE',
                    enrichment_failures = 0,
                    enrichment_last_attempt_at = NOW(),
                    enrichment_last_error = NULL
                WHERE id = %s
            """, [proposal_id])
        elif status == 'IN_PROGRESS':
            cur.execute("""
                UPDATE paper_trade_proposals
                SET enrichment_status = 'IN_PROGRESS',
                    enrichment_last_attempt_at = NOW()
                WHERE id = %s
            """, [proposal_id])
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _step_refresh_price(conn, proposal):
    """Step 1: Refresh quote price."""
    pid = proposal["id"]
    symbol = proposal["symbol"]
    t0 = time.time()
    try:
        from proposal_enrichment_loop import get_live_price
        price, source = get_live_price(symbol)
        if price and price > 0:
            cur = conn.cursor()
            cur.execute("""
                UPDATE paper_trade_proposals
                SET last_price_checked_at = NOW(), last_price_source = %s
                WHERE id = %s
            """, [source, pid])
            conn.commit()
            dur = time.time() - t0
            _log_step(conn, pid, "refresh_price", True, dur, output={"price": float(price), "source": source})
            return True
        else:
            dur = time.time() - t0
            _log_step(conn, pid, "refresh_price", False, dur, error="No price returned")
            return False
    except Exception as e:
        dur = time.time() - t0
        _log_step(conn, pid, "refresh_price", False, dur, error=str(e)[:200])
        return False


def _step_technical(conn, proposal):
    """Step 2: Run technical snapshot."""
    pid = proposal["id"]
    t0 = time.time()
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "proposal_technical_snapshot.py"),
             "--proposal-id", str(pid), "--apply"],
            capture_output=True, text=True, timeout=60,
            cwd=str(PROJECT_ROOT), env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "scripts")}
        )
        dur = time.time() - t0
        success = result.returncode == 0
        _log_step(conn, pid, "technical", success, dur,
                  error=result.stderr[:200] if not success else None)
        return success
    except Exception as e:
        dur = time.time() - t0
        _log_step(conn, pid, "technical", False, dur, error=str(e)[:200])
        return False


def _step_ai_review(conn, proposal):
    """Step 3: Run AI review (LLM analysis)."""
    pid = proposal["id"]
    t0 = time.time()
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "proposal_intelligence_analyzer.py"),
             "--proposal-id", str(pid), "--apply"],
            capture_output=True, text=True, timeout=AI_REVIEW_TIMEOUT,
            cwd=str(PROJECT_ROOT), env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "scripts")}
        )
        dur = time.time() - t0
        success = result.returncode == 0
        _log_step(conn, pid, "ai_review", success, dur,
                  error=result.stderr[:200] if not success else None)
        return success
    except subprocess.TimeoutExpired:
        dur = time.time() - t0
        _log_step(conn, pid, "ai_review", False, dur, error="ENRICHMENT_TIMEOUT (60s)")
        return False
    except Exception as e:
        dur = time.time() - t0
        _log_step(conn, pid, "ai_review", False, dur, error=str(e)[:200])
        return False


def _step_risk_gate(conn, proposal):
    """Step 4: Run risk gate check."""
    pid = proposal["id"]
    t0 = time.time()
    try:
        from risk_gate import RiskGate
        rg = RiskGate(conn)
        plan = {
            "entry": float(proposal["proposed_entry"]),
            "stop": float(proposal["proposed_stop"]),
            "target1": float(proposal["proposed_target1"]),
            "shares": int(proposal["proposed_shares"]),
        }
        plan["rr"] = (plan["target1"] - plan["entry"]) / (plan["entry"] - plan["stop"]) if plan["entry"] > plan["stop"] else 0
        decision = rg.check(proposal["symbol"], proposal["strategy_id"], trade_plan=plan, mode="paper")
        result_str = decision.result
        codes = decision.codes if hasattr(decision, "codes") else []
        cur = conn.cursor()
        cur.execute("UPDATE paper_trade_proposals SET risk_gate_result=%s, risk_gate_codes=%s WHERE id=%s",
                    (result_str, json.dumps(codes), pid))
        conn.commit()
        dur = time.time() - t0
        _log_step(conn, pid, "risk_gate", True, dur, output={"result": result_str, "codes": codes})
        return True
    except Exception as e:
        dur = time.time() - t0
        _log_step(conn, pid, "risk_gate", False, dur, error=str(e)[:200])
        return False


def _step_execution_readiness(conn, proposal):
    """Step 5: Recompute execution readiness."""
    pid = proposal["id"]
    t0 = time.time()
    try:
        from proposal_execution_readiness import fetch_proposals, assess_proposal, write_readiness
        proposals = fetch_proposals(conn, proposal_id=pid)
        if proposals:
            rec = assess_proposal(conn, proposals[0])
            write_readiness(conn, rec)
            dur = time.time() - t0
            _log_step(conn, pid, "readiness", True, dur,
                      output={"state": rec.get("readiness_state")})
            return True
        dur = time.time() - t0
        _log_step(conn, pid, "readiness", False, dur, error="Proposal not found")
        return False
    except Exception as e:
        dur = time.time() - t0
        _log_step(conn, pid, "readiness", False, dur, error=str(e)[:200])
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def enrich_proposal_light(proposal, force_all=False):
    """Curated paper-ATM fast path: price + readiness (+ risk if missing)."""
    pid = proposal["id"]
    symbol = proposal["symbol"]
    conn = _get_conn()
    if not conn:
        return {"id": pid, "symbol": symbol, "success": False, "error": "no_db"}
    _update_enrichment_status(conn, pid, "IN_PROGRESS")
    steps_ok = steps_total = 0
    first_error = None
    steps_total += 1
    if _step_refresh_price(conn, proposal):
        steps_ok += 1
    else:
        first_error = "refresh_price"
    if not proposal.get("risk_gate_result") or force_all:
        steps_total += 1
        if _step_risk_gate(conn, proposal):
            steps_ok += 1
        else:
            first_error = first_error or "risk_gate"
    steps_total += 1
    if _step_execution_readiness(conn, proposal):
        steps_ok += 1
    else:
        first_error = first_error or "readiness"
    if steps_ok == steps_total:
        _update_enrichment_status(conn, pid, "COMPLETE")
        log.info(f"  #{pid} {symbol}: COMPLETE (curated_light {steps_ok}/{steps_total})")
        return {"id": pid, "symbol": symbol, "success": True, "steps": f"light:{steps_ok}/{steps_total}"}
    failures = int(proposal.get("enrichment_failures") or 0) + 1
    if failures >= MAX_FAILURES:
        _update_enrichment_status(conn, pid, "FAILED", error=first_error)
    else:
        _update_enrichment_status(conn, pid, "PENDING", error=first_error)
    return {"id": pid, "symbol": symbol, "success": False, "error": first_error}


def enrich_proposal(proposal, force_all=False):
    """Run full enrichment pipeline for one proposal. Thread-safe (own connection)."""
    if _curated_light_eligible(proposal) and not force_all:
        return enrich_proposal_light(proposal, force_all=force_all)
    pid = proposal["id"]
    symbol = proposal["symbol"]
    conn = _get_conn()
    if not conn:
        log.error(f"  #{pid} {symbol}: no DB connection")
        return {"id": pid, "symbol": symbol, "success": False, "error": "no_db"}

    _update_enrichment_status(conn, pid, "IN_PROGRESS")
    steps_ok = 0
    steps_total = 0
    first_error = None

    # Step 1: Refresh price
    steps_total += 1
    if _step_refresh_price(conn, proposal):
        steps_ok += 1
    else:
        first_error = first_error or "refresh_price"

    # Step 2: Technical snapshot
    steps_total += 1
    if _step_technical(conn, proposal):
        steps_ok += 1
    else:
        first_error = first_error or "technical"

    # Step 3: AI review (non-blocking — timeout doesn't prevent COMPLETE)
    _ai_ok = _step_ai_review(conn, proposal)
    if not _ai_ok:
        log.info(f"  #{pid} {symbol}: ai_review skipped/timed out (non-blocking)")
    # AI review is optional — don't count it toward pass/fail

    # Step 4: Risk gate (only if NULL)
    if not proposal.get("risk_gate_result") or force_all:
        steps_total += 1
        if _step_risk_gate(conn, proposal):
            steps_ok += 1
        else:
            first_error = first_error or "risk_gate"

    # Step 5: Execution readiness (always — uses fresh data from above)
    steps_total += 1
    if _step_execution_readiness(conn, proposal):
        steps_ok += 1
    else:
        first_error = first_error or "readiness"

    # Update status
    if steps_ok == steps_total:
        _update_enrichment_status(conn, pid, "COMPLETE")
        log.info(f"  #{pid} {symbol}: COMPLETE ({steps_ok}/{steps_total} steps)")
        return {"id": pid, "symbol": symbol, "success": True, "steps": f"{steps_ok}/{steps_total}"}
    else:
        failures = proposal.get("enrichment_failures", 0) + 1
        if failures >= MAX_FAILURES:
            _update_enrichment_status(conn, pid, "FAILED", error=first_error)
            log.warning(f"  #{pid} {symbol}: FAILED ({failures}x, last: {first_error})")
        else:
            _update_enrichment_status(conn, pid, "PENDING", error=first_error)
            log.info(f"  #{pid} {symbol}: partial ({steps_ok}/{steps_total}, fail={first_error})")
        return {"id": pid, "symbol": symbol, "success": False, "steps": f"{steps_ok}/{steps_total}", "error": first_error}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-all", action="store_true", help="Override freshness checks, enrich everything")
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args()

    conn = _get_conn()
    if not conn:
        log.error("No DB connection")
        return

    proposals = _fetch_proposals(conn, force_all=args.force_all)
    if not proposals:
        log.info("No proposals need enrichment")
        # Update heartbeat
        cur = conn.cursor()
        cur.execute("UPDATE atm_state SET last_enrichment_at = NOW() WHERE id = 1")
        conn.commit()
        return

    proposals = proposals[:args.limit]
    log.info(f"Enriching {len(proposals)} proposals (force={args.force_all})")

    results = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(proposals))) as pool:
        futures = {pool.submit(enrich_proposal, p, args.force_all): p for p in proposals}
        for f in as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                p = futures[f]
                log.error(f"  #{p['id']} {p['symbol']}: exception {e}")
                results.append({"id": p["id"], "symbol": p["symbol"], "success": False, "error": str(e)})

    # Summary
    enriched = sum(1 for r in results if r.get("success"))
    failed = sum(1 for r in results if not r.get("success"))
    log.info(f"Done: {enriched} enriched, {failed} failed out of {len(proposals)}")

    # Update heartbeat
    cur = conn.cursor()
    cur.execute("UPDATE atm_state SET last_enrichment_at = NOW() WHERE id = 1")
    conn.commit()


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
