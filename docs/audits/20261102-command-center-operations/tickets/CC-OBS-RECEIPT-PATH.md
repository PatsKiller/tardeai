# CC-OBS-RECEIPT-PATH: Repair writer and reader receipt references

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-169 in docs/governance/OPEN_ITEMS.md.
Priority: P1. Owner: platform. Review by: 2026-11-05.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Compare actual writer paths and registered reader paths. Reuse relevant #2444 repairs; do not create a divergent second authoritative store.

## Acceptance evidence

Each member's reader consumes its writer's actual receipt with matching run identity; wrong paths fail visibly and authoritative divergence is escalated.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 23. Member SHA256: 7e231d1a549bc1282c06be12697ff83b7079af9e9dde4b8ae6695e8c8f3c501e.

- active-trader-session-review
- active-trader-session-review-close
- advisory-maturity-evidence
- agent-router-cron-deep
- agent-router-cron-full
- agent-router-cron-light
- calibration-shadow-harness
- cio-ask-research
- cio-portfolio-thesis
- classifier-health-check
- generate-weekly-docx
- held-exit-coverage-monitor
- holdings-drift-monitor
- jsonl-archive-rotate
- momentum-lifecycle-monitor
- options-desk-staleness-monitor
- portfolio-server-watchdog
- run-governed-symbol-thesis-acquisition
- run-options-paper-position-monitor
- run-protection-pipeline-at-30-20
- run-protection-pipeline-at-x-30-9-16
- run-pullback-macd-screener
- yfinance-info-snapshot
