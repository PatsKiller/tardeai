#!/usr/bin/env python3
"""report_operator_morning_packet.py — Consolidated operator morning packet.

Read-only. No DB writes. No trade/order calls.

Usage:
    .venv/bin/python scripts/report_operator_morning_packet.py --verbose
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
    p = argparse.ArgumentParser(description="Operator morning packet (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    a5_complete = today >= A5_END

    # Load existing reports
    gov = _load("docs/governance/governance_status_latest.json") or {}
    maturity = _load("docs/maturity_hardening/maturity_control_board_latest.json") or {}
    readiness = _load("docs/maturity_hardening/operator_readiness_latest.json") or {}
    gates = _load("docs/maturity_hardening/phase_readiness_latest.json") or {}

    # Holdings
    holdings_val = 0
    try:
        h = json.loads((PROJ / "data/portfolios/state/holdings.json").read_text())
        holdings_val = h.get("portfolio_totals", {}).get("total_value", 0)
    except Exception:
        pass

    # Safety
    alpaca = "unknown"
    llm_disable = "unknown"
    try:
        env_text = (PROJ / ".env").read_text()
        for line in env_text.splitlines():
            if line.startswith("ALPACA_MODE="): alpaca = line.split("=", 1)[1]
            if line.startswith("LLM_DISABLE_LIVE_EXECUTION="): llm_disable = line.split("=", 1)[1]
    except Exception:
        pass

    report = {
        "generated_at": now.isoformat(),
        "date": today,
        "safety": {"alpaca_mode": alpaca, "llm_disable": llm_disable, "holdings": round(holdings_val, 2)},
        "a5_status": "complete" if a5_complete else "in_progress",
        "a5_end_date": A5_END,
        "governance": gov.get("status", "unknown"),
        "maturity_score": maturity.get("overall_score", "?"),
        "live_trading": "BLOCKED",
        "phase_8d": "blocked" if not a5_complete else "review_ready",
        "allowed_actions": readiness.get("allowed_actions", []),
        "blocked_actions": readiness.get("blocked_actions", []),
        "operator_required": readiness.get("operator_required", []),
        "next_action": readiness.get("recommended_next", "Continue observation"),
        "backup_note": "Skipped in PAR-1 — BR-2B deferred",
    }

    if args.verbose:
        print(f"Operator Morning Packet — {today}")
        print(f"  Safety: ALPACA_MODE={alpaca}, LLM_DISABLE={llm_disable}, Holdings=${holdings_val:,.0f}")
        print(f"  A-5: {report['a5_status']} (ends {A5_END})")
        print(f"  Governance: {report['governance']}")
        print(f"  Maturity: {report['maturity_score']}/10")
        print(f"  Live trading: {report['live_trading']}")
        print(f"  Next: {report['next_action']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Operator Morning Packet — {today}",
              f"\n| Item | Status |", "|------|--------|",
              f"| Safety | ALPACA_MODE={alpaca}, LLM_DISABLE={llm_disable} |",
              f"| Holdings | ${holdings_val:,.0f} |",
              f"| A-5 | {report['a5_status']} (ends {A5_END}) |",
              f"| Governance | {report['governance']} |",
              f"| Maturity | {report['maturity_score']}/10 |",
              f"| Live trading | {report['live_trading']} |",
              f"| Phase 8D | {report['phase_8d']} |",
              f"| Backup | {report['backup_note']} |",
              f"| Next | {report['next_action']} |"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
