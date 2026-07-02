#!/usr/bin/env python3
"""proposal_quality_reviewer.py — Review pending proposals for quality.

Uses deterministic fields + qwen3:14b narrative to assess pending proposals.
Does NOT approve or reject — writes proposal_quality_reviews for human review.

Usage:
    .venv/bin/python scripts/proposal_quality_reviewer.py --dry-run
    .venv/bin/python scripts/proposal_quality_reviewer.py --apply
    .venv/bin/python scripts/proposal_quality_reviewer.py --apply --limit 5
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from cio_agent_contract import build_proposal_quality_json_schema, extract_json_object, merge_structured_into_result
from session13_db import get_conn
from local_llm_config import get_local_llm_model

log = logging.getLogger("proposal_quality_reviewer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

REVIEW_STATES = {
    "HIGH_QUALITY_TEST",
    "CAUTIOUS_TEST",
    "DATA_INCOMPLETE",
    "REJECT_RECOMMENDED",
    "BLOCKED_BY_RISK_GATE",
}


def _get_llm():
    try:
        from local_llm import generate, model_used
        return generate
    except ImportError:
        return None


def get_pending_proposals(conn, limit=10):
    cur = conn.cursor()
    cur.execute("""
        SELECT ptp.id, ptp.symbol, ptp.strategy_id, ptp.setup_type,
               ptp.proposed_entry, ptp.proposed_stop, ptp.proposed_target1,
               ptp.proposed_shares, ptp.proposed_dollar_risk,
               ptp.proposed_rr, ptp.signal_grade, ptp.signal_score,
               ptp.rvol, ptp.float_m, ptp.gap_pct, ptp.catalyst, ptp.catalyst_verified,
               ptp.risk_gate_result, ptp.risk_gate_codes,
               scan.critic_verdict, scan.critic_reasoning, scan.sector, scan.industry,
               scan.ticker_perf_1m, scan.sector_perf_1m, scan.vs_sector_pct,
               scan.change_pct
        FROM paper_trade_proposals ptp
        LEFT JOIN LATERAL (
            SELECT * FROM trade_ai_scans WHERE symbol=ptp.symbol
            ORDER BY scanned_at DESC LIMIT 1
        ) scan ON true
        WHERE ptp.status = 'PENDING'
        AND ptp.id NOT IN (SELECT proposal_id FROM proposal_quality_reviews WHERE proposal_id IS NOT NULL)
        ORDER BY ptp.created_at DESC
        LIMIT %s
    """, [limit])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _deterministic_review(p):
    """Compute review state from deterministic fields."""
    risk_gate = p.get("risk_gate_result", "")
    if risk_gate and "BLOCK" in risk_gate.upper():
        return "BLOCKED_BY_RISK_GATE", 0.1

    missing = []
    if not p.get("rvol"):
        missing.append("rvol")
    if not p.get("catalyst"):
        missing.append("catalyst")
    if not p.get("critic_verdict"):
        missing.append("critic")
    if not p.get("sector"):
        missing.append("sector")

    if len(missing) >= 2:
        return "DATA_INCOMPLETE", 0.3

    score = float(p.get("signal_score") or 0)
    rr = float(p.get("proposed_rr") or 0)
    critic = p.get("critic_verdict", "")
    verified = p.get("catalyst_verified", False)

    if critic == "BLOCK":
        return "REJECT_RECOMMENDED", 0.2

    quality = 0.5
    if score >= 40:
        quality += 0.15
    if rr >= 2.0:
        quality += 0.1
    if verified:
        quality += 0.15
    if critic in ("CONFIRM", "PASS"):
        quality += 0.1

    if critic == "DOWNGRADE":
        quality -= 0.15
    if score < 25:
        quality -= 0.15

    if quality >= 0.7:
        return "HIGH_QUALITY_TEST", round(quality, 2)
    else:
        return "CAUTIOUS_TEST", round(quality, 2)


def _build_review_prompt(p, det_state, det_score):
    """Build LLM prompt for narrative review."""
    return f"""/no_think
Review this paper trade proposal. Be concise (under 150 words).

Symbol: {p.get('symbol')}
Strategy: {p.get('strategy_id')}
Entry: ${float(p.get('proposed_entry') or 0):.2f}
Stop: ${float(p.get('proposed_stop') or 0):.2f}
Target: ${float(p.get('proposed_target1') or 0):.2f}
R:R: {p.get('proposed_rr') or 'N/A'}
Score: {p.get('signal_score') or 'N/A'}
Grade: {p.get('signal_grade') or 'N/A'}
RVOL: {p.get('rvol') or 'N/A'}
Catalyst: {str(p.get('catalyst') or 'None')[:100]}
Verified: {p.get('catalyst_verified')}
Critic: {p.get('critic_verdict') or 'N/A'}
Risk gate: {p.get('risk_gate_result') or 'N/A'}
Sector: {p.get('sector') or 'N/A'}
Deterministic review: {det_state} (score {det_score})

