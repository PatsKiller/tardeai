# CIO KNOWN_DARK Classification

Status: CLASSIFIED 2026-10-02 · `READ_ONLY_ADVISORY` · classification only

`scripts/check_dark_contracts.py` carries `KNOWN_DARK`, the 2026-08-27 census baseline of modules that define a
versioned schema but have no production consumer. That list said a module was dark. It did not say what should happen
to it. This document classifies every baseline entry, and the CIO operator-evidence coverage block exposes the same
classification as `capability_coverage.known_dark_classification`.

- Machine-readable source: `config/cio_known_dark_classification.json` (`CIOKnownDarkClassification@v1`).
- Census: `python scripts/check_dark_contracts.py --json` on 2026-10-02 reported inherited=25,
  resolved_since_baseline=5, new=0.
- `KNOWN_DARK` is **not** changed by this work, and no module is wired, moved or archived. RETIRE is a proposal:
  per AGENTS.md rule 6 a retired module is archived behind a tripwire and never deleted.
- `cio_operator_evidence` checks that every `KNOWN_DARK` key is classified (`baseline_check`). Any
  unclassified module appears in `unclassified_baseline_modules`.

## Vocabulary

- **WIRE**: should have, or already has, a production consumer
- **RETAIN_WITH_REASON**: no consumer by design; the reason is stated
- **RETIRE**: superseded; proposal only. Archive with a tripwire, never delete (AGENTS.md rule 6)

## CIO-relevant (21)

