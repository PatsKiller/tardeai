#!/usr/bin/env python3
"""Local + CI runner for CIO production-hardening gates (Phase 10).

Runs the pure unit suites that must stay green on every push/PR for the
investment-office / Alex CIO hardening program. Never contacts brokers or
sends Telegram.

Exit 0 only if all gates pass.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Ordered, explicit suite list (Phase 10.2)
GATES = [
    ("notification_no_network", [
        "tests/test_cio_phase1_notification_containment.py",
        "tests/test_cio_phase9_alex_telegram.py",
    ]),
    ("capital_ledger", [
        "tests/test_cio_capital_plan.py",
    ]),
    ("financial_truth_gate", [
        "tests/test_cio_financial_truth_gate.py",
    ]),
    ("freshness_materiality", [
        "tests/test_cio_freshness_materiality_gate.py",
    ]),
    ("decision_semantics", [
        "tests/test_cio_decision_semantics.py",
        "tests/test_cio_office_consistency.py",
    ]),
    ("sector_taxonomy", [
        "tests/test_cio_sector_opportunity.py",
    ]),
    ("report_model_and_parity", [
        "tests/test_cio_report_v2.py",
        "tests/test_cio_report_architecture.py",
        "tests/test_cio_report_analytics.py",
        "tests/test_cio_report_charts.py",
        "tests/test_cio_report_pipeline.py",
    ]),
    ("command_center", [
        "tests/test_cio_command_center.py",
    ]),
    ("release_manifest", [
        "tests/test_cio_release_manifest.py",
    ]),
    ("adversarial_phase11", [
        "tests/test_cio_phase11_adversarial.py",
    ]),
]


def main() -> int:
    os.chdir(REPO)
    os.environ.setdefault("TRADE_AI_CI", "1")
    os.environ.setdefault("CIO_TELEGRAM_INTERDICT", "1")
    # Ensure pytest interdicts telegram
    os.environ.setdefault("PYTEST_ADDOPTS", "")

    failed: list[str] = []
    for name, paths in GATES:
        existing = [p for p in paths if (REPO / p).is_file()]
        if not existing:
            print(f"[SKIP] {name}: no test files")
            continue
        print(f"[RUN]  {name}: {' '.join(existing)}")
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=line", *existing],
            cwd=str(REPO),
        )
        if r.returncode != 0:
            failed.append(name)
            print(f"[FAIL] {name}")
        else:
            print(f"[PASS] {name}")

    # Manifest check: committed MD+JSON must match live HEAD / product versions.
    # On GitHub Actions PRs, HEAD is often a synthetic merge commit that cannot
    # equal the branch tip pin — regenerate there so the gate still validates
    # product versions + forbidden SHAs against the checked-out tree.
    # Locally: do NOT auto-write (would hide a stale committed pin).
    print("[RUN]  release_manifest_check")
    if os.environ.get("GITHUB_ACTIONS", "").lower() in ("1", "true"):
        gen = subprocess.run(
            [sys.executable, "scripts/cio_release_manifest.py", "generate", "--write"],
            cwd=str(REPO),
        )
        if gen.returncode != 0:
            failed.append("release_manifest_check")
            print("[FAIL] release_manifest_check — generate failed on GITHUB_ACTIONS")
        else:
            print("[info] regenerated RELEASE_MANIFEST for CI HEAD")
    chk = subprocess.run(
        [sys.executable, "scripts/cio_release_manifest.py", "check"],
        cwd=str(REPO),
    )
    if chk.returncode != 0:
        failed.append("release_manifest_check")
        print("[FAIL] release_manifest_check — regenerate with: "
              "python scripts/cio_release_manifest.py generate --write")
    else:
        print("[PASS] release_manifest_check")

    if failed:
        print(f"\nCIO HARDENING CI FAILED: {failed}")
        return 1
    print("\nCIO HARDENING CI: ALL GATES PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
