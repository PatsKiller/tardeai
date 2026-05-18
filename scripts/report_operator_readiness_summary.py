#!/usr/bin/env python3
"""report_operator_readiness_summary.py — Daily operator readiness summary.

Read-only. No mutations.

Usage:
    .venv/bin/python scripts/report_operator_readiness_summary.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
A5_END = "2026-05-22"


def _load(path):
    p = PROJ / path
    if p.exists():
        try: return json.loads(p.read_text())
        except: pass
    return None


def main():
    p = argparse.ArgumentParser(description="Operator readiness summary (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    a5_complete = today >= A5_END

    board = _load("docs/maturity_hardening/maturity_control_board_latest.json") or {}
    gates = _load("docs/maturity_hardening/phase_readiness_latest.json") or {}
    gov = _load("docs/governance/governance_status_latest.json") or {}

    overall = board.get("overall_score", "?")
    blockers = board.get("blockers", [])

    allowed = [g for g in gates.get("gates", []) if g.get("status") == "allowed"]
    blocked = [g for g in gates.get("gates", []) if g.get("status") == "blocked"]
    waiting = [g for g in gates.get("gates", []) if g.get("status") == "waiting"]
    operator_req = [g for g in gates.get("gates", []) if g.get("status") == "operator_required"]

    report = {
        "generated_at": now.isoformat(),
        "overall_maturity": overall,
        "a5_complete": a5_complete,
        "a5_end_date": A5_END,
        "governance_status": gov.get("status", "unknown"),
        "allowed_actions": [a["phase"] for a in allowed],
        "blocked_actions": [b["phase"] for b in blocked],
        "waiting_actions": [w["phase"] for w in waiting],
        "operator_required": [o["phase"] for o in operator_req],
        "top_blockers": blockers[:5],
        "live_trading": "BLOCKED",
        "strategy_decisions": "BLOCKED" if not a5_complete else "review_ready",
        "recommended_next": allowed[0]["phase"] if allowed else "Continue observation",
    }

    if args.verbose:
        print(f"Operator Readiness — Maturity {overall}/10")
        print(f"  A-5: {'complete' if a5_complete else 'in progress'}")
        print(f"  Governance: {gov.get('status', '?')}")
        print(f"  Allowed: {[a['phase'] for a in allowed]}")
        print(f"  Blocked: {[b['phase'] for b in blocked]}")
        if operator_req:
            print(f"  Operator required: {[o['phase'] for o in operator_req]}")
        print(f"  Live trading: BLOCKED")
        print(f"  Next: {report['recommended_next']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Operator Readiness — {overall}/10",
              f"\nA-5: {'complete' if a5_complete else 'in progress'} | Live trading: BLOCKED",
              f"\n**Next:** {report['recommended_next']}",
              f"\n## Allowed: {', '.join(report['allowed_actions']) or 'none'}",
              f"## Blocked: {', '.join(report['blocked_actions']) or 'none'}"]
        if report["operator_required"]:
            md.append(f"## Operator Required: {', '.join(report['operator_required'])}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
