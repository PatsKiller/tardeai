---
Status: MEASURED (baseline; no new gate is claimed in this file)
as_of: 2026-09-28T11:05:00-04:00
Measured at: served a328a88177833e4b121cf6fec6724f8fbfe2075c
Campaign: LIVEPROOF-20260928
---
# 03 — Maturity board (history preserved; served re-measurement)

Rule (work order §7): a gate passes only with its named outcome, served pin, time, numerator/denominator and observer evidence. NOT_MEASURED stays separate from FAIL. An observation on an older SHA never becomes a served observation by inheritance.

## A. History, kept intact

| Board | Date / pin | Result | Source |
|---|---|---|---|
| Overnight autonomy scoreboard | 2026-09-02, CURRENT `433511415` | four-SHA gate; open PRs #835/#836/#777 listed as unfinished; no verdict authorises action | `docs/ops/CIO_OVERNIGHT_AUTONOMY_SCOREBOARD_2026-09-02.md` |
| Litmus set | 2026-09-01 | wake / money / coverage litmus documents | `docs/ops/litmus/` |
| CIO cognition tranche 3 served verdict | 2026-09-25 | NOT AUTONOMOUS: 1/5 M-proofs on the served SHA, 0/12 gates, p95 48 m vs 10 m target | session record (`wt/cio-cognition-t3-20260925`, local only) |
| Platform due diligence | 2026-09-27, `eb09dcf10` (header) | memory changed 0 of 22,392 wake decisions (MBI = 0 by rail); 128k unresolved contradictions; 5 queue styles; no central chooser | `docs/architecture/PLATFORM_INTELLIGENCE_DUE_DILIGENCE_2026-09-27.md` |
| Cognitive transformation Waves 1–5 tranche 1 | 2026-09-27/28, live on `c1c531500` then superseded by `a328a8817` | independent lane-written maturity 2.89 / 5 (receipts only); every W3–W5 behaviour SHADOW | `docs/ops/COGX_WAVE1_STATUS_2026-09-27.md`, `data/governance/maturity_latest.json` |

## B. M1–M5 (AGENTS.md §15) on the served SHA — `report_maturity_bar_m1_m5.py` 2026-09-28T14:59:23Z

| Proof | Served verdict | Evidence | Gate note |
|---|---|---|---|
| M1 Research | OBSERVED_PRE_DEPLOY | unattended persist 2026-09-28T00:04:19Z (5 persisted; next_eligible_at, cc_narrative changed) | predates promotion 14:14:47Z → needs natural re-observation |
| M2 Advice | OBSERVED_PRE_DEPLOY | critique writeback 2026-09-27T14:00:59Z EXIT:LGPS changed next_research_question | predates promotion |
| M3 Feedback | OBSERVED_PRE_DEPLOY | operator turn 2026-09-24 HELD:SCHD changed next_research_question vs counterfactual | predates promotion |
| M4 Consistency | PARTIAL | bridge pin soak streak 6, but soak stale 201 h (observed pin `8c12ea757`, 2026-09-20) | measurement itself is stale |
| M5 Persistence | **OBSERVED on served** | 2026-09-28T14:55:06Z cron `*/5` wake dispatch: subject_resolved 5, record_found 5, changed_by_record 5 | post-dates promotion |
| **Total** | **1/5 on the served SHA** | | the same shape as 2026-09-25 (1/5) |

## C. 12-gate board (agent `alex`) — `agent_gate_measurements.json` 2026-09-28T14:35:01Z, written hourly by `cio_gate_measurement_bridge.py` from CURRENT

| # | Gate | Status | Numerator / denominator | Reason recorded by the bridge |
|---|---|---|---|---|
| 1 | min_artifact_population | PASS | 28,680 advisory actions in `cio_action_ledger.jsonl` | population exists |
| 2 | retrieval_provenance_completeness | FAIL | 0 / 28,680 | no action carries evidence_refs AND a source_snapshot_id (28,402 refs without snapshot; 28,676 carry only a domain label) |
| 3 | independent_review_coverage | FAIL | 0 / 28,680 | 179 review rows exist; 174 name artifacts outside the action population, 5 carry no artifact id |
| 4 | independent_score_coverage | FAIL | 78 / 28,680 | scorer ≠ producer ≠ reviewer on 78 only |
| 5 | contradiction_rate | NOT_YET_MEASURED | denominator empty (gate 3 = 0) | |
| 6 | unsupported_claim_rate | NOT_YET_MEASURED | — | was hardcoded 0.0; needs a per-claim retrieval-support store |
| 7 | stale_input_refusal_accuracy | NOT_YET_MEASURED | — | was hardcoded 1.0; needs recorded refusals against a known-stale control set |
| 8 | deadline_budget_adherence | NOT_YET_MEASURED | — | per-run store records no elapsed / cost / model-call counts |
| 9 | duplicate_run_rate | NOT_YET_MEASURED | — | only caught duplicates were counted |
| 10 | operator_usefulness | NOT_YET_MEASURED | — | an operator rating; only a Darwin grade proxy (0.5432 over 88) exists |
| 11 | rollback_test_passed | NOT_YET_MEASURED | — | was hardcoded True from a test file's existence |
| 12 | authority_violations | NOT_YET_MEASURED | — | was hardcoded 0 from the existence of a deny-list |
| **Total** | | **1 PASS · 3 FAIL · 8 NOT_YET_MEASURED** | | honest board since the 2026-09-2x un-hardcoding; the earlier "8/12" and "11/12" boards were hardcoded values and are recorded as such in the bridge's docstring |

## D. What this campaign may change

Only rows in B and C that a served observation, replay or shadow trace re-measures; each such change cites `04-muted-and-replay-results.jsonl` by test_id. Nothing in the cognitive-transformation waves is counted here until the corresponding TP test fires on the served release.
