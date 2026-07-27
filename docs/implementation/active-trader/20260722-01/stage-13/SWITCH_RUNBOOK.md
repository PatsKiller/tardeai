# Stage 13 — Switch Runbook (production-INACTIVE; do NOT execute here)

Procedure to make /v3-next reachable in production **alongside** /v3. This runbook is documentation
only; Stage 13 executes **no** production change. Requires separate owner authorization + Stage 14.

## Preconditions
1. Reviewed exact SHA on `feat/active-trader-next`; PR #150 reviewed (still draft until authorized).
2. Build artifact hashes recorded: `apps/command-center-v3-next/dist` (base `/v3-next/`).
3. All promotion gates green (see PROMOTION_GATE_MATRIX.md) OR the switch is scoped to read-only
   fixture UI with all live flags OFF (v3-next ships actions-disabled).
4. Operator approval captured.

## Steps (when authorized)
1. Deploy `apps/command-center-v3-next/dist` to the static root served under `/v3-next/` (its own
   directory; do not overwrite the /v3 root).
2. Add a reverse-proxy location for `/v3-next/` → the new static root. **Match `/v3/` with the trailing
   slash / exact**, never bare `/v3`, so `/v3-next/` is not swallowed. Leave the existing `/v3/` location
   untouched.
3. Health checks: `GET /v3-next/` → 200; an asset under `/v3-next/assets/` → 200; `GET /v3/` still 200.
4. Confirm production feature flags remain OFF; v3-next actions remain disabled.
5. Cache: publish v3-next with content-hashed assets (already hashed); no shared cache key with /v3.
6. Audit: record the deploy + email the operator.

## Non-goals / guardrails
- Does NOT enable any live trading flag, broker call, order path, or Moomoo live use.
- Does NOT modify, replace, or remove the /v3 route or its assets.
- Does NOT change production DB, services (beyond adding the isolated static location), or firewall.
- LIVE_CANARY stays OFF and is out of scope for this switch.
