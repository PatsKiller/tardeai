# CC-GOV-PROTECTED-INSTRUMENTATION: Instrument protected lanes under scoped authority

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-157 in docs/governance/OPEN_ITEMS.md.
Priority: P1. Owner: execution. Review by: 2026-11-05.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Only registry and existing receipt metadata were audited. Prepare minimal generic instrumentation boundaries and request the exact engineering/operations grant before subsystem work; preserve broker/order/credential rails.

## Acceptance evidence

Each protected member has a measured safe contract or explicit scope/expiry/owner decision. No broker access or live flag change is inferred from this ticket.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 50. Member SHA256: 3faa2e2536a669040759314cecc22174b05155ba049533d880947f57a176c53d.

- active-trader-micro-recorder
- active-trader-micro-recorder-premarket
- active-trader-premarket-watch
- active-trader-session-review
- active-trader-session-review-close
- active-trader-signal-calibration
- after-close-pipeline-broker-truth
- alpaca-paper-reconciler
- alpaca-stop-manager-oco-repair
- alpaca-stop-manager-rth
- broker-stop-reconcile
- eod-open-trade-alert
- finviz-enrichment
- finviz-enrichment-scalp-hot
- finviz-market-movers
- finviz-momentum-scalp-early-lane
- finviz-screener-runner
- finviz-sector-research
- generate-max-hold-exit-proposals
- ingest-tos-watchlists
- momentum-scalp-advisory-alerts
- options-chain-snapshot
- options-iv-snapshot
- paper-execution-quality
- paper-execution-quality-analyzer
- paper-performance-governance
- paper-trade-advisory
- portfolio-broker-reconciliation
- premarket-watcher
- run-broker-proposal-curator
- run-broker-queue-autocal
- run-options-monitor
- run-options-paper-position-monitor
- run-pullback-macd-screener
- run-scalp-shadow-logger
- run-scalp-volume-profile-refresh
- scalp-hot-list
- schwab-econfirm-reconcile
- schwab-position-sync
- schwab-stream-daemon
- schwab-transaction-ingest-at-3-18-33-48-9-16
- schwab-transaction-ingest-classifier
- snaptrade-activity-ingest
- snaptrade-sync
- social-scalp-scanner
- sweep-schwab-instruments
- sync-basis-from-broker
- trade-ai-scalp-live
- tradeai-active-trader-motion-service
- tradeai-advisory-notif-broker
