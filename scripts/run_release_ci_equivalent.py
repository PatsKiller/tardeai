#!/usr/bin/env python3
"""Local CI-equivalent release proof (P0-6).

Runs the full release-gating suite in one shot and emits a single Markdown + JSON report
with per-step command, exit code, duration, and pass/fail. NO broker writes occur — every
step is a read-only validator or test. Mirrors .github/workflows/release-readiness.yml so the
same proof exists with or without GitHub Actions.

Usage:
  python3 scripts/run_release_ci_equivalent.py            # human summary
  python3 scripts/run_release_ci_equivalent.py --json     # JSON to stdout
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (label, command, optional=True means a non-zero exit is reported but not a hard CI failure)
STEPS = [
    ("execution_state", ["python3", "scripts/execution_state.py", "--json"], False),
    ("release_readiness", ["python3", "scripts/validate_release_readiness.py", "--json", "--skip-build"], False),
    ("schwab_write_policy", ["python3", "scripts/validate_schwab_write_policy.py"], False),
    ("no_broker_write_bypass", ["python3", "tests/test_no_broker_write_bypass.py"], False),
    ("execution_readiness", ["python3", "tests/test_execution_readiness.py"], False),
    ("evidence_bound_approval", ["python3", "tests/test_evidence_bound_approval.py"], False),
    ("intraday_window_fail_closed", ["python3", "tests/test_intraday_window_fail_closed.py"], False),
    ("order_lifecycle", ["python3", "tests/test_order_lifecycle.py"], False),
    ("reconcile_orders", ["python3", "tests/test_reconcile_orders.py"], False),
    ("audit_ledger", ["python3", "tests/test_audit_ledger.py"], False),
    ("options_hard_risk_blocks_matrix", ["python3", "tests/test_options_hard_risk_blocks_matrix.py"], False),
    ("options_hard_risk_blocks", ["python3", "tests/test_options_hard_risk_blocks.py"], False),
    ("llm_governance_no_override", ["python3", "tests/test_llm_governance_no_override.py"], False),
    ("kill_switches_status", ["python3", "scripts/brokers/kill_switches.py", "--status"], False),
    ("journal_ai_critique", ["python3", "tests/test_journal_ai_critique.py"], False),
    ("audit_ledger_coverage", ["python3", "scripts/audit_ledger.py", "--coverage", "--release-mode", "review", "--json"], True),
    # Frontend smoke (full build is heavy; smoke verifies presence/built dist).
    ("frontend_smoke", ["python3", "-c",
                        "import sys;sys.path.insert(0,'scripts');"
                        "import validate_release_readiness as v;c=v.frontend_smoke();"
                        "print(c.status,c.detail);sys.exit(0 if c.status!='FAIL' else 1)"], True),
]


def _run(cmd: list[str], timeout: int = 240) -> dict:
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
        rc = proc.returncode
        tail = (proc.stdout or proc.stderr or "").strip().splitlines()
        detail = tail[-1][:300] if tail else ""
    except subprocess.TimeoutExpired:
        rc, detail = 124, f"timeout after {timeout}s"
    except Exception as e:
        rc, detail = 1, str(e)[:200]
    return {"returncode": rc, "duration_s": round(time.monotonic() - start, 2), "detail": detail}


def run_all() -> dict:
    results = []
    for label, cmd, optional in STEPS:
        r = _run(cmd)
        passed = r["returncode"] == 0
        results.append({
            "step": label, "command": " ".join(cmd), "returncode": r["returncode"],
            "duration_s": r["duration_s"], "status": "PASS" if passed else ("WARN" if optional else "FAIL"),
            "optional": optional, "detail": r["detail"],
        })
    hard_fail = any(r["status"] == "FAIL" for r in results)
    warn = any(r["status"] == "WARN" for r in results)
    status = "FAIL" if hard_fail else ("WARN" if warn else "PASS")
    return {
        "ok": not hard_fail,
        "status": status,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "total_steps": len(results),
        "passed": sum(1 for r in results if r["status"] == "PASS"),
        "failed": sum(1 for r in results if r["status"] == "FAIL"),
        "warned": sum(1 for r in results if r["status"] == "WARN"),
        "total_duration_s": round(sum(r["duration_s"] for r in results), 2),
        "steps": results,
        "note": "Read-only CI-equivalent release proof. No broker writes performed.",
    }


def write_markdown(report: dict, out: Path) -> None:
    lines = [
        "# CI Evidence — Release Readiness Proof",
        "",
        f"**Status: {report['status']}**  ",
        f"_Generated: {report['generated_at']}_  ",
        "_Source: `python3 scripts/run_release_ci_equivalent.py --json`_  ",
        f"_Steps: {report['passed']} passed / {report['failed']} failed / {report['warned']} warn "
        f"in {report['total_duration_s']}s_",
        "",
        "No broker writes are performed — every step is a read-only validator or test.",
        "",
        "| Step | Status | Exit | Duration (s) | Command | Detail |",
        "|------|--------|------|--------------|---------|--------|",
    ]
    for r in report["steps"]:
        lines.append(f"| {r['step']} | {r['status']} | {r['returncode']} | {r['duration_s']} | "
                     f"`{r['command']}` | {str(r['detail'])[:60].replace('|', '/')} |")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md-out", default="docs/project/CI_EVIDENCE_LATEST.md")
    ap.add_argument("--json-out", default="data/runtime/ci_evidence_latest.json")
    args = ap.parse_args()

    report = run_all()
    md_out = ROOT / args.md_out
    write_markdown(report, md_out)
    try:
        json_out = ROOT / args.json_out
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"CI-equivalent release proof: {report['status']} "
              f"({report['passed']}/{report['total_steps']} passed, {report['total_duration_s']}s)")
        for r in report["steps"]:
            print(f"  [{r['status']}] {r['step']} (exit {r['returncode']}, {r['duration_s']}s)")
        print(f"Markdown: {md_out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
