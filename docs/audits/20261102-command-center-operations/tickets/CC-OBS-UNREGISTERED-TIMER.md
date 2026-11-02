# CC-OBS-UNREGISTERED-TIMER: Register the five observed scheduled timers

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-171 in docs/governance/OPEN_ITEMS.md.
Priority: P1. Owner: platform. Review by: 2026-11-05.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Reuse OI-148 for four established timer gaps and #2444 for the breaker probe. Declare actual output receipts and approved intent.

## Acceptance evidence

All five timers have reviewed registry ownership, schedule/output contract and runtime receipts, or a documented retirement decision.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 5. Member SHA256: 5ec2896d3022f24085e93e5260d2bf965de43072ea8bd4392929134cc7d69214.

- runtime-unit:tradeai-deploy-on-main.timer
- runtime-unit:tradeai-incident-daily.timer
- runtime-unit:tradeai-incident-supervisor.timer
- runtime-unit:tradeai-incident-watchers.timer
- runtime-unit:tradeai-n8n-breaker-probe.timer
