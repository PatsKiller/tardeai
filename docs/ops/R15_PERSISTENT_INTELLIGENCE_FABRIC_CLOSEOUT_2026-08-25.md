# R15 — Persistent intelligence fabric closeout

**Date:** 2026-08-25  
**Authority:** READ_ONLY_ADVISORY · `MEMORY_BEHAVIOR_INFLUENCE=0`  
**Canary:** `CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY` remains unset  
**Cash policy:** `cash_target_range_pct` still POLICY_GAP / unconfirmed  
**PR #505:** still OPEN, not merged

R15 closes the *institutional-intelligence lifecycle* in source. It is not another
notification pass and it is not a second portfolio book.

## What was already true (R14A handoff)

Protected main = CURRENT = `4d0859a5`. 440 tests passing. Exact-main deploy
green. Natural material-scan timer proven. Same-brain live. Free-first hourly
`:23 ET` proven with 120 `FRESH_NO_CHANGE` and zero paid dispatch.

## What R15 added

One fabric, not a rewrite:

1. **Producer inventory + coverage matrix** for 31 live intelligence domains.
   The GUI is explicitly not a producer. 3 domains are fully wired; 28 are
   partial; 0 are source-absent. The matrix names the missing flags.
2. **`IntelligenceDeltaReceipt@v1`** — projection/receipt only. Idempotent on
   source version. Forbidden financial-truth keys stripped.
3. **Deterministic materiality** — `NO_CHANGE` / `NON_MATERIAL_CHANGE` /
   `MATERIAL_CHANGE` / `CONFLICT` / `STALE` / `DATA_UNAVAILABLE`. No model.
4. **Graph impact resolver** that requires membership + exposure + freshness.
   Shared industry/sector *text* does not wake. Peers are context, never
   automatic thesis evidence. Stale and disputed edges do not propagate.
5. **Event-driven free-first pending** hooked fail-soft from the material
   scanner. Order remains TRS → Hermes → RAG → structured → residual SearXNG.
   Generic `<ticker> earnings catalyst 2026` queries are rejected.
6. **`CurationRun@v1`** with dedupe, critique-before-memory, no fake
   `NO_NEW_INFO` versions, rejected runs retained in audit, challenger results
   kept separate, private chain-of-thought stripped.
7. **`ModelTaskPerformance@v1` + `ModelRoutingCandidate@v1`** with a 30-sample
   gate, objective scoring (self-assessment ignored), shadow evaluation on
   fixtures, and a hard forbid on editing `llm_model_registry.json` /
   `llm_process_registry.json`.
8. **Outcome axes** extended with `research_quality` and `model_efficiency`.
   One trade is not methodology. Lessons cannot rewrite policy.
9. **Same-brain agent set** now includes Guardian, Ledger, and Command Center.
   Specialist disagreement is preserved.
10. **Command Center projection** of the lifecycle (`cio-brain-intelligence-lifecycle`
    and related bands) plus
    `GET /api/v3/cio/brain/intelligence-lifecycle` and
    `GET /api/v3/cio/brain/model-performance`. The GUI cannot self-promote
    routes and is not an ingestion bus.

## What was not done (on purpose)

- No exact-main deploy of this branch (not authorized in the R15 prompt).
- No Telegram canary enablement.
- No invented cash band.
- No production SQL / PR #505 merge.
- No autonomous model-policy edit.
- No synthesized live material event to raise maturity.

## Maturity

Overall deployed operating maturity remains **80**. The intelligence *subsystem*
moved from ~70 toward **~78 unit-proven**. Live CURRENT is still R14A.
Do not award 82–88 until this branch is exact-main deployed and natural cycles
are observed.

