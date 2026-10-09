#!/usr/bin/env python3
"""Local + CI runner for CIO production-hardening gates (Phase 10).

Runs the pure unit suites that must stay green on every push/PR for the
investment-office / Alex CIO hardening program. Never contacts brokers or
sends Telegram.

Exit 0 only if all gates pass.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Ordered, explicit suite list (Phase 10.2)
GATES = [
    (
        "options_workflow",
        [
            "tests/test_options_workflow.py",
            "tests/test_options_workflow_execution.py",
            "tests/test_options_workflow_journal.py",
            "tests/test_options_workflow_submission.py",
            "tests/test_options_workflow_entry.py",
        ],
    ),
    ("learning_outcome_governance", ["tests/test_learning_outcome_governance.py"]),
    ("learning_research_remediation", ["tests/test_learning_research_remediation.py"]),
    ("learning_operator_remediation", ["tests/test_learning_operator_remediation.py"]),
    ("learning_operational_remediation", ["tests/test_learning_operational_remediation.py"]),
    # Campaign m2-canary-20260907 — persistent wake, communications consumption,
    # research transport and shadow outcomes. Registered by the integration owner
    # at INTEGRATION_ORDER.md step 10 (SFR-A-003).
    #
    # These gate the edges the maturity audit found broken: a wake that loads
    # memory before acting, a receipt that names the object it consumed, and a
    # research item that changes a later question. They fail closed — a lane
    # module that stops importing takes the gate red rather than silently
    # dropping out of coverage.
    (
        "campaign_m2_canary_lanes",
        [
            "tests/test_persistent_agent_wake.py",
            "tests/test_replay_determinism_a.py",
            "tests/test_replay_determinism_b.py",
            "tests/test_replay_determinism_c.py",
            "tests/test_replay_determinism_d.py",
            "tests/test_research_dossier_consumption.py",
            "tests/test_comms_campaign_gaps_b.py",
            "tests/test_comms_memory_and_self_repair.py",
            # Every test file the campaign added must be collected by a gate —
            # scripts/check_test_coverage.py enforces it, and an unlisted new
            # test file is a test that CI never runs. Registered here rather
            # than DENY-listed: all of these are collectable and fast.
            "tests/test_belief_calibration_d.py",
            "tests/test_outcome_lifecycle_d.py",
            "tests/test_self_repair_d.py",
            "tests/test_memory_wake_loading.py",
            # 2026-09-10 MEMORY_MALFORMED regression: durable aif_memory schema
            # (memory_id + title-only subject) must not refuse wakes or load all rows.
            "tests/test_memory_loader_schema_compat.py",
            # 2026-09-10: #956 stopped the loader refusing durable rows;
            # it did not make them findable. 488 of 930 rows carry no
            # subject_guid and every wake loaded zero facts.
            "tests/test_wake_memory_symbol_resolve.py",
            # 2026-09-10: making memory findable armed refuse_stale_memory,
            # a branch that had never executed. It aborted real wakes.
            # 2026-09-11: degrading to empty was still a cliff — it kept the
            # decision and discarded every fact. Age is now a continuous decay
            # weight; these files pin "old is OLD, not absent".
            "tests/test_wake_stale_memory_degrades.py",
            "tests/test_memory_decay.py",
            "tests/test_memory_grounding_l2.py",
            # 2026-09-11 L3: node 6 had no caller at all — provenance.llm was a
            # literal None at four sites and null on 51 of 51 wakes. These pin
            # the ordering rail (L2 before L3), the refuse-before-spend gates,
            # provider separation, returned-model verification, and that a test
            # suite can never reach a paid provider.
            "tests/test_wake_l3_call_site.py",
            # 2026-09-11 node 2: identity_status was written into the
            # link-confidence column. The two enums overlap only on CONFIRMED,
            # so every unresolved identity raised CheckViolation and the
            # material-change detector died on every run for ~15h.
            "tests/test_narrative_subject_confidence.py",
            # 2026-09-11 A2: the first ORGANIC producer routed through the comms
            # gateway. SENT is not SETTLED, and a gateway failure must never
            # silently succeed as legacy. The producer had ALSO been passing the
            # alias `operator_alert` into an allowlist compared verbatim, so every
            # send failed closed before any provider I/O — covered here by a test
            # that exercises the REAL gate rather than a mock.
            "tests/test_material_change_gateway_route.py",
            # 2026-09-11: `ALTER TABLE t ADD COLUMN IF NOT EXISTS c` takes an
            # AccessExclusiveLock even when `c` exists — IF NOT EXISTS suppresses
            # the error, not the lock. Three scripts ran it against
            # material_changes on colliding schedules and deadlocked the notifier
            # AFTER it had already delivered to the operator, leaving the row
            # unconsumed and queued to re-send every 15 minutes.
            "tests/test_ddl_guard.py",
            # 2026-09-11: social_ingest reported rows_processed=0 as a hardcoded
            # literal while writing 761 real rows in 36h. None means NOT
            # MEASURED; 0 means measured and empty. Two states cannot express
            # "no input".
            "tests/test_social_ingest_rows_measured.py",
            "tests/test_l3_judgment_pipeline.py",
            "tests/test_l3_judgment_cache.py",
            "tests/test_l3_judgment_author_registered_20260919.py",
            "tests/test_l3_author_billing_fallback_20260919.py",
            "tests/test_l3_critic.py",
            "tests/test_l3_commitment.py",
            "tests/test_model_policy.py",
            "tests/test_material_residual_gate.py",
            "tests/test_judgment_schema.py",
            "tests/test_agent_view_v1_l3.py",
            "tests/test_deepseek_offpeak_l3.py",
            # 2026-09-10: a promote updates the served release and not the
            # hub tree the cron producers run from. A fix can be live and
            # inert at the same time, and nothing compared the two.
            "tests/test_hub_release_drift.py",
            "tests/test_runtime_identity.py",
            # 2026-09-11 oscillator affiliations: the one canonical registry
            # names every oscillator, so a reading is traceable to which
            # oscillator and scope produced it. Fail-closed on unknown ids and
            # invalid states. Confluence flips are bounded (STRONG entry only),
            # deduped, and routed DIGEST never IMMEDIATE.
            "tests/test_oscillator_registry.py",
            "tests/test_oscillator_alerts.py",
            "tests/test_confluence_flip_routing.py",
            "tests/test_oscillator_board_reads.py",
            # 2026-09-10 operator-channel presentation: navigation prose must
            # carry a tappable FQDN link, the plaintext fallback must unescape,
            # HTML bodies must not ship under Markdown, and the ledger must
            # record the wire copy.
            "tests/test_telegram_operator_presentation.py",
            "tests/test_wake_schedule_contract.py",
            "tests/test_wake_negative_mutation_controls.py",
            "tests/test_comms_memory_gateway.py",
            "tests/test_brave_router.py",
            "tests/test_brave_router_governs_api_v2.py",
            "tests/test_brave_router_shared_file_requests.py",
            "tests/test_brave_direct_call_bypass_scan.py",
            "tests/test_consumption_evidence_counting.py",
            "tests/test_integrated_traces.py",
            # SFR-A-FOLLOWUP-001: the cron-callable wake entrypoint. Registered by
            # the integration owner — this file is the central CI gate registry
            # and is never lane-leased.
            "tests/test_run_persistent_wake.py",
            # INC-2026-09-09-STATE-ROOT-FORK: wake evidence must not live inside
            # a release directory, or it forks silently on every promote.
            "tests/test_wake_state_root_stability.py",
            # SFR-A-FOLLOWUP2-001: wake subject selection.
            "tests/test_wake_subject_selector.py",
            # M2: critique → InstrumentRecord next_research_question writeback.
            "tests/test_critique_question_writeback_20260919.py",
            # M5: instrument-subject wakes so load-by-subject has a key.
            "tests/test_cio_instrument_wake_enqueue_20260919.py",
            "tests/test_wake_research_consumption.py",
            # Grok-closure Phase 2: canonical recurring research -> wake feed
            # producer. Governed Brave router + budget -> durable ResearchObject
            # -> atomic wake feed -> selector. Registered by the integration
            # owner; the producer is the ONLY writer of the research feed.
            "tests/test_governed_research_producer.py",
            # The producer above shipped as a library: no entrypoint, no cron,
            # flag default OFF, so research_objects_proxy read 0 on every
            # hourly pass and every wake fell through to material_change.
            # These controls pin the scheduled path fail-closed.
            "tests/test_governed_research_producer_runner.py",
            # The CURRENT pin gate refused a promote with unpinned_extra:66 while
            # diff_count was 0 -- all 66 were cron-written, git-ignored runtime
            # docs rsynced in by overlay_main. Exemption now asks git instead of
            # a hand-kept SKIP_PARTS list; these controls pin both halves.
            "tests/test_current_pin_gitignore_exemption.py",
            # NarrativeSubjectLink@v1. Fifteen narrative surfaces, one tagged;
            # sector_move stamped a SECURITY guid on a SECTOR event. These pin
            # sector canonicalisation (two spellings -> one guid), fail-loud on
            # an unknown type, and that an unresolvable security is a MISS.
            "tests/test_narrative_subject_identity.py",
            # Phase 2: a SECTOR event must never carry a member's SECURITY guid.
            "tests/test_sector_move_subject.py",
            # Phase 3 lane wiring: identity attached, fail-safe, behaviour rail,
            # and rotation tagged sector-first (it is sector-first by design).
            "tests/test_narrative_lane_wiring.py",
            # Phase 5: the wake had the memory code all along and production
            # plugged nothing into the ports. These pin the plugs.
            "tests/test_wake_memory_carryforward.py",
            # Phase 7: outbound messages carry identity. Includes the MSTR
            # regression -- "Strategy:" is a field label, not MicroStrategy.
            "tests/test_outbound_identity.py",
            # Composition: speak only when something changed, and narrate the
            # research when speaking. The model narrator is INJECTED, never
            # constructed, so importing it arms nothing (§12).
            "tests/test_narrative_composition.py",
            "tests/test_narrative_narrator.py",
            "tests/test_wake_composition.py",
            # SFR-R-001: the consumption loop must close. Slots 13:00Z/14:00Z on
            # 54639ff5a re-selected the same three sources because the runner's
            # own receipts never reached the selector.
            "tests/test_wake_consumption_loop_closure.py",
            # SFR-G-001: outbound gateway — agent output -> event -> delivery ->
            # provider acknowledgement -> SETTLED, and no duplicate delivery.
            "tests/test_agent_gateway_adapter.py",
            "tests/test_gateway_settlement.py",
            # Grok-closure Phase 3: settlement truth is durable on the EVENT
            # row (re-read after ack shows SETTLED, not just the memory mirror).
            "tests/test_durable_event_settlement.py",
            "tests/test_comms_settlement_terminal_states_20260930.py",
            # Lane I: inbound operator event -> correlation -> consumption receipt.
            "tests/test_inbound_event_normalizer.py",
            "tests/test_inbound_consumption.py",
            # Grok-closure Phase 3: one coherent intake — checkpoint advances
            # only after event + operator turn + receipt are all durable.
            "tests/test_atomic_inbound.py",
            # Phase 8: ATOMIC_INBOUND_ENABLED gate on the approved poller
            # (default OFF → legacy feed_telegram_update).
            "tests/test_atomic_inbound_poller_gate.py",
            # The operator asked twice and got silence: free text was persisted,
            # bound and receipted, then fell off the end of the poll loop. The
            # answer must go out on the bot that RECEIVED the question --
            # send_cio_message fans out to a different token entirely.
            "tests/test_cio_poller_reply.py",
            # The first live reply was "Hermes: promoted=2502 staged=342
            # topics=[]" to a question about Walmart, which had 3 rows. An
            # answer must be about the subject, not about the pipeline.
            "tests/test_cio_answer_quality.py",
            # Grok-closure Phase 4: canonical durable commitment contract
            # (falsifier/confidence/horizon/freeze) + scheduled outcome evaluator.
            "tests/test_governed_commitment.py",
            # Phase 8: GOVERNED_COMMITMENT_ENABLED shadow CLI (default OFF).
            "tests/test_governed_commitment_shadow.py",
            # Phase 8: AgentView + scoring cortex shadow (flags default OFF).
            "tests/test_cortex_shadow_pipeline.py",
            # Phase 8: optional wake→cortex shadow hook (flags default OFF; no
            # GOVERNED_COMMITMENT on this path).
            "tests/test_wake_cortex_shadow_hook.py",
            # Lane T: gog -n is MUTATING; the wrapper refuses it and verifies
            # remote hashes after any Drive mutation.
            "tests/test_drive_mutation_safety.py",
            # SFR-T-003: Command Center maturity truth is computed live, with
            # explicit zeroes; a stale score file is never served as current.
            "tests/test_campaign_maturity_truth.py",
            # A library with no caller is not a delivered edge. Lanes G and I
            # each shipped a correct, well-tested module that nothing in the
            # runtime ever calls; every per-lane suite was green and the
            # integrated candidate still could not produce one settlement or
            # inbound consumption. Unit tests prove a function is CORRECT; these
            # prove it RUNS. Expected RED until the runtime wiring lands.
            "tests/test_runtime_reachability.py",
            # Drives the REAL poll_once against a mocked provider: entry point,
            # normalization, authorization, correlation, deduplication, agent
            # consumption, receipt persistence, safe error response.
            "tests/test_inbound_poller_integration.py",
            # INC-2026-09-08: centralized receipt-write barrier. Five firing
            # controls -- direct, indirect, unknown wrapper, live-DSN leakage,
            # missing injected writer.
            "tests/test_receipt_write_barrier.py",
            # Maturity-gap-closure-20260909 lanes A/C/E/F–J hermetic controls.
            "tests/test_poller_release_identity.py",
            "tests/test_comms_credential_resolve.py",
            "tests/test_delivery_provenance_quarantine.py",
            "tests/test_maturity_lanes_f_j.py",
            # Maturity-gap remaining: Flash CIO soak observer, self-repair dry harness.
            "tests/test_observe_flash_cio_soak.py",
            "tests/test_gog_drive_safe_parse_id.py",
            # Docs sync keeps Drive copies of release-ephemeral captures (command-center-pages).
            "tests/test_drive_sync_preserved_captures_20260923.py",
            "tests/test_run_self_repair_loop_dry.py",
            # Holding-drawer LLM curation (feat/holding-llm-curation-cio-flash):
            # freshness classes, CIO Flash 4.1 triple-consensus reconcile,
            # refusal fail-closed, curation lineage GUIDs + prior-grounding.
            "tests/test_holding_llm_curation.py",
        ],
    ),
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
    # A paid provider lane can die without anything noticing: DeepSeek ran to a -$0.09
    # balance on 2026-09-17 and returned HTTP 402 on every call for three days while
    # risk/steph/tax produced nothing. This gate holds the alarm that names a billing or
    # auth stop, and the OAuth soft fallback that keeps those agents producing through one.
    (
        "provider_billing_alarm",
        [
            "tests/test_provider_health_alarm.py",
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
            "tests/test_alarm_fires_ci_outage_emergency_20261005.py",
            "tests/test_alarm_fires_positions_proof_20261006.py",
            "tests/test_alarm_fires_batch3.py",
            "tests/test_alarm_fires_batch4.py",
            "tests/test_alarm_fires_scalp_alerts_20261005.py",
            "tests/test_alarm_fires_batch5.py",
            "tests/test_alarm_fires_guard_approval.py",
            "tests/test_alarm_fires_options_intent_20261005.py",
            "tests/test_alarm_fires_disk_and_handler_20260919.py",
            "tests/test_alarm_fires_disk_pressure_20260921.py",
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
            # 2026-09-21: these three were written for this subsystem and run by
            # NOTHING -- named only in check_test_coverage.py's UNLISTED_BASELINE.
            # Unrun is how they rotted: two stubs in the blockers file drifted out
            # of sync with telegram_alert.send_telegram (a lambda that no longer
            # accepted reply_markup) and with the live SHADOW runtime mode, and no
            # gate said so for months. The two _db files SKIP without ALERT_TEST_DSN
            # (30 skipped, exit 0), so in CI they buy collection integrity, not
            # coverage -- which is precisely the rot that hid the stubs.
            "tests/test_alert_normalization_blockers.py",
            "tests/test_alert_occurrence_persistence_db.py",
            "tests/test_alert_delivery_recording_db.py",
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
    # Overnight maturity campaign 2026-09-12. Each file reproduces a defect
    # observed in live evidence before it was fixed, so each must keep running:
    # an unregistered test is a test that never runs, which is what the
    # ci_self_guards coverage gate exists to prevent.
    (
        "maturity_overnight_20260912",
        [
            # L3 durable judgment records: cost from the real client field,
            # prompt digest, release, and an id that identifies one judgment.
            "tests/test_l3_record_integrity_20260912.py",
            # Per-lane floors inside the shared daily LLM cap.
            "tests/test_llm_lane_reservation_20260912.py",
            # L1 producer-to-consumer reachability across the two state roots.
            "tests/test_state_root_split_20260912.py",
            # L2 circulation finishes inside its unit timeout and reports.
            "tests/test_free_first_deadline_20260912.py",
            # L5 health that can actually go false.
            "tests/test_free_first_scheduler_health_20260912.py",
            # L4 commitments revisited after their horizon.
            "tests/test_commitment_outcome_sweep_20260912.py",
            # The live board reads each oscillator from its own store.
            "tests/test_oscillator_board_truth_20260912.py",
            # A commitment inherits the judgment's falsifier, not a template.
            "tests/test_commitment_uses_judgment_falsifier_20260912.py",
            # A producer that writes zero rows says WHICH zero it is.
            "tests/test_detector_explains_its_zero_20260912.py",
            # A lane proves it RAN, not only that it produced.
            "tests/test_detector_heartbeat_20260912.py",
            # The health predicate reads the served SHA itself.
            "tests/test_health_derives_sha_20260912.py",
            # An unrendered secret is not a Postgres auth failure: a missing
            # DB_PASSWORD must refuse, not fall back to a stale ~/.pgpass.
            "tests/test_db_password_no_pgpass_fallback_20260912.py",
            # list_wakes() reads the event store once, and returns the same
            # answer as the algorithm it replaced.
            "tests/test_wake_jobs_single_pass_20260912.py",
            # The health boundary implements the interface its callers use.
            # Tests the REAL class: the defect survived because the only
            # coverage used fakes that defined the missing method.
            "tests/test_health_boundary_advisory_state_20260912.py",
            # A health check that did not produce a decision must not leave a
            # receipt claiming one was made.
            "tests/test_run_worker_health_receipt_20260912.py",
            # Absence of health evidence is not evidence of health: an
            # unassessed domain reports UNKNOWN, never READY.
            "tests/test_health_evidence_coverage_20260912.py",
            # The health-agent -> boundary translation, and the enforcement
            # gate that keeps "fed" separate from "allowed to block".
            "tests/test_health_snapshot_feed_20260912.py",
            # Freshness in market time for sources that only move in market
            # time. Most of it pins what must STILL go stale.
            "tests/test_market_aware_freshness_20260913.py",
            # The data_broker snapshot path is redirectable per call, so tests
            # cannot write into the repo tree -- via an env var, because the
            # package has two import identities and patching a constant reaches
            # only one of them.
            "tests/test_data_broker_state_override_20260913.py",
            # A pinned TRADEAI_STATE_ROOT actually isolates: control-plane
            # fallbacks no longer reach back into the checkout.
            "tests/test_state_root_is_honoured_20260913.py",
            # A forced exit must not discard the run's own report.
            "tests/test_scheduler_flush_before_force_exit_20260913.py",
            # A 1-5 rating scale refuses values that are not on it, instead of
            # stripping the "%" and laundering a percentage into a rating.
            "tests/test_finviz_recom_plausibility_20260913.py",
            # Column maps keyed by header name, never by position. Finviz
            # inserted three columns into v=141 and shifted every later field;
            # "Performance (10 Years)" was stored as a 1-5 analyst rating for
            # five months, inverted (a -100% stock read "Strong Buy").
            "tests/test_finviz_column_map_20260913.py",
            # Numeric scales are declared in config and measured against the
            # live database. The Finviz shift survived 130,155 rows because a
            # column's scale existed only in a docstring, where nothing could
            # check it.
            "tests/test_data_plausibility_contracts_20260913.py",
            # The alarm is watched firing. An alarm nobody has seen fire is
            # indistinguishable from no alarm -- and a real send returned True
            # while meaning "suppressed into the 4-hourly digest".
            "tests/test_data_plausibility_alarm_fires_20260913.py",
            # A DISABLED unit is not a FAILED unit, so systemctl --failed --
            # which is what health_agent uses -- is structurally incapable of
            # seeing it. cio-telegram sat disabled five days.
            "tests/test_expected_services_20260913.py",
            # "CRITICAL" in the body was decorative: telegram_alert_router
            # consults operator_alert_policy_v2 FIRST and returns on its
            # verdict, so _P0_PATTERNS never ran. Availability and integrity
            # alerts now interrupt, keyed on a sentinel rather than prose.
            "tests/test_immediate_availability_alerts_20260913.py",
            # A retention policy that errors is a policy NOT being enforced.
            # db_retention printed ERROR and exited 0, so two tables had been
            # failing their FK deletes on every run, unpruned and unreported.
            "tests/test_db_retention_reports_failures_20260913.py",
            # A generic word must not bind an issuer: "Research on file" filed
            # the Walmart answer against Research Frontiers (REFR) as CONFIRMED.
            # And a delivery must never be retried on TypeError.
            "tests/test_operator_turn_integrity_20260913.py",
            # "is it a buy / what's the target" is an analyst question. It was
            # answered from stop-curation research because nothing read
            # yahoo_analyst_targets_history. Freshness travels with the answer.
            "tests/test_analyst_view_domain_20260913.py",
            "tests/test_pending_expiry_unanswerable_20260913.py",
            "tests/test_pending_close_wording_20260913.py",
            "tests/test_subject_answer_completeness_20260913.py",
            "tests/test_subject_memory_recall_20260913.py",
            "tests/test_desk_spelled_ticker_levels_20260914.py",
            "tests/test_subject_dossier_pills_20260914.py",
            "tests/test_comms_editor_20260914.py",
            "tests/test_comms_editor_transport_20260914.py",
            "tests/test_single_letter_tickers.py",
            "tests/test_tg_chat_routing_20260914.py",
            "tests/test_cio_checkin_only_with_action_20260914.py",
            "tests/test_screener_go_alerts_20260914.py",
            "tests/test_screener_go_alerts_delivery_20260914.py",
            "tests/test_comms_editor_mode_file_20260914.py",
            # 2026-09-23 M5 4d: every scheduled recommendation sender passes the stance
            # gate; document captions pass the editor; editor fail mode is a switch.
            "tests/test_m5_gate_coverage_20260923.py",
            # 2026-09-18: investment-shaped Telegram held on CIO Avoid / missing decision.
            "tests/test_cio_telegram_stance_gate_20260918.py",
            # 2026-09-23 M5: AVOID/SELL hard hold, soft stances GO→WATCH, hold-ledger dedupe.
            "tests/test_cio_telegram_stance_gate_m5_20260923.py",
            "tests/test_cio_stance_review_request_20260923.py",
            "tests/test_cio_stance_classification_drain_20260923.py",
            # 2026-09-16 B-phase curation: STOP HEALTH per-symbol repeats collapse to one
            # batched card; GO + entry alerts carry a HELD / NOT HELD triage pill.
            "tests/test_stop_health_batch_20260916.py",
            "tests/test_held_label_20260916.py",
            # 2026-09-16 C-phase: ex-dividend dates surface on the daily morning brief.
            "tests/test_dividend_events_20260916.py",
            # 2026-09-16 D-phase: CIO-origin-only, proposals-only, durable daily budget.
            "tests/test_cio_origin_gate_20260916.py",
            "tests/test_proposal_channel_gate_20260916.py",
            "tests/test_daily_budget_20260916.py",
            # 2026-09-14 HPE: Hermes completed in 4 minutes and the answer never
            # reached the operator (pending waited on a store Hermes does not write).
            "tests/test_research_joinback_20260914.py",
            # 2026-09-23 MCD: sufficiency diagnostic is not an order; house facts
            # still answer when the research run does not land.
            "tests/test_hermes_mcd_close_20260923.py",
            "tests/test_answer_quality_research_landed_20260914.py",
            # 2026-09-14 Research Escalation Circle phase 1: question GUID, free-channel
            # laps, the grounded Context Analyzer, automatic check-ins.
            "tests/test_research_circle_20260914.py",
            # 2026-09-14 spend truth: real spend by provider/model/process, peak vs off-peak,
            # caps on measured cost, daily/weekly/monthly Telegram spend reports.
            "tests/test_llm_spend_20260914.py",
            # 2026-09-14 13:47: a 4,571-character desk answer was refused by Telegram and logged as replied.
            "tests/test_desk_reply_delivery_20260914.py",
            # 2026-09-14 "Gibberish": desk answers rendered for a phone, parts at paragraph breaks.
            "tests/test_telegram_desk_render_20260914.py",
            # 2026-09-14 research heartbeat: 62% of CIO Hermes requests failed in a week with
            # no alarm; lost projection writes, guard false positives, unreplayed transients,
            # and an escalation handler whose retries all exited 127.
            "tests/test_research_heartbeat_20260914.py",
            # 2026-09-14 15:15-16:30 bridge wedge: DeepSeek held calls ~906 s and the single-threaded bridge
            # queued every caller behind them. Deadline, threaded server, /health, and the watchdog.
            "tests/test_bridge_hang_20260914.py",
            # 2026-09-14: callers that shared advisory_desk_opinion bill to their own process ids.
            "tests/test_llm_label_split_20260914.py",
            # 2026-09-14 operator rule: scheduled paid work weekdays 09-21 ET or weekends, never DeepSeek peak;
            # spend report checks itself against the DeepSeek balance.
            "tests/test_operator_offpeak_window_20260914.py",
            # 2026-09-19 operator directive: the same window, but paid work that falls outside
            # it is now QUEUED rather than dropped by a PEAK_SKIP that recorded nothing, and
            # the operator sets per-caller priority in Command Center -> Ops -> LLM Spend.
            "tests/test_llm_offpeak_deferral.py",
            # 2026-09-14 Telegram: rich layouts, and a written-but-undelivered reply is a finding.
            "tests/test_telegram_rich_20260914.py",
            "tests/test_answer_quality_reply_not_delivered_20260914.py",
            # Rich layouts on the wire: GO, entry and material-change alerts with buttons and the chart preview.
            "tests/test_telegram_rich_wiring_20260914.py",
            # 2026-09-14 litmus vs Yahoo + live Finviz header: sub-share position
            # values written as closes, a stale Alpaca prev_close, positional
            # Finviz parsing and 1,000x unit mislabels in screening gates.
            "tests/test_price_unit_integrity_20260914.py",
            "tests/test_finviz_view_contracts_20260914.py",
            "tests/test_source_health_and_av_selection_20260914.py",
            # 2026-09-22 (split from #1189): researched names stay in the price-refresh universe.
            "tests/test_researched_price_universe_20260925.py",
            "tests/test_source_litmus_vs_yahoo_20260914.py",
            "tests/test_social_discovery_monday_window_20260914.py",
            "tests/test_retention_fk_and_schwab_fractional_20260914.py",
            "tests/test_eod_consolidated_close_sync_20260914.py",
            # 2026-09-13: the state tree existed twice for 18 days (dev tree vs
            # persistent-state). Identity of the directory is the check, not the
            # age of a file -- an age check on one copy is exactly what missed it.
            "tests/test_served_copy_split_20260913.py",
            # 2026-09-13 One Source of Truth: config/data_source_authority.json is the one
            # declaration of store, writer, provider and read path per domain; the gate
            # fails on a retired call site, an undeclared host, or a writer/direct-read
            # count that rose above its ceiling.
            "tests/test_data_source_authority_20260913.py",
            # Phases 3-6 of One Source of Truth (2026-09-13): health decays to
            # unknown; every projection carries as_of/age/source/stale/gap; Brave
            # denials spill to SearXNG from the registry; an account is LIVE/STALE/
            # SERVICE_DOWN/NO_API_MANUAL and never a silent $0.
            "tests/test_data_source_health_decay_20260913.py",
            "tests/test_data_plausibility_required_fields_20260913.py",
            "tests/test_data_broker_envelope_20260913.py",
            "tests/test_brave_router_spill.py",
            "tests/test_data_source_authority_resolve_backup.py",
            "tests/test_catalyst_news_search_backup.py",
            "tests/test_account_state_classifier.py",
            "tests/test_account_state_read_path.py",
            # Phase 7: a stale or missing answer walks declared vectors, free before
            # paid, receipted, with an ETA or an honest "no coverage".
            "tests/test_gap_resolver_20260913.py",
            "tests/test_gap_resolution_monitor_20260913.py",
            # 2026-09-16: the refusal that went nowhere. Measured on the live
            # ledger: 129 denial receipts, one caller, every one CALLER_DAILY_CAP
            # and every one spilled_to null -- refused, then asked of nobody,
            # while a free provider with a 10,000/day allowance sat idle. A caller
            # over its OWN slice is now answered free instead of lost; every free
            # request is metered and refunded; the receipt records which lane
            # answered; and a monitor reports refusals nobody answered at all.
            "tests/test_free_search_fallback_20260916.py",
            # 2026-09-16 P0/P1: the goal-loop control measurement and the identity
            # spine that makes goal/gap/question joinable without renumbering.
            "tests/test_identity_spine_20260916.py",
            # A NaN must not silently destroy a write, and a rescue must not be
            # claimed before the answer is durable.
            "tests/test_watchlist_snapshot_nonfinite_20260916.py",
            # An alert must survive past its first send: one shared transition
            # engine instead of seven private fingerprint blocks.
            "tests/test_alert_transition_20260916.py",
            # 2026-09-16 P2/P7: a goal stops because a PREDICATE over evidence
            # is satisfied, not because a step ran. Measured before this: three
            # goals, 34,347 wakes, 36 days, GOAL_STATUS_CHANGED = 0, and a
            # close_goal() that defaulted to "achieved" and required no evidence
            # at all. These pin the new event type being safe in BOTH directions
            # (rejected on write, silently ignored on read by an older reader),
            # predicate identity reusing goal_id rather than minting a sixth id
            # scheme, UNEVALUABLE for an unknown evaluator instead of a silent
            # pass, the refusal of a goal born overdue, and the append-only
            # repair of the three live goals that were.
            "tests/test_goal_predicate_20260916.py",
            # Termination: five named outcomes, evidence on every one, a
            # non-vacuous falsifier and a bound re-check before anything may be
            # called achieved, and operator_ask counted per goal so the day's
            # second question is no longer refused human escalation.
            "tests/test_goal_termination_20260916.py",
            # 2026-09-16 P3: a CUMULATIVE per-goal budget, keyed (goal_id,
            # predicate_version). Every budget before this one was PER INVOCATION
            # and reset every lap, so a goal could lap forever and accumulate
            # nothing. Fails closed on the search_budget rule -- an unreadable
            # ledger DENIES and is never rebuilt as a fresh zero counter -- and
            # is enforced at enqueue in the producer, never inside MvlRuntime,
            # so an agent can never extend its own budget.
            "tests/test_goal_budget_20260916.py",
            # 2026-09-16 P5: the need ledger, and the independence defect under it.
            # score_lap keyed independence on the RETRIEVAL CHANNEL, so six
            # publishers behind one search engine scored as one source while one
            # wire story reached through two engines scored as two. Every
            # min_sources >= 2 predicate read that number.
            "tests/test_goal_need_ledger_20260916.py",
            # 2026-09-16 P4: a goal can have a SECOND lap, and the second lap can
            # see the first. Measured before the fix: one goal worked 11,457
            # times, 29,653 duplicate enqueues against 1,759 accepted, 29,774
            # thesis events that are 100% PROVIDER_BLOCKED with retrieval_n=0,
            # and GOAL_STATUS_CHANGED = 0 across 37 days. The dedup key is now a
            # generation token (goal:{id}:{predicate_version}:{ledger_digest}) —
            # producer-side, because trigger_intake has no DDL in this repo and
            # amending its UNIQUE constraint would be §7A/§17 operator-gated.
            "tests/test_goal_loop_second_lap_20260916.py",
            # 2026-09-16 P8: the pilot proves the thesis on one goal type.
            # Its headline control is that a MISSING independent source is
            # unknowable, not false - omitted from the facts so the predicate
            # reads UNEVALUABLE and the goal terminates `bounded_ignorance`
            # rather than closing on an assumption. Also pins paid_calls == 0.
            "tests/test_goal_pilot_material_change_20260916.py",
            # 2026-09-17 drivers: the gap between ARMED and WORKING. One day
            # after the goal machinery shipped, three crons were armed and the
            # pilot had written 14 receipts carrying `ok: true` and no verdict
            # at all - its runner probed for an API that did not exist. The lap
            # ledger did not exist either, and GOAL_PREDICATE_SET was 0 against
            # 34,912 wakes. All of it looked healthy from outside. These pin
            # that a schedule firing can never again be read as work happening.
            "tests/test_goal_loop_drivers_20260917.py",
            "tests/test_hardening_ci_exit_code_20260916.py",
            # 2026-09-13 litmus tests: answers are symbol-scoped, drawn from house facts
            # (cash/sectors/policy read from the snapshot), and carry a Sources line.
            "tests/test_operator_answers_use_house_facts_20260913.py",
            "tests/test_data_gap_registry_writer_20260913.py",
            "tests/test_desk_gap_queue_reconnect_20260913.py",
            "tests/test_agent_number_grounding_20260913.py",
            "tests/test_report_maturity_bar_m1_m5_20260919.py",
            # 2026-09-20: Command /api/v2/command must name snapshot_source (M4 census WARN).
            "tests/test_command_snapshot_source_20260920.py",
            # 2026-09-20: file phantoms PASS when Attribution already filters (§17 holdings stay).
            "tests/test_census_phantom_accounts_20260920.py",
            # 2026-09-20: data_gap_resolver cron walks gap_resolver.resolve (QE organic path).
            "tests/test_data_gap_resolver_chain_resolve_20260920.py",
            "tests/test_gap_resolver_live_host_flag_20260920.py",
            "tests/test_synthesis_prompt_budget_20260913.py",
            # Answer-quality monitor + offline litmus replay of the 2026-09-13 questions.
            "tests/test_operator_answer_quality_20260913.py",
            # Every operator reply path goes through one chokepoint: Sources + Went outside + authority tail.
            "tests/test_operator_reply_routing_sources_20260913.py",
            # Stage 1+3 parity: shared Hermes join + internal-first finalize (desk + Maria).
            "tests/test_hermes_join_internal_first_20260923.py",
            # Failed-lane bodies never reach research consumers; the news guard vetoes a
            # headline whose stated 52-week extreme contradicts ours (PR #255 refresh).
            "tests/test_research_packet_hygiene_20260925.py",
            # M5 step 5: join keyed by subject_guid + DB opr_ leg; LEGEND in finalize; [n] citations.
            "tests/test_join_format_m5_20260923.py",
            # Stage 4 residual: atomic jobs.json mirror + bak/migrated recovery.
            "tests/test_gateway_cron_jobs_mirror_20260923.py",
            # Stage 2 parity: ban pseudo Iris/Alex/CIO attribution (desk + Maria).
            "tests/test_specialist_attribution_stage2_20260923.py",
            # M5 Module 3: Maria outbound gate (OpenClaw message_sending bridge).
            "tests/test_maria_outbound_gate_20260923.py",
            "tests/test_maria_gate_prose_stance_20260930.py",
            # Evidence coverage contract per intent: house facts first, false-empty claims rejected.
            "tests/test_operator_evidence_contract_20260913.py",
            # Subject resolution: registry-first tickers, company names incl. house-held names.
            "tests/test_operator_intent_resolution_20260913.py",
            "tests/test_company_names_from_house_20260913.py",
            # Phase 9: one write module per store; golden tests prove row shape and
            # subject GUID are identical to every legacy writer.
            "tests/test_sot_p9_symbol_profiles_writer.py",
            "tests/test_sot_phase9_quotes_prices_writers.py",
            "tests/test_sot_p9_news_articles_writer.py",
            "tests/test_watch_directives_writer_phase9.py",
            # Stage 5 honesty fields on directive create (subject_guid + membership via).
            "tests/test_watchlist_membership_honesty_20260923.py",
            # /api/v2/watchlist serves every ACTIVE ticker directive (S / 1278 surface-split).
            "tests/test_watchlist_api_reconciliation.py",
            # Legacy watchlist_items helpers: read fixed to the real schema, writers retired loudly.
            "tests/test_watchlist_items_legacy_20260923.py",
            "tests/test_sot_p9_hermes_research_writer.py",
            # Off UNLISTED_BASELINE at last. The ONLY coverage of
            # cio_run_worker._check_health, and its fakes are what hid CL-61.
            "tests/test_p26_shadow_autonomy.py",
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
            "tests/test_cio_scorecard_20260929.py",
        ],
    ),
    (
        "r12_operator_intelligence",
        [
            "tests/test_r12_policy_provenance.py",
            # Capital Policy field modal: DeepSeek help on its own registered process, server-built prompt.
            "tests/test_cio_policy_field_advisor.py",
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
            # Direct CIO decision lineage contract and basename-safe operator link.
            "tests/test_cio_decision_lineage_projection.py",
            # Operator evidence composition: research receipts, cognition, learning, coverage.
            "tests/test_cio_operator_evidence.py",
            # 10-02 review: per-decision research, honest clocks, bounded reads, shared cache.
            "tests/test_cio_operator_evidence_bounds_20261002.py",
            # Advisory desk: latest_delta indexed once per store version (was ~35 s/request).
            "tests/test_research_delta_index_20261002.py",
            # /api/v3/maturity/learning: stream + cache the 270 MB lesson store (was ~910 MB/request).
            "tests/test_maturity_lessons_stream_cache_20261002.py",
            "tests/test_cio_advisory_dependency_clocks_20261002.py",
            "tests/test_cio_cross_surface_links_20261002.py",
            "tests/test_cio_decision_lineage_states_20261002.py",
            # Labelled read-time registry identity for symbol-only decisions (operator-approved).
            "tests/test_cio_lineage_identity_readtime_20261003.py",
            "tests/test_cio_lineage_deeplinks_20261002.py",
            # Stages read the model/confidence/evidence_against producers already record.
            "tests/test_cio_lineage_stage_sources_20261003.py",
            "tests/test_decision_payload_guid_stamp_20261003.py",
            "tests/test_decision_trace_no_fabricated_notification_20261003.py",
            "tests/test_cio_operator_evidence_receipts_20261002.py",
            "tests/test_cio_source_clocks_20261002.py",
            "tests/test_cio_xsurface_census_completeness_20261002.py",
            # Step 13 closure: nested payload flow, fetched-but-ignored, classification gate, record ledgers.
            "tests/test_cio_payload_flow_20261002.py",
            "tests/test_cio_surface_panels_20261002.py",
            # Advisory run-now must disclose independent dependency clocks.
            "tests/test_cio_advisory_dependency_clocks.py",
            # Source-side API census and produced-versus-surfaced measurement.
            "tests/test_cio_api_contract_census.py",
            "tests/test_cio_completeness_measurement.py",
        ],
    ),
    # A failed producer must never overwrite good cached content. Registered here
    # so the guard runs behind the required context: the 2026-09-01 data loss was
    # invisible precisely because a fail-open write and a fail-closed write are
    # indistinguishable on a successful run.
    # Capital-plan decisions keep the versioned sizing policy through aggregation
    # (canon_frameworks methodology_ref) without churning decision ids.
    (
        "capital_plan_methodology_20261003",
        ["tests/test_capital_plan_methodology_20261003.py"],
    ),
    # Lineage join phases 1-2 (operator-approved 2026-10-03): production-case outcomes
    # and dispositions, and the declared stage-applicability contract.
    # CIO Desk cards: count checkpoints once (latest row), keep terminal
    # NOT_PRICE_RESOLVABLE out of "due", grade spine POPULATED theses by bucket.
    (
        "cio_desk_degraded_20261003",
        ["tests/test_cio_desk_degraded_20261003.py"],
    ),
    # Health agent scores live data only: paper inputs never raise a critical or move the score (operator 2026-10-03).
    (
        "health_paper_siem_20261003",
        [
            "tests/test_health_paper_excluded_20261003.py",
            "tests/test_siem_incident_visibility.py",
            "tests/test_siem_health_identity.py",
            "tests/test_siem_incident_identity.py",
            "tests/test_stop_health_recovery_20261006.py",
            "tests/test_alert_resolution_bounds_20261006.py",
        ],
    ),
    # Blocked-idea counterfactual ledger + comms editor word-ticker / approval-request fix (2026-10-03).
    (
        "blocked_ledger_comms_20261003",
        ["tests/test_blocked_ledger_comms_20261003.py"],
    ),
    # Blocked-idea ledger counts each idea once per strategy; meme-squeeze gate kept (2026-10-03).
    (
        "meme_squeeze_gate_20261003",
        ["tests/test_meme_squeeze_gate_20261003.py"],
    ),
    # CIO Desk cards read live outcome counts and keep measured lane counts (2026-10-03).
    (
        "cio_scorecard_live_counts_20261003",
        ["tests/test_cio_scorecard_live_counts_20261003.py"],
    ),
    # Stale draft/proposed plans expire append-only; plan store catches up on the log (2026-10-03).
    # Operator-approved store for otherwise-transient CIO outputs; hooks never change a send (2026-10-03).
    (
        "cio_operator_artifacts_20261003",
        ["tests/test_cio_operator_artifacts_20261003.py"],
    ),
    # AlertQuality@v1 scored from the real alert ledgers, persisted via operator artifacts (2026-10-03).
    (
        "alert_quality_producer_20261003",
        ["tests/test_alert_quality_producer_20261003.py"],
    ),
    (
        "cio_plan_expiry_20261003",
        ["tests/test_cio_plan_expiry_20261003.py"],
    ),
    # Decisions card degrades only for plans overdue under the expiry rule (2026-10-03).
    (
        "cio_browser_gates_20261003",
        ["tests/test_cio_browser_gates_20261003.py"],
    ),
    # Health criticals: Finviz cookie honours the API-token backstop; scalp policy skips are policy (2026-10-03).
    (
        "health_finviz_scalp_20261003",
        ["tests/test_health_finviz_scalp_20261003.py"],
    ),
    # Momentum scalps are advisory alerts, 06:00-12:00 ET, one 8% spread limit (operator 2026-10-03).
    (
        "scalp_advisory_20261003",
        ["tests/test_scalp_advisory_20261003.py"],
    ),
    # Shadow ignition engine skips startup DDL when its schema exists (crashed on lock timeouts from 09-17).
    (
        "scalp_shadow_schema_20261003",
        ["tests/test_scalp_shadow_logger_schema_20261003.py"],
    ),
    # CIO-LEARNING-001 compares due and matured from the same checkpoint store (2026-10-03).
    (
        "cio_learning_finding_20261003",
        ["tests/test_cio_learning_finding_20261003.py"],
    ),
    # Heavy CIO compositions share one re-entrant, cached build slot (2026-10-03).
    (
        "cio_heavy_bound_20261003",
        ["tests/test_cio_heavy_bound_20261003.py"],
    ),
    # Health agent: make_interval(hours => int) - a float raised on every run (2026-10-04).
    (
        "health_make_interval_20261004",
        ["tests/test_health_make_interval_20261004.py"],
    ),
    # Active Trader premarket watch: heads-up 07:00-09:29 with PM high / PM VWAP for the open; replay-safe,
    # fail-closed float, shadow by default, AT alert path only, no trade context (2026-10-05).
    (
        "at_premarket_watch_20261005",
        ["tests/test_at_premarket_watch_20261005.py"],
    ),
    # Policy apply script ratifies into production state, not the running tree (2026-10-04).
    (
        "apply_policy_default_store_20261004",
        ["tests/test_apply_policy_default_store_20261004.py"],
    ),
    # Active Trader microstructure recorder, entry/exit signals (moomoo + Schwab), trade replay, exit watch,
    # learning memory + calibration proposals; Schwab stream subscribes the scalp names (2026-10-05).
    (
        "at_microstructure_learning_20261005",
        ["tests/test_at_microstructure_learning_20261005.py"],
    ),
    # Active Trader Phase 1: ARMED/TRIGGERED alerts on moomoo L2 + tape; fail closed; no order path (2026-10-04).
    (
        "active_trader_momentum_alerts_20261004",
        ["tests/test_active_trader_momentum_alerts_20261004.py"],
    ),
    # Active Trader ARMED quality + stand-down + Trade-AI verdict + recorder reconnect (operator 2026-10-09:
    # 18 of 19 ARMED alerts never fired; ARMED printed last price as entry; dedupe keyed on price).
    (
        "active_trader_armed_quality_20261009",
        ["tests/test_active_trader_armed_quality_20261009.py"],
    ),
    # Active Trader alerts live: comms-editor exemption (missing-CIO hold only), Telegram path, feed API.
    (
        "active_trader_live_alerts_20261004",
        ["tests/test_active_trader_live_alerts_20261004.py"],
    ),
    # Operator options intents: standing memory on the ticker directive, proactive Schwab contract
    # matcher (shadow default, throttled digest), generic covered calls obey the intent floor (2026-10-05).
    (
        "options_intent_20261005",
        ["tests/test_options_intent_20261005.py"],
    ),
    # CIO event bus fork repair: re-link without loss/reorder, byte-exact archive, idempotent (2026-10-04).
    (
        "repair_cio_event_bus_fork_20261004",
        ["tests/test_repair_cio_event_bus_fork_20261004.py"],
    ),
    # Momentum-scalp universe fails closed on unknown float/price (looked up first); min stop distance (2026-10-05).
    (
        "scalp_universe_failclosed_20261005",
        ["tests/test_scalp_universe_failclosed_20261005.py"],
    ),
    # Alpha Vantage fundamentals paced (1 req/s free tier), fund exclusion; ET/API chrome not tickers.
    (
        "alpha_vantage_pacing_20261004",
        ["tests/test_alpha_vantage_pacing_20261004.py"],
    ),
    # Active Trader alert audit: outcomes from the price you could pay, stop-first is a miss, exits,
    # below-stop veto, supply evidence, your fills tagged to the alert before them (2026-10-05).
    (
        "at_alert_outcomes_20261005",
        ["tests/test_at_alert_outcomes_20261005.py"],
    ),
    # Secrets: one write path (render reported, never silently skipped), drift check, Finviz cookie tool (2026-10-05).
    (
        "secret_single_path_20261005",
        ["tests/test_secret_single_path_20261005.py"],
    ),
    # Social scanner: Reddit via official OAuth (loud when not configured), Hermes/Aegis merged as named
    # sources (scalp-universe rows only create candidates), catalyst research on scouts first (2026-10-05).
    (
        "social_multisource_20261005",
        ["tests/test_social_multisource_20261005.py"],
    ),
    # Ratified investment policy drives capital-plan sizing; 12% cap; required-only CONFIRMED (2026-10-03).
    (
        "policy_unify_20261003",
        ["tests/test_policy_unify_20261003.py"],
    ),
    # CI-provider outage emergency release: outage proof (incident + never-started jobs; real red stays red),
    # local replay evidence bound to the tree, release-emergency grant, commit rule, reconciliation (2026-10-05).
    (
        "ci_outage_emergency_release_20261005",
        ["tests/test_ci_outage_emergency_release_20261005.py"],
    ),
    # Auto-approver survives a dropped DB connection (fail-closed); market_day_gate runs its check (2026-10-03).
    (
        "atm_db_gate_fix_20261003",
        ["tests/test_atm_db_gate_fix_20261003.py"],
    ),
    # Alerts read the Command Center (data broker / CC API), never their own sources; producer ratchet;
    # material-change digest priced by the broker and concise; CIO entry plan sanity (2026-10-05).
    (
        "alert_single_source_20261005",
        ["tests/test_alert_single_source_20261005.py"],
    ),
    # Active Trader alert sync: sub-minute APPROACHING / intrabar TRIGGERED / EXTENDED + buy zone,
    # state-aware throttle, latency journaled; fast loop reads only the Command Center store (2026-10-05).
    (
        "at_alert_sync_20261005",
        ["tests/test_at_alert_sync_20261005.py"],
    ),
    # /v3/cio/home memory: stream the action ledger, tail-read logs, one plan-store load (2026-10-03).
    (
        "cio_home_memory_20261003",
        ["tests/test_cio_home_memory_20261003.py"],
    ),
    # One price truth for positions (data-broker quote; never the frozen `current_price`), stale basis
    # anchors not scaled, probe rows out of REALIZED, broker trade dates, CC-vs-broker reconciliation,
    # no new direct position-store readers (operator 2026-10-05).
    (
        "portfolio_price_truth_20261005",
        ["tests/test_portfolio_price_truth_20261005.py"],
    ),
    # Communications hub (operator 2026-10-07): categories, scores, re-entry status, actionability, TTL by category,
    # supersede, decision board, filters, bulk actions; lifecycle archive-then-delete refuses a short archive.
    (
        "comms_hub_20261007",
        ["tests/test_comms_hub_20261007.py"],
    ),
    # Watch decision standards (operator 2026-10-07 "watchlist etc"): category, priority, five scores, TTL/expiry,
    # status, actionability on every Watch card; held names never leave; search always finds the name.
    (
        "watch_decision_standards_20261008",
        ["tests/test_watch_decision_standards_20261008.py"],
    ),
    # Investment Command Center (operator 2026-10-08): opportunity engine (R:R ladder, six factors, conviction, rank,
    # type, stance), CIO-memory opportunity store (material-change versions, behaviour keys refused), API, Telegram line.
    (
        "investment_command_center_20261008",
        ["tests/test_investment_command_center_20261008.py"],
    ),
    # Cron interpreter resolution (operator 2026-10-09 "fix the broken cron jobs"): release dirs ship no .venv, so
    # rotation_autopilot died on `import dotenv` every 15 min and hermes_coordinator's child steps hit "No such file".
    (
        "cron_venv_resolver_20261009",
        ["tests/test_cron_venv_resolver_20261009.py"],
    ),
    # Paper/broker-adjacent child steps use the same resolver; telegram run_promoter no longer shadows os (F823).
    # Code-only, under execution-engineering grant dc66eb4b6db5107e (operator 2026-10-09).
    (
        "paper_venv_resolver_20261009",
        ["tests/test_paper_venv_resolver_20261009.py"],
    ),
    # Symbol-thesis job repair (operator 2026-10-09 "fix the thesis job"): 6 PUBLISHED of 315 runs in 5 days. Blocked-loop
    # backoff, no off-peak deferral that loses the answer, DEDUPE_SKIP release + one retry, 3200-token replies.
    (
        "thesis_job_fix_20261009",
        ["tests/test_thesis_job_fix_20261009.py"],
    ),
    # Opportunity actions (operator 2026-10-09): Request CIO review (symbol-thesis priority queue; operator flags and the
    # CIO's top-ranked names served first), Add to watchlist, CIO-memory fallback, quote-page news filter.
    (
        "opportunity_actions_20261009",
        ["tests/test_opportunity_actions_20261009.py"],
    ),
    # Trade-AI scalp scan every 5 min + one feed for Trade-AI and Active Trader + runner GO with catalyst
    # (operator 2026-10-09).
    (
        "trade_ai_scalp_5min_20261009",
        ["tests/test_trade_ai_scalp_5min_20261009.py"],
    ),
    # Scalp lane bulk catalyst read (operator 2026-10-09: "build the finviz API fix"): data-broker news plus the
    # Finviz Elite news export in batches instead of ~2 throttled Finviz page requests per ticker.
    (
        "scalp_catalyst_bulk_20261009",
        ["tests/test_scalp_catalyst_bulk_20261009.py"],
    ),
    # Opportunity modal news (operator 2026-10-08: "nothing here on what company does or latest news, catalyst"):
    # profile description, typed catalysts, latest news without catalyst repeats, and the news-ingestion opportunity
    # lane that gives the CIO's top-ranked names news beyond the 60-symbol cap.
    (
        "opportunity_modal_news_20261008",
        ["tests/test_opportunity_modal_news_20261008.py"],
    ),
    # Advice ranked by CIO conviction (operator 2026-10-08): Communications conviction sort + reward board, below-floor
    # names last and tagged; advice digest entry/re-entry ordered by conviction, below-floor collapsed, CIO notes uncapped.
    (
        "conviction_ordering_20261008",
        ["tests/test_conviction_ordering_20261008.py"],
    ),
    # Decision-speed redesign (operator 2026-10-08): Telegram decision cards route exactly like the old layout;
    # Home/Communications/Watch answer action-risk-opportunity first with strict colour families.
    (
        "decision_cards_20261008",
        ["tests/test_decision_cards_20261008.py"],
    ),
    # Advice digests (operator 2026-10-08): entry alerts / CIO advisory notes / thesis updates / watchlist BUY_READY
    # held for the 10/15/17 ET HTML digests; scalps, approvals and stop/protection stay immediate.
    (
        "advice_digests_20261008",
        ["tests/test_advice_digests_20261008.py"],
    ),
    # Positions store phase 1 (shadow, one writer positions_sync.py) + the 2026-10-06 Schwab validation fixes:
    # per-account basis check that applies broker basis, CSV lot no longer outranks the broker, reinvestment
    # drift auto-applied, every holdings.json read-modify-write under the shared lock (operator 2026-10-06).
    (
        "positions_store_phase1_20261006",
        ["tests/test_positions_store_phase1_20261006.py"],
    ),
    # Stale-price overwrites (2026-10-06): live monitor no longer writes holdings.json, repricer refuses a
    # near-empty live fetch, health finding portfolio_stale_marks pages + auto-reprices.
    (
        "price_writer_fix_20261006",
        ["tests/test_price_writer_fix_20261006.py"],
    ),
    # Positions plan phase 2: the 10-trading-day proof grader (runs, heartbeat, diff, lots; operator 2026-10-06).
    (
        "positions_proof_phase2_20261006",
        ["tests/test_positions_proof_phase2_20261006.py"],
    ),
    # Schwab ledger keeps transfer/journal direction; >1y fetch chunked; dry run never pages (2026-10-06).
    (
        "ledger_transfer_direction_20261006",
        ["tests/test_ledger_transfer_direction_20261006.py"],
    ),
    # Active Trader soul: "should have been" session review reproduces the operator's XNDU table;
    # automated mode is SIMULATION ONLY (one brain, sized to the ask supply, no live mode) (2026-10-05).
    (
        "at_soul_review_sim_20261005",
        ["tests/test_at_soul_review_sim_20261005.py"],
    ),
    (
        "lineage_phase12_20261003",
        [
            "tests/test_cio_lineage_production_cases_20261003.py",
            "tests/test_cio_stage_applicability_20261003.py",
        ],
    ),
    # Optional falsifier in the options / buy-ready CIO reviews (operator-approved 2026-10-03).
    # Empty Fidelity stop registry retires its stops; no baked-in fallback (2026-10-03).
    (
        "fidelity_registry_empty_20261003",
        ["tests/test_fidelity_registry_empty_20261003.py", "tests/test_fidelity_stop_sync.py"],
    ),
    (
        "review_falsifier_20261003",
        ["tests/test_review_falsifier_20261003.py"],
    ),
    (
        "ai_analyst_cache_fail_closed",
        [
            "tests/test_ai_analyst_cache_fails_closed.py",
        ],
    ),
    # Join design Phases 3-4 (operator-approved 2026-10-03): durable capital-plan
    # decision ids, run decision_ids stamping, framework refs per decision.
    (
        "lineage_phase34_20261003",
        [
            "tests/test_lineage_phase34_20261003.py",
        ],
    ),
    # Policy Review P2: only outcome-backed lessons queue; Darwin scores only market outcomes (2026-10-03).
    (
        "lesson_queue_darwin_20261003",
        ["tests/test_lesson_queue_darwin_20261003.py"],
    ),
    # Dark WIRE debt: DecisionRationale on decisions + lineage; thesis event wake in SHADOW (2026-10-03).
    (
        "dark_wire_rationale_wake_20261003",
        ["tests/test_dark_wire_rationale_wake_20261003.py"],
    ),
    # Hermes research joins the options review that asked for it (MORE_RESEARCH follow-up).
    (
        "lineage_run_hermes_join_20261003",
        [
            "tests/test_lineage_run_hermes_join_20261003.py",
        ],
    ),
    # Memory retrieval receipts carry the agent/wake/trace/decision a caller knew (operator-approved 2026-10-03).
    (
        "memory_retrieval_attribution_20261003",
        ["tests/test_memory_retrieval_attribution_20261003.py"],
    ),
    # P1 every call is falsifiable + P4 per-agent calibration (operator 2026-10-03).
    (
        "falsifiable_calls_20261003",
        ["tests/test_falsifiable_calls_20261003.py"],
    ),
    (
        "ai_analyst_freshness_sla",
        [
            "tests/test_ai_analyst_freshness.py",
        ],
    ),
    # A held position is never a re-entry candidate.
    (
        "s3_detector_excludes_held",
        [
            "tests/test_s3_detector_excludes_held.py",
        ],
    ),  # A directory a served surface reads must be linked into the release.
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
        "cogx_w1_foundations",
        [
            "tests/test_intelligence_client_facade.py",
            "tests/test_memory_chokepoint_ratchet.py",
            "tests/test_supervisor_foundations.py",
            "tests/test_approval_package_ledger.py",
            "tests/test_gir_projector_and_breach_detector.py",
            "tests/test_approval_package_reminder.py",
            "tests/test_memory_compliance.py",
            "tests/test_memory_ring2.py",
            "tests/test_containment_cleared_state.py",
            "tests/test_indicator_engine_rate_limit.py",
            "tests/test_research_write_path_and_fanout.py",
            "tests/test_sec_filings_feed.py",
            "tests/test_wave3_cognition.py",
            "tests/test_wave4_unification.py",
            "tests/test_wave5_maturity.py",
            "tests/test_m2_substrate_check.py",
            "tests/test_earnings_gate_vocabulary_20260928.py",
            "tests/test_lane_registry_bare_schedule_20260928.py",
            "tests/test_lane_registry_drift_events_20261008.py",
            "tests/test_lane_governance_packet_20261008.py",
            "tests/test_ops_summary_model_job_live_wiring_20261008.py",
        ],
    ),
    (
        "goal_work_minter_ratchet",
        [
            "tests/test_goal_work_minter_ratchet.py",
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
            # A push grant must name the branch or head SHA it covers (1.3.0).
            "tests/test_guard_push_scope_20260925.py",
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
    # A dead FINVIZ_COOKIE with a working FINVIZ_API_TOKEN is healthy (rotation note),
    # never "screener empty"; degraded only when both fail; no secret in any record.
    (
        "finviz_token_backstop_20261003",
        [
            "tests/test_finviz_token_backstop_20261003.py",
        ],
    ),
    # A function-local import that shadows a module-level one makes the name
    # local for the WHOLE function -> UnboundLocalError on every earlier use.
    # claude_escalation_handler:295 did exactly that from 2026-08-08, which broke
    # _verify_remediation for six weeks: no escalation could ever be marked
    # cleared, so 13 components paged "AUTO-RETRY PAUSED" at 78/hour forever.
    (
        "import_shadowing",
        [
            "tests/test_no_shadowed_module_imports_20260921.py",
        ],
    ),
    # Delivery must be PROVABLE. Measured 2026-09-21: 62 of 7,991 alert_events
    # carried a telegram_message_id (0.78%) and 51,193 of 52,930
    # communication_events sat UNSETTLED, because the "DB first, Telegram second"
    # contract means the provider id does not exist at save_alert_event() time.
    (
        "alert_delivery_id",
        ["tests/test_alert_delivery_id_attach_20260921.py"],
    ),
    # Phase 2 of the same work: the writer existed but NOTHING called it, and the
    # legacy settle path dropped the id it already held. Measured 2026-09-22:
    # 62 of 8,003 alert_events carried a telegram_message_id (0.78%), 51,193 of
    # 52,930 communication_events were UNSETTLED (the 79 SETTLED all came from
    # the gateway path, which passes provider_message_id), and
    # destination_policy_id was NULL on all 52,929 delivery + outbox rows. This
    # gate holds the wiring down: it fails if a call site stops binding the id
    # save_alert_event returns, if the legacy settle stops passing the provider
    # id, or if the outbox stops recording which policy chose the channel.
    (
        "alert_delivery_wiring",
        [
            "tests/test_alert_delivery_wiring_20260922.py",
        ],
    ),
    # pipeline_freshness_monitor._age_days_table returned None for an ABSENT
    # table, a RAISED query, and a table that EXISTS BUT IS EMPTY. check()
    # rendered all three as "no output / table/file absent" and the escalation
    # handler paged on it: seven missing_* components, ~126 pages each per day,
    # against tables that all exist with fresh rows.
    (
        "freshness_reason",
        [
            "tests/test_freshness_reason_is_not_conflated_20260921.py",
        ],
    ),
    # communication_events.subject_guid was written by exactly ONE caller
    # (telegram_alert._tag_outbound), as an UPDATE after publish. Every other
    # producer — the gateway-owned path and ~40 direct publish_communication
    # call sites — wrote a row with no subject: 8,786 of 54,676 OUTBOUND events
    # carried one on 2026-09-22 (16.1%). The stamp now happens inside
    # publish_communication, before persist. That is only safe while the
    # 2026-09-21 template guards hold — one alert's boilerplate ("After <n>
    # retries") had become 57.5% of the identity spine — so the wiring and the
    # guards are gated by the same suite, against a registry in which the
    # template words ARE registered entities.
    (
        "publish_chokepoint_identity",
        [
            "tests/test_publish_chokepoint_identity_20260922.py",
        ],
    ),
    # Operator turns bound nothing: 114 of 114 in the seven days to 2026-09-23
    # stored a NULL subject_guid ("how is sentinel one doing", "is mcdonalds a
    # good investment", "is S a good investment"), and research/gap rows carried
    # a GUID on REQUESTED only. Gated with the chrome-leak negatives so the
    # any-case windows cannot reopen "Price" -> TROW or "Data" -> DAIO.
    (
        "operator_turn_identity_binding",
        [
            "tests/test_identity_anycase_windows_20260923.py",
            "tests/test_identity_stamp_rows_20260923.py",
        ],
    ),
    # The memory join was open at both ends. Measured 2026-09-22: causation_id
    # and parent_event_id were NULL on all 54,928 communication_events, so no
    # reply resolved to the event that caused it; and subject_guid was NULL on
    # all 199 agent consumption receipts, because the column exists on the
    # table and on the dataclass but was missing from the INSERT. Both were
    # wiring, not design. This gate pins the defaults (a root event points at
    # itself; a root has NO parent, because self-parenting loops a recursive
    # walk) and pins subject_guid into the receipt write. M5 (2026-09-23): the
    # ids now travel the whole question -- turn -> gap / Hermes request ->
    # completion -> outbound -- through one lineage scope, the reply to a
    # multi-message send ("53968,53969") binds from the ledger, and watch rows
    # get subject_guid behind a column probe (additive migration).
    (
        "comms_lineage_join",
        [
            "tests/test_phase4_lineage_join_20260922.py",
            "tests/test_event_lineage_20260924.py",
        ],
    ),
    # market_quotes is 34.2M rows / 5.67 GB, of which 97.7% is intraday
    # resolution nobody queries: both consumers read one row per symbol per day.
    # The downsampler deletes, so its gate pins dry-run-by-default, DELETE
    # confined to one function, and the keep-query ordered DESC (ASC would keep
    # the session's FIRST quote and shift every close by a full day).
    (
        "market_quotes_downsample",
        [
            "tests/test_market_quotes_downsample_20260921.py",
        ],
    ),
    # Nothing removes a queued escalation whose condition has resolved:
    # enqueue_escalations only appends, and removal happens solely on successful
    # verify, which is unreachable without a retry_cmd. Measured 2026-09-22: 18
    # queued items, 0 fixable, 0 with retry_cmd -> ~1,870 pages/day forever.
    # The reaper deletes durable state, so its gate pins dry-run-by-default,
    # archive-before-write, and FAIL-CLOSED on a broken probe (an empty live-set
    # would otherwise make every entry look resolved).
    (
        "escalation_queue_reaper",
        [
            "tests/test_escalation_queue_reaper_20260922.py",
        ],
    ),
    # The last three storming conditions, measured 2026-09-22 11:07 EDT. Each
    # exhausted at max attempts, logged "Skipping ...: retries exhausted", never
    # ran its retry_cmd again and re-armed every 1800s forever. Root causes, in
    # order: a verify predicate stricter than the detector it verifies; a
    # detector reading the frozen served copy of a log the cron writes in the DEV
    # tree; and a review-only item that escaped the shed because its component
    # was in neither hard-coded namespace. This gate holds all three.
    (
        "escalation_storm_last3",
        [
            "tests/test_escalation_storm_last3_20260922.py",
        ],
    ),
    # The queue also GROWS on its own. hermes_health_inspector._escalate builds
    # every item with the same constant component and used to append it
    # unconditionally, so each run re-queued an already-queued condition --
    # 6 duplicate rows accreted from 2026-08-07. This gate holds the dedupe.
    (
        "hermes_escalation_dedupe",
        [
            "tests/test_hermes_escalation_dedupe_20260922.py",
            # Agent-job producers dedup against PENDING work (a fresh-id ON CONFLICT never
            # fires) and direct Ollama callers share one num_ctx rule (PR #165 refresh).
            "tests/test_agent_queue_dedup_and_ollama_ctx_20260925.py",
        ],
    ),
    # Training trades must never page the operator. open_trade_monitor sent
    # "EXTENDED PROFIT: BAX +$170.04" 12 times in 36 minutes for a position the
    # operator does not own -- every paper_trades row is ALPACA_PAPER, TOS_PAPER
    # or the tradeai_automated sandbox, and schwab_positions_live holds none of
    # those symbols. Also pins the stop_decisions.decided_at column whose wrong
    # name aborted the transaction each cycle, rolling back the dedupe row while
    # the Telegram had already gone out.
    (
        "paper_trades_never_page",
        [
            "tests/test_paper_trades_never_page_20260922.py",
            # M5 guardrails 2026-09-23: the same rule for the four senders the
            # 09-22 fix missed, pytest kept off the live M2 shadow, and the
            # stance observe receipt kept out of reach of test fixtures.
            "tests/test_m5_guardrails_20260923.py",
        ],
    ),
    # A DELIVERED message must not discard its provider id. _legacy_send called
    # the bool wrapper instead of _raw_send_telegram_result, and only the result
    # variant populates _LAST_MESSAGE_IDS -- so all 121 LEGACY_DELIVERED messages
    # in 24h reached Telegram with the id thrown away one frame later, and
    # attach_telegram_message_id honestly no-opped at all 7 wired call sites.
    (
        "legacy_send_captures_message_id",
        [
            "tests/test_legacy_send_captures_message_id_20260922.py",
        ],
    ),
    # Measured 2026-09-22: grep for error_budget|slo_target|burn_rate across
    # scripts/ and config/ returned NOTHING. Every alarm in the tree is a
    # threshold on a CAUSE, which is how one AUTO-RETRY alert became 57% of the
    # identity spine while "did the alert reach a human" had no number at all.
    # The gate pins the three things an earlier draft got wrong -- a decorative
    # window_seconds, consumed_budget_pct as burn_rate*100, and validation
    # deferred out of the config -- each with its own negative control, plus
    # suppression on thin traffic so the budget alarm does not become the next
    # storm. DB assertions skip when hermetic; the math never does.
    (
        "slo_burn_rate",
        [
            "tests/test_slo_burn_rate_20260922.py",
        ],
    ),
    # Two gates in the maturity roadmap were unmeasurable as written, for
    # reasons unrelated to the system's behaviour. Phase 1 froze the storm
    # baseline at a MID-DAY count (1,673) and compared it to a per-day target;
    # the full 09-21 day is 7,627. Phase 2 required >=95% of "last-7-day
    # alerts" to carry a provider message id, while 97.67% of delivery rows are
    # SUPPRESSED and can never acquire one -- a ceiling of 2.1% against a 95%
    # bar. This gate pins both restatements to the measured numbers AND holds
    # the line against a future loosening: separate controls assert the 95%
    # threshold is unchanged, that the worse 7-day window was not swapped for
    # the flattering 24-hour one, and that the corrected storm baseline demands
    # a LARGER reduction than the partial figure did. The doc predicates are
    # each run against the exact superseded wording, so a predicate that
    # returned True for everything would fail here. Hermetic: no DB, no log.
    (
        "maturity_gate_restatement",
        [
            "tests/test_maturity_gate_restatement_20260922.py",
            # Governance truth repair 2026-09-25: gate status is read from the
            # measurement store at render time (never a count frozen in the
            # catalog); AGENTS.md policy state on main; the Drive mirror
            # updates one pinned file id and never creates a duplicate.
            "tests/test_governance_truth_repair_20260925.py",
            "tests/test_agents_drive_mirror_20260925.py",
        ],
    ),
    (
        "lane_registry",
        [
            "tests/test_lane_registry.py",
            "tests/test_lane_state_drift_20261007.py",
            "tests/test_report_lane_fire_ledger_20261007.py",
            "tests/test_lane_portfolio_repricer.py",
            # Day P/L for shares traded today (fills) + basis rebase on trade-sized share change.
            "tests/test_intraday_day_pl_and_basis_20260923.py",
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
        "research_identity_tagging",
        [
            # The GUID/sector tags downstream agents are told to trust. Pins the
            # GICS allowlist (a fund mandate is not a sector), the one-way
            # identity rank (a feed that stops publishing CUSIPs must not be able
            # to downgrade a CONFIRMED entity), and that an unresolvable symbol
            # yields NO tag rather than a null-subject one that would inflate
            # apparent coverage.
            "tests/test_research_identity_tagging.py",
        ],
    ),
    (
        "pipeline_rows_unknown",
        [
            # 16 of 20 PipelineRun users never call .rows(), so a default of 0
            # made pipeline_zero_rows fire on five pipelines that had never
            # reported a row. Pins that unknown stays distinct from zero.
            "tests/test_pipeline_rows_unknown.py",
            # A retry that raises (subprocess timeout) is a failed retry, not an ERROR flood:
            # run closed as failed, action recorded, escalation at MAX_RETRIES (PR #140 refresh).
            "tests/test_pipeline_watchdog_retry_failure_20260925.py",
        ],
    ),
    (
        "mentions_retention",
        [
            # I shipped document_mentions with NO retention on the day AGENTS.md
            # gained "every suppression needs a shelf life". Pins that windows are
            # READ from db_retention (never copied), that an unwindowed source is
            # reported rather than guessed, and that no model runs in the pruner.
            "tests/test_mentions_retention.py",
        ],
    ),
    (
        "document_mentions",
        [
            # Subject vs passing mention. The canonical case: an Apple article
            # that cites Morgan Stanley must never be filed under MS. Also pins
            # that macro sources (FRED) can never be given an issuer.
            "tests/test_document_mentions.py",
        ],
    ),
    (
        "llm_cap_admin",
        [
            # The spend caps had NO operator surface — not the Command Center,
            # not api_v2. Pins that a change writes BOTH the registry and the DB,
            # that ceilings hold even for the operator, and that drift is
            # reported rather than silently reconciled.
            "tests/test_llm_cap_admin.py",
            # 2026-09-19: /api/v2/paper-proposals/enrich-all spawned seven scripts with
            # no env, so an LLM-spending child inherited whatever the server unit
            # carried. With LLM_GLOBAL_DAILY_USD_CAP absent every governed call failed
            # COST_CONFIGURATION_INVALID and eight of them opened the agent_flash
            # circuit breaker for 900s, blocking the healthy cron drains too. Pins that
            # the cap is resolved from the durable host file and that the steps are
            # skipped, never run uncapped, when no cap resolves anywhere.
            "tests/test_enrich_all_governed_env.py",
        ],
    ),
    (
        "governed_bridge_cap_semantics",
        [
            # A budget decision must not be reported as a server fault. The
            # request-count cap is enforced only inside reserve_projected_cost,
            # whose failures were all flattened to RESERVATION_FAILED/500 — a
            # code classify_failure() rates RETRYABLE_TRANSIENT. On 2026-09-06
            # the caller duly retried, spent its whole 46,106-row queue on a
            # refusal that could not change, and reported a normal result.
            # Pins the code->status map against the reservation's actual raise
            # sites, that the traceback is logged, and that the consuming loop
            # stops on a refusal without writing the rows it abandons.
            "tests/test_cap_breach_is_not_a_server_fault.py",
        ],
    ),
    (
        "runtime_state_survives_checkout",
        [
            # Two files were classified as runtime state and still owned by git.
            # SearXNG's live config was bind-mounted rw into the repo, so the
            # container chowned it 977:977 and `git checkout` could not unlink it —
            # one file blocked 70 others and left 18 merged commits not running on
            # the tree that actually executes. hermes_score_weights was declared
            # "runtime_state_with_release_seed" in the release manifest, but nothing
            # enforced it, so the same checkout reverted v11 to the v9 seed and
            # discarded nine grafts of learning.
            "tests/test_runtime_state_survives_checkout.py",
        ],
    ),
    (
        "subject_identity_spine",
        [
            # Stage 0. ~336,000 rows could not be joined to a subject: three tables
            # had no subject_guid column at all, two had one and never filled it. A
            # dossier keyed on identity therefore read a third of the corpus, and
            # under-answering is indistinguishable from answering. Pins that the
            # backfill stays free (no model on any row), that it distinguishes
            # "registry unreadable" from "symbol unknown" and stops rather than
            # writing the former as the latter, and that unknown is the LOWEST rank
            # — a guard that coalesced NULL to CONFIRMED reported 23 symbols
            # resolved while writing zero rows.
            "tests/test_backfill_subject_identity.py",
        ],
    ),
    (
        "material_change_detector",
        [
            # Stage 1. Every research job here is schedule-triggered, so a sweep
            # treats every name identically and structurally cannot notice that ONE
            # name is behaving unlike itself — which is why three watchlist names up
            # 15-40% on 2026-09-05 produced no alert. Pins that the threshold is
            # relative to each symbol's own average daily move (a fixed percent
            # cannot be right for two different names at once), that corrupt data is
            # skipped rather than alarmed on (a NaN compares False to every
            # threshold, so the first run emitted BHVN at magnitude NaN), and that
            # what could NOT be evaluated is counted and reported.
            "tests/test_material_change_detector.py",
        ],
    ),
    (
        "material_change_notify",
        [
            # Stage 2 — the alert that would have arrived on Friday. Pins that a
            # change is announced EXACTLY once (change_guid is uuid and psycopg2
            # sends text[]; the first live run sent the alert then failed on the
            # UPDATE, so the next run re-announced all three), that a change outside
            # market hours is HELD rather than dropped, and that a send the platform
            # did not accept leaves the change pending instead of silently
            # consuming it.
            "tests/test_notify_material_change.py",
        ],
    ),
    (
        "due_diligence_questions",
        [
            # Stages 3-5 — the loop that closes it. Before 2026-09-06 ZERO research
            # rows had ever been requested because a name moved. Pins the operator's
            # curation order (flash -> free OAuth -> deepseek pro -> ASK, inverted
            # from the house default because curation emits a parsed contract), that
            # research lanes are RANKED BY MEASURED delivery and quality rather than
            # hardcoded (the shipped default was claude, dead since 2026-08-01;
            # replacing it with grok picked the worst lane at 0.470 vs chatgpt's
            # 0.616), that grounding is enforced in code rather than requested in the
            # prompt, and that a change suppressed as UNCORROBORATED is never
            # reasoned about.
            "tests/test_due_diligence_questions.py",
        ],
    ),
    (
        "price_spike_quarantine",
        [
            # A previous one-sided detector ate real history. Six of seven jumps over
            # 50% are reverse splits in micro-caps (NXTT 0.0616 -> 6.42, then 5.88-7.95
            # all week) and a reverting spike is an ordinary micro-cap pump with
            # exactly the SHAPE of corruption. Only a second source disagreeing ON THE
            # SAME DATE convicts. Pins that corroboration is keyed on (symbol, date) —
            # keyed on symbol alone this reported CONTRADICTED=82 and would have
            # deleted 82 rows on a July-vs-September comparison; keyed correctly it is
            # 0 — and that a row is archived before it is deleted.
            "tests/test_quarantine_price_spikes.py",
        ],
    ),
    (
        "llm_escalation",
        [
            # Operator policy: free OAuth -> deepseek-flash -> ASK -> further paid.
            # Step 3 is a hard STOP. Pins that a gated lane is never entered
            # without an explicit re-run, and that a failed notification does not
            # become permission to spend.
            "tests/test_llm_escalation.py",
        ],
    ),
    (
        "inbound_identity_tagging",
        [
            # Tagging was one-way: research and news carried GUIDs, the inbound
            # path carried nothing and stored nothing. Pins that a ticker
            # resolves, that a company NAME is recorded as a measured gap rather
            # than dropped, and that no model runs in the deterministic path.
            "tests/test_inbound_identity_tagger.py",
            # Company names come from the broker instrument feed, never a
            # hand-rolled map. A test fails if a symbol->name pair is hardcoded.
            "tests/test_company_name_index.py",
        ],
    ),
    (
        "generated_file_merge",
        [
            # 6 of 6 consecutive merges conflicted on the same five generated
            # files. Runs REAL git merges in a temp repo: the conflict exists
            # without the driver, the driver resolves it, and a genuine code
            # conflict still stops the merge.
            "tests/test_generated_file_merge_driver.py",
        ],
    ),
    (
        "identity_custodian",
        [
            # Nothing watched the GUID spine at all until 2026-09-06. Pins that
            # the custodian stays deterministic (no model, no network), that its
            # freshness grace survives a weekend, and that a commented cron does
            # not count as scheduled.
            "tests/test_identity_health.py",
        ],
    ),
    (
        "deterministic_integrity",
        [
            # The daily sweep. Run cold against main it rediscovered every defect
            # a full session found by hand, plus db_retention unscheduled. Pins
            # that it never repairs, that a commented cron is not scheduled, and
            # that populations aggregate instead of emitting 309 alarms.
            "tests/test_deterministic_integrity.py",
            # The sweep's own alarm, OBSERVED firing. test_alarm_coverage caught
            # this missing on 2026-09-06: a new send_telegram site with no firing
            # test, in the session that documented the rule.
            "tests/test_integrity_sweep_alarm_fires.py",
            # The one place a model touches identity: proposes CANDIDATE, never
            # commits, never mints a GUID, free lanes only.
            "tests/test_identity_resolution_advisor.py",
        ],
    ),
    (
        "librarian_dedup_ttl",
        [
            # Three research_backlog rows from 2026-06-02 muted two of four
            # detectors for 96 days, which is why hermes_advisory_events took its
            # last write on 2026-07-14 while 108,102 catalysts matched. Pins that
            # every dedup COUNT is time-bounded.
            "tests/test_librarian_dedup_ttl.py",
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
            # AGENTS.md 1.3.0 (ratified 2026-09-27): execution engineering needs a per-task grant, and
            # the broker-boundary verifier must refuse every out-of-envelope mutation.
            "tests/test_agents_policy_1_3_0_amendment.py",
            # AGENTS.md 3.0.0 (ACTIVE 2026-10-09): §23 Agent nodes, parity, preconditions checklist.
            "tests/test_agents_policy_3_0_0_amendment.py",
            # AGENTS.md 4.1.0 (PROPOSED 2026-10-09): registry dispatch, wave ladder, program push budget, 48 h merge approval.
            "tests/test_agents_policy_4_1_0_amendment.py",
            "tests/test_trading_session_grant_20260925.py",
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
            # Design toggles, and the fault signals the loader refuses to make
            # configurable — the exemption is the thing under test.
            "tests/test_design_features.py",
        ],
    ),
    (
        # Provider capacity is what the provider said; the ceiling is what we
        # chose. brave_search.py asserted a 1,000/month Brave plan nobody had
        # measured while discarding the X-RateLimit headers that would have
        # settled it.
        "research_provider_truth",
        [
            "tests/test_research_provider_truth.py",
        ],
    ),
    (
        # 2026-09-15: 573 refresh jobs sat QUEUED since 09-13 with no worker; 513 packet inserts failed on NaN json.
        "watch_refresh_queue_drain",
        [
            "tests/test_watch_refresh_queue_drain_20260915.py",
        ],
    ),
    (
        # The overnight lane's schedule (22:00-05:35 ET) and its DeepSeek peak
        # guard (10:00-21:00 ET) never overlapped, so it had never once run.
        "overnight_deep_peak_guard",
        [
            "tests/test_overnight_deep_peak_guard.py",
        ],
    ),
    (
        # Every SearXNG engine in the pool was verified by query before being
        # listed. The pool had six declared engines and one that worked; google
        # failed SILENTLY (0 results, no error) and read as healthy.
        "searxng_engine_pool",
        [
            "tests/test_searxng_engine_pool.py",
        ],
    ),
    (
        # Two always-on health findings that were never about the system: an
        # expected-release pin nothing ever wrote, and a validator whose only
        # caller passed an argument it did not accept.
        "release_pin_and_validator",
        [
            "tests/test_release_pin_and_validator.py",
            "tests/test_aec_agent_bus_memory_20260919.py",
            "tests/test_aec_narrator_20260919.py",
            "tests/test_aec_narrator_real_brief_20261007.py",
            "tests/test_bitemporal_correctness.py",
            # M5 Module 2: SINGLE_VALUED supersession, atomic receipts, MRU token budget.
            "tests/test_m5_memory_substrate_20260923.py",
            "tests/test_memory_agent_least_privilege_20260924.py",
            "tests/test_memory_prod_cutover_20260924.py",
            "tests/test_record_bridge_pin_soak.py",
            "tests/test_agent_number_grounding_slo_20260918.py",
            "tests/test_agent_number_grounding_derivations_20260930.py",
            "tests/test_research_quality_escalate_20260918.py",
            # Main landed these without gating — coverage gate treated them as NEW.
            "tests/test_agent_router_trade_write_gate_20260918.py",
            "tests/test_cio_wake_jobs_corrupt_tail_20260918.py",
            "tests/test_maturity_oauth_envelope_20260918.py",
            "tests/test_phase1_pi_untrusted_20260918.py",
            "tests/test_postgres_main_health.py",
            "tests/test_prod_ready_final4_20260918.py",
            "tests/test_weekly_disk_cleanup_notify_20260918.py",
            "tests/test_alarm_fires_disk_and_handler_20260919.py",
            "tests/test_cio_telegram_stance_gate_20260918.py",
        ],
    ),
    (
        # The Communications ledger must not report a delivery that did not
        # happen. Two adjacent rows both read LEGACY_DELIVERED: one arrived,
        # one was router-suppressed and never did.
        "comms_ledger_truth",
        [
            "tests/test_comms_ledger_says_what_happened.py",
            # 2026-09-14: repeated alerts collided with the first event ever sent.
            "tests/test_comms_repeat_alerts_20260914.py",
        ],
    ),
    (
        # Durable data directories must survive a promote. data/audit held a
        # 39KB receipt written the same day and was a real dir inside the
        # release, so every deploy discarded it and the lane read SILENT.
        "deploy_durable_dirs",
        [
            "tests/test_deploy_durable_dirs.py",
        ],
    ),
    (
        # 2026-09-15: watch-tier pullback proposals expired in the pass that created them, and the watchlist
        # bridge created proposals the enrichment loop expired minutes later (>15% from live).
        "watchlist_proposal_churn",
        [
            "tests/test_pullback_reconcile_tiers_20260915.py",
            "tests/test_watchlist_bridge_entry_drift_20260915.py",
        ],
    ),
    (
        # 2026-09-15 architect remediation: ledger test isolation + pinned fork (R-01), retired-provider
        # health (R-02), research discovery refresh (R-02), health headline (E-03).
        "architect_remediation_20260915",
        [
            "tests/test_audit_ledger_isolation_forks_20260915.py",
            "tests/test_retired_provider_health_20260915.py",
            "tests/test_research_discovery_refresh_20260915.py",
            "tests/test_health_headline_20260915.py",
            "tests/test_rag_borrowed_conn_txn_20260915.py",
            "tests/test_offpeak_drain_lock_wait_20260915.py",
            "tests/test_opportunity_queue_drained_state_20260915.py",
            "tests/test_research_lane_state_recovery_20260915.py",
            "tests/test_health_decision_store_integrity_20260915.py",
            "tests/test_watchlist_bridge_recreate_cooldown_20260915.py",
            "tests/test_system_health_retired_component_20260915.py",
            "tests/test_system_health_agent_conn_and_retired_20261007.py",
            "tests/test_persistent_state_root_import_20261008.py",
            "tests/test_scheduled_wrappers_resolve_own_tree_20261007.py",
            "tests/test_units_execute_served_tree_20261008.py",
            "tests/test_expected_services_lane_states_20261008.py",
            "tests/test_health_agent_retry_disarmed_20261008.py",
            "tests/test_agent_auto_queue_valid_symbols_20260915.py",
        ],
    ),
    (
        # 2026-09-15: hermes_subject_enhance and the directive service sat idle in transaction holding row
        # locks; the directive service and Finviz screener writes failed on lock timeouts.
        "watch_lock_holders",
        [
            "tests/test_watch_lock_holders_20260915.py",
            "tests/test_watch_idle_txn_20260924.py",
            "tests/test_watch_review_automation.py",
        ],
    ),
    (
        # 2026-09-15: every active strategy card had catalyst_summary NULL; catalyst_symbol_impact had 0 rows ever.
        "watch_card_catalysts",
        [
            "tests/test_strategy_card_catalysts_20260915.py",
            "tests/test_catalyst_symbol_impact_writer_20260915.py",
        ],
    ),
    (
        # 2026-09-15 operator decision: small caps are in scope and labeled, not quarantined by the $500M floor.
        "watch_small_cap_labels",
        [
            "tests/test_watch_small_cap_labels_20260915.py",
        ],
    ),
    (
        # 2026-09-15: capped / circuit-open / input-limit agent jobs were marked failed and never retried.
        "watchlist_agent_job_llm_retries",
        [
            "tests/test_watchlist_agent_job_llm_retries_20260915.py",
        ],
    ),
    (
        # 2026-09-15 operator: goods tracked consistently across the watchlist and proposals.
        "watch_goods_consistency",
        [
            "tests/test_watch_goods_consistency_20260915.py",
        ],
    ),
    (
        # 2026-09-15: the incubator promoter proposed flat 2R geometry that the gate refused; nothing promoted since 07-01.
        "incubator_promoter_authoritative_levels",
        [
            "tests/test_incubator_promoter_authoritative_levels_20260915.py",
        ],
    ),
    (
        # 2026-09-15 operator decisions: CIO owns entry state / BUY, operator and CIO alerted, small caps labeled.
        "cio_entry_state",
        [
            "tests/test_cio_entry_state_20260915.py",
            "tests/test_cio_entry_state_alarm_fires_20260915.py",
            # 2026-09-24 operator "build options": BUY_READY packet = per-unit options
            # alternatives + portfolio facts + validated CIO review; wake subject bound.
            "tests/test_buy_ready_options_20260924.py",
        ],
    ),
    (
        # 2026-09-15 operator: material-change notices said a name moved but not which way, quoted web-page
        # titles as catalysts and gave no watchlist origin, strategy, plan or CIO view.
        "material_change_notice_context",
        [
            "tests/test_material_change_notice_context_20260915.py",
            # 2026-09-21 operator: "plan is stale" was emitted for a plan 93% of the way
            # to its target AND for one 31% through its stop — abs() erased the sign.
            "tests/test_plan_state_not_stale_20260921.py",
            # 2026-09-24 maturity review: page only held names / fresh CIO BUY_READY, one daily
            # digest, one reconciled CIO verdict, editor holds are not deliveries.
            "tests/test_material_change_alert_v2_20260924.py",
            "tests/test_material_change_sql_placeholders_20260915.py",
            "tests/test_maturity_runtime_evidence_per_agent_20260915.py",
            "tests/test_material_change_notice_position_20260915.py",
            "tests/test_producer_cursor_holds_on_capacity_drop_20260915.py",
            "tests/test_agent_runtime_lease_rebuild_20260915.py",
            "tests/test_agent_stale_window_exceeds_lease_interval_20260915.py",
        ],
    ),
    (
        # 2026-09-15 cron hygiene: dead-script check resolves like cron (cd dir, absolute paths).
        "cron_hygiene_20260915",
        [
            "tests/test_check_cron_sanity_resolves_like_cron_20260915.py",
        ],
    ),
    (
        # 2026-09-15 remediation follow-ups: CIO desk delivery receipt, daily LLM spend cap proven (E-10).
        "remediation_followups_20260915",
        [
            "tests/test_health_llm_spend_receipt_20260915.py",
            "tests/test_telegram_enable_flag_values_20260915.py",
        ],
    ),
    (
        # 2026-09-15: agent maturity status legal for the DB constraint; drain loads the host LLM cap file.
        "agent_maturity_status_and_drain_cap_20260915",
        [
            "tests/test_agent_maturity_status_and_drain_cap_20260915.py",
        ],
    ),
    (
        # 2026-09-14: promote left the dev tree, where cron and the units run, on the old commit, and a
        # refused fast-forward was reported as success.
        "deploy_ff_dev_tree",
        [
            "tests/test_ff_dev_tree_20260914.py",
        ],
    ),
    (
        # An uninitialised inbound checkpoint returned 0, so replay-denial could
        # never say no — on a path carrying approve/reject callbacks.
        "inbound_checkpoint_seed",
        [
            "tests/test_inbound_checkpoint_seed.py",
        ],
    ),
    (
        # If one LLM lane fails the next must be tried, and the substitution
        # said out loud. chatgpt failed 11/11 on 2026-09-05 while grok was
        # healthy and never asked, because generate() takes one lane.
        "llm_fallback",
        [
            "tests/test_llm_fallback.py",
        ],
    ),
    (
        # A weekday-only freshness check must not page for the weekend. Second
        # fix in the same gate: G1 asked whether TODAY was Saturday; this one
        # counted calendar weekday hours instead of hours the writer could run.
        "freshness_weekend_gate",
        [
            "tests/test_freshness_weekend_gate.py",
        ],
    ),
    (
        # A curated alert must be more useful than the JSON and never less true.
        # The alert that prompted this had a `Fix:` section restating its own
        # trigger, and showed 2 of 6 firing lanes.
        "alert_curation",
        [
            "tests/test_alert_curation.py",
        ],
    ),
    (
        # Phase 5 release discipline. READY must be earned by every item; absent
        # evidence blocks rather than abstains. A closeout that reads green
        # because nobody looked is worse than none, because it ends the looking.
        "campaign_closeout",
        [
            "tests/test_campaign_closeout.py",
        ],
    ),
    (
        # Remote (Telegram) operator approval for guard scopes. The operator
        # types APPROVE on their phone; the agent never does. Every refusal path
        # is pinned here because the refusals are what make it safe.
        "guard_remote_approval",
        [
            "tests/test_guard_remote_approval.py",
        ],
    ),
    (
        # 2026-07-28 /v3 blank-page reload loop. This file was named test_*.py,
        # lived in tests/, defined no test function, and was listed in no gate —
        # so its eleven assertions ran only when someone typed the path.
        "cc_v3_boot_no_reload_loop",
        [
            "tests/test_cc_v3_boot_no_reload_loop.py",
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
            "tests/test_comms_agent_contracts_wave_e.py",
            "tests/test_comms_artifact_curation.py",
            "tests/test_comms_channel_adapters.py",
            "tests/test_comms_communication_event.py",
            "tests/test_comms_curation.py",
            "tests/test_comms_delivery_ledger.py",
            "tests/test_comms_enforcement_gate.py",
            "tests/test_comms_inbound.py",
            "tests/test_comms_librarian.py",
            "tests/test_comms_librarian_purge_receipt.py",
            "tests/test_comms_shadow_compare.py",
            "tests/test_comms_subject_memory.py",
            "tests/test_comms_telegram_canary_active.py",
            "tests/test_comms_vocabulary.py",
            "tests/test_communications_portal.py",
            "tests/test_provider_chokepoint_ratchet.py",
            "tests/test_telegram_alert_rich_send.py",
        ],
    ),
    (
        # tip hygiene: disk/docs/librarian enforcers (2026-09-10 fill incident)
        "tip_hygiene_enforcers",
        [
            "tests/test_backup_enforcer.py",
            "tests/test_disk_hygiene_enforcer.py",
            "tests/test_docs_tip_hygiene_enforcer.py",
            "tests/test_hermes_librarian_retention_runner.py",
        ],
    ),
    (
        # 2026-09-16 P6 — tiered validation, blocking, non-self-certifying.
        # Measured before this gate existed: independent_critic 31/31 accept with zero
        # disagreements, agent_view_v1.critic_pass 346/346 True with critique_id None,
        # research_quality 608 completions with zero FAILED, StructuralGoldenJudge
        # returning literals on most of its rubric, cloud_consensus_verdict matching 0
        # candidates in 16 runs a day. Four validators, none of which had ever contested
        # anything, all reported as working — and CriticPanel, which is written correctly,
        # had no production caller at all.
        #
        # These pin the four anti-blindness mechanisms and the third independence edge:
        # a validator that passes a seeded known-bad is BLIND and its window is voided;
        # zero disagreements at n>=30 is UNCALIBRATED; a constant score axis is not a
        # measurement; PASS/REJECT survives as a DISAGREEMENT rather than being voted
        # away; tier 2 spends nothing without the operator (§17); and reviewer != scorer
        # is enforced in the contract AND against the durable rows.
        "tiered_validation_20260916",
        [
            "tests/test_validator_calibration_20260916.py",
            "tests/test_tiered_validation_20260916.py",
            # 2026-09-17 — the tranche's fourth entrypoint was never armed. The
            # :35 gate-measurement bridge, the :40 goal-pilot material-change
            # runner and the :50 dormant-lane consumer all got crontab lines on
            # 2026-09-16; the tiered-validation gate got a SCHEDULED_ENTRYPOINT
            # reading "PROPOSAL ONLY -- not installed". That was true, and it was
            # also why nothing counted it: check_dark_contracts.py skips any module
            # holding that constant whatever it says, so the one module in the
            # tranche with no caller at all passed the gate written to find modules
            # with no caller. The constant is gone and the gate now runs hourly
            # inside the already-armed dormant-lane consumer -- no new cron entry,
            # which is operator-only (AGENTS.md §17). This pins the wire, the
            # anti-rot check on the declaration, and that the lane stays $0 even
            # with TRADEAI_TIER2_PAID_JUDGE set in the host environment.
            #
            # That module is deliberately NOT spelled out here. check_dark_contracts
            # counts a bare token as a consumer, comments included, so naming it in
            # this file would hold the gate green from a comment and the wiring
            # would stop being the thing that holds it up. Verified 2026-09-17:
            # with the lane's import broken the gate reports it NEW, and it only
            # started doing so once this comment stopped naming it.
            "tests/test_tiered_validation_wiring.py",
        ],
    ),
    (
        # P9/P10 (2026-09-16) — gate honesty and archive-or-wire.
        #
        # P9: six maturity gates were hardcoded literals justified by prose
        # comments rather than rows in a store, and independent_review_coverage
        # reused the SCORE count, so the board read 8/12 passing with
        # gates_not_measured: 0 for an agent that had measured almost nothing.
        # These gates fail closed now: a gate with no store reads
        # NOT_YET_MEASURED and can never pass.
        #
        # P10: the subject-collapse law (one research decision per subject per
        # day, cap 5) was a transitive dark chain — both its importers declare
        # NO_CONSUMER_REASON — so it was enforced nowhere in the live path. It
        # is now applied in the */5 dispatcher, and the archive batch is a
        # proposal that must stay unapplied.
        "gate_honesty_and_archive_or_wire",
        [
            "tests/test_gate_honesty_p9.py",
            "tests/test_research_budget_live_wire_p10.py",
            "tests/test_dormant_lane_wiring_p10.py",
            "tests/test_archive_manifest_proposal_p10.py",
        ],
    ),
    (
        # 2026-09-22 P6 — two gates that were green for the wrong reason.
        #
        # reviewer != scorer was enforced from the SCORING side only, and only in
        # one insertion order: record_score asked the durable agent_reviews rows
        # whether the scorer had already reviewed, while nothing asked agent_scores
        # whether the reviewer had already scored. Score-then-review by one agent
        # was accepted; review-then-score by the same agent was refused. Review
        # also carried no scorer_agent_id, so the contract answered the same
        # question differently depending on which record the caller built. Both
        # sides and both orders are pinned now.
        #
        # The alarm batch is the other half: ten send_telegram sites that were
        # lines in config/alarm_firing_baseline.txt — named, counted, unproven —
        # are now driven to the transport and REMOVED from that file. The ratchet
        # number moved because the alarms were tested, not because the baseline
        # absorbed them, which is the only direction that file may move.
        "gate_honesty_p6_20260922",
        [
            "tests/test_independence_reviewer_scorer_20260922.py",
            "tests/test_alarm_fires_batch6_20260922.py",
        ],
    ),
    (
        # 2026-09-22 P6 — ten suites promoted out of UNLISTED_BASELINE.
        #
        # Measured before this entry: 1,461 test files, 506 run by CI (34.6%), with
        # 949 files sitting in check_test_coverage.UNLISTED_BASELINE as inherited
        # debt. That baseline makes the gap visible and may only shrink; these ten
        # shrink it. Each was run on 2026-09-22 and passes hermetically in under a
        # second with no database, network or broker — chosen for that reason, so
        # registering them adds real coverage without adding a flaky gate that
        # someone would later disable.
        "agent_runtime_suites_promoted_20260922",
        [
            "tests/test_agent_context_envelope.py",
            "tests/test_agent_decision_payload.py",
            "tests/test_agent_replay_harness.py",
            "tests/test_agent_run_trace.py",
            "tests/test_agent_runtime_critics.py",
            "tests/test_agent_runtime_deadlines.py",
            "tests/test_agent_runtime_instrumentation.py",
            "tests/test_agent_runtime_knowledge.py",
            "tests/test_agent_runtime_migration_contract.py",
            "tests/test_agent_runtime_missing_modules.py",
        ],
    ),
    (
        # 2026-09-22 — the four `send_telegram_document` alarms, observed firing.
        #
        # send_telegram_document entered alarm_firing_coverage.TRANSPORT earlier
        # the same day by operator decision (sites_total 188 -> 192). That made
        # four alarm call sites COUNTED for the first time on any branch — and all
        # four were untested, so they became four lines of named debt in
        # config/alarm_firing_baseline.txt. This gate is the receipt for paying
        # them: all four files are REMOVED from that file because every transport
        # site in each of them is now driven to the transport, documents included.
        #
        # test_alarm_coverage.py rides with it deliberately. The firing test and
        # the ratchet that reads its COVERS list must move together: the COVERS
        # list is parsed with `ast` and accepts only literal strings, so a
        # comprehension there reads as ZERO coverage while the firing test stays
        # green. Running both in one gate means the baseline and the tests cannot
        # disagree without something going red.
        "alarm_document_sites_20260922",
        [
            "tests/test_alarm_fires_documents_20260922.py",
            "tests/test_alarm_coverage.py",
        ],
    ),
    (
        # 2026-09-25 — agentic-memory tranche 2 (D2 Slices 4 + 6). Slice 4: the
        # daily memory shadow measure gains cross_agent_memory_agreement — do
        # CIO / Hermes / Advisory read the same durable memory ids for one
        # subject in one window (G8), reported honestly incl. UNAVAILABLE.
        # Slice 6: options outcomes join the identity spine (contract identity
        # from the OCC symbol at record time; settled paper outcomes feed the
        # scoped options envelope and the belief writer). The two shadow-measure
        # suites leave UNLISTED_BASELINE and run here.
        "agentic_memory_tranche2_20260925",
        [
            "tests/test_options_manual_close_identity_20260925.py",
            "tests/test_cross_agent_memory_agreement_20260925.py",
            "tests/test_agent_memory_shadow_measure.py",
            "tests/test_memory_shadow_measure_honesty.py",
            "tests/test_options_pipeline_validation.py",
            # Live Schwab Options Desk Stage A–E + Alpaca retirement (2026-09-25).
            "tests/test_live_schwab_options_desk_stage_abc.py",
            # Credit-spread R:R floor — refuse $66 vs $1,184 Ideas (2026-09-25).
            "tests/test_options_credit_spread_rr_floor_20260925.py",
            # Stock-versus-options comparison contract (2026-09-25).
            "tests/test_recommendation_comparison_20260925.py",
            "tests/test_options_decision_stages_20260925.py",
            "tests/test_options_universe_census_20260925.py",
            "tests/test_options_research_universe_v2.py",
            "tests/test_options_desk_complete.py",
            "tests/test_options_full_chain.py",
        ],
    ),
    (
        # 2026-09-24 — agentic-memory tranche 1 (docs/agentic-memory-gap D2).
        # Slice 1: outcome checkpoints bind a registry subject + subject_key and a
        # real due_at at mint; legacy null-due event-relative rows project to
        # created_at+30d; one InstrumentRecord store path. Slice 2 adds the
        # belief block + mutation test to this same gate.
        "instrument_belief_20260925",
        [
            "tests/test_checkpoint_subject_binding_20260925.py",
            "tests/test_outcome_settlement_20260930.py",
            "tests/test_outcome_resolution.py",
            "tests/test_cio_instrument_record.py",
            # Slice 2: beliefs on the record (rail + writer) and the mutation
            # test: with vs without a belief, the gate route / next question and
            # the wake commitment differ; no behaviour key anywhere in either.
            "tests/test_instrument_belief_mutation_20260925.py",
            "tests/test_wake_subject_selector.py",
            "tests/test_decide_consults_wake_hits.py",
        ],
    ),
    (
        # 2026-09-24 — agentic-memory acceleration Slice A+B.
        # option_strategy_guid + contract_guid on desk proposals; scoped
        # MEMORY_BEHAVIOR_INFLUENCE_OPTIONS envelope (global MBI stays 0).
        "options_identity_memory_20260924",
        [
            "tests/test_options_identity_memory_20260924.py",
            "tests/test_agent_feature_flags.py",
        ],
    ),
    (
        # 2026-09-25 — SCHD decision integrity. One DecisionIntegrity@v1 result
        # before an actionable-looking plan reaches Telegram/CIO/Watch/ticket/
        # alert: price at/below stop suppresses mechanics and relabels the plan
        # historical; exact quote age; operator-quoted price reconciled; every
        # held account named; house 30d hold ≠ wash-sale; alert truth. Plus the
        # release-grant binding (a grant authorizes only the release it names),
        # the worker pin check, the watch-alert quote-freshness guard and the
        # case recorder (dry run by default).
        "schd_decision_integrity_20260925",
        [
            "tests/test_decision_integrity_schd_20260925.py",
            "tests/test_release_grant_binding_20260925.py",
            "tests/test_worker_pin_and_alert_freshness_20260925.py",
            "tests/test_cio_entry_state_20260915.py",
            "tests/test_operator_answers_use_house_facts_20260913.py",
        ],
    ),
    (
        # 2026-09-26 — P1 audit remediation: cron/unit linters that reproduce the
        # live scheduler defects (relative .venv inside a release that ships
        # none; two schedules of a broker-touching script under different
        # locks; relative path with no cd; python -c quoting) and the unit
        # EnvironmentFile linter (silently skipped missing env files).
        "p1_cron_unit_linters_20260926",
        [
            "tests/test_p1_cron_unit_linters_20260926.py",
            "tests/test_check_cron_sanity_hardened.py",
            "tests/test_check_cron_sanity_resolves_like_cron_20260915.py",
        ],
    ),
    (
        # 2026-09-26 — P2 audit remediation: alarms that see the truth. Health
        # agent reads a cron-written crontab snapshot when `crontab -l` is denied
        # (R-03); FK-safe catalyst purge + failure-streak circuit breaker (R-04);
        # ACTIVE_RELEASE written on promote (R-09); remediations skip PAUSED/
        # RETIRED lanes (R-15); stop-band recheck alerts DELIVERED, not just
        # stored (C-11).
        "p2_alarms_truth_20260926",
        [
            "tests/test_p2_alarms_truth_20260926.py",
            "tests/test_news_symbol_guard.py",
            "tests/test_p1_cron_unit_linters_20260926.py",
        ],
    ),
    (
        # 2026-09-26 — P2 audit remediation: cron hygiene CLI replacing the
        # quoting-bug one-liners (R-10); grant USE consumption on release
        # preflight and pre-push (C-10, the ledger under-counted every Claude
        # Code push/promote); MariaDeskExchange@v1 receipt so a desk answer that
        # reaches the operator via OpenClaw leaves a durable row (C-05).
        "p2_hygiene_guard_lineage_20260926",
        ["tests/test_p2_hygiene_guard_lineage_20260926.py"],
    ),
    (
        # 2026-09-26 — P2 audit remediation: the cadence reports fail LOUDLY.
        # Weekly (NoneType format) and monthly (undefined total_val) had failed
        # on every run for months while the launcher said "skipped (non-fatal)"
        # and the pipeline recorded status=ok.
        "p2_report_honesty_20260926",
        ["tests/test_p2_report_honesty_20260926.py"],
    ),
    (
        # 2026-09-26 — P2 audit remediation R-06/K-07: declared controls must exist.
        # The Tier-2 daily cap / off-peak / provider flags are read and enforced
        # fail-closed by TierPolicy; RISK_GATE_H4_ENABLED warns that H4 is not
        # built instead of being silently ignored; check_env_flags_unread lists
        # every env name set on a governed surface and read by no code.
        "p2_controls_truth_20260926",
        ["tests/test_p2_controls_truth_20260926.py"],
    ),
    (
        # 2026-09-25 — CIO cognition tranche 3: prompt event-driven cognition on
        # the existing bus/wake-store/dispatcher lane (cursor lands on the
        # newest handled event, singular `symbol` subjects, priority-FIFO
        # dispatch, dead-letter after 3 lease recoveries, stale IN_FLIGHT
        # expiry, legacy action-ledger rows), the research→advice→feedback→
        # outcome→belief→judgment joins (record tips not history, goal binding
        # and due advance, honest goal close, judgment-aware decide, consumer
        # memory receipts), and the M1–M5 verifier gated on the served SHA.
        "cio_cognition_t3_20260925",
        [
            "tests/test_cio_event_path_t3_20260925.py",
            "tests/test_cio_cognition_chain_t3_20260925.py",
            "tests/test_report_maturity_bar_m1_m5_20260919.py",
            "tests/test_cio_goals_and_dispatcher.py",
            "tests/test_cio_goals_and_reactive.py",
            "tests/test_cio_action_ledger.py",
        ],
    ),
    (
        # 2026-09-25 -- CI speed + evidence redesign: no new live-host paths in tests
        # (a test reading /home/johnclaw/trade-ai-releases broke #1234 on a deploy).
        "test_host_paths_ratchet_20260925",
        [
            "tests/test_check_test_host_paths_20260925.py",
            "tests/test_cio_ci_profiles_20260925.py",
            "tests/test_ci_pr_selection_20260925.py",
            # 2026-10-09 -- sharded full suite (plan complete/disjoint/balanced, ci-gate
            # completeness) + tree-attested promote with a fake gh/git layer (flag off by default).
            "tests/test_ci_shards_tree_attest_20261009.py",
        ],
    ),
    (
        # 2026-09-26 -- CIO Desk: material actions only, one readable message, once per window.
        "cio_action_notify_20260926",
        ["tests/test_cio_action_notify_20260926.py", "tests/test_cio_checkin_only_with_action_20260914.py"],
    ),
    (
        # 2026-09-26 -- "everything BLOCKED": income ideas screened before a card is built,
        # Aegis worker heartbeat + stall alarm, Watch refresh workers outside the scheduler cgroup.
        "everything_blocked_20260926",
        [
            "tests/test_everything_blocked_20260926.py",
        ],
    ),
    (
        # 2026-09-26 -- options carry the same thesis bar as a stock purchase: pinned symbol
        # thesis, OptionsThesisRecord by strategy GUID (append-only, hash-chained), queue refusal.
        "options_thesis_20260926",
        [
            "tests/test_options_thesis_20260926.py",
            "tests/test_options_thesis_lifecycle_20260926.py",
            "tests/test_options_identity_memory_20260924.py",
        ],
    ),
    (
        # 2026-09-27 -- contradiction candidates derived incrementally (only the new
        # delta's pairs; ids equal the full O(n^2) derivation, which took 31 s per accept).
        "contradiction_incremental_20260927",
        ["tests/test_contradiction_incremental_20260927.py", "tests/test_research_metadata_contradiction.py"],
    ),
    (
        # 2026-09-27 -- symbol-thesis acquisition runs after the operator clears
        # P0 containment (archive tripwire); a flag missing without a clear still
        # fails closed. It had exited 78 every day since 09-16.
        "thesis_acquisition_containment_20260927",
        ["tests/test_thesis_acquisition_containment_20260927.py"],
    ),
    (
        # 2026-09-27 -- the Hermes external lane breaker also trips on 'unavailable'
        # (ChatGPT CODEX_HEADLESS), not only HTTP 401/403.
        "lane_breaker_unavailable_20260927",
        ["tests/test_lane_breaker_unavailable_20260927.py"],
    ),
    (
        # 2026-09-27 -- local_llm_compat registered with a hard cap; the shim logs
        # refusals instead of silently returning "" to its 18 importers.
        "local_llm_compat_20260927",
        ["tests/test_local_llm_compat_registered_20260927.py"],
    ),
    (
        # 2026-09-27 -- symbol-news curation with an SLA: gap-driven approval of a
        # symbol's company news (topic_curator never reviewed it), priority
        # acquisition requests from the options CIO loop, SLA breach reporting.
        "symbol_news_curation_20260927",
        ["tests/test_symbol_news_curation_20260927.py", "tests/test_options_thesis_lifecycle_20260926.py"],
    ),
    (
        # 2026-09-27 -- news_articles has source_url, not url: the thesis evidence
        # gate never counted approved news for any symbol (since 2026-08-19).
        "news_url_column_20260927",
        ["tests/test_news_url_column_20260927.py"],
    ),
    (
        # 2026-09-27 -- thesis evidence excludes the house's own conclusions
        # (cio_decision etc.) and rows that do not name the symbol/company.
        "thesis_evidence_not_circular_20260927",
        ["tests/test_thesis_evidence_not_circular_20260927.py"],
    ),
    (
        # 2026-09-27 -- closed-market quotes are not a liquidity verdict: ideas are kept
        # and labelled "awaiting live quotes" instead of dropped as NO_LIQUID_CONTRACT.
        "weekend_aware_liquidity_20260927",
        ["tests/test_weekend_aware_liquidity_20260927.py"],
    ),
    (
        # 2026-09-27 -- fundamentals F1/F2/F4: SEC company facts -> sec_xbrl (quarter vs
        # YTD, restatements, like-for-like YoY), PRIMARY_REGULATORY thesis evidence,
        # fundamentals freshness SLA in the curation monitor.
        "fundamentals_feed_20260927",
        [
            "tests/test_fundamentals_feed_20260927.py",
            "tests/test_symbol_news_curation_20260927.py",
            "tests/test_fundamentals_f3_f5_20260927.py",
        ],
    ),
    (
        # 2026-09-27 -- options Wave A: honest expected P/L (not credit x POP), net cost if
        # assigned / cash committed / hedge floor, instrument classes and the leveraged-fund
        # policy, real not-approvable reasons, desk-side never-approvable guarantees, and
        # retirement of unanswerable thesis gaps.
        "options_economics_20260927",
        [
            "tests/test_options_economics_20260927.py",
            # SEC facts reach the thesis prompt; reworded gaps still retire (DELL v5).
            "tests/test_thesis_packet_sec_and_stance_retire_20260927.py",
        ],
    ),
    (
        # 2026-09-27 -- options Wave B: per-leg liquidity, combined same-symbol exposure,
        # policy blocks lead, EV withheld on non-tradeable quotes, "fully researched" needs a
        # stance, and same-symbol research is reused across strikes (DELL: 11 requests/26h).
        "options_wave_b_20260927",
        ["tests/test_options_wave_b_20260927.py"],
    ),
    (
        # 2026-09-27 -- Dell 8-K EX-99.1 primary evidence: the earnings-release exhibit is
        # fetched, parsed into dated dollar-figure facts (backlog, orders, guidance ...),
        # stored on (accession, exhibit), and reaches the thesis catalog / synthesis prompt
        # (with url + date) and the options CIO packet (with real per-leg liquidity,
        # fundamentals and the RPO-is-not-backlog note); web queries keep "AI" and ask sec.gov.
        "sec_filing_documents_20260927",
        [
            "tests/test_sec_filing_documents_20260927.py",
            # --since-days: one-off wider 8-K window (DELL Q1 FY27 release on 2026-05-28)
            "tests/test_sec_ingest_since_days_20260927.py",
        ],
    ),
    (
        # 2026-09-27 -- options fill truth (reviewer work order): credit spreads priced from an
        # explicit fill assumption (sell short at bid, buy long at ask; midpoint labelled, not a
        # fill; a non-credit is refused), both legs gated, hedged-put headline = floor not
        # premium, archived ideas out of combined exposure, blocked cards never POSITIVE,
        # "fully researched" needs research on file, leg quote timestamps.
        "options_fill_truth_20260927",
        ["tests/test_options_fill_truth_20260927.py"],
    ),
    (
        # 2026-09-27 -- broker-layer order gate proofs for the options desk (per-task
        # execution-engineering grant): 2FA, kill switch, submit-time re-check, leg pin (strict
        # xfail: spec_from_intent rebuilds from the cache), stale quote (strict xfail: missing
        # age passes when a data_source is named), LLM cannot unlock.
        "options_broker_gates_20260927",
        ["tests/test_options_broker_gates_20260927.py"],
    ),
    (
        # 2026-09-27 -- a failed options CIO review is retryable (attempt-suffixed job key),
        # the router's dedupe skip is classified, raw response heads are kept for diagnosis,
        # and failed attempts are capped (max_review_failures) and named on the card.
        "cio_review_retry_20260927",
        ["tests/test_cio_review_retry_20260927.py"],
    ),
    (
        # 2026-09-27 -- the options CIO packet supplies the spread ratios a reviewer derives
        # (loss:credit 2.15 refused the DELL MONITOR_ONLY review); the traceability rail is
        # unchanged and still refuses a number that is not in the facts.
        "cio_packet_derived_ratios_20260927",
        ["tests/test_cio_packet_derived_ratios_20260927.py"],
    ),
    (
        # 2026-09-27 -- options order-authorization contract (execution-engineering grant):
        # the order is built from the 2FA'd intent only, the evidence-bound approval is
        # created at confirm, freshness is recomputed from the intent's timestamps (absent
        # fails closed regardless of source), buying power is read and gated, and changed
        # legs / account / quantity / limit / proposal version after approval fail closed.
        "options_order_authorization_20260927",
        ["tests/test_options_order_authorization_20260927.py", "tests/test_options_broker_gates_20260927.py"],
    ),
    (
        # 2026-09-27 wave 3 -- researched-watchlist lane reads catalysts from catalyst_events and
        # logs a failing read; a rejected CIO review releases the lane's dedupe mark; a manual
        # lifecycle run takes the scheduler's lock; submit re-reads buying power.
        "wave3_lane_dedupe_lock_bp_20260927",
        ["tests/test_wave3_lane_dedupe_lock_bp_20260927.py"],
    ),
    (
        # 2026-09-27 -- Defense CC queue evaluates queue-time eligibility (mode live), the
        # fail-closed gates run at preflight/confirm; queue rows approved before the pin
        # existed are pinned to their stored proposal_json + reviewed_at.
        "options_queue_eligibility_legacy_pins_20260927",
        ["tests/test_options_queue_eligibility_legacy_pins_20260927.py"],
    ),
    (
        # 2026-09-27 -- Command Center redesign PR3: the metric guide (assets/ui_metric_guide.yaml,
        # GET /api/v2/ui/metric-guide, generated key union) and server-supplied insight lines
        # (scripts/lib/ui_insight.py) -- help text and takeaways are API-supplied (AGENTS 13).
        "ui_metric_guide_insight_20260927",
        ["tests/test_ui_metric_guide.py", "tests/test_ui_insight.py"],
    ),
    (
        # Reviewer 2026-09-28: a failed Schwab chain call must never look like an empty chain;
        # HTTP status typed before json(), error payloads typed, one expiration pinned, rows carry
        # two_sided/spread_pct so a one-sided quote is never called "Mid".
        "options_chain_truth_20260928",
        ["tests/test_option_chain_truth_20260928.py"],
    ),
    (
        # 2026-09-28: the Telegram BUY_READY / ENTRY_NEAR packets get one list endpoint and a lane on
        # the Re-Entry page: zone position, plan R:R vs R:R at quote (entry price stated), options
        # alternative outcome, and a desk disposition (proposal | not built: reason | not scanned).
        "reentry_entry_alerts_lane_20260928",
        ["tests/test_buy_ready_packets_index_20260928.py"],
    ),
    (
        # Failed acceptance 2026-09-28 (490735fba rolled back): the index served a pre-fix AXTI packet as
        # OPTIONS_ALT_OK / qualified 1 from the file's own flag. Verdicts now go through packet_view
        # (STALE_PRE_FIX) or fail closed (PACKET_UNVERIFIED); a unit counts only when current, known,
        # earnings-cleared and gate-stamped; the single-symbol handler is the live-proof hunk.
        "buy_ready_packet_verdict_20260928",
        ["tests/test_buy_ready_packet_verdict_20260928.py"],
    ),
    (
        # 2026-09-28: the lifecycle script self-deadlocked against the crontab's own flock
        # (57 skipped passes, every options thesis stuck at CREATED). An ancestor's lock is
        # inherited from /proc/self/fd, a foreign holder is still refused.
        "options_lifecycle_inherited_lock_20260928",
        ["tests/test_lifecycle_inherited_lock_20260928.py"],
    ),
    (
        # LIVEPROOF-20260928 (LP-DEF-01/02/04): AXTI 10:20 ET incident replay on a fixed clock — the
        # a328a8817 gate (verbatim fixture) qualified the MAPPED value "debit_spread"; the candidate
        # refuses it, fails closed on unknown event data / ids, serves the stored packet STALE_PRE_FIX
        # and recomputes cached pre-fix verdicts at preflight.
        "earnings_gate_replay_axti_20260928",
        ["tests/test_earnings_gate_replay_axti_20260928.py"],
    ),
    (
        # Reviewer 2026-09-28: combined same-symbol exposure includes the shares held (by account),
        # reports options-only / shares / whole-position P/L per row and groups rows by expiration;
        # the earnings gate blocks debit spreads and long puts and names its trigger.
        "options_exposure_earnings_20260928",
        ["tests/test_options_exposure_earnings_20260928.py"],
    ),
    (
        # 2026-09-27 -- protective puts / covered calls reconcile held shares and cost basis to
        # the holdings snapshot of record at preflight (fail closed on stale, missing, short,
        # changed); every CIO-packet yield names its denominator.
        "options_hedge_recon_yield_labels_20260927",
        ["tests/test_options_hedge_recon_yield_labels_20260927.py"],
    ),
    (
        # 2026-09-27 -- options order gates (operator work order, PR 3): the submit-mode risk
        # evaluator fails closed on an input the desk does not have (quote/chain age, session,
        # buying power, liquidity); approvals are pinned to the legs and expire; archived
        # ideas lose their approved row; preflight_desk_gate runs before any broker call.
        "options_order_gates_20260927",
        ["tests/test_options_order_gates_20260927.py"],
    ),
    (
        # 2026-09-26 -- options-gap CIO research reads the web first (SearXNG, then the
        # Brave router), answers cite supplied urls only, and CIO follow-ups are research
        # tasks (a symbol with no thesis also gets the four thesis questions).
        "hermes_web_research_20260926",
        [
            "tests/test_hermes_web_research_20260926.py",
            "tests/test_options_thesis_lifecycle_20260926.py",
            "tests/test_research_heartbeat_20260914.py",
        ],
    ),
    (
        # 2026-09-26 -- options history into the CIO's bitemporal memory (M2): thesis
        # versions, decisions (SUPERSEDES provenance), follow-ups, validations and
        # abandonments projected by event_hash with a payload allowlist; the CIO
        # options review reads prior decisions back (config memory_reads).
        "options_memory_20260926",
        [
            "tests/test_options_memory_projection_20260926.py",
            "tests/test_options_thesis_lifecycle_20260926.py",
            "tests/test_aec_agent_bus_memory_20260919.py",
        ],
    ),
    (
        # 2026-09-26 -- watchlist names read at-the-money IV from their Schwab chain
        # (technical_snapshot.json is holdings-only); one chain read per pass.
        "chain_iv_fallback_20260926",
        [
            "tests/test_chain_iv_fallback_20260926.py",
            "tests/test_options_holdings_funnel.py",
            "tests/test_cc_yield_scoring_20260926.py",
            "tests/test_truthful_cards_20260926.py",
            "tests/test_card_cleanup_20260926.py",
            "tests/test_calendar_catalyst_20260926.py",
            "tests/test_options_validate_20260926.py",
            "tests/test_option_spot_freshness_20260926.py",
            "tests/test_iv_history_depth_20260926.py",
        ],
    ),
    (
        # 2026-09-26 -- options research answers improve the SYMBOL thesis through the one
        # existing writer path: per-question answers mapped to invalidation / catalysts /
        # bear-case evidence, merged (never replaced) lists, authored summaries kept, and
        # the governed ENRICHES rule (fill empty fields only; cooldown in config).
        "symbol_thesis_enrich_20260926",
        [
            "tests/test_symbol_thesis_enrich_20260926.py",
            "tests/test_research_thesis_delta.py",
            "tests/test_symbol_thesis_integration.py",
            "tests/test_cio_product_reassessment.py",
        ],
    ),
    (
        # 2026-09-26 -- Drive sync: dated top-level docs files no longer purged + re-uploaded
        # hourly; config/strategies/_archive excluded by rule; redacted options runtime export
        # (no account names, no dollar amounts) mirrored under runtime/options/ and preserved.
        "drive_sync_options_export_20260926",
        [
            "tests/test_drive_sync_purge_20260926.py",
            "tests/test_options_runtime_export_20260926.py",
            "tests/test_options_runtime_export_url_digits_20261007.py",
        ],
    ),
    (
        # 2026-09-26 — WS-7 C-13. Hourly wakes were not consuming beliefs:
        # unconsumed_research carried no symbol (NO_SUBJECT), and the reserved
        # instrument_record_due slot stuck on the first-due record because
        # next_eligible_at never moved. Cadence is the record's own field;
        # a missing one is recorded and not invented. MBI_BEHAVIOR stays 0.
        "ws7_belief_wake_20260926",
        [
            "tests/test_ws7_belief_wake_20260926.py",
        ],
    ),
    (
        # 2026-09-26 WS-4 — six suites that sat outside CI while red or hanging.
        # Standing HOLD next_review is the demoted cadence (not a dated
        # catalyst); absent data_quality is partial, not INVALID. Advisory
        # enrich is hermetic (no live desk build). Alpaca Hub routes stay
        # 403. Spread fixture expiry stays in the future. Handoffs carry
        # parent_run_id. Not-installed declarations include the SLO report.
        "ci_honesty_ws4_20260926",
        [
            "tests/test_r18_2_production_hardening.py",
            "tests/test_advisory_desk_phase3.py",
            "tests/test_alpaca_paper_options_executor.py",
            "tests/test_dark_contract_guard.py",
            "tests/test_options_prime_rubric.py",
            "tests/test_p211_restart.py",
        ],
    ),
    (
        # 2026-09-27 — remaining audit phases that are safe to land.
        # Desk bot is a bound unit. Rollback restarts bound units and rewrites
        # the pin. The heartbeat backfill no longer appends legacy ledger rows.
        "audit_remaining_phases_20260927",
        ["tests/test_audit_remaining_phases_20260927.py"],
    ),
    (
        # 2026-09-27 — rest of the audit that does not delete routes or tables.
        # Route counts, jsonl head archived not deleted, SUPERSEDED headers
        # win over the path guess, update_docx generators tripwire-retired.
        "audit_rest_20260927",
        ["tests/test_audit_rest_20260927.py"],
    ),
    (
        # 2026-09-27 — wake store and scored tickers link to the live copies.
        # Migration report lists filenames only. v3_0–v3_2 and v2_0 are
        # superseded by v3_3.
        "audit_all_phases_20260927",
        ["tests/test_audit_all_phases_20260927.py"],
    ),
    (
        # 2026-09-27 — two uncalled state-changing ATM posts refuse.
        # Session validators move under scripts/archive with a tripwire stub.
        "audit_finish_20260927",
        ["tests/test_audit_finish_20260927.py"],
    ),
    (
        # 2026-09-28 — momentum-scalp proposal contract: the $3 momentum floor, the
        # analyst gate and the shared 5% spread ceiling discarded every scalp GO since
        # 2026-07-13; the strategy YAML now carries a paper-only proposal_contract.
        "momentum_scalp_proposal_contract_20260928",
        ["tests/test_momentum_scalp_proposal_contract_20260928.py"],
    ),
    (
        # 2026-09-28 — GO alerts carry delivery evidence (provider message id; accepted_no_id
        # is not "sent"; a held GO reports whether the CIO review was enqueued) and three
        # collectors own the scalp lane: GO→proposal conversion, underfilled streaks for
        # real reasons, social-inject failures.
        "go_alerts_and_lane_collectors_20260928",
        [
            "tests/test_go_alerts_and_lane_collectors_20260928.py",
            "tests/test_screener_go_alerts_delivery_20260914.py",
            "tests/test_cio_telegram_stance_gate_20260918.py",
        ],
    ),
    (
        # 2026-09-28 — execution truth: market_cap_usd beside the millions field; expired
        # proposals leave the blocked queue; a stale summary mirror is not a clock divergence;
        # a fund's cached NAV is not a degraded quote; extended-hours provider declared;
        # continuous runner derives its root (unit pinned to CURRENT).
        "execution_truth_20260928",
        [
            "tests/test_execution_truth_20260928.py",
            "tests/test_quote_selection_contract.py",
            "tests/test_portfolio_aggregate_contract.py",
        ],
    ),
    (
        # 2026-09-28 — pre-open window honesty: 0400/0700 run two screeners by design and
        # were labelled UNIVERSE_TOO_SMALL every day; per-window floors + PREOPEN_WINDOW_BY_DESIGN
        # (status/auto-proposal gate unchanged); unenriched injects → MANUAL_REVIEW, never scored.
        "preopen_window_honesty_20260928",
        ["tests/test_preopen_window_honesty_20260928.py"],
    ),
    (
        # 2026-09-28 — scanner social overlay was silently dead (_execute without fetch
        # returns True → 'bool' object is not iterable every live cycle) and source labels
        # were alphabetical (ai_discovered outranked screener); fixed + priority from config.
        "social_inject_source_priority_20260928",
        ["tests/test_social_inject_and_source_priority_20260928.py"],
    ),
    (
        # 2026-09-28 — momentum-scalp lane alarm: the lane log said PASS for ten days while
        # Finviz was never refreshed; the health agent now reads the refresh receipt
        # (missing / killed / stale / failed) and flags a lane that only ever skips refresh.
        "momentum_scalp_refresh_alarm_20260928",
        ["tests/test_momentum_scalp_refresh_alarm_20260928.py", "tests/test_momentum_scalp_source_health.py"],
    ),
    (
        # 2026-09-28 — momentum-scalp lane refresh: the */15 Finviz-refresh cron line was
        # killed silently every quarter-hour (timeout 150 < stage 240, shared lock) and the
        # lane had not refreshed since 09-18; the stage now clamps to an outer deadline,
        # writes STARTED/DONE receipts and the */5 line refreshes when the receipt is stale.
        "momentum_scalp_lane_refresh_20260928",
        ["tests/test_momentum_scalp_lane_refresh_20260928.py"],
    ),
    (
        # 2026-09-28 — lane registry: 107 host cron lines installed 09-27/28 with no lane
        # row broke check_lane_registry on main; recorded as a dated inherited tranche
        # with provenance (the original baseline is not grown) that the gate honours.
        "lane_registry_inherited_tranche_20260928",
        [
            "tests/test_lane_registry_inherited_tranche_20260928.py",
            "tests/test_alarm_fires_reminder_and_supervisor_20260928.py",
        ],
    ),
    (
        # 2026-09-28 — home book map. A zero day_change uses today's broker_day_pl.
        # Cash is reported beside the map and is not a tile. Unpriced rows stay
        # in the payload and are not drawn.
        "book_map_day_pl_20260928",
        ["tests/test_book_map_rows_20260928.py"],
    ),
    (
        # 2026-09-29 — options proposal cache: a non-force read outside REGULAR
        # serves the last snapshot at any age. The regular session still rebuilds
        # a snapshot older than 10 minutes. force=1 still rebuilds.
        "options_proposal_cache_cadence_20260929",
        ["tests/test_options_proposal_cache_cadence_20260929.py"],
    ),
    (
        # 2026-09-29 — cross-asset decision intelligence Phase 1: canonical
        # signal-to-expression contract and append-only shadow store.
        "cross_asset_decision_intelligence_phase1_20260929",
        ["tests/test_cross_asset_decision_intelligence.py"],
    ),
    (
        # 2026-09-30 — CIO Desk observability: executive health contract,
        # fail-closed status calculation, and remediation evidence projection.
        "cio_desk_observability_20260930",
        ["tests/test_cio_observability.py"],
    ),
    (
        # 2026-09-29 — READY ENTRY ALERT chrome must never resolve ENTRY/ALERT as
        # tickers (Telegram footers / Symbol Intelligence ALERT dossier).
        "alert_chrome_stopwords_20260929",
        ["tests/test_alert_chrome_stopwords_20260929.py"],
    ),
    (
        # 2026-09-29 — NFLX: thin llm_curation + Hermes queue must open a pending
        # so try_fulfill can deliver the completed thesis (not answered-only).
        "interim_plus_hermes_queue_20260929",
        ["tests/test_interim_plus_hermes_queue_20260929.py"],
    ),
    (
        # 2026-09-29 — an operator "watchlist and research" ask is monitored and
        # researched. Owed names sort first, keep a reserve outside the shared
        # external budget, and count as WATCH membership. The watchlist add
        # returns inside the client timeout while a slow enrich finishes.
        "operator_watch_research_20260929",
        ["tests/test_operator_watch_research_20260929.py"],
    ),
    (
        # 2026-09-29 — Cross-Asset Decision Intelligence Phase 1–3 scaffold:
        # SymbolDecisionObject, expression router, shadow hooks, missed ledger.
        "cross_asset_decision_intel_20260929",
        [
            "tests/test_cross_asset_symbol_decision_object_20260929.py",
            "tests/test_security_research_spine_20260929.py",
            "tests/test_cadi_spine_hooks_20260929.py",
            "tests/test_identity_carriage_20260929.py",
            "tests/test_identity_forward_ingestion_pivot_20260929.py",
            "tests/test_hermes_last_n_stamp_20260929.py",
            "tests/test_spine_multi_producer_lifecycle_20260929.py",
            "tests/test_spine_gaps_close_20260929.py",
        ],
    ),
    (
        # 2026-10-05 — portfolio-server shutdown record names the signal and exit
        # code (the journal line at 15:06 ET had neither). The ATM protection
        # pass releases its read transaction before apply()'s quote/HTTP work.
        "exit_cause_txn_scope_20261005",
        ["tests/test_exit_cause_txn_scope_20261005.py"],
    ),
    (
        # 2026-10-05 — the June maturity_score_latest.json must not be served as
        # current. Readers stamp STALE after 30 days and do not open the archive copy.
        "maturity_score_stale_20261005",
        ["tests/test_maturity_score_latest_stale_20261005.py"],
    ),
    (
        # 2026-10-05 — ATM approver must not reuse a cursor after its decision
        # commit, and must not hold the read transaction across submit HTTP.
        # The protection quote helper releases its own read before quote HTTP.
        "atm_cursor_txn_scope_20261005",
        ["tests/test_atm_cursor_txn_scope_20261005.py"],
    ),
    (
        # 2026-10-05 — an unanswered operator turn for its own subject is a wake
        # candidate even when research would fill the limit. Memory influence
        # stays off; the turn is not attached to a different subject.
        "wake_operator_turn_selection_20261005",
        ["tests/test_wake_operator_turn_selection_20261005.py"],
    ),
    (
        # Runtime convergence: denied observations, unregistered schedulers, lock skips,
        # shadow/live separation and release rebind coverage.
        "scheduler_operations",
        [
            "tests/test_scheduler_operations.py",
            "tests/test_n8n_release_rebind.py",
            "tests/test_scheduler_launcher_roots.py",
        ],
    ),
    (
        # 2026-10-08 — lane registry scheduler kind `n8n` (scheduler-of-record program):
        # validation, ledger/receipt-proven presence, the double-scheduler conflicts,
        # the per-line `_cutover.py --lane` cutover/rollback against a fake crontab, and
        # the per-lane readiness verdicts. Hermetic; no registry row is flipped here.
        "N8N_LANE_KIND",
        [
            "tests/test_lane_registry_n8n_kind_20261008.py",
            "tests/test_n8n_lane_cutover_20261008.py",
            "tests/test_n8n_lane_readiness_20261008.py",
        ],
    ),
    (
        # 2026-10-07 — n8n lab coordination is local code. These tests pin the
        # muted pilots, the receipt vocabulary, and the unenabled watchdog.
        # Listing them here does not enable a timer or promote the branch.
        "n8n_parallel_20261007",
        [
            "tests/test_approval_reminder_receipt_20261007.py",
            "tests/test_approval_reminder_reconcile_20261007.py",
            "tests/test_approval_reminder_reconcile_lane_20261007.py",
            "tests/test_llm_adr_model_id_20261007.py",
            "tests/test_n8n_model_job_20261007.py",
            "tests/test_n8n_model_job_operation_20261007.py",
            "tests/test_n8n_phase1_dispatch_20261007.py",
            "tests/test_notification_outbox_projection_20261008.py",
            "tests/test_approval_board_20261008.py",
            "tests/test_platform_maintenance_pipeline_20261007.py",
            # 2026-10-07 cron consolidation tranche C (low-risk): options tick, orchestrator
            # slot wrapper, drive syncs runner, hermes subject dispatcher. Proposals only; no
            # cron line is installed by listing them here.
            "tests/test_cron_tranche_c_lowrisk_20261007.py",
            "tests/test_tranche_b_readiness_20261008.py",
            # Cron consolidation RANK 3: the 5-minute health tick that absorbs 17
            # monitor crontab lines. Hermetic (fake steps, tmp locks/state); it
            # pins due-phase arithmetic, lock skip, timeout = failure, receipt
            # shape and that dry-run writes nothing. Timer stays NEVER_SCHEDULED.
            "tests/test_health_tick_20261007.py",
            # 2026-10-09 n8n maturity B3.1: tick exit = tick health (findings in the
            # receipt), step timeouts clamped to a tick deadline, leftover children
            # reaped; portfolio_live_monitor --once; cron_self_heal acts + live $PY.
            "tests/test_health_tick_outcomes_20261009.py",
            "tests/test_cron_self_heal_acts_20261009.py",
            # B3.1 review: monitors report a finding with EXIT_FINDING=3, never 1.
            "tests/test_monitor_finding_exit_codes_20261009.py",
            "tests/test_morning_brief_sent_flag_20261007.py",
            "tests/test_telegram_ack_hook_20261007.py",
            "tests/test_retention_registry_20261007.py",
            "tests/test_pgvector_migration_plan_20261008.py",
            "tests/test_maturity_score_independent_20261007.py",
            "tests/test_n8n_coordination_gateway_20261007.py",
            "tests/test_n8n_research_intake_20261008.py",
            "tests/test_n8n_coordination_ledger_20261007.py",
            "tests/test_n8n_gateway_http_20261007.py",
            "tests/test_n8n_lab_watchdog_20261007.py",
            "tests/test_n8n_gateway_durable_20261007.py",
            "tests/test_n8n_pilot_observations_20261007.py",
            "tests/test_n8n_coordination_projection_20261007.py",
            "tests/test_n8n_lane_host_conflict_20261007.py",
            "tests/test_n8n_pilot_compare_20261007.py",
            "tests/test_n8n_pilot_contracts_20261007.py",
        ],
    ),
    (
        # N8N_RUN_ROUTE — 2026-10-08 n8n scheduler-of-record tranche N1: the gateway `run` operation
        # (per-caller keys, coordination_run scope, config/n8n_run_allowlist.json), the ledger `runs`
        # table, the executor (fake runner, lock skip, timeout, receipt) and the allowlist safety test.
        # Hermetic: tmp_path ledgers and state roots; no unit is installed by listing these.
        "N8N_RUN_ROUTE",
        [
            "tests/test_n8n_run_route_20261008.py",
            "tests/test_n8n_run_store_20261008.py",
            "tests/test_n8n_run_executor_20261008.py",
            "tests/test_n8n_run_allowlist_20261008.py",
            # 2026-10-08 first N1 shadow burst: ledger RLock across gateway handler threads (16-wide run and
            # event bursts, same-nonce race) on a tmp_path ledger and 127.0.0.1 port 0.
            "tests/test_n8n_gateway_concurrency_20261008.py",
        ],
    ),
    (
        # ANCHOR: N8N_MATURITY_CRON_TZ — 2026-10-09 n8n-maturity B5.1 (design 02 §3.2 step 1, F11):
        # DST-safe fires_between / is_sub_hourly / last_fire_at_or_before in scripts/lib/cron_schedule.py.
        # Pure and hermetic: explicit instants only, no clock, no I/O.
        "n8n_maturity_cron_tz_20261009",
        [
            "tests/test_n8n_maturity_cron_tz_20261009.py",
        ],
    ),
    (
        # N8N_WORKFLOW_GEN (2026-10-08, plan streamed-humming-wolf workstream H): the n8n
        # scheduler-of-record workflow generator and the per-lane cutover checklist. The tests
        # pin determinism (--check), the four-node allowlist, the relay contract, the N1 lane set
        # and the INDEX shape; the checklist renders from receipts under tmp_path only. Listing
        # them imports nothing into n8n and retires no cron line.
        "n8n_workflow_gen_20261008",
        [
            "tests/test_n8n_workflow_templates_20261008.py",
            "tests/test_n8n_cutover_checklist_20261008.py",
        ],
    ),
    (
        # ANCHOR: N8N_MATURITY_GENERIC_WORKFLOWS (2026-10-09, design 02 §11, B5.6): the six generic
        # registry-driven workflows (build-generic). Static only: byte-determinism, node allowlist, /run body keys,
        # bridge-IP relay, errorWorkflow, no lane constants beyond SYSTEM_FILTER_LANES. Imports nothing into n8n.
        "n8n_maturity_generic_workflows_20261009",
        [
            "tests/test_n8n_maturity_generic_workflows_20261009.py",
        ],
    ),
    (
        # ANCHOR: N8N_AGENT_GATE_GOVERNANCE — 2026-10-09 AGENTS.md 3.0.0 §23.10 preconditions before any n8n
        # Agent node: P16 activation attribution (n8n publish evidence vs guard grants naming the workflow id),
        # P17 registry-first (active n8n workflows are a lane-registry discovery source; UNDECLARED_N8N_WORKFLOW
        # fails --fail-on-new), P18 git-vs-live workflow drift, P20 n8n identity rows + gateway denylist parity
        # with agent_runtime_mvl global_denied_tools. Hermetic: fixtures under tmp_path, fake psql runner.
        "n8n_agent_gate_governance_20261009",
        [
            "tests/test_n8n_registry_first_20261009.py",
            "tests/test_n8n_workflow_drift_20261009.py",
            "tests/test_n8n_activation_grants_20261009.py",
            "tests/test_n8n_agent_identity_parity_20261009.py",
        ],
    ),
    (
        # ANCHOR: N8N_OPS_LANES — 2026-10-09 operator "add the lanes": storage-watch, backup-verify (dump dir
        # config-driven), monthly trade-ai-restore-drill (throwaway DB only; drop guard pinned), N7 shadow
        # workflows. Hermetic: tmp_path dumps/stamps, fake runners, fake DB connections that record SQL.
        "n8n_ops_lanes_20261009",
        ["tests/test_n8n_ops_lanes_20261009.py"],
    ),
    (
        # ANCHOR: N8N_MATURITY_RETRY_DLQ — n8n maturity B5.4 (design 02 §3.3/§3.4, F8/F9): N8nRetryPolicies@v1
        # + program rules, verdict table, additive ledger schema (runs dispatch columns, dead_letters, breakers,
        # event_cursors), DLQ + breaker after 3, n8n_dlq.py list/release receipts. Hermetic tmp_path ledgers.
        "n8n_maturity_retry_dlq_20261009",
        ["tests/test_n8n_maturity_retry_dlq_20261009.py"],
    ),
    (
        # ANCHOR: N8N_SCHED_FIXES — 2026-10-09 audit (operator "fix the broken cron jobs"): watchdog unit lock
        # miss = clean skip; ACTIVE kind-n8n rows need an active workflow (INACTIVE_N8N_WORKFLOW); board
        # same-second receipt tie-break; executor opt-in bounded retry; cleanup_stale_locks report-only.
        # Hermetic: tmp_path receipts/registries, fake runner and sleeper.
        "n8n_sched_fixes_20261009",
        ["tests/test_n8n_sched_fixes_20261009.py"],
    ),
    (
        # ANCHOR: N8N_MATURITY_EXECUTOR_V2 — n8n maturity B5.5 (design 02 §5): executor v2 — N workers, per-lane
        # lock (claim_next_v2), global/class caps, reserved priority worker, stale-RUNNING reaper, verdict/DLQ/
        # breaker via finalize_outcome, RunReceipt@v2 + ExecutorStatus@v1; workers=1 is the v1 path. Hermetic:
        # tmp_path ledgers, fake clock, gated fake runners, tiny real subprocesses.
        "n8n_maturity_executor_v2_20261009",
        ["tests/test_n8n_maturity_executor_v2_20261009.py"],
    ),
    (
        # ANCHOR: N8N_SCALP_LANE — 2026-10-09 operator "n8n drives a governed lane": trade-ai-scalp-live
        # shadow-only allowlist entry (no live_arg), --dry-run writes nothing, per-run receipt, registry
        # output_signal resolvable (no '~'), fan-in STALLED source. Hermetic: tmp state root, fake clocks.
        "n8n_scalp_lane_20261009",
        ["tests/test_n8n_scalp_lane_20261009.py", "tests/test_agents_policy_4_0_0_scalp_lane.py"],
    ),
    (
        # ANCHOR: SCALP_CYCLE_RECEIPT_B4 — n8n maturity B4 2026-10-09: ScalpCycleReceipt@v1 per 5-min cycle
        # (started/ok/error/killed on SIGTERM), market-hours-aware monitor (P2 2 missed RTH slots, P1 30 min),
        # fan-in source 3h, state saved before the send, slot guard. Hermetic: tmp state root, fakes, no send.
        "scalp_cycle_receipt_b4_20261009",
        ["tests/test_scalp_cycle_receipt_b4_20261009.py"],
    ),
    (
        # N8N_RUN_RELAY — 2026-10-08: bearer-authenticated host relay; hermetic tests only.
        "N8N_RUN_RELAY",
        ["tests/test_n8n_run_relay_20261008.py"],
    ),
    (
        # PHONE_STATUS — 2026-10-09: read-only Tailscale-only phone status endpoint; hermetic tests only
        # (bind refusal, HMAC/envelope auth, window, replay, rate, <= 2 KB, no secrets in output).
        "PHONE_STATUS",
        ["tests/test_phone_status_endpoint_20261009.py"],
    ),
    (
        # N8N_AGENT2_W1 — 2026-10-08: observed registry rows, safe routing and durable legacy-job receipts.
        "N8N_AGENT2_W1",
        ["tests/test_n8n_w1_registry_20261008.py"],
    ),
    (
        # N8N_AGENT2_W2 — 2026-10-08: N6 provenance and fail-closed external contracts.
        "N8N_AGENT2_W2",
        ["tests/test_n8n_w2_registry_20261008.py"],
    ),
    (
        # Cron tranche B (2026-10-07, ranks 5-7 of 13-cron-consolidation): manifest-driven serial
        # stage runner for the post-close, premarket and Hermes chains. Hermetic: the tests drive
        # the runner with true/false/sleep manifests against a scratch project root, prove that
        # --dry-run (the default) executes nothing, that --apply with an empty stage executes
        # nothing, per-step timeout + continue-on-error + receipts, and that the four committed
        # manifests are verbatim crontab slices with every broker/stop/order/market_day_gate line
        # excluded. Listing them here schedules nothing: the runners are NEVER_SCHEDULED lanes.
        "cron_tranche_b_20261007",
        [
            "tests/test_pipeline_manifest_runner_20261007.py",
        ],
    ),
    (
        # ANCHOR: CADENCE_TIMER_UNITS — 2026-10-08: the five timer-driven pipeline services (governance,
        # portfolio daily/weekly/monthly/lookthrough) executed the DEV tree from host-only unit copies with no
        # repo text; tradeai-operator-answer-quality.service was the sixth --alert monitor still dev-tree.
        # Pins the 11 repo unit files to the served CURRENT tree (ExecStart + WorkingDirectory, measured
        # OnCalendar preserved, no live-host literal) and the governance controller's PY fallback (exit 78).
        # Hermetic; reads repo files only. Listing them here installs nothing.
        "cadence_timer_units_20261008",
        [
            "tests/test_cadence_timer_units_20261008.py",
        ],
    ),
    (
        # ANCHOR: N8N_MIGRATION_BOARD — n8n scheduler-of-record program, stream G (2026-10-08):
        # the `runs` source on the coordination projection (tmp sqlite), the incident fan-in
        # `runs` source (P2 RUN_FAILED/RUN_TIMEOUT, P1 executor stalled, self-closing on RUN_DONE,
        # TRADEAI_FANIN_RUNS=0 opt-out) and scripts/n8n_migration_board.py (phases, risk flags,
        # rollback readiness, --write/--markdown) from fixture receipts. Hermetic; no host path,
        # no crontab read, no ledger write. Listing them here schedules nothing.
        "n8n_migration_board_20261008",
        [
            "tests/test_n8n_coordination_runs_projection_20261008.py",
            "tests/test_n8n_incident_fanin_runs_20261008.py",
            "tests/test_n8n_migration_board_20261008.py",
        ],
    ),
    (
        # ANCHOR: N8N_OBS_GAPS — n8n scheduler-of-record program, observability gaps (2026-10-08):
        # the lane monitor renders scheduler_label and, for kind n8n, the last run with the
        # FRESH/ORPHANED evaluate_lane decided (research_lane_health --lanes / alert body, governance
        # packet `detail`); the incident fan-in `relay` source (P2 relay:auth_failures from the relay
        # last file's counter diffed against the previous receipt, P1 relay:down, TRADEAI_FANIN_RELAY=0
        # opt-out); the rotation daemon's pure due-selection + --dry-run and the two weekly
        # secret_registry entries. Hermetic: tmp registry, tmp sqlite ledger, tmp relay/receipt files,
        # tmp secret registry + state. Listing them here schedules nothing.
        "n8n_observability_gaps_20261008",
        [
            "tests/test_lane_monitor_n8n_rendering_20261008.py",
            "tests/test_n8n_incident_fanin_relay_20261008.py",
            "tests/test_secret_rotation_schedule_20261008.py",
        ],
    ),
    (
        # ANCHOR: N8N_INCIDENT_NOTIFIER — N8N maturity B2 (2026-10-09): scripts/incident_notifier.py, the human
        # end of the incident fan-in. P1 at once, P2 one batch per window, recovery on clear, per-incident 24 h
        # dedupe, daily cap from env, operator acks from the ledger, dry-run sends and records nothing, and the
        # sender is only the SYSTEM ops module (no family, token or chat; this module is not a SYSTEM caller).
        # Hermetic: tmp state root, tmp sqlite ledger, stub sender/previewer. Listing it here schedules nothing.
        "N8N_INCIDENT_NOTIFIER",
        [
            "tests/test_incident_notifier_20261009.py",
        ],
    ),
    (
        # 2026-10-08 — n8n model job, live shape (workstream C, Day 0). Pins the bridge's nested
        # `_tradeai` governance envelope, request_id -> provider_cost client_request_id, the
        # server-side PROCESS_TASK_TYPE map (unknown process = process_not_registered before any
        # call) and server-rendered prompt templates that reproduce the inline prompt byte for
        # byte. Hermetic: injected governed call, stubbed HTTP, scratch state root; no provider.
        "N8N_MODEL_JOB_SHAPE",
        [
            "tests/test_n8n_model_job_20261007.py",
            "tests/test_n8n_model_job_operation_20261007.py",
            "tests/test_ops_summary_model_job_live_wiring_20261008.py",
        ],
    ),
    (
        # ANCHOR: N8N_W4_ROUTING_20261008 — routing policy load, unknown header refusal,
        # lane_unhealthy before any provider call, receipt routing_decision, per-provider semaphore size.
        "n8n_w4_routing_20261008",
        [
            "tests/test_llm_routing_policy_20261008.py",
        ],
    ),
    (
        # ANCHOR: BRIDGE_EXECUTOR_HARDENING — 2026-10-09 guardrail audit B: H1 one provider call per streamed
        # bridge request; H2 caller auth off|report|enforce (report default, enforce refuses before reservation);
        # M1 executor unit carries the crontab-wide lane env; M2 lanes inherit no n8n secret.
        "bridge_executor_hardening_20261009",
        [
            "tests/test_bridge_executor_hardening_20261009.py",
        ],
    ),
    (
        # ANCHOR: N8N_AGENT_GATE_BRIDGE — AGENTS.md 3.0.0 §23.10 bridge preconditions (2026-10-09):
        # P4 sanitise_for_external on every governed call (TRADEAI_EGRESS_SANITISER report default, enforce
        # redacts); P5 per-process tool allowlist (typed 400 before reservation, tool_calls refused typed);
        # P6 n8n_* output schema + behaviour scan; P21 cost_ceiling_usd / latency_budget_ms / advisory_only;
        # n8n routing Grok -> ChatGPT -> DeepSeek with transport failover.
        "n8n_agent_gate_bridge_20261009",
        [
            "tests/test_bridge_agent_preconditions_20261009.py",
        ],
    ),
    (
        # ANCHOR: BACKUP_COVERAGE_GATE_20261009 — operator question 2026-10-09: every repo-declared asset
        # (authority store, persistent tree, unit, secret name, migration table, fixed infra) resolves to a
        # backup class in config/backup_coverage_manifest.json; a new unmapped asset or a new gap fails,
        # baselined gaps are reported (ratchet). Runs scripts/check_backup_coverage.py on the real repo.
        "backup_coverage_gate_20261009",
        [
            "tests/test_backup_coverage_gate_20261009.py",
        ],
    ),
    (
        # ANCHOR: AGENTS_GUARD_HOOK — 2026-10-09 Claude Code PreToolUse hook enforcing the AGENTS.md hard rails
        # (broker, delete, remote routing, secrets, live ops behind guard grants, governed served paths); log-only
        # first week, fail-open on its own errors, redacted AgentsGuardDecision@v1 log. Hermetic: tmp HOME/state/ledger.
        "AGENTS_GUARD_HOOK",
        [
            "tests/test_agents_guard_hook_20261009.py",
        ],
    ),
    (
        # ANCHOR: ROLLUP_RECURSION_AND_FUSED_EMBEDDINGS — storage audit 2026-10-09 (#1, #5) + operator decision:
        # system_rollup_daily payload bounded (trends = compact headlines only, no stored trends panel, byte cap
        # -> typed ROLLUP_PAYLOAD_TOO_LARGE, receipt, non-zero exit); rag_indexer fused_signal text carries real
        # fields, empty signals skipped + counted; content_embeddings source_windows (30 d) enforced as verified
        # ARCHIVE_THEN_DELETE batches; one-time junk fused_signal purge is dry-run by default.
        "rollup_recursion_and_fused_embeddings_20261009",
        [
            "tests/test_system_rollup_bounded_20261009.py",
            "tests/test_rag_fused_signal_text_20261009.py",
            "tests/test_retention_source_windows_junk_20261009.py",
        ],
    ),
    (
        # Cron crash fixes (operator 2026-10-09: "fix the broken cron jobs"): failed --user units detected,
        # econfirm finds gog outside cron PATH, disarmed retries not counted as retried, bridge refusal code kept
        # in 503 errors, alert-quality registry row matches the host.
        "cron_crash_fixes_20261009",
        ["tests/test_cron_crash_fixes_20261009.py"],
    ),
    (
        # 2026-10-09 cron audit, stale/silent jobs: document_mentions watermark + budget + flushed log;
        # job_coverage_monitor schedule-aware (last due fire), systemd timers, dev-tree logs, moved schedulers;
        # schwab stream reconnects while open + line-buffered log; ri_overnight / paper post-close processors
        # resolve a real interpreter in release dirs; BOOK checkpoints never price-resolvable.
        "cron_stale_fixes_20261009",
        ["tests/test_cron_stale_fixes_20261009.py"],
    ),
    (
        # ANCHOR: SYSTEM_TELEGRAM_INTERDICT_SCOPE — 2026-10-09: C4's lowest-layer interdict keyed on
        # CIO_TELEGRAM_INTERDICT alone blocked every TRADE_AI_SYSTEM send since 2026-09-19. Scoped by a typed
        # SendFamily the transport confirms (caller module, ops bot, ops chat, SYSTEM_TELEGRAM_ENABLED): CIO and
        # financial sends stay interdicted, SYSTEM_OPS answers to SYSTEM_TELEGRAM_INTERDICT, pytest blocks all,
        # spoofing refused; heartbeat once per NY date, one alert per transition kind per date; what-would-send.
        "SYSTEM_TELEGRAM_INTERDICT_SCOPE",
        [
            "tests/test_system_telegram_interdict_scope_20261009.py",
        ],
    ),
]


# ---------------------------------------------------------------------------
# Execution profiles (2026-09-25, operator: "speed up to like 5 mins")
#
# Measured before this change (3 green CI runs, 2026-09-25): the gates step took
# 610-1090 s of a 1077-1127 s job. It ran 181 pytest invocations one after the
# other; one gate (maturity_overnight_20260912, 130 files) alone took 226-385 s.
# No test was run twice (567 unique files, 7 shared), so the only lever that
# keeps every registered test is PARALLELISM, not pruning.
#
#   fast (default; the required `cio-hardening` context): EVERY gate still runs.
#         Gates execute concurrently in a worker pool; gates with many files are
#         split into file chunks so no single gate bounds the wall clock. Gates
#         whose tests touch shared state (the live docs/INDEX.md, git in the repo,
#         a Postgres test database) run afterwards, one at a time.
#   full: the historical behaviour -- one gate at a time, in declared order. It is
#         the isolation reference (a test that only passes in `fast` or only in
#         `full` has a hidden dependency) and runs on push to main, nightly, and on
#         workflow_dispatch in `cio-hardening-full`.
#
#   pr:   the required `cio-hardening` context on pull requests (operator budget:
#         5 minutes wall clock including runner setup). Runs a SELECTION, in the
#         fast pool: the smoke gates, the full named gates of every HIGH risk tier
#         the diff touches, every changed test, every test that imports/references
#         a changed file, then further-reachable tests nearest-first while the
#         estimate fits config/ci_risk_tiers.json budget_seconds. What does not
#         fit is DEFERRED -- listed in the log and job summary -- and runs in the
#         post-merge `full` run (push to main), which opens an issue on failure.
#         See scripts/lib/test_impact.py. If the base ref or the map is unusable
#         it falls back to `fast` (everything).
#
# All profiles run the same tail checks (docs index drift, release manifest).
# Registration is unchanged: a test file is covered iff it is in GATES
# (check_test_coverage.py enforces that), whatever the profile.
# ---------------------------------------------------------------------------

#: Parallel work is packed into units of about this many seconds (by duration hint).
UNIT_TARGET_SECONDS = float(os.environ.get("CIO_CI_UNIT_SECONDS", "25"))

#: Per-file wall-second hints (config/ci_test_duration_hints.json). They only order
#: and pack work; a missing or stale hint can never drop a test.
DURATION_HINTS_PATH = REPO / "config" / "ci_test_duration_hints.json"
DEFAULT_FILE_SECONDS = 1.0

#: A FILE runs in the serial tail if it matches one of these. They mark tests that
#: touch state other workers can see: the committed docs index, git operations, a
#: Postgres test database, or a probe file planted in scripts/. (Per file, not per gate: the rest of a gate still runs in
#: parallel.) Conservative on purpose -- a false positive only costs a few seconds.
SHARED_STATE_PATTERNS = (
    r"docs/INDEX\.md",
    r"\bm2_conn\b",
    r"psycopg2\.connect",
    r"M2_TEST_DATABASE",
    r"\bgit\b[\"', ]+(?:stash|checkout|reset|commit|worktree|merge)\b",
    # plants a probe file INTO scripts/ (ROOT / "scripts" / "_pytest_..._probe.py") to
    # prove a tree-wide ratchet fires; any concurrent tree scan would see it too
    r"[\"']scripts[\"']\s*/\s*f?[\"']_",
)
_SHARED_STATE_RE = re.compile("|".join(SHARED_STATE_PATTERNS))

#: pytest exit 5 = "no tests collected": a unit whose every module skips at import
#: (e.g. the Postgres-only files split out of a gate when psycopg2 is absent). The
#: serial `full` profile never saw it because those files shared one invocation
#: with runnable tests.
#: Only when pytest reports skips -- a unit that collects nothing at all still fails.
PASS_CODES = frozenset({0, 5})


def _unit_passed(rc: int, out: str) -> bool:
    return rc == 0 or (rc == 5 and " skipped" in out)


#: Files proven to need the serial tail even though no pattern marks them.
SERIAL_FILES: frozenset[str] = frozenset()


def _profile_from_env() -> str:
    return (os.environ.get("CIO_CI_PROFILE") or "fast").strip().lower()


def _default_jobs() -> int:
    raw = os.environ.get("CIO_CI_JOBS")
    if raw and raw.strip().isdigit():
        return max(1, int(raw))
    return max(1, min(os.cpu_count() or 2, 8))


def load_duration_hints(path: Path = DURATION_HINTS_PATH) -> dict[str, float]:
    try:
        import json

        return {str(k): float(v) for k, v in (json.loads(path.read_text(encoding="utf-8")).get("files") or {}).items()}
    except (OSError, ValueError):
        return {}


def file_needs_serial(path: str) -> bool:
    if path in SERIAL_FILES:
        return True
    try:
        return bool(_SHARED_STATE_RE.search((REPO / path).read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return False


def gate_needs_serial(name: str, paths: list[str]) -> bool:
    """True if any file of the gate needs the serial tail (kept for callers/tests)."""
    return any(file_needs_serial(p) for p in paths)


def plan_units(gates, *, unit_seconds: float = UNIT_TARGET_SECONDS, hints: dict[str, float] | None = None):
    """Return (parallel_units, serial_units); a unit is (gate_name, [files]).

    Every existing registered file appears in exactly one unit per registration.
    """
    hints = load_duration_hints() if hints is None else hints

    def w(p: str) -> float:
        return hints.get(p, DEFAULT_FILE_SECONDS)

    parallel, serial = [], []
    for name, paths in gates:
        existing = [p for p in paths if (REPO / p).is_file()]
        if not existing:
            continue
        shared = [p for p in existing if file_needs_serial(p)]
        free = [p for p in existing if p not in shared]
        if shared:
            serial.append((name, shared))
        chunk: list[str] = []
        acc = 0.0
        for p in free:
            if chunk and acc + w(p) > unit_seconds:
                parallel.append((name, chunk))
                chunk, acc = [], 0.0
            chunk.append(p)
            acc += w(p)
        if chunk:
            parallel.append((name, chunk))

    parallel.sort(key=lambda u: sum(w(p) for p in u[1]), reverse=True)  # longest first
    return parallel, serial


def _run_unit(unit):
    name, files = unit
    t0 = time.monotonic()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider", *files],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    return name, files, r.returncode, (r.stdout or "") + (r.stderr or ""), time.monotonic() - t0


def run_gates(gates, *, profile: str, jobs: int) -> list[str]:
    """Run every gate; return the names of failed gates."""
    failed: list[str] = []
    if profile == "full" or jobs <= 1:
        for name, paths in gates:
            existing = [p for p in paths if (REPO / p).is_file()]
            if not existing:
                print(f"[SKIP] {name}: no test files", flush=True)
                continue
            print(f"[RUN]  {name}: {' '.join(existing)}", flush=True)
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=line", *existing], cwd=str(REPO))
            if r.returncode != 0:
                failed.append(name)
                print(f"[FAIL] {name}", flush=True)
            else:
                print(f"[PASS] {name}", flush=True)
        return failed

    parallel, serial = plan_units(gates)
    print(f"[plan] profile=fast jobs={jobs} parallel_units={len(parallel)} serial_gates={len(serial)}", flush=True)
    results: dict[str, list[tuple]] = {}

    def record(res):
        name, files, rc, out, secs = res
        results.setdefault(name, []).append(res)
        tail = (out.strip().splitlines() or [""])[-1]
        status = "PASS" if _unit_passed(rc, out) else "FAIL"
        print(f"[{status}] {name} ({len(files)} files, {secs:.1f}s) {tail[-100:]}", flush=True)
        if not _unit_passed(rc, out):
            print(out[-6000:], flush=True)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for res in pool.map(_run_unit, parallel):
            record(res)
    for unit in serial:
        record(_run_unit(unit))

    declared = [n for n, _ in gates]
    for name in declared:
        if any(not _unit_passed(r[2], r[3]) for r in results.get(name, [])) and name not in failed:
            failed.append(name)
    return failed


ALARM_GATE_NAMES = ("alarm_fires", "alarm_document_sites_20260922")


def _touches_alarm_sites(changed: list[str]) -> bool:
    """True when a changed scripts/*.py file contains a send_telegram call (alarm-coverage scope)."""
    for p in changed or []:
        if not (p.startswith("scripts/") and p.endswith(".py")):
            continue
        try:
            if "send_telegram" in (REPO / p).read_text(encoding="utf-8", errors="ignore"):
                return True
        except OSError:
            continue
    return False


def select_pr_gates(
    base: str, *, include_worktree: bool = False, budget: float | None = None, changed: list[str] | None = None
):
    """Return (gates, profile) for the pr profile; falls back to (GATES, "fast")."""
    import json

    sys.path.insert(0, str(REPO))
    from scripts.lib import test_impact

    t0 = time.monotonic()
    if changed is None:
        changed = test_impact.changed_paths(base, root=REPO, include_worktree=include_worktree)
    if changed is None:
        print(f"[select] base {base!r} unusable -> FALLBACK to fast (every gate)", flush=True)
        return GATES, "fast"
    try:
        impact_map, status = test_impact.load_map(REPO)
        tiers = test_impact.load_tiers()
    except (OSError, ValueError) as exc:
        print(f"[select] impact map/tiers unusable ({exc}) -> FALLBACK to fast (every gate)", flush=True)
        return GATES, "fast"
    sel = test_impact.select(
        changed,
        GATES,
        impact_map=impact_map,
        tiers=tiers,
        hints=load_duration_hints(),
        default_seconds=DEFAULT_FILE_SECONDS,
        budget_seconds=budget,
    )
    # A new send_telegram call is invisible to the tier map and the import graph, so the
    # alarm-coverage gates ran only after merge and main went red (2026-10-04: two new alert senders
    # shipped without firing tests). Any changed script that sends Telegram pulls them in.
    if _touches_alarm_sites(changed):
        have = {name for name, _f in sel["gates"]}
        for name, files in GATES:
            if name in ALARM_GATE_NAMES and name not in have:
                sel["gates"].append((name, files))
                print(f"[select] ALARM: {name} added (a changed script calls send_telegram)", flush=True)
    n_files = sum(len(f) for _n, f in sel["gates"])
    print(
        f"[select] base={base} changed={len(changed)} tier={sel['tier']} map={status} "
        f"impacted={sel['impacted']} selected_files={n_files} gates={len(sel['gates'])} "
        f"estimate={sel['estimate_seconds']}s (mandatory {sel['mandatory_estimate_seconds']}s, "
        f"budget {sel['budget_seconds']}s) deferred={len(sel['deferred'])} "
        f"select_secs={time.monotonic() - t0:.1f}",
        flush=True,
    )
    for cat, paths in sorted(sel["high"].items()):
        print(f"[select] HIGH {cat}: {', '.join(paths[:8])}{' ...' if len(paths) > 8 else ''}", flush=True)
    for f in sel["deferred"][:25]:
        print(f"[select] DEFERRED to post-merge full run: {f}", flush=True)
    if len(sel["deferred"]) > 25:
        print(
            f"[select] ... and {len(sel['deferred']) - 25} more DEFERRED (all listed in the job summary "
            "and in CIO_CI_SELECTION_OUT when set)",
            flush=True,
        )
    if sel["unknown_gates"]:
        print(f"[select] WARNING tier config names unknown gates: {sel['unknown_gates']}", flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = [
            "## cio-hardening (pr profile)",
            f"- changed paths: {len(changed)}; risk tier: **{sel['tier'].upper()}**",
            f"- selected: {n_files} test files in {len(sel['gates'])} gates; "
            f"estimate {sel['estimate_seconds']} s of {sel['budget_seconds']} s budget",
            f"- deferred to the post-merge full run: {len(sel['deferred'])}",
        ]
        if sel["high"]:
            lines.append("")
            lines.append("### HIGH-risk paths touched -- independent review required (reviewer is not the author)")
            for cat, paths in sorted(sel["high"].items()):
                lines.append(f"- **{cat}**: " + ", ".join(f"`{p}`" for p in paths))
        if sel["deferred"]:
            lines.append("")
            lines.append("<details><summary>Deferred tests</summary>\n")
            lines += [f"- `{f}`" for f in sel["deferred"]]
            lines.append("\n</details>")
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError:
            pass
    out = os.environ.get("CIO_CI_SELECTION_OUT")
    if out:
        Path(out).write_text(
            json.dumps({k: v for k, v in sel.items()}, indent=1, default=list) + "\n", encoding="utf-8"
        )
    return sel["gates"], "fast"


def write_duration_hints(*, jobs: int) -> int:
    """Measure per-file wall time and rewrite config/ci_test_duration_hints.json."""
    import json

    files = sorted({p for _n, ps in GATES for p in ps if (REPO / p).is_file() and not file_needs_serial(p)})

    def one(path: str):
        t0 = time.monotonic()
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", path],
            cwd=str(REPO),
            capture_output=True,
        )
        return path, round(time.monotonic() - t0, 1)

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        measured = dict(pool.map(one, files))
    doc = {
        "schema": "CiTestDurationHints@v1",
        "note": (
            "Per-file wall seconds (one pytest process per file). Used ONLY to order and pack work in "
            "run_cio_hardening_ci.py --profile fast; never decides which tests run. Files below 2 s are "
            "omitted (default weight 1 s). Refresh with scripts/run_cio_hardening_ci.py --write-duration-hints."
        ),
        "files": {k: v for k, v in sorted(measured.items()) if v >= 2.0},
    }
    DURATION_HINTS_PATH.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {DURATION_HINTS_PATH.relative_to(REPO)} ({len(doc['files'])} files >= 2 s of {len(files)})")
    return 0


# ---------------------------------------------------------------------------
# Sharded full suite (operator-approved 2026-10-09; .github/workflows/cio-full-suite-sharded.yml)
#
# `--shard I/N` runs shard I of N (or `serial/N`, `pg/N`) of EVERY registered file -- nothing
# deferred -- and writes a CiShardManifest@v1 naming each file it ran, its unit results and
# measured per-file seconds. `--verify-shards DIR --shards N` (the `ci-gate` job) recomputes the
# registered list from GATES and fails unless the shards' reported files are exactly that list,
# each once, all passed, on the same tree and plan. Planning: scripts/lib/ci_shards.py.
# ---------------------------------------------------------------------------

#: Per-file seconds measured by the sharded run (overlays DURATION_HINTS_PATH for balancing).
SHARD_HINTS_PATH = REPO / "config" / "ci_shard_duration_hints.json"


def shard_hints() -> dict[str, float]:
    hints = load_duration_hints()
    hints.update(load_duration_hints(SHARD_HINTS_PATH))
    return hints


def file_needs_db(path: str) -> bool:
    from scripts.lib import ci_shards

    try:
        return ci_shards.source_needs_db((REPO / path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False


def shard_plan(n: int) -> dict:
    sys.path.insert(0, str(REPO))
    from scripts.lib import ci_shards

    hints = shard_hints()
    return ci_shards.plan_shards(
        GATES,
        n=n,
        weight=lambda p: hints.get(p, DEFAULT_FILE_SECONDS),
        needs_serial=file_needs_serial,
        needs_db=file_needs_db,
        exists=lambda p: (REPO / p).is_file(),
    )


def _git_value(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out:
        raise RuntimeError("git " + " ".join(args) + " failed")
    return out


def _run_unit_junit(job):
    """One pytest process for a unit, with a junit report for per-file timings."""
    import xml.etree.ElementTree as ET

    from scripts.lib import ci_shards

    (name, files), xml_path = job[0], job[1]
    env = job[2] if len(job) > 2 else None
    t0 = time.monotonic()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider",
         f"--junitxml={xml_path}", "-o", "junit_family=xunit1", *files],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env=env,
    )
    secs = time.monotonic() - t0
    out = (r.stdout or "") + (r.stderr or "")
    try:
        xml_text = Path(xml_path).read_text(encoding="utf-8")
    except OSError:
        xml_text = ""
    skipped = 0
    try:
        skipped = sum(1 for _ in ET.fromstring(xml_text).iter("skipped")) if xml_text else 0
    except ET.ParseError:
        pass
    return {
        "gate": name,
        "files": list(files),
        "rc": r.returncode,
        # A registered file with no test functions (e.g. a script-style check) collects nothing:
        # pytest exit 5 "no tests ran". In the fast/full profiles it shares an invocation with
        # its gate's other files and is accepted there; a shard may run it alone, so accept it
        # the same way and record it. Collection errors (exit 2) still fail.
        "passed": _unit_passed(r.returncode, out) or (r.returncode == 5 and "no tests ran" in out),
        "no_tests": r.returncode == 5 and "no tests ran" in out,
        "seconds": round(secs, 1),
        "skipped": skipped,
        "tail": (out.strip().splitlines() or [""])[-1][-200:],
        "output": out,
        "file_seconds": ci_shards.file_seconds_from_junit(xml_text, files, secs),
    }


#: DSN env vars whose database each pg-shard file gets fresh (``<database>_f<i>``).
PER_FILE_DB_ENV = ("ALERT_TEST_DSN",)


def _per_file_db_env(path: str, index: int) -> dict | None:
    """Environment for one pg-shard file: each PER_FILE_DB_ENV DSN re-pointed at a new database.

    The database is created by scripts/ensure_m2_test_database.py, which refuses any name that
    is not ``m2_shadow_test[_suffix]`` -- so this can never point a test at a live database.
    A DSN whose database does not fit that pattern is left unchanged.
    """
    sys.path.insert(0, str(REPO))
    from scripts.lib.m2_live_shadow_guard import TEST_DATABASE_RE, dsn_database, with_database

    env = dict(os.environ)
    changed = False
    for var in PER_FILE_DB_ENV:
        dsn = env.get(var, "").strip()
        base = dsn_database(dsn) if dsn else ""
        if not base or not TEST_DATABASE_RE.match(f"{base}_f{index}"):
            continue
        name = f"{base}_f{index}"
        r = subprocess.run([sys.executable, "scripts/ensure_m2_test_database.py", "--name", name],
                           cwd=str(REPO), capture_output=True, text=True)
        print(f"[shard] {path}: {var} -> database {name} (ensure rc={r.returncode})", flush=True)
        if r.returncode == 0:
            env[var] = with_database(dsn, name)
            changed = True
    return env if changed else None


def run_shard(shard_arg: str, *, jobs: int, out: Path | None) -> int:
    import json
    import tempfile

    sys.path.insert(0, str(REPO))
    from scripts.lib import ci_shards

    sid, n = ci_shards.parse_shard_arg(shard_arg)
    plan = shard_plan(n)
    files = plan["shards"][sid]
    parallel, serial = plan_units(ci_shards.gates_for_files(GATES, files), hints=shard_hints())
    one_at_a_time = sid in (ci_shards.SERIAL_SHARD, ci_shards.PG_SHARD) or jobs <= 1
    print(
        f"[shard] {sid}/{n} files={len(files)} est={plan['loads'][sid]}s parallel_units={len(parallel)} "
        f"serial_units={len(serial)} jobs={1 if one_at_a_time else jobs} plan={plan['digest'][:12]}",
        flush=True,
    )
    t0 = time.monotonic()
    results = []

    def record(res):
        results.append(res)
        status = "PASS" if res["passed"] else "FAIL"
        print(f"[{status}] {res['gate']} ({len(res['files'])} files, {res['seconds']:.1f}s, "
              f"skipped={res['skipped']}) {res['tail'][-100:]}", flush=True)
        if not res["passed"]:
            print(res["output"][-6000:], flush=True)

    with tempfile.TemporaryDirectory(prefix=f"cio-shard-{sid}-") as tmp:
        jobs_list = [(u, str(Path(tmp) / f"u{i}.xml")) for i, u in enumerate(parallel + serial)]
        par_jobs, ser_jobs = jobs_list[: len(parallel)], jobs_list[len(parallel):]
        if one_at_a_time:
            # serial/pg: one pytest process PER FILE (a gate unit may hold several files that
            # share state), and in the pg shard each file gets its own fresh database for the
            # per-file DSN env vars (two alert-DB files sharing one database failed in CI run
            # 37957892733: "cannot drop columns from view").
            singles = [(name, [f]) for name, fs in parallel + serial for f in fs]
            for i, u in enumerate(singles):
                env = _per_file_db_env(u[1][0], i) if sid == ci_shards.PG_SHARD else None
                record(_run_unit_junit((u, str(Path(tmp) / f"f{i}.xml"), env)))
        else:
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                for res in pool.map(_run_unit_junit, par_jobs):
                    record(res)
            for j in ser_jobs:
                record(_run_unit_junit(j))
    wall = time.monotonic() - t0
    for res in results:
        res.pop("output", None)
    manifest = ci_shards.build_manifest(
        shard=sid, n=n, sha=_git_value("rev-parse", "HEAD"), tree=_git_value("rev-parse", "HEAD^{tree}"),
        digest=plan["digest"], files=files, units=results, wall=wall,
    )
    out = out or Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()) / f"cio_shard_{sid}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    failed = sorted({r["gate"] for r in results if not r["passed"]})
    print(f"[timing] shard={sid}/{n} files={len(manifest['files'])} wall={wall:.0f}s manifest={out}", flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(f"## shard {sid}/{n}\n- files: {len(manifest['files'])}; wall {wall:.0f} s; "
                         f"skipped tests: {sum(r['skipped'] for r in results)}; failed gates: {failed or 'none'}\n")
        except OSError:
            pass
    if failed:
        print(f"\nCIO SHARD {sid}/{n} FAILED: {failed}")
        return 1
    print(f"\nCIO SHARD {sid}/{n}: ALL UNITS PASS")
    return 0


def verify_shards(
    manifest_dir: Path, *, n: int, timings_out: Path | None = None, attestation_out: Path | None = None
) -> int:
    """The `ci-gate` aggregate: completeness + success across every shard, then the attestation."""
    import json

    sys.path.insert(0, str(REPO))
    from scripts.lib import ci_shards, tree_attested_promote

    manifests = []
    for p in sorted(Path(manifest_dir).rglob("cio_shard_*.json")):
        try:
            manifests.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            manifests.append({"schema": "unreadable", "shard": p.name})
    expected = ci_shards.registered_files(GATES, lambda p: (REPO / p).is_file())
    needs = json.loads(os.environ.get("CI_GATE_NEEDS") or "null")
    res = ci_shards.verify_manifests(
        manifests,
        expected_files=expected,
        n=n,
        expected_tree=_git_value("rev-parse", "HEAD^{tree}"),
        expected_digest=shard_plan(n)["digest"],
        needs=needs if isinstance(needs, dict) else None,
    )
    print(json.dumps({k: v for k, v in res.items() if k not in ("missing_files", "extra_files")}, sort_keys=True))
    for f in res["missing_files"][:50]:
        print(f"[ci-gate] MISSING (registered, not run by any shard): {f}")
    for f in res["extra_files"][:50]:
        print(f"[ci-gate] UNREGISTERED (run but not in GATES): {f}")
    for m in manifests:
        for u in m.get("units") or []:
            if u.get("no_tests"):
                print(f"[ci-gate] NOTE no test functions collected (accepted, as in the fast profile): {u.get('files')}")
    if timings_out:
        timings_out.parent.mkdir(parents=True, exist_ok=True)
        timings_out.write_text(json.dumps(ci_shards.merge_timings(manifests), indent=1, sort_keys=True) + "\n",
                               encoding="utf-8")
    if attestation_out:
        att = tree_attested_promote.build_attestation(
            _git_value, ok=res["ok"], run_id=os.environ.get("GITHUB_RUN_ID"),
            run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"), summary=res,
        )
        attestation_out.parent.mkdir(parents=True, exist_ok=True)
        attestation_out.write_text(json.dumps(att, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(f"## ci-gate\n- {'PASS' if res['ok'] else 'FAIL'}: {res['ran_files']} of "
                         f"{res['expected_files']} registered files ran across {n}+2 shards\n"
                         f"- errors: {res['errors'] or 'none'}\n- shard walls (s): {res['shard_walls']}\n")
        except OSError:
            pass
    print("\nCI-GATE: " + ("PASS" if res["ok"] else "FAIL " + ", ".join(res["errors"])))
    return 0 if res["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--profile", choices=("pr", "fast", "full"), default=_profile_from_env())
    ap.add_argument("--base", default=os.environ.get("CIO_CI_BASE", "origin/main"), help="pr profile: diff base")
    ap.add_argument("--include-worktree", action="store_true", help="pr profile: add uncommitted/untracked paths")
    ap.add_argument("--print-selection", action="store_true", help="pr profile: print the selection and exit")
    ap.add_argument("--changed", nargs="+", default=None, help="pr profile: use these paths instead of the git diff")
    ap.add_argument("--budget", type=float, default=None, help="pr profile: override budget_seconds (fast_check.sh)")
    ap.add_argument(
        "--no-tail",
        action="store_true",
        help="skip the docs-index/manifest tail checks (fast_check.sh: the candidate manifest step writes files)",
    )
    ap.add_argument("--jobs", type=int, default=_default_jobs())
    ap.add_argument("--list-plan", action="store_true", help="print the fast-profile plan and exit")
    ap.add_argument(
        "--write-duration-hints",
        action="store_true",
        help="time every parallel-safe registered file (one pytest per file) and rewrite the hints file",
    )
    ap.add_argument("--shard", default=None, help="run shard I/N (or serial/N, pg/N) of every registered file")
    ap.add_argument("--shard-out", type=Path, default=None, help="--shard: manifest path")
    ap.add_argument("--print-shard-plan", type=int, default=None, metavar="N", help="print the N-shard plan")
    ap.add_argument("--verify-shards", type=Path, default=None, metavar="DIR", help="ci-gate: verify manifests")
    ap.add_argument("--shards", type=int, default=8, help="--verify-shards: shard count N")
    ap.add_argument("--timings-out", type=Path, default=None, help="--verify-shards: merged timing hints")
    ap.add_argument("--attestation-out", type=Path, default=None, help="--verify-shards: CiGateAttestation@v1")
    args = ap.parse_args(argv)

    os.chdir(REPO)
    os.environ.setdefault("TRADE_AI_CI", "1")
    os.environ.setdefault("CIO_TELEGRAM_INTERDICT", "1")
    # Ensure pytest interdicts telegram
    os.environ.setdefault("PYTEST_ADDOPTS", "")

    if args.write_duration_hints:
        return write_duration_hints(jobs=args.jobs)
    if args.shard:
        return run_shard(args.shard, jobs=args.jobs, out=args.shard_out)
    if args.verify_shards:
        return verify_shards(
            args.verify_shards, n=args.shards, timings_out=args.timings_out, attestation_out=args.attestation_out
        )
    if args.print_shard_plan:
        import json

        plan = shard_plan(args.print_shard_plan)
        print(json.dumps({"n": plan["n"], "digest": plan["digest"], "loads": plan["loads"],
                          "counts": {k: len(v) for k, v in plan["shards"].items()}}, sort_keys=True))
        return 0

    if args.list_plan:
        parallel, serial = plan_units(GATES)
        print(f"parallel_units={len(parallel)} serial_gates={len(serial)}")
        for name, files in serial:
            print(f"  serial: {name} ({len(files)} files)")
        return 0

    t0 = time.monotonic()
    gates, profile = GATES, args.profile
    if profile == "pr":
        gates, profile = select_pr_gates(
            args.base, include_worktree=args.include_worktree, budget=args.budget, changed=args.changed
        )
        if args.print_selection:
            return 0
    failed = run_gates(gates, profile=profile, jobs=args.jobs)
    print(f"[timing] gates profile={args.profile} jobs={args.jobs} wall={time.monotonic() - t0:.0f}s", flush=True)

    if args.no_tail:
        if failed:
            print(f"\nCIO HARDENING CI FAILED: {failed}")
            return 1
        print("\nCIO HARDENING CI: ALL SELECTED GATES PASS (tail checks skipped)")
        return 0

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
