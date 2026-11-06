# CC-OBS-SYSTEMD-SCHEDULE: Expose actual systemd timer recurrence and run evidence

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-170 in docs/governance/OPEN_ITEMS.md.
Priority: P1. Owner: platform. Review by: 2026-11-05.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Integrate the existing #2444 census/read-model work and verify it against generic timer metadata. Last and next timer fire are not themselves successful service output.

## Acceptance evidence

Every enabled timer has measured recurrence, correlated service completion and output; continuous services stay separate.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 75. Member SHA256: 7078a7bb1a66719d0633e8bc7a88503933b77735dda8188120adc08dc46ed205.

- advisory-lessons-reflect
- advisory-outcome-scorer
- advisory-shadow-seed
- aegis-overnight
- aegis-surveillance
- agent-runtime-health
- agent-worktree-retention
- autonomy-watchdog
- cio-defer-revisit
- cio-delivery
- cio-desk-memo-regen
- cio-material-scan
- cio-memory-shadow-measure
- cio-nightly-reflection
- cio-reactive-cycle
- cio-wake-turn-effects
- contradiction-adjudicator
- data-plausibility-audit
- data-source-health-audit
- disk-pressure-guard
- edge-fanout-consumer
- eod-consolidated-close-sync
- expected-services-audit
- finviz-view-contracts
- free-first-circulation
- gap-resolution-audit
- gir-projector
- governance-pipeline
- health-tick
- hermes-backlog-health-check
- hermes-deep-research-local
- hermes-librarian-backlog-loop
- hermes-librarian-retention
- hermes-observation-check
- hermes-shadow-scorer
- hermes-update-check
- holdings-agent-enqueue
- launchpadlib-cache-clean
- n8n-lab-watchdog
- operator-answer-quality-audit
- platform-maintenance-monthly
- platform-maintenance-nightly
- platform-maintenance-weekly
- portfolio-backup-cadence
- portfolio-daily-cadence
- portfolio-lookthrough-cadence
- portfolio-monthly-cadence
- portfolio-price-cache
- portfolio-weekly-cadence
- postgres-main-watchdog
- premarket-delivery-deadman
- provider-cost-reconcile
- recovery-watch
- research-lane-health
- served-copy-split-audit
- slo-burn-rate
- sm-render
- snap-firmware-updater-firmware-notifier
- source-litmus-vs-yahoo
- supervisor-breach-detector
- tax-lots-rebuild
- trade-ai-news-monitor
- tradeai-advisory-notif-broker
- tradeai-aec-command-center-cycle
- tradeai-agent-runtime-alex
- tradeai-agent-runtime-morgan
- tradeai-agent-runtime-producer
- tradeai-agent-runtime-steph
- tradeai-backup-enforcer
- tradeai-hermes-cio-worker
- tradeai-maturity-feeds
- tradeai-watch-decision-scheduler
- ubuntu-insights-collect
- ubuntu-insights-upload
- weekly-disk-cleanup
