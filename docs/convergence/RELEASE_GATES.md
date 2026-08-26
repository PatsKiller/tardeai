# R20–R24 release gates

Do not mix these.

## LOCAL_R20_R24_READY_FOR_SYNC

Local release-candidate for a later one-sync. Does **not** require deployed CURRENT.

Requires:

- contracts green (CONTROL_PLANE_API_V1.1)
- R22/R23/R24 implemented
- runtime mocks = 0
- `/control-plane/*` registered as preview (no live cutover)
- frontend `npx tsc --noEmit` via `apps/command-center-v3` after `npm ci`
- production build (`npm run build`) green
- dry-run green
- temporal lookahead leaks = 0
- replay classification truthful
- fault campaign green
- HTTP authority green (unauthorized_successes=0)
- secret scan green
- parity measured, regressions = 0
- `scripts/ai_local_acceptance.sh` PASS
- QA `ready_for_integrator_acceptance=true` against the exact HEAD

Does **not** require:

- production CURRENT SHA
- host services/timers/queue consumers
- real historical control-plane traces (none existed pre-deploy)

## LIVE_R20_R24_ACCEPTANCE

After a later deploy of the merge SHA.

Requires:

- CURRENT == merge SHA
- host services/timers/workers verified
- canonical production stores available
- specialist office runtime verified
- operator-requested live review
- NATURAL_CURRENT evidence
- real route/UI smoke against deployed backend

Until then: `LIVE_R20_R24_ACCEPTANCE=NOT_APPLICABLE_PRE_DEPLOY`

R20 local display: `NOT_DEPLOYED` / `CALLABLE_ONLY` / `SHADOW` / `UNKNOWN` according to evidence. Never LIVE because source exists.
