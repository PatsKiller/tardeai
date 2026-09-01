# AIF ↔ Financial Senses — governed read-only integration

Status:      ACTIVE
as_of:       2026-08-17T17:24:31-04:00
Measured at: efcc51365 / not measured

READ_ONLY_ADVISORY. MEMORY_BEHAVIOR_INFLUENCE = 0. No broker / order / stop /
2FA / risk-policy authority. No auto-promotion.

## Why one gateway

The Agent Intelligence Foundation already owns the single read-only MCP
chokepoint (`scripts/lib/mcp_read_only_gateway.py`). Financial Senses already
owns provider contracts and `FinancialSenseResult@v1`.

This integration **registers** FS capabilities on that gateway. It does not
create `financial_senses_mcp_server`, a second router, a second memory brain,
or a second financial-truth authority.

```
AIF agent wake
  → get_context_for_agent() / call_mcp_tool()
    → mcp_read_only_gateway (allowlist, denylist, SSRF, rate, timeout)
      → FinancialSensesReadOnlyProvider
        → existing FS provider.query()
          → FinancialSenseResult.validate()
            → structured specialist_context.financial_senses
            → AgentRunTrace tool receipt (shadow_only=true, behavior_influence=false)
```

## Responsibility boundary

| Layer | Owns | Must not |
|---|---|---|
| Financial Senses | evidence, Fact vs ModelEstimate, quality, freshness, providers | execution, MCP routing, memory authority |
| AIF | gateway, envelope, trace, flags, UNTRUSTED_DATA, rate/timeout | FS calculation, promoting estimates to facts |
| Adapter (`financial_senses_aif.py`) | registration, validation, envelope mapping, redaction | new truth, writes |

## Fact vs ModelEstimate / quality / freshness / provenance

Preserved end-to-end. Only explicit `FRESH` evidence may count as current
authoritative Fact support. `STALE` / `UNKNOWN` / missing / malformed
freshness does not. Invalid quality is rejected. ModelEstimate cannot occupy
`facts[]`.

## ContextEnvelope

`specialist_context.financial_senses` is a structured sub-section (not prose).
Budgeting drops FS items before office_truth / decision / governance. Critical
classification fields are never silently stripped.

## Trace

Every FS call through the gateway emits a tool receipt with request_id,
provider, capability, validation, freshness/quality summaries, Fact /
ModelEstimate counts, provenance refs, `shadow_only=true`,
`behavior_influence=false`.

## Memory

Raw FS output is not auto-persisted. Admission must use the existing AIF
memory path. Memory cannot turn ModelEstimate→Fact or STALE→FRESH.
`MEMORY_BEHAVIOR_INFLUENCE` remains 0.

## Security

SEC / FRED / OpenFIGI / OpenBB text is UNTRUSTED_DATA. Prompt-injection
strings stay evidence text. Secrets are redacted. Unconfigured providers
return `NOT_CONFIGURED` — no fabricated data.

## Failure / rate

Hung providers time out. The global in-flight bound still applies.
`governor=None` uses the shared default governor (cannot bypass).
Provider failure is fail-soft for advisory context and fail-closed for
authority.

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `AIF_FINANCIAL_SENSES_SHADOW` | `0` | Permit FS calls + envelope + traces (shadow only) |
| `MEMORY_BEHAVIOR_INFLUENCE` | `0` | Unchanged. Must stay 0. |

There is **no** behavior-influence flag for Financial Senses.

## Rollback

1. Set `AIF_FINANCIAL_SENSES_SHADOW=0` (or unset).
2. If needed, restore the previous immutable CURRENT release.
3. Do not hotfix live after rollback.

OpenBB is intentionally unexposed (optional plumbing, not in the governed
manifest).
