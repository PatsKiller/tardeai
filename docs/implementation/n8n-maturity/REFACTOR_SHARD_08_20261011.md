Status: SOURCE_ONLY LOCAL_SOURCE_PROPOSAL — not live
as_of: 2026-10-11
Owner: Codex refactor shard 08

# Refactor shard 08

Frozen source base `9f602186a958df4c2d9f36f04a0ad1809bfce808`; branch `n8nmat/refactor-shard-08`. Two new DRAFT proposals among 37 assigned lanes. Existing reviewed rows remain unchanged. No scheduler, release, n8n import, sends or broker changes.

`agent-recommendation-normalizer --apply --dry-run` now returns before env/DB access. Its implicit no-apply READ ONLY database preview remains available. Real runs retain the legacy underscore receipt and add the canonical lane-id receipt; connection/loader failures keep previous ok_at and raise the original error. Its own loader names DB fields only; shared session13_db dotenv loading remains report-mode debt.

`hermes-score-event-feeder --apply --dry-run` returns before config, kill-switch, DB and heartbeat access. Real runs preserve queue deduplication, scope policy, stdout and exit behavior, adding a canonical receipt. Soft kill-switch failure keeps exit0 and does not advance ok_at. Existing heartbeat is preserved; queue is hermes_score_event_queue, not a new queue abstraction.

Exact argv proof comes from the native-approved scoped cron snapshot `authorized_cron_snapshot_05_08.json` at `2026-10-11T17:05:28.513179+00:00`; only selected matching jobs were captured. The normalizer has no outer cron flock: `/tmp/agent-recommendation-normalizer.lock` is proposed only, requiring a governed operator packet before canary. Feeder preserves `/tmp/hermes_event_feeder.lock`. Both live_arg=null, env_allowlist_mode=report, retries=none, contracts=DRAFT. Live run counts and SLOs are NOT_MEASURED, never a measured zero.

Tests use pre-import empty dotenv fixtures, isolated state/home, M2_SKIP_DOCKER=1 and inherited DB/socket/production-file barriers from the first run. Frozen base entrypoints prove actual cron business argv compatibility. Removing the new preview guard reaches a fake work boundary and fails. Existing implicit preview and real SQL tests remain; explicit-preview tests now forbid the connection instead of accepting reads.

Evidence: local REFACTOR_EVIDENCE_08.md, refactor-gates-08/summary.json, tests/fixtures/refactor_shard_08/cron_argv.json and legacy_entrypoints.json. Required source gates and any review/isolation refusals must be assessed at the exact local head before integration. All production/runtime/natural-fire acceptance is NOT_MEASURED.

## Per-lane disposition

| Lane | Result | Reason |
|---|---|---|
| hermes-top20-external-intel | BLOCKED | Cross-child named provider research routes need governed process/closure review; no model invoked. |
| autonomy-watchdog | BLOCKED | Systemd timer requires separate supported admission shape and host evidence; NOT_MEASURED. |
| portfolio-price-cache | BLOCKED | Systemd timer requires separate supported admission shape and host evidence; NOT_MEASURED. |
| operator-answer-quality-audit | BLOCKED | Systemd timer requires separate supported admission shape and host evidence; NOT_MEASURED. |
| slo-burn-rate | BLOCKED | Systemd timer requires separate supported admission shape and host evidence; NOT_MEASURED. |
| run-cio-event-detector-once-at-0-9 | BLOCKED | Retired registry row retained; not resurrected from historical shard list. |
| tradeai-agent-runtime-pulse | BLOCKED | Systemd timer requires separate supported admission shape and host evidence; NOT_MEASURED. |
| indicator-cache-refresh | SKIP_SENDER | Sender call path excluded; notification-intent migration is separate. |
| after-close-pipeline-close-capture | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| after-close-pipeline-planning | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| orchestrator-slot | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| due-diligence-questions | BLOCKED | Shared offpeak launcher and provider-named curation/research process need integrator governance review. |
| hermes-usefulness-backfill | BLOCKED | Provider-named feedback-loop route and shared offpeak launcher are outside shard-only admission. |
| agent-outcome-scorer | BLOCKED | Already shadow/REVIEWED on frozen main; preserve existing authority and reviewer fields, no new admission. |
| agent-recommendation-normalizer | SHADOW_READY | SOURCE_ONLY DRAFT proposal; guarded CLI/fake work tests; no runtime activation. |
| alert-daily-digest | SKIP_SENDER | Sender call path excluded; notification-intent migration is separate. |
| momentum-scalp-advisory-alerts | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| cleanup-stale-proposals | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| compute-intraday-vwap | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| compute-source-weights | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| defense-weekly-paid-review | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| etf-analyst-enrich | BLOCKED | Already shadow/REVIEWED on frozen main; preserve existing authority and reviewer fields, no new admission. |
| hermes-score-event-feeder | SHADOW_READY | SOURCE_ONLY DRAFT proposal; guarded CLI/fake work tests; no runtime activation. |
| hermes-youtube-discovery | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| trade-ai-scalp-live | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| overnight-batch-tax | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| overnight-batch-outcomes | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| rag-indexer | BLOCKED | rag_retrieval.embed_text uses lib.ollama_embedding_policy; Ollama retired, model selection awaits operator. |
| reconcile-pullback-outcomes | BLOCKED | Price helper imports holdings_gain_guardian._bars_with_volume; financial/broker closure excluded. |
| record-decision-outcome | BLOCKED | Already shadow/REVIEWED on frozen main; preserve existing authority and reviewer fields, no new admission. |
| refresh-operator-product | SKIP_CLASS | Operator monitoring/cache projection is outside R1 ingest/llm/learn admission. |
| reporting-engine | BLOCKED | Cron uses inline Python eligible_report_payload call; shared reporting engine/CLI routing change needs integrator. |
| run-afterhours-candidate-preparation | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| run-scalp-volume-profile-refresh | SKIP_BROKER | Financial/broker-adjacent metadata or source import boundary; implementation left untouched. |
| hermes-shadow-scorer | BLOCKED | Systemd shape and versioned execution root require runtime/timer evidence; no host state inferred. |
| topic-ingestion | BLOCKED | Actual approved family runner owns cadence; child paid/cookie/model closure cannot become a second scheduler. |
| youtube-cookie-health-check | SKIP_SENDER | Sender call path excluded; notification-intent migration is separate. |