{build_proposal_quality_json_schema()}"""


def review_proposal(conn, p, generate_fn, dry_run=False):
    pid = p["id"]
    symbol = p["symbol"]

    det_state, det_score = _deterministic_review(p)

    if dry_run:
        log.info(f"[dry-run] {symbol} #{pid}: {det_state} ({det_score})")
        return {"success": True, "dry_run": True, "state": det_state}

    approve_case = None
    reject_case = None
    llm_model = None
    narrative_source = "deterministic"
    llm_parsed = None

    if generate_fn and det_state not in ("BLOCKED_BY_RISK_GATE",):
        try:
            prompt = _build_review_prompt(p, det_state, det_score)
            raw = generate_fn(prompt, timeout=90, fallback=False, fast=True)
            if raw:
                try:
                    parsed = extract_json_object(raw)
                    if parsed:
                        llm_parsed = merge_structured_into_result(parsed)
                        approve_case = llm_parsed.get("approve_case")
                        reject_case = llm_parsed.get("reject_case")
                        narrative_source = "local_llm"
                        try:
                            from local_llm import model_used
                            llm_model = model_used
                        except Exception:
                            llm_model = get_local_llm_model()
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"LLM failed for {symbol}: {e}")

    if not llm_model:
        llm_model = get_local_llm_model()

    missing = []
    if not p.get("rvol"):
        missing.append("rvol")
    if not p.get("catalyst"):
        missing.append("catalyst")
    if not p.get("critic_verdict"):
        missing.append("critic")

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO proposal_quality_reviews
            (proposal_id, symbol, strategy_id, review_state, quality_score,
             approve_case, reject_case, missing_data, source_evidence,
             llm_model, narrative_source, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """, [
        pid, symbol, p.get("strategy_id"), det_state, det_score,
        approve_case, reject_case,
        json.dumps(missing) if missing else None,
        json.dumps({
            "score": float(p.get("signal_score") or 0),
            "grade": p.get("signal_grade"),
            "rvol": float(p.get("rvol") or 0),
            "catalyst_verified": p.get("catalyst_verified"),
            "critic": p.get("critic_verdict"),
            "risk_gate": p.get("risk_gate_result"),
        }),
        llm_model, narrative_source,
        json.dumps({
            "deterministic_state": det_state,
            "deterministic_score": det_score,
            **(llm_parsed or {}),
        }),
    ])

    log.info(f"  {symbol} #{pid}: {det_state} ({det_score}) [{narrative_source}]")
    return {"success": True, "symbol": symbol, "state": det_state, "score": det_score}


def run(limit=10, dry_run=False):
    generate_fn = _get_llm()
    log.info(f"LLM available: {generate_fn is not None}")
    log.info(f"Model: {get_local_llm_model()}")

    conn = get_conn()
    try:
        proposals = get_pending_proposals(conn, limit)
        log.info(f"Found {len(proposals)} proposals needing quality review")

        results = {"high_quality": 0, "cautious": 0, "incomplete": 0, "reject": 0, "blocked": 0}
        for p in proposals:
            r = review_proposal(conn, p, generate_fn, dry_run)
            if r.get("state") == "HIGH_QUALITY_TEST":
                results["high_quality"] += 1
            elif r.get("state") == "CAUTIOUS_TEST":
                results["cautious"] += 1
            elif r.get("state") == "DATA_INCOMPLETE":
                results["incomplete"] += 1
            elif r.get("state") == "REJECT_RECOMMENDED":
                results["reject"] += 1
            elif r.get("state") == "BLOCKED_BY_RISK_GATE":
                results["blocked"] += 1
            if not dry_run:
                conn.commit()

        log.info(f"Reviewed {len(proposals)} proposals: {results}")
        return {"processed": len(proposals), "dry_run": dry_run, **results}
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Proposal quality reviewer")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Write reviews to DB")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--proposal-id", type=int, default=None, help="Review specific proposal ID")
    args = parser.parse_args()
    dry = not args.apply
    if args.proposal_id:
        # Run for a single proposal by temporarily overriding the query
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT ptp.id, ptp.symbol, ptp.strategy_id, ptp.setup_type,
                       ptp.proposed_entry, ptp.proposed_stop, ptp.proposed_target1,
                       ptp.proposed_shares, ptp.proposed_dollar_risk,
                       ptp.proposed_rr, ptp.signal_grade, ptp.signal_score,
                       ptp.rvol, ptp.float_m, ptp.gap_pct, ptp.catalyst, ptp.catalyst_verified,
                       ptp.risk_gate_result, ptp.risk_gate_codes,
                       scan.critic_verdict, scan.critic_reasoning, scan.sector, scan.industry,
                       scan.ticker_perf_1m, scan.sector_perf_1m, scan.vs_sector_pct,
                       scan.change_pct
                FROM paper_trade_proposals ptp
                LEFT JOIN LATERAL (
                    SELECT * FROM trade_ai_scans WHERE symbol=ptp.symbol
                    ORDER BY scanned_at DESC LIMIT 1
                ) scan ON true
                WHERE ptp.id = %s
            """, [args.proposal_id])
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            if row:
                p = dict(zip(cols, row))
                result = review_proposal(conn, p, _get_llm(), dry)
                if not dry:
                    conn.commit()
                print(json.dumps(result, indent=2, default=str))
            else:
                print(f"Proposal {args.proposal_id} not found")
                sys.exit(1)
        finally:
            conn.close()
    else:
        result = run(limit=args.limit, dry_run=dry)
        print(json.dumps(result, indent=2))
