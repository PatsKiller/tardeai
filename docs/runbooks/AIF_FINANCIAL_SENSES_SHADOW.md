# Runbook — AIF ↔ Financial Senses shadow

Status:      ACTIVE
as_of:       2026-08-17T17:24:31-04:00
Measured at: efcc51365 / not measured

READ_ONLY_ADVISORY. Do not enable behavior influence.

## Enable shadow (read-only observation)

On the CURRENT process environment only:

```
AIF_FINANCIAL_SENSES_SHADOW=1
MEMORY_BEHAVIOR_INFLUENCE=0
```

Restart only CURRENT consumers (portfolio_server). Do not touch broker /
protection services.

## Disable shadow

Unset or set `AIF_FINANCIAL_SENSES_SHADOW=0`. Restart CURRENT consumers.

## Verify no behavior influence

```
python3 - <<'PY'
from scripts.lib.financial_senses_aif import behavior_influence, memory_behavior_influence, shadow_enabled
print("shadow", shadow_enabled())
print("fs_behavior", behavior_influence())
print("memory_behavior", memory_behavior_influence())
assert behavior_influence() is False
assert memory_behavior_influence() == 0
PY
```

Tool traces must show `shadow_only=true` and `behavior_influence=false`.

## NOT_CONFIGURED

- FRED: missing `FRED_API_KEY` → `macro.*` returns NOT_CONFIGURED
- OpenFIGI: missing `OPENFIGI_API_KEY` → `identity.resolve` returns NOT_CONFIGURED
- SEC: store/fetcher issues → UNAVAILABLE / PARTIAL, never fabricated facts

## Verify traces

Receipts live on the existing AIF tool-trace JSONL (`agent_tool_traces.jsonl`).
Look for `fs_provider`, `fs_capability`, `request_id`, `validation_ok`.

## Rollback

Restore previous immutable CURRENT via `cio_phase2_exact_main_deploy.sh rollback`.
Keep `AIF_FINANCIAL_SENSES_SHADOW=0`.