| Module | Census | Classification | Reason | Consumer / successor | Action |
|---|---|---|---|---|---|
| `scripts/lib/cio_advisory_notify.py` | INHERITED_DARK | **RETIRE** | Superseded by the live notification chain: cio_notification_signal -> operator_notification_outbox -> cio_delivery_mode -> cio_telegram_receipts (coverage rows 'notification policy' and 'delivery/outbox'). A second prepare/send/receipt path would be a competing writer. | scripts.lib.cio_notification_signal + scripts.lib.cio_delivery_mode | PROPOSED |
| `scripts/lib/cio_curation_run.py` | INHERITED_DARK | **RETAIN_WITH_REASON** | CurationRun@v1 is the governance contract for material curation summaries. Curation currently reaches the spine as security_research_spine contributions (kind llm_llm_curation) without this lineage. Wiring it means scheduling governed LLM curation runs, which spends paid model budget: operator decision (AGENTS.md section 17). | operator decision on paid curation cadence | NO_ACTION |
| `scripts/lib/cio_intelligence_outcomes.py` | INHERITED_DARK | **RETIRE** | Its decision/outcome/lesson linkage (DecisionOutcome@v1, ResearchDecisionLink@v1) has no store. The live chain is outcome_observations.jsonl (cio_institutional_learning) -> lesson_candidates.jsonl -> InstrumentRecord beliefs (cio_belief_writer), and the operator-evidence learning link_graph composes those edges from real ids. | scripts.lib.cio_institutional_learning + scripts.lib.cio_belief_writer | PROPOSED |
| `scripts/lib/cio_office_cycle.py` | INHERITED_DARK | **RETIRE** | A second autonomous truth -> CIO -> notify -> memory loop. The office cycle runs through cio_run and the wake lanes (cio_wake_jobs.jsonl, workflow-lineage CIO_GENERATION nodes). Wiring this one would create a competing cycle. | scripts.lib.cio_run + wake lanes | PROPOSED |
| `scripts/lib/decision_rationale.py` | INHERITED_DARK | **WIRE** | DecisionRationale@v1 (auditable reasons that reject private chain-of-thought) is the rationale record the evidence surface lacks. Research reason_used_or_rejected is null for most artifacts because no producer writes a reason. Consumer: the CIO judgment writer (cio_run) emits it; operator evidence displays it. | scripts.lib.cio_run (judgment) -> cio_operator_evidence | PROPOSED |
| `scripts/lib/intelligence_coverage_v2.py` | INHERITED_DARK | **RETIRE** | IntelligenceCoverageMatrix@v2 (SUPPORTED/MISSING) is superseded by the runtime census in cio_operator_evidence capability_coverage (LIVE/PARTIAL/UNWIRED/DARK/UNKNOWN plus freshness). Keeping both would produce two coverage verdicts. | scripts.lib.cio_operator_evidence capability_coverage | PROPOSED |
| `scripts/lib/symbol_thesis_event_wake.py` | INHERITED_DARK | **WIRE** | Adds thesis-coverage checks to existing wake event types (watch.new_signal, hermes.research_promoted, hermes.contradiction_found...) without a new bus. Consumer: cio wake dispatch. It must stay behind the existing SHADOW wake flags until the operator flips persistent wake. | cio_wake_dispatch_entrypoint (SHADOW) | PROPOSED |
| `scripts/materialize_cio_seasonality_history.py` | INHERITED_DARK | **RETAIN_WITH_REASON** | Manual backfill entrypoint for SeasonalityState@v1 inputs (market_ohlcv_bars). It runs once on operator request, so having no scheduler is correct. | manual | NO_ACTION |
| `scripts/refresh_advisory_maturity_evidence.py` | INHERITED_DARK | **WIRE** | Refreshes the read-only evidence that MaturityScorecard@v1 consumes, but nothing schedules it, so the scorecard reads stale snapshots. Wiring needs a crontab entry plus a lane_registry update, which is an operator change. | cron (operator) -> MaturityScorecard@v1 | PROPOSED |
| `scripts/symbol_thesis_integration_audit.py` | INHERITED_DARK | **RETAIN_WITH_REASON** | Manual read-only audit (no backfill, no enqueue). Run on demand after symbol-thesis changes. | manual | NO_ACTION |
| `scripts/r71_health_audit.py` | INHERITED_DARK | **RETIRE** | R7.1 release-closeout audit of RAG schedule, Hermes coordinator and Cursor dependency. Its checks now live in health monitors and the coverage census. | health monitor + capability_coverage | PROPOSED |
| `scripts/dump_research_prompt_fixture.py` | INHERITED_DARK | **RETAIN_WITH_REASON** | Acceptance-evidence tool that dumps the redacted stateful research prompt on demand. It has no runtime role. | manual | NO_ACTION |
| `scripts/research_output_token_report.py` | INHERITED_DARK | **RETIRE** | Report for the concluded M2 output-ceiling experiment. No production config depends on it. | none | PROPOSED |
| `scripts/sandbox_output_ceiling_20.py` | INHERITED_DARK | **RETIRE** | Sandbox for the concluded M2 output-ceiling experiment (writes data/cio/sandbox only). | none | PROPOSED |
| `scripts/repair_hermes_backlog_taxonomy.py` | INHERITED_DARK | **RETAIN_WITH_REASON** | Manual repair tool (preview by default, --apply edits evidence_json only). Keep until the librarian backlog taxonomy is proven clean. | manual | NO_ACTION |
| `scripts/lib/r17_gui_pane.py` | INHERITED_DARK | **RETIRE** | Single-ticker GUI projection superseded by the CIO hub and security card surfaces. | CioHub / security card | PROPOSED |
| `scripts/lib/memory_vector_index_benchmark.py` | INHERITED_DARK | **RETAIN_WITH_REASON** | Deterministic vector-index harness. HNSW/IVFFlat stay UNMEASURED until a Postgres shadow workload runs (pgvector is installed). Keep it as the benchmark vehicle. | manual benchmark | NO_ACTION |
| `scripts/lib/embedding_policy.py` | INHERITED_DARK | **RETIRE** | EmbeddingPolicy@v1 duplicates scripts/lib/ollama_embedding_policy.py, which is the module its apparent consumers actually import (census 2026-08-30 substring collision). | scripts.lib.ollama_embedding_policy | PROPOSED |
| `scripts/lib/hermes_golden_judge.py` | RESOLVED_SINCE_BASELINE | **WIRE** | A consumer now exists (check_dark_contracts resolved_since_baseline, 2026-10-02). No action here; the KNOWN_DARK entry can be dropped in a separate change. | already wired | ALREADY_WIRED |
| `scripts/lib/memory_m2_v2.py` | RESOLVED_SINCE_BASELINE | **WIRE** | A consumer now exists (resolved_since_baseline, 2026-10-02). | already wired | ALREADY_WIRED |
| `scripts/lib/proactive_cio.py` | RESOLVED_SINCE_BASELINE | **WIRE** | A consumer now exists (resolved_since_baseline, 2026-10-02). | already wired | ALREADY_WIRED |

