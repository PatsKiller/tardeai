# CIO cognition tranche 3 — prompt event-driven cognition and the closed learning chain

Status: BRANCH `wt/cio-cognition-t3-20260925`, not deployed · as_of 2026-09-25 10:40 ET · measured against served release `1c60ecb4264ba4dcc6a38106e76fae0d96a26787` (CURRENT = `1c60ecb42-main-exact-phase2-20260925-091436`, promoted 13:15:32Z, portfolio-server booted 09:15:49 ET on that pin; origin/main, dev tree and this branch's base all equal that SHA).

Authority: READ_ONLY_ADVISORY throughout. `MEMORY_BEHAVIOR_INFLUENCE=0`, `MBI_BEHAVIOR=0`; nothing here touches sizing, orders, stops, weights, the broker, credentials or 2FA. No production cron, timer, flag, deploy or data repair was performed. The two scheduled first-fires this branch depends on (commitment-outcome sweep 18:20 ET, instrument-belief writer 18:50 ET, installed 2026-09-24 21:35 ET) had not yet occurred at measurement time; their absence is not treated as failure.

## 1. Truth established (read-only)

| Surface | Value |
|---|---|
| origin/main, worktree base, CURRENT `SOURCE_COMMIT`/`BUILD_SHA`, dev tree | `1c60ecb42…` (all equal) |
| Served portfolio-server | pid 3949467, port 7777, `process_started_at 2026-09-25T09:15:49-04:00`, `loaded_pin_sha == current_pin_sha` |
| Wake path A (dispatcher) | cron `*/5` `cio_wake_dispatch_entrypoint.py` from CURRENT |
| Wake path B (persistent wake) | hourly `run_persistent_wake.py`; served wakes on `1c60ecb42` at measurement: 3 (14:00Z slot) |
| Reactive cycle | hourly `cio_reactive_cycle.py` (bus → EVENT_BUS wakes) |
| Verifier docs from the governance/maturity session | Cursor store `…/bc-5f36c3f9…/files/{docs,internal}/trade-ai-maturity-*-20260925.md`; that session owns `scripts/agent_runtime/gate_status.py`, `maturity_observability.py`, `config/agent_maturity_catalog.json` — untouched here |
| Queued ~19:10 ET read-only capture | another session's in-process waiter; not a timer; inspect after it completes |

## 2. Wake-path trace and event→effect latency (served stores, 24 h to 14:36Z)

`scripts/report_event_effect_latency.py --hours 24` (new, read-only):

| Event type | events | wakes | dispatched | duplicate wakes | enqueue p50/p95 (min) | dispatch p50/p95 (min) | ≤10 min share |
|---|---|---|---|---|---|---|---|
| situation.raised | 43 | 43 | 34 | **83** | 2.03 / 2.43 | 29.3 / 47.7 | 0.47 |
| thesis.changed | 85 | 85 | 59 | 10 | 0.90 / 2.06 | 22.6 / 49.6 | 0.52 |
| watch.new_signal | 4 | 4 | 0 | 4 | 1.73 / 1.86 | — | 1.00 (enqueue only) |
| plan.enriched | 43 | 0 | — | — | — | — | not routed |
| **all, first effect** | 175 | 132 | | | | **p50 24.2 / p95 48.0** | |

The 10-minute objective is **measured, not met, and not enforced**: making it an SLA or changing the `*/5` / hourly cadence is an operator decision (§17). Enqueue latency is already inside the objective; the gap is dispatch (5 slots per 5-minute cycle, LIFO order, cadence skips consuming slots) plus the hourly reactive cycle itself.

Defects found on the trace and fixed on this branch (each has a fail→pass control):

| ID | Defect (served) | Fix | Control |
|---|---|---|---|
| D-CURSOR | `bus.poll` is newest-first; the reactive cycle set the consumer cursor to the OLDEST event of a batch, re-reading newer events every hour (83 duplicate wakes on 43 situations in 24 h) | process oldest-first; cursor lands on the newest handled event; partial batches advance only through what was handled | `test_cio_event_path_t3_20260925.py::test_cursor_lands_on_newest_processed_event_and_second_cycle_is_quiet`, `…partial_batch…` |
| D-SUBJECT | `thesis.changed` (1,814 live rows), `watch.new_signal` (277), `behavioral.flag_raised` (17) carry singular `symbol`; the cycle read only `symbols` → 110/228 event wakes subject-less | `_payload_symbols` accepts both shapes; `context.symbol/symbols` set | `…singular_symbol_becomes_the_wake_subject`, `…payload_symbols_accepts_both_shapes` |
| D-CORR | no stable correlation id from event to receipt | `context.correlation_id = event_id`, `event_ts`, `source_sha` on every EVENT_BUS wake; store-level `priority` honored from the producer | `…stamps_source_sha…`, `…high_priority_event_is_stored_as_high` |
| D-LIFO | `list_wakes` newest-first + 5 slots → older PENDING wakes starved to the 24 h expiry | `list_wakes(order="priority_fifo")` (high→normal→low, then oldest); dispatcher over-fetches and caps at `max_dispatches` | `…priority_fifo_order…`, `…dispatcher_claims_oldest_pending_first` |
| D-RECOVER | lease recovery scanned only the 50 newest streams, re-released without limit, could not move stranded IN_FLIGHT wakes (no IN_FLIGHT→PENDING transition by design) | whole-store scan; `release_count` in the projection; dead-letter EXPIRED after `MAX_LEASE_RECOVERIES=3` with reason `dead_letter:…`; IN_FLIGHT/ACKNOWLEDGED older than `STALE_IN_FLIGHT_SECONDS` (6 h) EXPIRED as `stale_in_flight:…`; `store.last_dead_lettered` surfaced by the dispatcher log | `…dead_letters_after_max_recoveries`, `…scans_beyond_fifty_newest_streams`, `…stale_in_flight_wake_is_expired_with_reason` |
| D-OUT | `CIOActionLedger.list_events` indexed `stream_id` on legacy rows (88/108 live rows, incl. the current tail row) → `KeyError` from every `create_action` since 2026-08-27: zero actions and zero operator notifications from the dispatcher path | tolerate legacy rows in `list_events`, `list_actions`, `_get_last_event_hash` | `…action_ledger_tolerates_legacy_rows_without_stream_id` |

Not fixed here (reported): the ledger's tail row is legacy-shaped, i.e. a second writer still appends the old shape to the same file (two writers, one file); `on_run_completed` is only called with the worker's exit status, so non-terminal worker statuses still leave a wake IN_FLIGHT until the new 6 h stale expiry names it; retries (`RETRY_PENDING`) remain unused; receipt ids stay deterministic per (agent, source, purpose) so a later wake's re-consumption of the same source is deduplicated rather than receipted.

## 3. The chain: research → record → advice → feedback/goals → outcome → belief → later judgment

| Hop | Served state (measured) | Branch fix | Control |
|---|---|---|---|
| Research → record | M1 OBSERVED but evidence 00:03Z predates the 13:15Z promotion | verifier now states `OBSERVED_PRE_DEPLOY` | `test_report_maturity_bar…::test_served_gate_places_evidence_against_promotion` |
| Record consolidation | selector loaded the append-only record file line by line; the OLDEST version per subject won the `seen` guard, so `HELD:NOC` was always "due" and took the reserved slot every hour | `latest_record_per_subject` tip collapse; critique writeback stamps `record_as_of_before/after`, honors `TRADEAI_WAKE_INSTRUMENT_RECORDS_PATH` / `TRADEAI_WAKE_CRITIQUE_ARTIFACT_PATH` (hermetic replay) | `test_cio_cognition_chain…::test_selector_uses_latest_record_version_not_oldest`, `…critique_writeback_paths_honor_env_overrides` |
| Advice (L3 judgment → commitment) | `context["judgment"]` set before `decide()` and read by nothing; cortex-shadow rebuilt a template | `default_decide` mints `L3_JUDGMENT` only for a directional stance with a claim and a NON-vacuous falsifier; INSUFFICIENT/ABSTAIN/NEUTRAL fall through (view, not prediction) | `…mints_from_directional_judgment_with_real_falsifier`, `…ignores_insufficient_or_vacuous_judgment` |
| Feedback (operator turn) | turn 115 replayed as the primary decision on 308 ADBE wakes | turns already consumed with a behavioural effect are marked `already_consumed` from the receipts store and skipped; a live turn still outranks the judgment | `…operator_turn_outranks_judgment_but_consumed_turn_does_not` |
| Goals | run `trigger_ref` is `wake_goal_<goal>_<bucket>`, loader accepted only `goal_…` → 0 runs ever bound a goal (11,950 wakes on `goal_695a5dbe2401`); `due_ts` never advanced so the goal was due every cycle; `lane_close_goal` called `close_goal` without the required `evidence=` | `goal_id_from_trigger_ref`; `record_wake` advances a past-due `due_ts` by `cadence_hours` (default 24 h) through a durable `next_due_ts` in the event; lane passes evidence + falsifier and refuses (`no_falsifier`) rather than raising | `…goal_id_recovered…`, `…record_wake_advances_past_due_ts_one_cadence`, `…lane_close_goal_refuses_without_falsifier_and_passes_evidence` |
| Outcome → belief | writer dry run: 8 beliefs on BND/SCHD/V/XLI/JEPI; **no belief exists on any served record yet** (first scheduled write 18:50 ET today) | — (no production run forced) | — |
| Belief → later judgment | `BELIEF_REVIEW` unreachable whenever any memory fact existed (always, live); wake surfaced `latest_belief` while the research gate acted on `weak_beliefs` | belief branch moved above memory salience; `salient_belief` (weakest sufficiently-sampled, else latest) used by the wake | `…belief_review_now_reachable_with_memory_facts_present`, `…salient_belief_prefers_weak_settled_over_latest`; same-input counterfactual: `tests/test_instrument_belief_mutation_20260925.py` |
| Consumer proof of shared memory | `THREE_WAY_SHARED` proves co-location, not reading | `MemoryConsumptionReceipt@v1` (`scripts/lib/memory_consumption_receipt.py`), written by `advisory_desk_operator.join_durable_memory` and `research_prompt_context._memory_context` (Hermes) only when memory ids were returned; summarized in the daily `MemoryShadowMeasure@v1` as `consumer_receipts` | `…consumption_receipt_written_only_when_memory_ids_returned`, `…receipt_carries_no_behavior_fields` |

## 4. Evidence matrix — AGENTS.md §15 M1–M5 on the served SHA

`scripts/report_maturity_bar_m1_m5.py` (branch version, read-only against served persistent-state, 14:36Z). `verdict` reads the artifact as before; `served_verdict` is what may be claimed for the deployed SHA.

| Proof | verdict | served_verdict | evidence as_of | note |
|---|---|---|---|---|
| M1 Research | OBSERVED | **OBSERVED_PRE_DEPLOY** | 2026-09-25T00:03:26Z | persist of `next_eligible_at`, `cc_narrative` on 5 subjects, before 13:15Z promotion |
| M2 Advice | OBSERVED | **OBSERVED** | 2026-09-25T14:01:24Z | critique `crt_4107cafde6cfaf0e567b8c7b` changed `next_research_question` on `HELD:NOC`, unattended, on the served pin |
| M3 Feedback | OBSERVED | **OBSERVED_PRE_DEPLOY** | 2026-09-24T22:10:24Z | operator `defer` on `HELD:SCHD` changed the question vs counterfactual, before promotion |
| M4 Consistency | PARTIAL | PARTIAL | 2026-09-20T06:01:58Z | soak ledger 128.6 h old, observed pin `8c12ea757` ≠ served; census 2026-09-20 |
| M5 Persistence | OBSERVED | **OBSERVED_PRE_DEPLOY** | 2026-09-25T12:55:14Z | `changed_by_record=5` (a recorded disposition, not a cadence skip), 20 min before promotion |

`observed_on_served_sha = 1/5`. Verifier changes: `served_runtime()` block (pin SHA, promoted_at, boot_at), per-proof `served_gate`, M4 48 h freshness + observed-pin check, M5 counts only `decisions_changed_by_record` (a cadence skip is the record honoring its own prior write and is reported as CANDIDATE), hermetic when given an explicit root.

## 5. The twelve Alex gates (bridge, read-only against served persistent-state)

Passing 0/12 · failing 4 · not measured 8 · promotable False (HUMAN_ONLY). Real denominators, no default PASS:

| Gate | measured | change on this branch |
|---|---|---|
| min_artifact_population | 82 / 100 | — (population frozen since 2026-08-10; see D-OUT) |
| retrieval_provenance_completeness | **0/82** (was 78/78 "domain present") | measures non-empty `evidence_refs` AND `source_snapshot_id`; 78 rows carry an empty `evidence_refs` list |
| independent_review_coverage | 0/82 | sentinel writer now stamps `artifact_id` per affected action so future rows join |
| independent_score_coverage | 78/82 | Darwin scorer no longer asserts `reviewer: "iris"`; reviewer comes from actual review rows or is None — expect this to FALL once new scorecards are written, because the independence was manufactured |
| gates 5–12 | NOT_YET_MEASURED | unchanged: no store answers them; the bridge names why for each |

`agent_gate_measurements.json` (written hourly at :35) still has no reader on the read side (`gate_status.py`, governance-owned) — reported, not changed.

## 6. Changed-contract inventory

| Contract / surface | Change | Compatibility |
|---|---|---|
| `CIOWakeJobStore.enqueue` | honors top-level `priority` in {high,normal,low} | additive |
| `CIOWakeJobStore.release` | `reason` kwarg; `CIO_WAKE_RELEASED.payload.reason` | additive |
| wake projection | `release_count`, `last_release_reason` | additive |
| `recover_expired_leases` | kwargs `max_recoveries`, `stale_in_flight_seconds`; may EXPIRE (dead-letter, stale in-flight); `last_dead_lettered` | behavioural: a wake that expires its lease 4× or sits IN_FLIGHT > 6 h is now EXPIRED with a reason instead of re-queued/stranded |
| `list_wakes(order=)` | `"priority_fifo"` | default order unchanged |
| EVENT_BUS wake `context` | `correlation_id`, `event_ts`, `source_sha`; `symbol` from singular payloads | additive |
| `cio_reactive_cycle.process_event_bus` | extracted from `run_once` | internal |
| `CIOActionLedger` | tolerates rows without `stream_id`/`event_hash` | additive |
| `CIOGoalStore.record_wake` | `GOAL_WAKE_RECORDED.payload.next_due_ts`, `due_advanced_from`; projection sets `due_ts` | additive event field |
| `cio_run_worker.goal_id_from_trigger_ref` | new | additive |
| `run_dormant_lane_consumers close_goal` | passes `evidence`, `falsifier`, `checkpoint_root`; returns `refused[]` | fixes a call that would raise |
| `default_decide` | new `L3_JUDGMENT` commitment kind (fields `falsifier`, `stance`, `horizon`, `judgment_id`, `critique_id`, `evidence_source_ids`); `BELIEF_REVIEW` now precedes `MEMORY_SALIENCE`; consumed operator turns skipped | behavioural for wakes with a directional judgment or a belief |
| `_normalize_selection` | carries `symbol` | additive |
| `cio_instrument_record.salient_belief` | new | additive |
| critique writeback row | `record_as_of_before/after`, `record_version_before`, `store_path`; env overrides | additive |
| `MemoryConsumptionReceipt@v1` | new JSONL `data/cio/memory_consumption_receipts.jsonl`; `consumption_receipt_id` on advisory `durable_memory` join and Hermes `_memory_context` | additive |
| `MemoryShadowMeasure@v1` | `consumer_receipts` section | additive |
| `MaturityBarM1M5Report@v1` | `served`, per-proof `served_verdict`/`on_served_sha`/`evidence_as_of`/`gate_note`, `observed_on_served_sha`; M5 cadence-only → CANDIDATE; M4 freshness | `verdict` unchanged; new fields additive; M4/M5 readings stricter |
| gate bridge gate 2 | evidence_refs + snapshot | stricter measure |
| Darwin scorecard `reviewer` | from review rows, else None; `reviewer_source` | stricter |
| sentinel review rows | one per affected action, `artifact_id` | more rows, joinable |
| `EventEffectLatency@v1` | new report script | new |
| CI | gate `cio_cognition_t3_20260925` registered; digests regenerated | governed surface |

## 7. Rollback plan

Revert the branch merge commit (`git revert -m 1`) and re-run `scripts/regenerate_generated_files.sh`; no migration, flag, cron or data shape was changed. Rows written by the new code are additive and readable by the prior code (`release_count`, `next_due_ts`, `correlation_id`, receipts file) — older code ignores them. Wakes EXPIRED by dead-letter/stale rules are terminal and are not resurrected by a rollback; they are named by reason on their streams.

## 8. Verdicts

**Code readiness (branch head, see PR):** READY FOR INDEPENDENT REVIEW. 40 new controls pass (12 event path, 17 chain, 11 verifier additions), 295 existing tests in the touched suites pass, dark-contract / coverage / line-ending / lane-registry gates clean, digests regenerated. Pre-existing failures on untouched main left alone (`test_p211_restart::test_handoff_persistence`, `test_r18_2_production_hardening` ×3, and the four noted in tranches 1–2). Not deployed; no production state changed.

**Served-runtime maturity (`1c60ecb42`, 14:36Z):** NOT AUTONOMOUS. On the served SHA exactly one of five proofs (M2) is observed post-promotion; M1/M3/M5 are OBSERVED_PRE_DEPLOY and M4 is PARTIAL on a 5-day-old soak of another pin. 0/12 gates pass. Event→first-effect p50 24 min, p95 48 min against a 10-minute objective that is not yet an SLA. No outcome-to-later-judgment trace exists: the chain is **explicitly broken at "settled outcome → belief written on a served record"** — no `beliefs[]` block exists on any served InstrumentRecord, because the belief writer's first scheduled run is 18:50 ET today. The first missing link is therefore a written belief; the next natural observation that could close it is the 18:50 ET `write_instrument_beliefs.py --apply` run (expected 8 beliefs on BND/SCHD/V/XLI/JEPI from 82 settled advisory rows), followed by the next hourly persistent wake that selects one of those subjects. On the served code that wake would still not mint `BELIEF_REVIEW` when a memory fact exists; on this branch it would. The 19:10 ET read-only capture queued by the other session should be inspected for both first-fires.
