# CC-OBS-MTIME-NOT-SUCCESS: Replace modification-time evidence with run completion

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-164 in docs/governance/OPEN_ITEMS.md.
Priority: P1. Owner: platform. Review by: 2026-11-05.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Preserve mtime only as capture/source metadata. Reuse existing wrapper and receipt infrastructure to record identity, start, finish, exit and output.

## Acceptance evidence

All members have actual completion evidence or an explicit missing instrumentation state; touching a log must not change success or last-success time.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 198. Member SHA256: 90d8c894d36f479d7e7b6789bdb6ef6aba1bdc43d877966d4eaffd0d1bf60bf3.

- active-trader-micro-recorder
- active-trader-micro-recorder-premarket
- active-trader-premarket-watch
- active-trader-signal-calibration
- advice-digest
- aegis-synthesis
- after-close-pipeline-broker-truth
- after-close-pipeline-close-capture
- after-close-pipeline-planning
- agent-event-router
- agent-number-grounding-slo
- agent-recommendation-normalizer
- agent-watchlist-engine
- alert-dispatcher-unified
- alpaca-paper-reconciler
- alpaca-stop-manager-oco-repair
- alpaca-stop-manager-rth
- analyst-urgent-refresh
- approval-package-reminder
- approval-reminder-reconcile
- ask-alerts
- audit-enrichment-coverage
- audit-position-basis
- auto-enrichment-runner
- auto-proposal-general
- auto-research
- broker-stop-reconcile
- build-hermes-canonical-status
- catalyst-momentum-engine
- cio-lineage-completion-report
- cio-opportunity-curator
- cio-stance-classification-drain
- claude-escalation-handler
- cleanup-stale-proposals
- comms-lifecycle
- compute-intraday-vwap
- compute-source-weights
- data-gap-resolver-pre
- data-gap-resolver-weekly
- deepseek-balance-snapshot
- defense-inverse-stoplights
- defense-recommendations
- defense-weekly-paid-review
- deploy-detect
- deploy-monitor
- deploy-recompute
- directive-keyword-enhancer
- drain-discovery-backlog
- due-diligence-questions
- enrich-proposal-technicals
- eod-open-trade-alert
- event-detector
- external-market-data-ingest-fundamentals
- fee-efficiency-analyzer
- fidelity-stop-sync
- finviz-momentum-scalp-early-lane
- generate-analyst-reports-autonomous-full
- generate-analyst-reports-autonomous-weekly
- generate-max-hold-exit-proposals
- goal-loop-baseline
- grok-stop-review
- health-agent-llm-review
- hermes-cross-source-synthesizer
- hermes-directive-discovery
- hermes-discovery-ingestors
- hermes-learning-pipeline-learn
- hermes-learning-pipeline-tune
- hermes-overnight-pipeline-close
- hermes-overnight-pipeline-night
- hermes-score-alerts
- hermes-think-tank
- holding-protection-advisor-at-5-17
- holding-protection-advisor-lane
- holdings-gain-guardian
- incubator-llm-screener
- industry-momentum-groups
- ingest-tos-watchlists
- intel-auto-discovery
- ipo-lockup-alert
- iris-taxonomy-agent-at-0-10
- iris-taxonomy-agent-freshness
- iterate-research-topics
- journal-annotation-reminder
- journal-review-builder
- llm-deferred-drain
- llm-intelligence-enrichment
- llm-intelligence-enrichment-section
- market-regime-collector
- material-change-notifier-stage2
- maturity-remeasure
- momentum-cache-reconcile
- momentum-scalp-advisory-alerts
- monthly-protection-meta-review
- moomoo-live-read-sync
- morning-brief-0730
- multi-tier-trade-reviewer-monthly
- multi-tier-trade-reviewer-overnight
- multi-tier-trade-reviewer-weekly
- news-ingestion
- news-ingestion-tail
- oauth-lane-keepalive
- options-chain-snapshot
- options-intent-matcher
- options-iv-snapshot
- orchestrator-slot
- overnight-batch-tax
- oversight-weekly-digest
- paper-execution-quality
- paper-execution-quality-analyzer
- paper-performance-governance
- paper-trade-advisory
- persistent-wake-hourly
- plan-drift-revalidator
- portfolio-broker-reconciliation
- portfolio-level-qa
- portfolio-lookthrough-themes
- portfolio-repricer
- positions-proof-daily
- positions-shadow-diff
- positions-sync
- premarket-data-pipeline
- premarket-watcher
- pro-analyst-fetch
- process-reaper
- proposal-enrichment-loop
- proposal-lifecycle
- proposal-llm-review-worker
- proposal-monitor
- protection-atm-pass
- rag-indexer
- reclassify-momentum-proposals
- reconcile-alpaca-paper-options
- reconcile-exit-advisory-outcomes
- reconcile-pullback-outcomes
- reconcile-watch-outcomes
- refresh-operator-product
- reporting-engine
- research-intelligence-queue
- research-scheduler
- rotation-autopilot
- run-broker-proposal-curator
- run-broker-queue-autocal
- run-inference-cycle-midday
- run-inference-cycle-postclose
- run-inference-cycle-preopen
- run-options-monitor
- run-pullback-macd-monitor
- run-research-intelligence-overnight-archive
- run-scalp-shadow-logger
- run-scalp-volume-profile-refresh
- run-scheduled-quote-refresh-incubator
- run-scheduled-quote-refresh-pending
- run-scheduled-stale-proposal-sweeper-at-25-8
- run-scheduled-strategy-audits
- run-scheduled-two-way-curation-desk
- run-scheduled-two-way-curation-options
- run-scheduled-watchpool-alerts-diagnostic
- run-scheduled-watchpool-alerts-maturity
- run-warrior-weekly-audit
- run-watchlist-agent-jobs-offpeak
- schwab-econfirm-reconcile
- schwab-position-sync
- schwab-transaction-ingest-at-3-18-33-48-9-16
- schwab-transaction-ingest-classifier
- screener-go-alerts
- sec-filings-feed
- sec-fundamentals-ingest
- sector-momentum-engine
- send-telegram-proposal-alert
- set-purge-dates
- shadow-batch-generator-at-15-10
- snaptrade-activity-ingest
- snaptrade-sync
- social-ingest-stocktwits
- social-scalp-scanner
- start-trade-ai-lab-moomoo-opend
- stop-drift-alert
- strategy-tilt
- strategy-weekly-review
- sweep-schwab-instruments
- sync-basis-from-broker
- technicals-gap-backfill
- telegram-smart-alerts
- topic-curator-at-30-9-13
- topic-ingestion
- wake-selection-feed
- warm-caches
- watch-alerts-eval
- watch-directive-hygiene
- watch-directives-service
- watch-review-workers
- watch-review-workers-cio
- watchlist-entry-planner-limit
- watchlist-entry-planner-scope
- watchlist-hygiene
- write-state-freshness-history
- youtube-channel-discovery
- youtube-transcript-ingest
