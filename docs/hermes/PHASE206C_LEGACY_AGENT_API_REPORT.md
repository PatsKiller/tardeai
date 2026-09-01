# Phase 206C — Legacy/Retired Agent API — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T10:29:34-04:00
Measured at: efcc51365 / not measured

## Endpoint
`GET /api/v2/hermes/legacy-agents` → `scripts/api_v2.py::_hermes_legacy_agents`. READ-ONLY. Registered in
the v2 route table (consumed by v3). Backed by `data/hermes/legacy_agent_inventory_latest.json` (built by
`hermes_legacy_agent_inventory.py`; retired dirs are immutable so the cached JSON is served, regenerated
only if absent).

## Response shape
```
ok, read_only=true, scanned_at, retired_dirs[], counts{}, total,
items[] = {name, path, source_dir, status, model, tools, purpose, last_modified, safety_note,
           migration_recommendation},
gateway_service_active, gateway_service_enabled,
actions_available=[]   (no enable/run/edit for retired items),
warning  (audit-only banner text)
```

## Safety properties (verified)
- No secrets in payload (redacted in the inventory; runtime-state contents not exposed).
- `actions_available=[]` — the endpoint offers **no** enable/run/edit action for retired items; it does
  not call retired wrappers or start services.
- Surfaces gateway state for the UI banner: live read `failed / disabled`.

## Live result (2026-06-07)
HTTP 200, ok=true, total=24, counts `{RETIRED_SOUL:2, RETIRED_AGENT:1, RETIRED_WRAPPER:4,
UNSAFE_RUNTIME_ARTIFACT:13, ACTIVE_PROFILE:4}`, gateway `failed/disabled`, read_only=true. Retired dirs:
`.hermes.RETIRED_20260606_2140`, `…_2154`, `install.RETIRED_20260606_2140`.
