# CC-OBS-CONTINUOUS-SERVICE: Measure continuous services as services

Status: OPEN. Local source fixes do not establish production recovery.
Canonical register: OI-159 in docs/governance/OPEN_ITEMS.md.
Priority: P1. Owner: platform. Review by: 2026-11-05.
Baseline: 2026-11-02T18:45:27.608050Z. Recorded: 2026-11-02T19:41:04Z.

## Required action

Use liveness, restart/error and heartbeat contracts rather than inventing recurring cron opportunities. Preserve the distinction between healthy process and useful output.

## Acceptance evidence

Every continuous service has independent liveness, freshness, error and output evidence or an explicit remediation child item.

See [root causes](../ROOT_CAUSES.md), [implementation](../IMPLEMENTATION.md),
[failure diagnostics](../FAILURE_DIAGNOSTICS.md), [self-heal readiness](../SELF_HEAL_READINESS.md)
and [full inventory](../inventory/inventory.json). Protected scope and lane owner stay explicit.

## Members

Frozen cohort count: 19. Member SHA256: 32f0fca9f423565b10d9e69c5fee3c9a5205f8a48a77c0a3806f8b74f7ecb49e.

- chatgpt-oauth-proxy-service
- cio-governed-bridge-service
- dof-dashboard-service
- grok-oauth-proxy-service
- heartbeat-receiver-service
- openclaw-gateway-service
- ops-controls-applier
- portfolio-server-service
- power-watch-service
- telegram-callback-poller
- trade-ai-lab-moomoo-opend-service
- tradeai-active-trader-motion-service
- tradeai-cio-telegram-service
- tradeai-health-agent-service
- tradeai-lab-postgres-service
- tradeai-n8n-coordination-gateway-service
- tradeai-n8n-run-executor-service
- tradeai-n8n-run-relay-service
- tradeai-ops-agent-service
