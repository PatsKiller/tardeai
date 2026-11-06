# CC-FAIL-MISSED: Account for six observed missed jobs

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-155 in docs/governance/OPEN_ITEMS.md.
Priority: P0. Owner: platform. Review by: 2026-11-03.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Trace scheduler to admission to attempt to output. Reuse #2444 for the three native relay lanes. Preserve the frozen Hermes completion-time limit and protected scalp lock boundary.

## Acceptance evidence

Each member has a proven schedule and attempt/completion evidence or an owner-approved retirement/blocked disposition; no lock removal or speculative rerun.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 6. Member SHA256: 3c026648a3b4f81fc88191d95ddda2f89e076145eff75be72bc7f7f75b5e2e6d.

- crontab-snapshot-for-health-agent
- hermes-subject-enhance-dispatch
- n8n-pilot-dispatch
- n8n-research-intake-consumer
- prospectus-build
- trade-ai-scalp-live
