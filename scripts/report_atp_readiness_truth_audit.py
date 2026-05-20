#!/usr/bin/env python3
"""report_atp_readiness_truth_audit.py — Audit proposal readiness truth vs display.

Read-only. No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
import requests

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def main():
    p = argparse.ArgumentParser(description="ATP readiness truth audit (read-only)")
    p.add_argument("--base-url", default="http://localhost:7777")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    resp = requests.get(f"{args.base_url}/api/v2/paper-proposals", timeout=30)
    data = resp.json()
    summary = data.get("summary", {})
    proposals = data.get("proposals", [])

    audit = {
        "total_proposals": len(proposals),
        "ready": summary.get("ready_count", 0),
        "needs_review": summary.get("needs_review_count", 0),
        "unknown_quote": summary.get("unknown_quote_count", 0),
        "stale_quote": summary.get("stale_count", 0),
        "entry_missed": summary.get("entry_missed_count", 0),
        "exec_missing": summary.get("exec_missing_count", 0),
        "approval_allowed_count": sum(1 for p in proposals if p.get("approval_allowed")),
        "approval_blocked_count": sum(1 for p in proposals if not p.get("approval_allowed")),
        "proposals": [],
    }

    for prop in proposals:
        pid = prop.get("id")
        sym = prop.get("symbol")
        blockers = prop.get("primary_blockers", [])
        audit["proposals"].append({
            "id": pid,
            "symbol": sym,
            "status": prop.get("status"),
            "verdict": prop.get("operator_verdict") or ("UNKNOWN_QUOTE" if not prop.get("last_price_checked_at") else "NEEDS_REVIEW"),
            "verdict_reason": prop.get("operator_verdict_reason") or prop.get("primary_blocker") or "unknown",
            "approval_allowed": prop.get("approval_allowed"),
            "primary_blocker": prop.get("primary_blocker"),
            "primary_blockers": blockers,
            "rr": prop.get("risk_reward", {}).get("rr"),
            "high_rvol_warning": prop.get("high_rvol_warning"),
            "high_gap_warning": prop.get("high_gap_warning"),
            "quote_provider": prop.get("quote_provider"),
            "last_price_checked": prop.get("last_price_checked_at"),
            "has_execution_readiness": bool(prop.get("execution_readiness")),
            "llm_review_status": prop.get("llm_review_status"),
            "backtest_status": prop.get("backtest_status"),
        })

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), **audit}

    if args.verbose:
        print(f"ATP Readiness Truth Audit")
        print(f"  Total: {audit['total_proposals']} | Ready: {audit['ready']} | Unknown quote: {audit['unknown_quote']}")
        print(f"  Stale: {audit['stale_quote']} | Exec missing: {audit['exec_missing']}")
        print(f"  Approval allowed: {audit['approval_allowed_count']} | Blocked: {audit['approval_blocked_count']}")
        for p in audit["proposals"]:
            print(f"  #{p['id']} {p['symbol']:6s} verdict={str(p['verdict'] or '?'):15s} approved={p['approval_allowed']} blockers={p['primary_blockers']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = ["# ATP Readiness Truth Audit\n",
              f"| Metric | Count |", f"|--------|-------|",
              f"| Total | {audit['total_proposals']} |",
              f"| Ready | {audit['ready']} |",
              f"| Unknown quote | {audit['unknown_quote']} |",
              f"| Stale quote | {audit['stale_quote']} |",
              f"| Exec missing | {audit['exec_missing']} |",
              f"| Approval allowed | {audit['approval_allowed_count']} |",
              f"| Approval blocked | {audit['approval_blocked_count']} |"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
