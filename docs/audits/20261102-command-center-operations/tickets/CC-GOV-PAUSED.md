# CC-GOV-PAUSED: Adjudicate paused declarations

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-156 in docs/governance/OPEN_ITEMS.md.
Priority: P1. Owner: coordinator. Review by: 2026-11-05.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Keep paused intent visible, identify the owner decision and prerequisites for each lane. Self-heal remains a separate named activation decision.

## Acceptance evidence

Every paused member has current intent, owner and review date. Installing or arming requires its existing operator authority; intentional pause is never an outage.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 22. Member SHA256: 216a8399077594282e83840aa136872ee55c3a465d7f21a4832330ebf20c8023.

- alex-daily
- alex-gov-research
- alex-hygiene
- alex-monthly
- alex-weekly
- cio-decision-engine
- coder-dispatch
- conflict-rule-proposals
- defense-execution
- hermes-autonomous-loop
- n8n-activation-grants
- n8n-workflow-drift-check
- nightly-cutover-controller
- options-lifecycle-digest
- options-lifecycle-run
- self-heal-fixer
- tradeai-continuous
- tradeai-flash-llm-intelligence
- tradeai-flash-watchlist-daily
- tradeai-hermes-research-remediation
- tradeai-intelligence-remediation
- tradeai-main-desk-free-llm-weekly
