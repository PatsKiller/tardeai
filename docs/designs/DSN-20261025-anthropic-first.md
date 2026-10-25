# DSN-20261025 Anthropic-first governed routing

Status: APPROVED TO BUILD by operator REQUIREMENTS.md (2026-10-25); source only, no activation/release.
Design-Task: DSN-20261025-anthropic-first-P1-T1

The existing authenticated bridge and process-consumption gate remain the authority for callers, manual intent, memory, schemas, per-process caps and paid fallback. Configuration declares the promotional provider before OAuth and DeepSeek. Provider-pinned probes and protected broker/order/stop processes retain their existing routes. Direct SDK bypasses are inventoried, not rewritten.

An injected HTTP adapter supports current Messages and explicit asynchronous Batch calls without adding a dependency. Repeated system prompts use ephemeral caching. Token classes, long-context pricing and Batch rates come from dated configuration, not code. API errors contain stable classifications only, never provider bodies or credentials.

An append-only, locked credit-authorization journal under the existing provider_cost runtime namespace holds worst-case cost before dispatch. Pending and ambiguous holds survive midnight; corrupt records fail closed. The journal authorizes credit locally, backed by an additional promotion-total and UTC-day cap on the existing PostgreSQL reservation table under its global advisory lock. Losing local journal state cannot reset that durable cap. The existing consumption and provider-cost ledgers meter actual calls. Both are reconciled in health/readback, and a missing accounting write stops further promotional dispatch. Promotional credit is separate from the unchanged paid global cap; paid fallback must reacquire authorization on the existing reservation under its existing lock. Per-process caps and manual rules continue to bind.

One canonical read-only status projection supplies LLM Spend, provider-health output, agent runtime health and digest. Platform/Jobs/needs-action wiring is pending normal handoff from the active owners named in the build report. Notifications use existing host notification intents with deterministic milestone identities. No new host schedule or workflow activation is authorized. Before a real key/canary the provider is not configured or awaiting observations, never proven healthy.

Proof uses synthetic fixtures, pinned clocks, HTTP spies, isolated journals and a temp PROJECT_ROOT. No credentials, real portfolio fixtures, model calls, live server traffic, merges or releases. The PostgreSQL aggregate census is currently unavailable due to a sandbox Unix-socket refusal; the inventory contains only trusted file-ledger counts and marks complete call volume unmeasured.
