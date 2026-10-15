# n8n executor env-allowlist enforce readiness (generated)

```
Schema:   N8nEnvEnforceReadiness@v1
Source:   scripts/report_n8n_env_enforce_readiness.py over config/n8n_run_allowlist.json (as_of 2026-10-09)
Method:   static AST closure; names only, never values; READY_NOW is necessary, not sufficient
```

**103 lanes**: 12 enforce, 91 report-pinned. **8 READY_NOW** by static analysis; flip candidates (report + READY_NOW): 3; enforced lanes the analysis would block: 2.

| Blocking reason | Lanes |
|---|---|
| `dynamic_env_reads` | 78 |
| `missing_defaulted_names` | 80 |
| `missing_required_names` | 72 |
| `unbounded_env_loader` | 77 |

| Lane | Mode | Verdict | Closure | Missing required | Missing defaulted | Dynamic | Loaders | .env | Reasons |
|---|---|---|---|---|---|---|---|---|---|
| `advisory-desk-run-now` | report | BLOCKED | 1121 | 4 | 509 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `aegis-brief-regenerate` | report | BLOCKED | 1121 | 4 | 513 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `aegis-evening-packet` | report | BLOCKED | 1122 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `aegis-nightly-ingestion` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `aegis-social-sentiment` | report | BLOCKED | 1122 | 4 | 513 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `aegis-transcript-discovery` | report | BLOCKED | 1122 | 4 | 513 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `agent-calibration-engine` | report | BLOCKED | 6 | 0 | 0 | 0 | 1 | 1 | unbounded_env_loader |
| `agent-number-grounding-slo` | report | BLOCKED | 2 | 0 | 1 | 2 | 0 | 2 | missing_defaulted_names, dynamic_env_reads |
| `agent-outcome-linker` | report | BLOCKED | 7 | 0 | 0 | 0 | 1 | 1 | unbounded_env_loader |
| `agent-outcome-scorer` | report | READY_WITH_RESIDUAL | 7 | 0 | 0 | 0 | 0 | 1 | — |
| `analyst-prospectus-generate` | report | BLOCKED | 1121 | 4 | 513 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `audit-enrichment-coverage` | report | BLOCKED | 1122 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `backup-verify` | report | BLOCKED | 1122 | 4 | 515 | 90 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `catalyst-graph` | report | BLOCKED | 1123 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `catalyst-momentum-engine-overnight` | report | BLOCKED | 1124 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `catalyst-symbol-impact` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `classifier-health-check` | enforce | READY_WITH_RESIDUAL | 4 | 0 | 0 | 0 | 0 | 0 | — |
| `classify-instruments` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `commitment-outcome-sweep` | report | BLOCKED | 31 | 0 | 4 | 2 | 0 | 0 | missing_defaulted_names, dynamic_env_reads |
| `crawl-v3-dashboard` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `crontab-snapshot-for-health-agent` | enforce | READY_NOW | 0 | 0 | 0 | 0 | 0 | 0 | — |
| `daily-incubator-refresh` | report | BLOCKED | 17 | 0 | 10 | 2 | 0 | 1 | missing_defaulted_names, dynamic_env_reads |
| `data-gap-resolver-at-0-10-16` | report | BLOCKED | 1121 | 4 | 518 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `data-gap-resolver-pre` | report | BLOCKED | 1121 | 4 | 518 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `data-gap-resolver-weekly` | report | BLOCKED | 1121 | 4 | 518 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `desk-suggestions-digest` | report | BLOCKED | 1122 | 4 | 513 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `document-mentions-backfill` | report | BLOCKED | 20 | 0 | 11 | 0 | 0 | 0 | missing_defaulted_names |
| `enterprise-backtester` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `etf-analyst-enrich` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `etf-performance-enrich` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `fee-efficiency-analyzer` | report | BLOCKED | 1120 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `feedback-loop-processor` | report | BLOCKED | 1121 | 4 | 514 | 87 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `finviz-enrichment` | report | BLOCKED | 1120 | 4 | 508 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `finviz-enrichment-scalp-hot` | report | BLOCKED | 1120 | 4 | 508 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `finviz-health-check` | report | BLOCKED | 1121 | 4 | 514 | 87 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `finviz-market-movers` | report | BLOCKED | 1121 | 4 | 508 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `finviz-proactive-research` | report | BLOCKED | 1122 | 4 | 516 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `finviz-screener-runner` | report | BLOCKED | 1121 | 4 | 512 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `finviz-sector-research` | report | BLOCKED | 1121 | 4 | 512 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `finviz-view-contracts` | report | BLOCKED | 1121 | 5 | 513 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `generate-analyst-daily-digest` | report | BLOCKED | 1122 | 4 | 511 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `heartbeat-watch` | report | BLOCKED | 1121 | 9 | 512 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-analyst-signal-discovery` | report | BLOCKED | 1123 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-entity-spike-discovery` | report | BLOCKED | 1122 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-governance-api` | report | BLOCKED | 1120 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-learning-autonomous-self-tune` | report | BLOCKED | 1121 | 4 | 525 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-learning-config-governor` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-learning-outcome-feedback-agent` | report | BLOCKED | 1126 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-learning-outcome-grader` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-learning-outcome-learning` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-learning-tag-engine` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-momentum-catalyst-scalp` | report | BLOCKED | 1123 | 4 | 515 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-news-bridge` | report | BLOCKED | 19 | 0 | 2 | 0 | 1 | 2 | missing_defaulted_names, unbounded_env_loader |
| `hermes-pipeline-health` | report | BLOCKED | 1125 | 4 | 517 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-research-agenda-at-45-7` | report | READY_WITH_RESIDUAL | 5 | 0 | 0 | 0 | 0 | 2 | — |
| `hermes-research-worker-pool` | report | READY_NOW | 4 | 0 | 0 | 0 | 0 | 0 | — |
| `hermes-scope-governor` | report | BLOCKED | 1127 | 5 | 513 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-score-event-feeder` | report | BLOCKED | 1122 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-social-sentiment` | report | BLOCKED | 1125 | 4 | 513 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `hermes-topic-monitor-bridge` | report | BLOCKED | 13 | 0 | 1 | 0 | 0 | 0 | missing_defaulted_names |
| `identity-sweep-stage0` | report | READY_WITH_RESIDUAL | 13 | 0 | 0 | 0 | 0 | 0 | — |
| `instrument-belief-writer` | report | BLOCKED | 1121 | 4 | 512 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `investment-costs` | report | BLOCKED | 1120 | 4 | 517 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `job-coverage-monitor` | report | BLOCKED | 1122 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `journal-tilt-morning-hook` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `lane-governance-packet-weekly` | report | BLOCKED | 1127 | 9 | 534 | 89 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `material-change-detector-stage1` | report | BLOCKED | 1122 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `materialize-watchlist-strategy-cards` | enforce | READY_WITH_RESIDUAL | 5 | 0 | 0 | 0 | 0 | 1 | — |
| `maturity-remeasure` | enforce | READY_NOW | 5 | 0 | 0 | 0 | 0 | 0 | — |
| `momentum-cache-reconcile` | enforce | BLOCKED | 1121 | 9 | 516 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `momentum-lifecycle-monitor` | enforce | BLOCKED | 1121 | 9 | 516 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `n8n-comms-intent-consumer` | enforce | READY_NOW | 7 | 0 | 0 | 0 | 0 | 0 | — |
| `n8n-incident-fanin` | report | BLOCKED | 1129 | 4 | 520 | 87 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `n8n-lab-watchdog` | enforce | READY_NOW | 1 | 0 | 0 | 0 | 0 | 0 | — |
| `n8n-pilot-dispatch` | report | BLOCKED | 1122 | 9 | 510 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `n8n-research-intake-consumer` | report | BLOCKED | 1121 | 4 | 513 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `n8n-workflow-drift-check` | enforce | READY_NOW | 6 | 0 | 0 | 0 | 0 | 0 | — |
| `news-to-catalyst` | report | BLOCKED | 1123 | 4 | 516 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `proposal-backtest-engine` | report | READY_NOW | 7 | 0 | 0 | 0 | 0 | 0 | — |
| `record-decision-outcome` | report | READY_WITH_RESIDUAL | 5 | 0 | 0 | 0 | 0 | 1 | — |
| `research-insight-extractor` | enforce | READY_WITH_RESIDUAL | 4 | 0 | 0 | 0 | 0 | 1 | — |
| `resolve-due-checkpoints` | report | BLOCKED | 27 | 0 | 4 | 2 | 0 | 0 | missing_defaulted_names, dynamic_env_reads |
| `scalp-hot-list` | report | BLOCKED | 1122 | 4 | 508 | 87 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `sec-data-ingest` | report | BLOCKED | 10 | 0 | 0 | 0 | 1 | 3 | unbounded_env_loader |
| `sector-rs-daily` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `setup-quality-prior` | enforce | READY_WITH_RESIDUAL | 4 | 0 | 0 | 0 | 0 | 0 | — |
| `signal-fusion-active` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `signal-fusion-full` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `social-ingest-all` | report | BLOCKED | 1121 | 4 | 514 | 87 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `source-attribution-monitor` | enforce | READY_WITH_RESIDUAL | 1 | 0 | 0 | 0 | 0 | 0 | — |
| `storage-watch` | report | BLOCKED | 6 | 0 | 0 | 4 | 0 | 1 | dynamic_env_reads |
| `sync-social-to-intelligence` | report | BLOCKED | 1122 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `trade-ai-restore-drill` | report | BLOCKED | 1123 | 4 | 515 | 90 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `trade-ai-scalp-live` | report | BLOCKED | 1147 | 9 | 529 | 90 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `trade-backtest-engine` | report | READY_WITH_RESIDUAL | 4 | 0 | 0 | 0 | 0 | 0 | — |
| `trade-thesis-review-engine` | report | READY_NOW | 6 | 0 | 0 | 0 | 0 | 0 | — |
| `update-agent-performance` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `update-lockup-earnings-dates` | report | READY_WITH_RESIDUAL | 5 | 0 | 0 | 0 | 0 | 1 | — |
| `validate-expense-ratios` | report | BLOCKED | 1121 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `watch-goods-consistency` | report | BLOCKED | 1122 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `watchlist-enrichment-sweep` | report | BLOCKED | 1120 | 4 | 514 | 86 | 10 | 10 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `weekly-incubator-builder` | report | BLOCKED | 9 | 0 | 14 | 2 | 2 | 2 | missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
| `write-state-freshness-history` | report | BLOCKED | 8 | 1 | 3 | 2 | 1 | 1 | missing_required_names, missing_defaulted_names, dynamic_env_reads, unbounded_env_loader |
