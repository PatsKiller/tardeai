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
        "tests/test_cio_telegram_canary_dry.py",
    ]),
    ("notification_signal_over_spam", [
        "tests/test_cio_notification_signal.py",
    ]),
    ("telegram_notification_normalization", [
        "tests/test_telegram_notification_normalization.py",
        "tests/test_r20_v2_notification_idempotency.py",
    ]),
    ("capital_ledger", [
        "tests/test_cio_capital_plan.py",
    ]),
    ("financial_truth_gate", [
        "tests/test_cio_financial_truth_gate.py",
        "tests/test_cio_canonical_quote.py",
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
    ("institutional_sizing", [
        "tests/test_cio_institutional_sizing.py",
    ]),
    ("decision_quality", [
        "tests/test_cio_decision_quality_pr1.py",
    ]),
    ("account_capital_ledger", [
        "tests/test_cio_account_capital_ledger.py",
    ]),
    ("decision_field_parity", [
        "tests/test_cio_decision_parity.py",
    ]),
    ("live_report_parity", [
        "tests/test_cio_live_report_parity.py",
    ]),
    ("advisory_provenance", [
        "tests/test_cio_advisory_provenance.py",
    ]),
    ("strategy_seasonality", [
        "tests/test_cio_strategy_seasonality.py",
        "tests/test_cio_research_brain.py",
    ]),
    ("acceptance_harness_v4", [
        "tests/test_cio_acceptance_v4.py",
    ]),
    ("intelligence_lineage", [
        "tests/test_cio_intelligence_lineage.py",
    ]),
    ("maturity_closure_v2", [
        "tests/test_cio_maturity_closure_v2.py",
    ]),
    ("r11_operator_value_tier0", [
        "tests/test_r11_situation_engine.py",
        "tests/test_r11_office_integration.py",
        "tests/test_r11_golden_scenarios.py",
        "tests/test_r11_feedback_learning.py",
        "tests/test_r11_telegram_attention.py",
        "tests/test_r11_gpu_and_authority.py",
        "tests/test_cio_r9_2_cash_capital.py",
        "tests/test_cio_brain_snapshot.py",
        "tests/test_cio_brain_frontend.py",
    ]),
    ("r12_operator_intelligence", [
        "tests/test_r12_policy_provenance.py",
        "tests/test_r12_situation_matrix.py",
        "tests/test_r12_dedupe_message_samebrain.py",
        "tests/test_r12_chokepoint_outbox.py",
        "tests/test_r12_acceptance_scenarios.py",
        "tests/test_r12_properties.py",
    ]),
    ("ci_self_guards", [
        "tests/test_ci_test_coverage_gate.py",
    ]),
    ("agent_brief", [
        "tests/test_agent_brief.py",
    ]),
    ("r13_institutional", [
        "tests/test_r13_institution.py",
        "tests/test_r13_goldens_properties_faults.py",
        "tests/test_cio_brain_frontend.py",
        "tests/test_cio_brain_snapshot.py",
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

    # Phase 2: never regenerate the committed manifest before validating it.
    # 1) check-committed — read-only integrity of the files in git
    # 2) candidate — write a generated copy to an isolated dir and show the diff
    print("[RUN]  validate_committed_manifest")
    chk = subprocess.run(
        [sys.executable, "scripts/cio_release_manifest.py", "check-committed"],
        cwd=str(REPO),
    )
    if chk.returncode != 0:
        failed.append("validate_committed_manifest")
        print("[FAIL] validate_committed_manifest — committed RELEASE_MANIFEST failed integrity")
    else:
        print("[PASS] validate_committed_manifest")

    print("[RUN]  generate_candidate_manifest")
    cand = REPO / "data" / "audit" / "manifest_candidate"
    if os.environ.get("GITHUB_ACTIONS", "").lower() in ("1", "true"):
        cand = Path(os.environ.get("RUNNER_TEMP") or "/tmp") / "cio_manifest_candidate"
    gen = subprocess.run(
        [sys.executable, "scripts/cio_release_manifest.py", "candidate", "--out-dir", str(cand)],
        cwd=str(REPO),
    )
    if gen.returncode != 0:
        failed.append("generate_candidate_manifest")
        print("[FAIL] generate_candidate_manifest")
    else:
        print(f"[PASS] generate_candidate_manifest → {cand}")
        committed = REPO / "docs" / "investment-office" / "RELEASE_MANIFEST.json"
        generated = cand / "RELEASE_MANIFEST.json"
        if committed.is_file() and generated.is_file():
            diff = subprocess.run(
                ["diff", "-u", str(committed), str(generated)],
                cwd=str(REPO), capture_output=True, text=True,
            )
            if diff.returncode == 0:
                print("[info] candidate == committed pin")
            else:
                print("[info] candidate DIFFERS from committed pin (informational; not a substitute for check-committed)")
                print((diff.stdout or "")[:2000])

    if failed:
        print(f"\nCIO HARDENING CI FAILED: {failed}")
        return 1
    print("\nCIO HARDENING CI: ALL GATES PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