## Outside the CIO surface (9); classified so the baseline check is complete

| Module | Census | Classification | Reason | Consumer / successor | Action |
|---|---|---|---|---|---|
| `scripts/lib/alert_semantic_aggregation.py` | INHERITED_DARK | **RETAIN_WITH_REASON** | Comms-layer aggregation of alert events by meaning. The owner is outside the CIO evidence surface, and it is a candidate for the comms editor chokepoint. | comms owner | NO_ACTION |
| `scripts/lib/control_plane_contract_v1.py` | INHERITED_DARK | **RETAIN_WITH_REASON** | Frozen ControlPlane@v1.0.0 types. The frontend consumes them through JSON fixtures, not Python imports, so the gate cannot see the consumer. | apps/command-center-v3 fixtures | NO_ACTION |
| `scripts/lib/free_first_scheduler_health.py` | INHERITED_DARK | **RETAIN_WITH_REASON** | FREE_FIRST timer health predicate, exercised by CI and tests. Its health-monitor owner is outside CIO. | health monitor owner | NO_ACTION |
| `scripts/lib/provider_spend_snapshot.py` | INHERITED_DARK | **RETAIN_WITH_REASON** | Opt-in (--write) provider spend snapshot documented in docs/ops/MATURITY_SCORECARD.md and run by hand. | manual | NO_ACTION |
| `scripts/audit_local_model_decommission.py` | INHERITED_DARK | **RETAIN_WITH_REASON** | Evidence collector to run before any operator-authorized model removal. It is manual by design. | manual | NO_ACTION |
| `scripts/lib/r18_2_closeout.py` | INHERITED_DARK | **RETIRE** | R18.2 local closeout with zero references repo-wide. | none | PROPOSED |
| `scripts/lib/r18_data_closeout.py` | INHERITED_DARK | **RETIRE** | R18-DATA.1 local closeout. The release is closed. | none | PROPOSED |
| `scripts/lib/tradeai_record_envelope.py` | RESOLVED_SINCE_BASELINE | **WIRE** | A consumer now exists (resolved_since_baseline, 2026-10-02). | already wired | ALREADY_WIRED |
| `scripts/repair_health_threshold_tuning_noise.py` | RESOLVED_SINCE_BASELINE | **WIRE** | A consumer now exists (resolved_since_baseline, 2026-10-02). | already wired | ALREADY_WIRED |

## Summary

| Census state | WIRE | RETAIN_WITH_REASON | RETIRE |
|---|---|---|---|
| INHERITED_DARK | 3 | 11 | 11 |
| RESOLVED_SINCE_BASELINE | 5 | 0 | 0 |

The three inherited WIRE items each need a decision before they can be built: `decision_rationale`
(a CIO judgment writer change), `symbol_thesis_event_wake` (stays behind the SHADOW wake flags until the operator
flips them) and `refresh_advisory_maturity_evidence` (a crontab and lane_registry change, which is operator-only).
The five resolved entries have consumers now; their `KNOWN_DARK` lines can be removed in a separate change to
`check_dark_contracts.py`.
