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
    # The P1 digest tier had no delivery: a P1_DIGEST verdict archived the message
    # and returned False, and nothing pushed the archive. 4,387 rows since
    # 2026-07-02 against 1,707 delivered.
    ("p1_digest_sender", [
        "tests/test_p1_digest_sender.py",
    ]),
    # The gog credential broker: an unapproved agent must be refused ON APPROVAL,
    # and the broker must never read the operator-only ~/.openclaw/credentials path.
    ("gog_broker_approval", [
        "tests/test_gog_broker_approval.py",
    ]),
    # C1 (batch 1: send_telegram). Every alarm must be OBSERVED firing; the
    # uncovered set is a named number in config/alarm_firing_baseline.txt that can
    # only shrink. Presence of alarm code is not evidence it fires.
    ("alarm_fires", [
        "tests/test_alarm_capture_selftest.py",
        "tests/test_alarm_fires.py",
        "tests/test_alarm_fires_stop_path.py",
        "tests/test_alarm_fires_batch3.py",
        "tests/test_alarm_coverage.py",
    ]),
    # C5: declared cadence vs observed output for stores feeding operator surfaces.
    # strategy_signals stopped advancing 2026-08-07 and nothing watched the date.
    ("store_cadence", [
        "tests/test_store_cadence.py",
    ]),
    # C3: an alarm whose delivery failure is swallowed is worse than no alarm.
    # Shrink-only baseline of named inherited debt; new swallows fail the build.
    ("no_swallowed_alarms", [
        "tests/test_no_swallowed_alarms.py",
    ]),
    # C2: every symbol imported on an alarm path must resolve. Two incidents months
    # apart -- send_alert (never existed) and telegram_bot (module never existed) --
    # both sat in bare excepts and reported to nobody.
    ("alarm_imports_resolve", [
        "tests/test_alarm_imports_resolve.py",
    ]),
    # Two detectors that could not tell two states apart: the docs inventory counted
    # gitignored artifacts (tracked 2274 vs filesystem 2276, reddening a required
    # gate), and signal_flow_audit read OK when nothing had been scanned.
    ("detectors_distinguish_states", [
        "tests/test_detectors_distinguish_states.py",
    ]),
    # Pins the 2026-08-08 -> 2026-08-31 Strategy Desk outage: an ON CONFLICT clause
    # naming a constraint that does not exist (every signal insert raised), and the
    # alarms that reported it to nobody by importing a send_alert that has never existed.
    ("signal_flow_regression", [
        "tests/test_signal_sync_onconflict_regression.py",
    ]),
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
    ("scripts_lib_bootstrap", [
        "tests/test_scripts_lib_bootstrap.py",
    ]),
    ("stop_path_notification", [
        "tests/test_stop_path_notification_imports.py",
    ]),
    ("research_scheduler_child_interpreter", [
        "tests/test_research_scheduler_child_interpreter.py",
    ]),
    ("decision_field_honesty", [
        "tests/test_decision_field_honesty.py",
    ]),
    ("stop_warning_transitions", [
        "tests/test_stop_warning_transitions.py",
    ]),
    ("notification_memory", [
        "tests/test_notification_memory.py",
    ]),
    ("notification_receipts", [
        "tests/test_notification_receipts.py",
    ]),
    ("telegram_chokepoint_ratchet", [
        "tests/test_telegram_chokepoint_ratchet.py",
    ]),
    ("notification_integrity_cdeg", [
        "tests/test_notification_integrity_waves_cdeg.py",
    ]),
    ("governance_section_zero_parity", [
        "tests/test_agents_section_zero_parity.py",
    ]),
    ("guard_push_auth", [
        "tests/test_guard_push_auth.py",
    ]),
    ("agents_type_vocabulary", [
        "tests/test_agents_type_vocabulary.py",
    ]),
    ("agent_brief", [
        "tests/test_agent_brief.py",
    ]),
    ("research_reaches_surface", [
        "tests/test_research_reaches_surface.py",
    ]),
    ("overnight_b2_b3_failure_surfaces", [
        "tests/test_overnight_b2_b3_failure_surfaces.py",
    ]),
    ("money_surface_honesty", [
        "tests/test_money_surface_honesty.py",
        "tests/test_cash_guidance_provenance.py",
        "tests/test_overnight_b4_b5_asof_provenance.py",
        "tests/test_overnight_w3_3b_frozen_fields.py",
    ]),
    ("overnight_b6_reentry_scope", [
        "tests/test_overnight_b6_reentry_scope.py",
    ]),
    ("overnight_d2_pending_data", [
        "tests/test_overnight_d2_pending_data.py",
    ]),
    ("overnight_d3_lesson_provenance", [
        "tests/test_overnight_d3_lesson_provenance.py",
    ]),
    ("overnight_wave_e_catalyst", [
        "tests/test_overnight_wave_e_catalyst.py",
    ]),
    ("overnight_f1_f2_search_bound", [
        "tests/test_overnight_f1_f2_search_bound.py",
    ]),
    ("overnight_f5_model_cost", [
        "tests/test_overnight_f5_model_cost.py",
    ]),
    ("overnight_g3_docs_index", [
        "tests/test_overnight_g3_docs_index.py",
    ]),
    ("finviz_data_producers", [
        "tests/test_finviz_token_screener_fallback.py",
        "tests/test_agents_data_producers.py",
    ]),
    ("lane_registry", [
        "tests/test_lane_registry.py",
    ]),
    ("search_budget", [
        "tests/test_search_budget_and_health.py",
    ]),
    ("overnight_f3_search_budget", [
        "tests/test_overnight_f3_search_budget.py",
    ]),
    ("overnight_f4_search_health", [
        "tests/test_overnight_f4_search_health.py",
    ]),
    ("overnight_g1_resolution", [
        "tests/test_overnight_g1_resolution.py",
    ]),
    ("overnight_g2_import_normalise", [
        "tests/test_overnight_g2_import_normalise.py",
    ]),
    ("corpus_grades_cost_units", [
        "tests/test_corpus_grades_and_cost_units.py",
    ]),
    ("wake_loads_record", [
        "tests/test_wake_loads_record.py",
        "tests/test_reactive_enqueue_routing.py",
        "tests/test_next_eligible_normal_path.py",
    ]),
    ("overnight_d1_m5_cadence", [
        "tests/test_overnight_d1_m5_cadence.py",
    ]),
    ("overnight_g4_archive_mechanism", [
        "tests/test_overnight_g4_archive_mechanism.py",
    ]),
    ("overnight_g6_missing_stores", [
        "tests/test_overnight_g6_missing_stores.py",
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
    print("[RUN]  docs_index_drift")
    dix = subprocess.run(
        [sys.executable, "scripts/report_docs_inventory.py", "--check-index"],
        cwd=str(REPO),
    )
    if dix.returncode != 0:
        failed.append("docs_index_drift")
        print("[FAIL] docs_index_drift — docs/INDEX.md does not match regenerate")
    else:
        print("[PASS] docs_index_drift")

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
