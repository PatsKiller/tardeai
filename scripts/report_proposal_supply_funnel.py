#!/usr/bin/env python3
"""report_proposal_supply_funnel.py — Read-only proposal supply funnel audit.

Re-runs the May-2026 attrition table with current DB data. No mutations.

Usage:
    .venv/bin/python scripts/report_proposal_supply_funnel.py --since-days 5 --verbose
    .venv/bin/python scripts/report_proposal_supply_funnel.py --output-md docs/audits/PROPOSAL_SUPPLY_AUDIT_2026-06-26.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def get_conn():
    from session13_db import get_conn as _gc
    return _gc()


def _one(cur, sql, params=None):
    cur.execute(sql, params or [])
    row = cur.fetchone()
    if not row:
        return 0
    return row[0] if len(row) == 1 else row


def build_report(since_days: int = 5) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    interval = f"{since_days} days"
    now = datetime.now(timezone.utc).isoformat()

    universe = _one(cur, "SELECT COUNT(DISTINCT symbol) FROM symbol_profiles WHERE symbol IS NOT NULL")
    scanned = _one(cur, f"""
        SELECT COUNT(*) FROM trade_ai_scans
        WHERE scanned_at > NOW() - INTERVAL '{interval}'
    """)
    scored = scanned
    go_count = _one(cur, f"""
        SELECT COUNT(*) FROM trade_ai_scans
        WHERE scanned_at > NOW() - INTERVAL '{interval}' AND score >= 40
    """)
    wait_count = _one(cur, f"""
        SELECT COUNT(*) FROM trade_ai_scans
        WHERE scanned_at > NOW() - INTERVAL '{interval}' AND score >= 30 AND score < 40
    """)
    signals = _one(cur, f"""
        SELECT COUNT(*) FROM strategy_signals
        WHERE fired_at > NOW() - INTERVAL '{interval}'
    """)
    auto_proposals = _one(cur, f"""
        SELECT COUNT(*) FROM paper_trade_proposals
        WHERE created_at > NOW() - INTERVAL '{interval}'
          AND proposed_by = 'auto_proposal_generator'
    """)
    incubator_promos = _one(cur, f"""
        SELECT COUNT(*) FROM paper_trade_proposals
        WHERE created_at > NOW() - INTERVAL '{interval}'
          AND (origin ILIKE '%%incubator%%' OR discovery_source ILIKE '%%incubator%%')
    """)
    total_created = _one(cur, f"""
        SELECT COUNT(*) FROM paper_trade_proposals
        WHERE created_at > NOW() - INTERVAL '{interval}'
    """)
    blocked_created = _one(cur, f"""
        SELECT COUNT(*) FROM auto_proposal_decisions
        WHERE created_at > NOW() - INTERVAL '{interval}'
          AND decision IN ('BLOCKED', 'SKIPPED', 'REJECTED')
    """)
    pending = _one(cur, """
        SELECT COUNT(*) FROM paper_trade_proposals
        WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST', 'APPROVED')
    """)
    execution_ready = _one(cur, f"""
        SELECT COUNT(*) FROM paper_trade_proposals p
        WHERE p.created_at > NOW() - INTERVAL '{interval}'
          AND p.status IN ('APPROVED_FOR_PAPER_TEST', 'APPROVED')
          AND p.paper_trade_id IS NOT NULL
    """)
    atm_approved = _one(cur, f"""
        SELECT COUNT(*) FROM paper_trade_proposals
        WHERE created_at > NOW() - INTERVAL '{interval}'
          AND status = 'APPROVED_FOR_PAPER_TEST'
    """)
    broker_pending = _one(cur, """
        SELECT COUNT(*) FROM paper_trade_proposals
        WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST')
          AND (intended_broker ILIKE 'schwab%%' OR intended_broker ILIKE 'fidelity%%')
    """)

    cur.execute(f"""
        SELECT
          CASE
            WHEN score >= 40 THEN '40+ GO'
            WHEN score >= 30 THEN '30-39 WAIT'
            WHEN score >= 20 THEN '20-29'
            WHEN score >= 10 THEN '10-19'
            WHEN score >= 1 THEN '1-9'
            ELSE '0 DISQUALIFIED'
          END AS band,
          COUNT(*) AS c
        FROM trade_ai_scans
        WHERE scanned_at > NOW() - INTERVAL '{interval}'
        GROUP BY 1 ORDER BY MIN(score) DESC
    """)
    score_bands = {r[0]: r[1] for r in cur.fetchall()}

    cur.execute(f"""
        SELECT COALESCE(risk_gate_result, 'UNKNOWN') AS gate, COUNT(*) AS c
        FROM paper_trade_proposals
        WHERE created_at > NOW() - INTERVAL '{interval}'
          AND risk_gate_result IS NOT NULL
        GROUP BY 1 ORDER BY c DESC LIMIT 12
    """)
    gate_blocks = {r[0]: r[1] for r in cur.fetchall()}

    days = max(since_days, 1)
    per_day = round(total_created / days, 1)
    go_rate = round(100.0 * go_count / scored, 2) if scored else 0.0
    exec_rate = round(100.0 * execution_ready / max(total_created, 1), 1)

    return {
        "generated_at": now,
        "since_days": since_days,
        "funnel": {
            "screener_universe": universe,
            "scored_per_window": scored,
            "score_30_plus": wait_count + go_count,
            "score_40_plus_go": go_count,
            "go_pass_rate_pct": go_rate,
            "strategy_signals": signals,
            "auto_proposals": auto_proposals,
            "incubator_promotions": incubator_promos,
            "total_proposals_created": total_created,
            "proposals_per_day": per_day,
            "auto_decision_blocks": blocked_created,
            "pending_now": pending,
            "broker_queue_pending": broker_pending,
            "atm_approved_window": atm_approved,
            "linked_to_trade_window": execution_ready,
            "execution_link_rate_pct": exec_rate,
        },
        "score_bands": score_bands,
        "risk_gate_blocks": gate_blocks,
    }


def render_md(report: dict) -> str:
    f = report["funnel"]
    lines = [
        f"# Proposal Supply Funnel Audit — {report['generated_at'][:10]}",
        "",
        f"Window: last **{report['since_days']}** days · generated {report['generated_at']}",
        "",
        "## Funnel attrition",
        "",
        "```",
        f"{'Stage':<32} {'Window':>10} {'Per day':>10}  Notes",
        "-" * 72,
        f"{'Screener universe':<32} {f['screener_universe']:>10} {'—':>10}  symbol_profiles",
        f"{'Scored (trade_ai_scans)':<32} {f['scored_per_window']:>10} {f['scored_per_window']/max(report['since_days'],1):>10.0f}",
        f"{'Score ≥ 30 (WAIT+GO)':<32} {f['score_30_plus']:>10} {f['score_30_plus']/max(report['since_days'],1):>10.0f}  {f['go_pass_rate_pct']:.2f}% are GO (≥40)",
        f"{'Score ≥ 40 (GO)':<32} {f['score_40_plus_go']:>10} {f['score_40_plus_go']/max(report['since_days'],1):>10.0f}",
        f"{'Strategy signals':<32} {f['strategy_signals']:>10} {f['strategy_signals']/max(report['since_days'],1):>10.0f}",
        f"{'Auto proposals':<32} {f['auto_proposals']:>10} {f['auto_proposals']/max(report['since_days'],1):>10.0f}",
        f"{'Incubator promotions':<32} {f['incubator_promotions']:>10} {f['incubator_promotions']/max(report['since_days'],1):>10.0f}",
        f"{'Total proposals created':<32} {f['total_proposals_created']:>10} {f['proposals_per_day']:>10.1f}",
        f"{'ATM approved (window)':<32} {f['atm_approved_window']:>10}",
        f"{'Linked to paper trade':<32} {f['linked_to_trade_window']:>10}  {f['execution_link_rate_pct']:.1f}% link rate",
        f"{'Pending now':<32} {f['pending_now']:>10}",
        f"{'Broker queue pending':<32} {f['broker_queue_pending']:>10}",
        "```",
        "",
        "## Scoring distribution",
        "",
        "| Band | Count |",
        "|------|------:|",
    ]
    for band, cnt in report.get("score_bands", {}).items():
        lines.append(f"| {band} | {cnt} |")
    lines += ["", "## Risk-gate blocks (window)", "", "| Gate result | Count |", "|-------------|------:|"]
    for gate, cnt in report.get("risk_gate_blocks", {}).items():
        lines.append(f"| {gate} | {cnt} |")
    lines += [
        "",
        "## vs May-2026 baseline",
        "",
        "- May audit: ~9 proposals/day, 0 execution-ready (spread/price blocks dominated).",
        f"- Current: **{f['proposals_per_day']}/day** created, **{f['execution_link_rate_pct']}%** linked to trades in window.",
        "- Downstream readiness improved if link rate > 0; scoring attrition still expected for momentum filters.",
        "",
    ]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Proposal supply funnel audit (read-only)")
    p.add_argument("--since-days", type=int, default=5)
    p.add_argument("--output-json")
    p.add_argument("--output-md")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    report = build_report(args.since_days)
    if args.verbose:
        print(json.dumps(report, indent=2, default=str))
    md = render_md(report)
    if args.output_md:
        out = Path(args.output_md)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md)
        print(f"Wrote {out}")
    else:
        print(md)

    if args.output_json:
        out = Path(args.output_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, default=str))
        print(f"Wrote {out}")


if __name__ == "__main__":
    main()