```yaml
R15_PERSISTENT_INTELLIGENCE:
  start_maturity: 80
  end_maturity: 80
  intelligence_start: 70
  intelligence_unit_proven: 78
  highest_proven_maturity: 80

  main_sha: 4d0859a5a18e5e64f9ebacae19f53c82e290a9d2
  current_sha: 4d0859a5a18e5e64f9ebacae19f53c82e290a9d2
  exact_main: true

  source_domains_total: 31
  domains_fully_wired: 3
  domains_partially_wired: 28
  domains_unwired: 0

  graph:
    entities: [ticker, issuer, sector, industry, subindustry, theme, peer, catalyst, calendar]
    relationships: [LINEAR, LATERAL, VERTICAL, MACRO, CALENDAR]
    unresolved_identities: 17
    cross_entity_propagation_proven: UNIT

  context:
    sections_total: 16
    sections_live: UNIT_CONTRACT
    sections_not_configured: honest_status_never_omitted
    same_brain_live: true

  research:
    hourly_free_first_live: true
    event_driven_free_first: SOURCE_WIRED_NOT_DEPLOYED
    hermes_reuse: true
    rag_reuse: true
    structured_reuse: true
    residual_web: true
    research_gap_lifecycle: true
    free_resolved_without_llm: UNIT

  curation:
    material_versions: UNIT
    no_change_versions_created: 0
    curation_run_lineage: UNIT
    rejected_curations_retained: true
    thesis_linkage: UNIT

  llm:
    unchanged_cycle_calls: 0
    paid_calls: 0
    fast_calls: 0
    fast_think_calls: 0
    challenger_calls: 0
    pro_calls: 0
    average_cost: 0
    average_latency: n/a
    dedupe_proven: UNIT

  model_learning:
    performance_records: 0
    task_cohorts: 10
    routing_candidates: UNIT
    automatic_route_changes: 0
    shadow_evaluation_proven: UNIT

  memory:
    research_admissions: selective_existing
    rejected_admissions: retained
    contradictions: preserved
    temporal_history: UNIT
    outcome_links: UNIT
    lesson_candidates: UNIT
    behavior_influence: 0

  specialists:
    maria: SAME_BRAIN_CONTRACT
    steph: SAME_BRAIN_CONTRACT
    guardian: ADDED_TO_SAME_BRAIN_SET
    ledger: ADDED_TO_SAME_BRAIN_SET
    disagreement_preserved: true

  gui:
    lifecycle_visible: SOURCE
    graph_context_visible: SOURCE
    curation_history_visible: SOURCE
    model_reason_visible: SOURCE
    unwired_providers_visible: SOURCE

  safety:
    broker_changed: false
    risk_changed: false
    two_factor_changed: false
    trading_changed: false
    production_sql_changed: false
    memory_behavior_influence: 0
    model_policy_auto_changed: false

  tests:
    passed: 728
    failed: 0
    prior_r11_r13_still_passing: 440
    combined_passed: 1190
    new_unit: ~163
    integration: 63
    property: 75
    fault: 30
    goldens: 400

  natural:
    scheduled_cycles: 0
    material_cycles: 0
    real_llm_curation_cycles: BLOCKED_REAL_WORLD_EVENT
    zero_cost_no_change_cycles: preexisting_hourly_free_first

  remaining_gaps:
    - exact-main deploy of this branch
    - 10 natural post-deploy cycles
    - event-driven FREE_FIRST_PENDING on a real holdings/catalyst delta
    - 17 unresolved TickerResearchState identities
    - operator-confirmed cash_target_range_pct
    - Telegram canary still a separate authority decision
    - model/task samples below min-n for any routing recommendation
    - specialist natural multi-agent soak still UNIT_PROVEN

  highest_proven_maturity: 80
  next_10_actions:
    - Merge R15 PR to protected main when reviewed
    - Exact-main prepare/promote of the merged SHA
    - Observe 10 natural material-scan + free-first cycles
    - Capture one real event-driven FREE_FIRST_PENDING if it occurs
    - Confirm FRESH_NO_CHANGE still spends $0
    - Do not enable CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY without explicit auth
    - Confirm cash_target_range_pct with the operator
    - Remediate 17 unresolved security_guid rows
    - Accumulate ≥30 objective ModelTaskPerformance samples per cohort before any routing review
    - Soak specialist same-brain on a live Guardian/Ledger/Steph/Maria cycle
  exact_resume_command: |
    git -C /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild fetch origin
    git -C /home/johnclaw/trade-ai-v12-rebuild/wt-r15-intelligence status -sb
    # Deploy only after merge + explicit exact-main authorization:
    # bash scripts/cio_phase2_exact_main_deploy.sh prepare && bash scripts/cio_phase2_exact_main_deploy.sh promote
```
