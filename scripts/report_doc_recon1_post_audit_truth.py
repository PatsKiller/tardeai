#!/usr/bin/env python3
"""report_doc_recon1_post_audit_truth.py — Current truth for POST-AUDIT-OPS-1 workstreams.

Read-only. No trades. No orders. Documentation reconciliation only.
"""
import argparse, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent

WORKSTREAMS = [
    {"id": "REGIME-CRON-1", "commit": "03baf9d",
     "root_cause": "save_*() defaulted dry_run=True; callers never passed False",
     "result": "Snapshot fresh; run log recording; transaction recovery added",
     "safety": "No strategy activation, no rotation auto-apply, no trades/orders"},
    {"id": "AGENT-WORKER-1", "commit": "00a6967",
     "root_cause": "fused_signals.overall_signal schema mismatch (actual: direction); poisoned transactions",
     "result": "125 stuck jobs recovered; queue processing restored; smoke test 2/2",
     "safety": "No fake completions, no trades/orders"},
    {"id": "LLM-FIX-1", "commit": "50c0846",
     "root_cause": "Phantom table reference overnight_recovery_verdicts; real LLM output existed but not extracted",
     "result": "109 actionable outcomes populated; report fixed to check correct tables",
     "safety": "No fake LLM verdicts"},
    {"id": "COUNT-TRUTH-1", "commit": "d8ef77f",
     "root_cause": "Scope drift / ambiguous count labels across PaperGovernance, PaperJournal, CIODashboard",
     "result": "Scope-specific labels added (Paper Open/Closed, All-Time Decisions, Pending Review)",
     "safety": "No data manipulation"},
    {"id": "ATTR-1", "commit": "442c46b",
     "root_cause": "yfinance >= 0.2.x MultiIndex broke benchmark price fetch; SPY/ITA/AGG missing from cache",
     "result": "Alpha +1.02%; all metrics populated from real 1604-day price history",
     "safety": "No fake attribution data"},
]


def main():
    p = argparse.ArgumentParser(description="POST-AUDIT-OPS-1 current truth report")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scorecard": "5/5 FIXED",
        "remaining": "A-5 final review after 2026-05-22",
        "workstreams": [],
    }

    for ws in WORKSTREAMS:
        # Verify commit exists
        try:
            r = subprocess.run(["git", "log", "--oneline", "-1", ws["commit"]],
                               capture_output=True, text=True, cwd=str(PROJ))
            commit_found = r.returncode == 0
            commit_msg = r.stdout.strip() if commit_found else "NOT FOUND"
        except Exception:
            commit_found = False
            commit_msg = "git error"

        entry = {**ws, "commit_found": commit_found, "commit_msg": commit_msg}
        report["workstreams"].append(entry)

    # Check docs exist
    docs_dir = PROJ / "docs" / "operator_hygiene" / "phase_post_audit_ops1_remaining_backend_fixes"
    report["readme_exists"] = (docs_dir / "00_README.md").exists()
    report["closure_memo_exists"] = (docs_dir / "post_audit_ops1_5_of_5_closure_memo.md").exists()
    report["readme_says_fixed"] = False
    if report["readme_exists"]:
        text = (docs_dir / "00_README.md").read_text()
        report["readme_says_fixed"] = "5/5" in text and "FIXED" in text

    if args.verbose:
        print(f"POST-AUDIT-OPS-1 Truth: {report['scorecard']}")
        for ws in report["workstreams"]:
            found = "OK" if ws["commit_found"] else "MISSING"
            print(f"  {ws['id']:20s} {ws['commit']} [{found}] {ws['result'][:60]}")
        print(f"  README fixed: {report['readme_says_fixed']}")
        print(f"  Closure memo: {report['closure_memo_exists']}")
        print(f"  Remaining: {report['remaining']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [f"# POST-AUDIT-OPS-1 Current Truth\n",
              f"**Scorecard:** {report['scorecard']}\n",
              "| Workstream | Commit | Verified | Result |",
              "|---|---|---|---|"]
        for ws in report["workstreams"]:
            md.append(f"| {ws['id']} | `{ws['commit']}` | {'Yes' if ws['commit_found'] else 'NO'} | {ws['result'][:80]} |")
        md.append(f"\n**Remaining:** {report['remaining']}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
