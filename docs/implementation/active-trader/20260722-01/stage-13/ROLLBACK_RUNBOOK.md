# Stage 13 — Rollback Runbook (production-INACTIVE; do NOT execute here)

Return to classic /v3-only operation by removing /v3-next. Documentation only; no production change is
executed in Stage 13. The drill proved the rollback motion locally (killing v3-next left /v3 at HTTP 200).

## Rollback trigger
Any of: v3-next health check fails; an unexpected /v3 regression correlates with the v3-next deploy;
operator decision; a promotion gate is found to have been prematurely relied upon.

## Steps (when authorized)
1. Remove (or disable) the reverse-proxy `/v3-next/` location. The `/v3/` location was never modified,
   so classic returns immediately.
2. Health check: `GET /v3/` → 200 (classic serving). `GET /v3-next/` → 404/unreachable (expected).
3. Cache invalidation: v3-next assets are content-hashed and namespaced under `/v3-next/assets/`; removing
   the location strands no /v3 cache entry. Purge `/v3-next/*` edge cache if a CDN is in front.
4. Asset rollback: delete/retire the `/v3-next/` static root; /v3 root untouched.
5. API rollback: none required — v3-next has no production API mount; read_api/dev-write plane are not
   deployed to production.
6. Data compatibility: none required — v3-next writes nothing to production (fixtures/lab only).
7. Audit + email the operator with the rollback record.

## Proven locally
Dual-run drill: after terminating the v3-next preview, `GET http://127.0.0.1:7789/v3/` returned **200**
with no change to the classic bundle; teardown left **0** processes / **0** listeners.

## Guardrails
Rollback never touches production DB, /v3 assets, flags, or firewall. It only removes the additive
`/v3-next/` location and static root.
