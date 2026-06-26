#!/usr/bin/env python3
"""
Release readiness gate for Trade AI.

Read-only. Aggregates the repo hygiene classifier plus key validators/builds. It
is deliberately conservative around broker/protective-stop code: dirty
execution-adjacent source is a release FAIL unless explicitly cleaned/staged and
reviewed outside this script.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Check:
    name: str
    status: str
    detail: str
    returncode: int | None = None


def run(cmd: list[str], timeout: int = 120) -> Check:
    name = " ".join(cmd)
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        out = (proc.stdout or proc.stderr or "").strip().splitlines()
        detail = out[-1] if out else "no output"
        return Check(name=name, status="PASS" if proc.returncode == 0 else "FAIL", detail=detail[:500], returncode=proc.returncode)
    except FileNotFoundError as exc:
        return Check(name=name, status="WARN", detail=f"missing command: {exc}")
    except subprocess.TimeoutExpired:
        return Check(name=name, status="FAIL", detail=f"timeout after {timeout}s")


def repo_hygiene() -> Check:
    proc = subprocess.run(["python3", "scripts/repo_hygiene_report.py", "--json"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return Check("repo_hygiene_report", "FAIL", proc.stderr.strip()[:500], proc.returncode)
    try:
        data = json.loads(proc.stdout)
    except Exception as exc:
        return Check("repo_hygiene_report", "FAIL", f"invalid json: {exc}", proc.returncode)

    live_dirty = data.get("live_broker_dirty_count", 0)
    secret_dirty = data.get("secret_or_config_dirty_count", 0)
    dirty_count = data.get("dirty_count", 0)
    if secret_dirty:
        return Check("repo_hygiene_report", "FAIL", f"{secret_dirty} secret/config dirty files; dirty_count={dirty_count}", proc.returncode)
    if live_dirty:
        return Check("repo_hygiene_report", "FAIL", f"{live_dirty} live-broker/execution-adjacent dirty files; dirty_count={dirty_count}", proc.returncode)
    if dirty_count:
        return Check("repo_hygiene_report", "WARN", f"dirty_count={dirty_count}, but no live-broker/secrets dirty files", proc.returncode)
    return Check("repo_hygiene_report", "PASS", "working tree clean", proc.returncode)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()

    checks: list[Check] = []
    checks.append(repo_hygiene())
    checks.append(run(["python3", "scripts/validate_metric_consistency.py", "--strict"], timeout=120))

    if Path("scripts/validate_symbol_card_quality.py").exists():
        checks.append(Check("symbol_card_quality_validator", "PASS", "validator present; run with /api/v2/symbol-cards export during deployment"))

    if Path("scripts/validate_schwab_write_policy.py").exists():
        checks.append(run(["python3", "scripts/validate_schwab_write_policy.py"], timeout=180))
    else:
        checks.append(Check("validate_schwab_write_policy.py", "WARN", "not present in this checkout"))

    if not args.skip_build and Path("apps/command-center-v3/package.json").exists():
        checks.append(run(["npm", "--prefix", "apps/command-center-v3", "run", "build"], timeout=240))
    else:
        checks.append(Check("command_center_v3_build", "WARN", "skipped or package.json missing"))

    if Path("scripts/execution_state.py").exists():
        checks.append(run(["python3", "scripts/execution_state.py", "--json"], timeout=60))
    else:
        checks.append(Check("execution_state", "FAIL", "scripts/execution_state.py missing"))

    if Path("scripts/brokers/execution_readiness.py").exists():
        checks.append(Check("execution_readiness", "PASS", "central readiness resolver present"))
    else:
        checks.append(Check("execution_readiness", "FAIL", "scripts/brokers/execution_readiness.py missing"))

    if Path("scripts/brokers/kill_switches.py").exists():
        checks.append(run(["python3", "scripts/brokers/kill_switches.py", "--status"], timeout=30))
    else:
        checks.append(Check("kill_switches", "FAIL", "kill_switches.py missing"))

    if Path("tests/test_no_broker_write_bypass.py").exists():
        checks.append(run(["python3", "tests/test_no_broker_write_bypass.py"], timeout=120))
    else:
        checks.append(Check("no_broker_write_bypass_test", "FAIL", "test missing"))

    if Path("scripts/export_diligence_evidence.py").exists():
        checks.append(Check("export_diligence_evidence", "PASS", "diligence export script present"))
    else:
        checks.append(Check("export_diligence_evidence", "FAIL", "export script missing"))

    blockers = [c for c in checks if c.status == "FAIL"]
    fail = any(c.status == "FAIL" for c in checks)
    warn = any(c.status == "WARN" for c in checks)
    manifest_path = Path("docs/project/RELEASE_MANIFEST_LATEST.md")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        f"# Release Manifest (auto-generated)\n\nStatus: {'FAIL' if fail else 'WARN' if warn else 'PASS'}\n\n"
        + "\n".join(f"- [{c.status}] {c.name}: {c.detail}" for c in checks)
        + "\n\n*Does not authorize live trading. Operator-approved path only.*\n",
        encoding="utf-8",
    )
    report = {
        "ok": not fail,
        "status": "FAIL" if fail else "WARN" if warn else "PASS",
        "blockers": [asdict(c) for c in blockers],
        "checks": [asdict(c) for c in checks],
        "manifest_path": str(manifest_path),
        "notes": [
            "This gate is read-only.",
            "It does not authorize broker execution.",
            "A PASS means the repo is ready for review/release, not that live trading is enabled.",
        ],
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Release readiness: {report['status']}")
        for c in checks:
            print(f"[{c.status}] {c.name}: {c.detail}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
