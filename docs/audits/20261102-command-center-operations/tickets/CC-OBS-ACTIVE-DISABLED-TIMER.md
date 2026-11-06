# CC-OBS-ACTIVE-DISABLED-TIMER: Resolve active declarations with disabled or unloaded timers

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-158 in docs/governance/OPEN_ITEMS.md.
Priority: P1. Owner: platform. Review by: 2026-11-05.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Reconcile each of eight contradictory declarations with its owner. Template instances may intentionally be unloaded; restore or retire is an owner decision.

## Acceptance evidence

Actual runtime intent and registry agree for every member, with evidence and approved changes. No timer is enabled merely to make the page green.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 8. Member SHA256: f30510e8b258b9efbe68d39b3e04c75ef8491183aff0160d0d00cde802919111.

- db-retention-timer
- mcporter-token-refresh
- systemd-tmpfiles-clean
- tradeai-agent-runtime-atlas
- tradeai-agent-runtime-concierge
- tradeai-agent-runtime-hermes
- tradeai-agent-runtime-pulse
- tradeai-iris-taxonomy
