# CC-OBS-NEVER-SCHEDULED-COUNT: Stop counting intentionally unscheduled entries as unmeasured jobs

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-165 in docs/governance/OPEN_ITEMS.md.
Priority: P0. Owner: platform. Review by: 2026-11-03.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Integrate b48296dad's explicit not_scheduled population. Keep real applied receipts as registry/runtime drift, without inventing a schedule.

## Acceptance evidence

All 32 members show Not scheduled and no next due. Their count is separate from due-today/active evidence gaps; future or dry-run receipts cannot prove installation.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 32. Member SHA256: e3284bf17306ea07e03ff59d42cadbd702b1acf2500bb42872ef9dc1de404e8f.

- agent-claim-compact
- alert-quality
- archive-offbox-sync
- backup-verify
- cio-company-facts-populate
- cio-residual-web
- counterfactual-ledger
- db-hygiene-nightly
- docs-index
- hermes-learning-outcome-feedback-agent
- lane-governance-packet-weekly
- main-red-autoheal
- options-desk-quote-refresh
- portfolio-backup
- portfolio-daily
- portfolio-lookthrough
- portfolio-monthly
- portfolio-weekly
- pr-merge-digest
- pr-merge-reconcile
- pr-merge-telegram-notify
- prospectus-deliver
- release-window
- storage-watch
- tmp-hygiene-apply
- tmp-hygiene-pressure
- trade-ai-restore-drill
- tradeai-flash-portfolio-risk-hourly
- tradeai-flash-portfolio-risk-weekend
- tradeai-governance-facts
- tradeai-governance-status
- tradeai-maturity-board
