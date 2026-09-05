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
    # Cash age is the age of the dollars. PP2 (the cash letter) and PP4 (provenance)
    # stopped borrowing a clock; PP3 (the freshness board) is reported, not changed.
    (
        "cash_as_of_surfaces",
        [
            "tests/test_cash_as_of_three_surfaces.py",
        ],
    ),
    # The P1 digest tier had no delivery: a P1_DIGEST verdict archived the message
    # and returned False, and nothing pushed the archive. 4,387 rows since
    # 2026-07-02 against 1,707 delivered.
    (
        "p1_digest_sender",
        [
            "tests/test_p1_digest_sender.py",
        ],
    ),
    # The gog credential broker: an unapproved agent must be refused ON APPROVAL,
    # and the broker must never read the operator-only ~/.openclaw/credentials path.
    (
        "gog_broker_approval",
        [
            "tests/test_gog_broker_approval.py",
        ],
    ),
    # C1 (batch 1: send_telegram). Every alarm must be OBSERVED firing; the
    # uncovered set is a named number in config/alarm_firing_baseline.txt that can
    # only shrink. Presence of alarm code is not evidence it fires.
    (
        "alarm_fires",
        [
            "tests/test_alarm_capture_selftest.py",
            "tests/test_alarm_fires.py",
            "tests/test_alarm_fires_stop_path.py",
            "tests/test_alarm_fires_batch3.py",
            "tests/test_alarm_fires_batch4.py",
            "tests/test_alarm_fires_batch5.py",
            "tests/test_alarm_coverage.py",
        ],
    ),
    # C5: declared cadence vs observed output for stores feeding operator surfaces.
    # strategy_signals stopped advancing 2026-08-07 and nothing watched the date.
    (
        "store_cadence",
        [
            "tests/test_store_cadence.py",
        ],
    ),
    # C3: an alarm whose delivery failure is swallowed is worse than no alarm.
    # Shrink-only baseline of named inherited debt; new swallows fail the build.
    (
        "no_swallowed_alarms",
        [
            "tests/test_no_swallowed_alarms.py",
        ],
    ),
    # C2: every symbol imported on an alarm path must resolve. Two incidents months
    # apart -- send_alert (never existed) and telegram_bot (module never existed) --
    # both sat in bare excepts and reported to nobody.
    (
        "alarm_imports_resolve",
        [
            "tests/test_alarm_imports_resolve.py",
        ],
    ),
    # Two detectors that could not tell two states apart: the docs inventory counted
    # gitignored artifacts (tracked 2274 vs filesystem 2276, reddening a required
    # gate), and signal_flow_audit read OK when nothing had been scanned.
    (
        "detectors_distinguish_states",
        [
            "tests/test_detectors_distinguish_states.py",
        ],
    ),
    # Pins the 2026-08-08 -> 2026-08-31 Strategy Desk outage: an ON CONFLICT clause
    # naming a constraint that does not exist (every signal insert raised), and the
    # alarms that reported it to nobody by importing a send_alert that has never existed.
    (
        "signal_flow_regression",
        [
            "tests/test_signal_sync_onconflict_regression.py",
        ],
    ),
    (
        "notification_no_network",
        [
            "tests/test_cio_phase1_notification_containment.py",
            "tests/test_cio_phase9_alex_telegram.py",
            "tests/test_cio_telegram_canary_dry.py",
        ],
    ),
    (
        "notification_signal_over_spam",
        [
            "tests/test_cio_notification_signal.py",
        ],
    ),
    (
        "telegram_notification_normalization",
        [
            "tests/test_telegram_notification_normalization.py",
            "tests/test_r20_v2_notification_idempotency.py",
        ],
    ),
    (
        "capital_ledger",
        [
            "tests/test_cio_capital_plan.py",
        ],
    ),
    (
        "financial_truth_gate",
        [
            "tests/test_cio_financial_truth_gate.py",
            "tests/test_cio_canonical_quote.py",
        ],
    ),
    (
        "freshness_materiality",
        [
            "tests/test_cio_freshness_materiality_gate.py",
        ],
    ),
    (
        "decision_semantics",
        [
            "tests/test_cio_decision_semantics.py",
            "tests/test_cio_office_consistency.py",
        ],
    ),
    (
        "sector_taxonomy",
        [
            "tests/test_cio_sector_opportunity.py",
        ],
    ),
    (
        "report_model_and_parity",
        [
            "tests/test_cio_report_v2.py",
            "tests/test_cio_report_architecture.py",
            "tests/test_cio_report_analytics.py",
            "tests/test_cio_report_charts.py",
            "tests/test_cio_report_pipeline.py",
        ],
    ),
    (
        "command_center",
        [
            "tests/test_cio_command_center.py",
        ],
    ),
    (
        "release_manifest",
        [
            "tests/test_cio_release_manifest.py",
        ],
    ),
    (
        "adversarial_phase11",
        [
            "tests/test_cio_phase11_adversarial.py",
        ],
    ),
    (
        "institutional_sizing",
        [
            "tests/test_cio_institutional_sizing.py",
        ],
    ),
    (
        "decision_quality",
        [
            "tests/test_cio_decision_quality_pr1.py",
        ],
    ),
    (
        "account_capital_ledger",
        [
            "tests/test_cio_account_capital_ledger.py",
        ],
    ),
    (
        "decision_field_parity",
        [
            "tests/test_cio_decision_parity.py",
        ],
    ),
    (
        "live_report_parity",
        [
            "tests/test_cio_live_report_parity.py",
        ],
    ),
    (
        "advisory_provenance",
        [
            "tests/test_cio_advisory_provenance.py",
        ],
    ),
    (
        "strategy_seasonality",
        [
            "tests/test_cio_strategy_seasonality.py",
            "tests/test_cio_research_brain.py",
        ],
    ),
    (
        "acceptance_harness_v4",
        [
            "tests/test_cio_acceptance_v4.py",
        ],
    ),
    (
        "intelligence_lineage",
        [
            "tests/test_cio_intelligence_lineage.py",
        ],
    ),
    (
        "maturity_closure_v2",
        [
            "tests/test_cio_maturity_closure_v2.py",
        ],
    ),
    (
        "r11_operator_value_tier0",
        [
            "tests/test_r11_situation_engine.py",
            "tests/test_r11_office_integration.py",
            "tests/test_r11_golden_scenarios.py",
            "tests/test_r11_feedback_learning.py",
            "tests/test_r11_telegram_attention.py",
            "tests/test_r11_gpu_and_authority.py",
            "tests/test_cio_r9_2_cash_capital.py",
            "tests/test_cio_brain_snapshot.py",
            "tests/test_cio_brain_frontend.py",
        ],
    ),
    (
        "r12_operator_intelligence",
        [
            "tests/test_r12_policy_provenance.py",
            "tests/test_r12_situation_matrix.py",
            "tests/test_r12_dedupe_message_samebrain.py",
            "tests/test_r12_chokepoint_outbox.py",
            "tests/test_r12_acceptance_scenarios.py",
            "tests/test_r12_properties.py",
        ],
    ),
    (
        "ci_self_guards",
        [
            "tests/test_ci_test_coverage_gate.py",
            "tests/test_wake_turn_effect.py",
        ],
    ),
    # A failed producer must never overwrite good cached content. Registered here
    # so the guard runs behind the required context: the 2026-09-01 data loss was
    # invisible precisely because a fail-open write and a fail-closed write are
    # indistinguishable on a successful run.
    (
        "ai_analyst_cache_fail_closed",
        [
            "tests/test_ai_analyst_cache_fails_closed.py",
        ],
    ),
    # A held position is never a re-entry candidate.
    (
        "s3_detector_excludes_held",
        [
            "tests/test_s3_detector_excludes_held.py",
        ],
    ),
    # A directory a served surface reads must be linked into the release.
    (
        "release_links_reports",
        [
            "tests/test_release_links_reports_dir.py",
        ],
    ),
    # "latest" must mean most recent, not biggest.
    (
        "scalp_latest_run_recency",
        [
            "tests/test_scalp_latest_run_is_most_recent.py",
        ],
    ),
    # A freshness field must describe the DATA, not the run that wrote it.
    (
        "holdings_data_clock",
        [
            "tests/test_holdings_data_clock.py",
        ],
    ),
    (
        "scripts_lib_bootstrap",
        [
            "tests/test_scripts_lib_bootstrap.py",
        ],
    ),
    (
        "stop_path_notification",
        [
            "tests/test_stop_path_notification_imports.py",
        ],
    ),
    (
        "research_scheduler_child_interpreter",
        [
            "tests/test_research_scheduler_child_interpreter.py",
        ],
    ),
    (
        "decision_field_honesty",
        [
            "tests/test_decision_field_honesty.py",
        ],
    ),
    (
        "stop_warning_transitions",
        [
            "tests/test_stop_warning_transitions.py",
        ],
    ),
    (
        "notification_memory",
        [
            "tests/test_notification_memory.py",
        ],
    ),
    (
        "notification_receipts",
        [
            "tests/test_notification_receipts.py",
        ],
    ),
    (
        "telegram_chokepoint_ratchet",
        [
            "tests/test_telegram_chokepoint_ratchet.py",
        ],
    ),
    (
        "notification_integrity_cdeg",
        [
            "tests/test_notification_integrity_waves_cdeg.py",
        ],
    ),
    (
        "governance_section_zero_parity",
        [
            "tests/test_agents_section_zero_parity.py",
        ],
    ),
    # Both sides added gates. Keeping both: a conflict in a gate LIST is never
    # resolved by choosing a side, because each side is a check something needs.
    (
        "dashboard_no_embedded_key",
        [
            "tests/test_dashboard_never_embeds_a_key.py",
        ],
    ),
    (
        "guard_push_auth",
        [
            "tests/test_guard_push_auth.py",
        ],
    ),
    (
        "agents_type_vocabulary",
        [
            "tests/test_agents_type_vocabulary.py",
        ],
    ),
    (
        "agent_brief",
        [
            "tests/test_agent_brief.py",
        ],
    ),
    (
        "research_reaches_surface",
        [
            "tests/test_research_reaches_surface.py",
        ],
    ),
    (
        "overnight_b2_b3_failure_surfaces",
        [
            "tests/test_overnight_b2_b3_failure_surfaces.py",
        ],
    ),
    (
        "money_surface_honesty",
        [
            "tests/test_money_surface_honesty.py",
            "tests/test_cash_guidance_provenance.py",
            "tests/test_overnight_b4_b5_asof_provenance.py",
            "tests/test_overnight_w3_3b_frozen_fields.py",
        ],
    ),
    (
        "overnight_b6_reentry_scope",
        [
            "tests/test_overnight_b6_reentry_scope.py",
        ],
    ),
    (
        "overnight_d2_pending_data",
        [
            "tests/test_overnight_d2_pending_data.py",
        ],
    ),
    (
        "overnight_d3_lesson_provenance",
        [
            "tests/test_overnight_d3_lesson_provenance.py",
        ],
    ),
    (
        "overnight_wave_e_catalyst",
        [
            "tests/test_overnight_wave_e_catalyst.py",
        ],
    ),
    (
        "overnight_f1_f2_search_bound",
        [
            "tests/test_overnight_f1_f2_search_bound.py",
        ],
    ),
    (
        "overnight_f5_model_cost",
        [
            "tests/test_overnight_f5_model_cost.py",
        ],
    ),
    (
        "overnight_g3_docs_index",
        [
            "tests/test_overnight_g3_docs_index.py",
        ],
    ),
    (
        "finviz_data_producers",
        [
            "tests/test_finviz_token_screener_fallback.py",
            "tests/test_agents_data_producers.py",
            "tests/test_finviz_cookie_classification.py",
        ],
    ),
    (
        "lane_registry",
        [
            "tests/test_lane_registry.py",
            "tests/test_lane_portfolio_repricer.py",
        ],
    ),
    (
        "search_budget",
        [
            "tests/test_search_budget_and_health.py",
        ],
    ),
    (
        "overnight_f3_search_budget",
        [
            "tests/test_overnight_f3_search_budget.py",
        ],
    ),
    (
        "overnight_f4_search_health",
        [
            "tests/test_overnight_f4_search_health.py",
        ],
    ),
    (
        "overnight_g1_resolution",
        [
            "tests/test_overnight_g1_resolution.py",
        ],
    ),
    (
        "overnight_g2_import_normalise",
        [
            "tests/test_overnight_g2_import_normalise.py",
        ],
    ),
    (
        "corpus_grades_cost_units",
        [
            "tests/test_corpus_grades_and_cost_units.py",
        ],
    ),
    (
        "wake_loads_record",
        [
            "tests/test_wake_loads_record.py",
            "tests/test_reactive_enqueue_routing.py",
            "tests/test_next_eligible_normal_path.py",
        ],
    ),
    (
        "overnight_d1_m5_cadence",
        [
            "tests/test_overnight_d1_m5_cadence.py",
        ],
    ),
    (
        "cio_p1_load_by_subject",
        [
            "tests/test_cio_p1_load_by_subject.py",
        ],
    ),
    (
        "wake_research_persist_hits",
        [
            "tests/test_wake_research_persist_hits.py",
        ],
    ),
    (
        "decide_consults_wake_hits",
        [
            "tests/test_decide_consults_wake_hits.py",
        ],
    ),
    (
        "wake_consult_reaches_the_row",
        [
            "tests/test_wake_consult_reaches_the_row.py",
        ],
    ),
    (
        "cash_letter_rows",
        [
            "tests/test_cash_letter_rows.py",
            "tests/test_cio_cc_record_narrative_slice_c.py",
        ],
    ),
    (
        "watch_instrument_admit",
        [
            "tests/test_cio_watch_instrument_admit.py",
        ],
    ),
    (
        "agent_governance_sop",
        [
            "tests/test_agent_clients_registry.py",
            "tests/test_agent_session_and_lease.py",
            "tests/test_agent_hooks_ci_hermetic.py",
            "tests/test_agent_worktree_identity.py",
            "tests/test_agent_file_lease_canonical.py",
            "tests/test_agent_changed_file_quality.py",
            "tests/test_sop_evidence_integrity.py",
            "tests/test_sop_toolchain.py",
            "tests/test_sop_attestation_base.py",
            "tests/test_agents_drive_mirror_policy.py",
            "tests/test_operator_approval_workflow_docs.py",
        ],
    ),
    (
        "canonical_observation_contract",
        [
            # The producer/API root split and the hardcoded pipeline_status
            # (audit cc-truth-v1-20260902T202759Z). The two defects conceal each
            # other -- fixing either alone looks like it worked -- so both files
            # run in one gate or neither result means anything.
            "tests/test_canonical_observation.py",
            "tests/test_overview_observation_contract.py",
        ],
    ),
    (
        # cc-header-truth-v2 (2026-09-03): one canonical GO/WAIT/NOGO summary,
        # VIX source+observation, ALL-ACCOUNTS portfolio aggregate, journal
        # basis/window/scope — all wired into the served endpoints, not just
        # defined and left unused.
        "cc_header_truth_v2",
        [
            "tests/test_setup_run_contract.py",
            "tests/test_cc_header_truth_v2_api.py",
            "tests/test_quote_selection_contract.py",
            "tests/test_api_v2_ruff_quality_corrections.py",
            "tests/test_portfolio_aggregate_contract.py",
            # The 2026-09-04 live capture: the Sep-3/Sep-4 clock contradiction
            # and the 48/60/0 count contradiction, pinned against verbatim
            # production fixtures in tests/fixtures/header_truth/.
            "tests/test_header_truth_regression.py",
        ],
    ),
    (
        "research_observation_contract",
        [
            "tests/test_research_observation_contract.py",
            "tests/test_research_eligibility_policy.py",
            "tests/test_research_observation_join.py",
            "tests/test_research_consumer_gate.py",
        ],
    ),
    (
        "cc_runtime_harness",
        [
            "tests/test_cc_runtime_harness.py",
            "tests/test_command_center_live_truth_tranche.py",
        ],
    ),
    (
        "state_root_convergence",
        [
            # Producers run under `cd $PROJ`; releases symlink
            # data/portfolios/state at the persistent root. Measured 2026-09-03:
            # 59 of 88 stores forked, worst skew 143 days, and no surface said
            # so. Both files run together -- the producer fix and the report
            # that makes the next fork visible are one contract.
            "tests/test_portfolio_news_state_root.py",
            "tests/test_state_root_divergence.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): the SERVER decides what a
        # surface is showing. Eleven /v3/control-plane/* routes shipped a
        # PREVIEW/FIXTURE label compiled into the bundle while live domains
        # answered behind seven of them; the write token and operator name live
        # in localStorage; /v3-next is served from outside the repository with no
        # manifest. All four contracts are read-only and fail closed.
        "whole_site_surface_truth",
        [
            "tests/test_whole_site_truth.py",
            "tests/test_operator_control_contract.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): a configured intention is not a
        # running fact. Feature flags the loader coerces, timers that are disabled
        # or whose last run failed, and a Finviz store whose "no data" has three
        # unrelated causes -- each reported DECLARED next to EFFECTIVE.
        "effective_truth",
        [
            "tests/test_effective_truth.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): F12.15, the per-route audit. The
        # 401/403 classification only protects reads that go through useApi; this
        # enumerates the ones that do not (100 reads across 49 files, pre-existing)
        # and pins that this campaign's own five surfaces are not among them.
        "useapi_route_audit",
        [
            "tests/test_useapi_route_audit.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): the five surfaces that still lied.
        # Watch counts now come from one population and never render authoritative
        # while the list is unresolved; Closed Loop's four circulations age on their
        # own clocks; stale research is not missing research; a MANUAL writer is
        # never shown as if a schedule mints it; and a re-entry row finally carries
        # one canonical status instead of gates a consumer has to interpret.
        "residual_surfaces",
        [
            "tests/test_residual_surfaces.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): the guarded migration door. Every
        # rail is exercised against an ISOLATED byte-copied replica -- wrong SHA,
        # wrong manifest, changed hashes, missing/corrupt backup, no disk, active
        # writer, bad schema, interrupted write, financial conflict -- and every
        # failure proves the target's bytes came back unchanged. Financial truth
        # stores fail closed; recency never decides a financial value.
        "state_migration_rehearsal",
        [
            "tests/test_state_migration_rehearsal.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-04): Phase B1. Asking the transaction
        # history what Phase A refused to guess showed both candidate share counts were
        # wrong -- the positions were fully exited, so the answer was zero. Lots are
        # closed only where the broker reports no position AND the history nets to zero
        # AND every action in it is classified. The eligibility rule is the safety
        # mechanism, so most of the suite is about the cases where it must refuse.
        "exited_tax_lot_closure",
        [
            "tests/test_exited_tax_lot_closure.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-04): Phase A repair of the duplicates that
        # writer defect left behind. It may remove exact-duplicate CLOSED lots and
        # nothing else. The dangerous version is one line shorter -- dedupe everything --
        # and would have rewritten share counts in 15 records by up to 100x for
        # securities the broker no longer holds, where nothing could confirm the result.
        "tax_lot_duplicate_repair",
        [
            "tests/test_tax_lot_duplicate_repair.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-04): the tax-lot rebuild appended the whole
        # transaction history on top of its own previous output, so run N held N copies
        # of every lot. tax_lots.json reached 98% duplicates before anyone noticed,
        # because the duplicates were closed lots carrying zero remaining shares and
        # every quantity check still reconciled against the broker.
        "tax_lot_rebuild_idempotency",
        [
            "tests/test_tax_lot_rebuild_idempotency.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): record-level reconciliation. A
        # store-level "these two files disagree" is true but blunt. Each divergent
        # record is decided against the authority that governs it -- broker positions
        # for lot totals, live broker order state for stops -- and a verdict may never
        # cite recency. What no authority can settle stays UNRESOLVED and keeps both
        # originals; nothing disputed is ever handed a value.
        "financial_reconciliation",
        [
            "tests/test_financial_reconciliation.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): every surface in every state it can
        # reach -- populated, empty, partial, stale, malformed, disconnected,
        # unauthorized, forbidden, error. A surface tested only with good data is only
        # known to work in the case that never needed it. Failure must never report a
        # count: an outage and a quiet market must not render identically.
        "surface_state_matrix",
        [
            "tests/test_surface_state_matrix.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): detection is not resolution. Every
        # audited store gets one verdict from a closed taxonomy, Command Center
        # criticality is derived from the surface, and each open fork carries an
        # executable migration plan this lane is forbidden to run (AGENTS.md rule 5).
        "state_root_disposition",
        [
            "tests/test_state_root_disposition.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): stop coverage over ONE population.
        # The served Risk surface published 0.39% while the same rows it returns say
        # 11.92%: four broker-held stops read as NO STOP, and the percentage divided
        # by the whole portfolio rather than the population it summed.
        "protection_truth",
        [
            "tests/test_protection_truth.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): validation must never dirty the
        # candidate worktree, the committed ledger is the expectation rather than a
        # file the run just wrote, and no control may carry a hardcoded commit SHA.
        "ci_fixture_immutability",
        [
            "tests/test_ci_fixture_immutability.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): 401/403 are authorization answers,
        # not connectivity. They must not consume the transient retry ladder.
        "useapi_authorization_contract",
        [
            "tests/test_useapi_authorization_contract.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): operator controls proven against a
        # DISPOSABLE PostgreSQL cluster -- its own initdb data directory in a temp
        # path, loopback-only on a dynamic port, test-only role and database,
        # destroyed afterwards. The real admin_write guard runs its full
        # ACCESS -> CONFIRM -> APPLY -> AUDIT chain; nothing is mocked. Skips
        # cleanly on a host without PostgreSQL server binaries.
        "operator_control_isolated_db",
        [
            "tests/test_operator_control_isolated_db.py",
        ],
    ),
    (
        # cc-whole-site-residual-v1 (2026-09-03): the browser/state matrix caught
        # /v3/strategy throwing and rendering the ENTIRE shell blank. Every route is
        # now wrapped so one page's failure is contained and stated.
        "route_error_containment",
        [
            "tests/test_route_error_boundary.py",
        ],
    ),
    (
        "wake_writer_stamp",
        [
            "tests/test_wake_writer_stamp.py",
        ],
    ),
    (
        "overnight_g4_archive_mechanism",
        [
            "tests/test_overnight_g4_archive_mechanism.py",
        ],
    ),
    (
        "overnight_g6_missing_stores",
        [
            "tests/test_overnight_g6_missing_stores.py",
        ],
    ),
    (
        "r13_institutional",
        [
            "tests/test_r13_institution.py",
            "tests/test_r13_goldens_properties_faults.py",
            "tests/test_cio_brain_frontend.py",
            "tests/test_cio_brain_snapshot.py",
        ],
    ),
    (
        # comms-gateway-phase0: gateway contracts, portal, rich send, provider ratchet
        "comms_gateway_phase0",
        [
            "tests/test_comms_agent_contracts.py",
            "tests/test_comms_channel_adapters.py",
            "tests/test_comms_communication_event.py",
            "tests/test_comms_curation.py",
            "tests/test_comms_delivery_ledger.py",
            "tests/test_comms_enforcement_gate.py",
            "tests/test_comms_librarian.py",
            "tests/test_comms_shadow_compare.py",
            "tests/test_comms_subject_memory.py",
            "tests/test_communications_portal.py",
            "tests/test_provider_chokepoint_ratchet.py",
            "tests/test_telegram_alert_rich_send.py",
        ],
    ),
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
                cwd=str(REPO),
                capture_output=True,
                text=True,
            )
            if diff.returncode == 0:
                print("[info] candidate == committed pin")
            else:
                print(
                    "[info] candidate DIFFERS from committed pin (informational; not a substitute for check-committed)"
                )
                print((diff.stdout or "")[:2000])

    if failed:
        print(f"\nCIO HARDENING CI FAILED: {failed}")
        return 1
    print("\nCIO HARDENING CI: ALL GATES PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
