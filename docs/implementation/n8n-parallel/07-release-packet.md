# Release packet and access block

Dated 2026-10-07. This is not a promotion and not a merged pull request.

## ACCESS_BLOCKED

Push needs a git-push grant whose reason names branch `wt/n8n-parallel-20261007` and the exact commit that contains this file. At the 2026-10-07T01:46:08Z read every local grant scope was expired. The expired git-push scope named a different branch and a different commit. The expired release-write scope named the already-served SHA `18a27ff288894c4e428151d5f385e68522ecd47b`. Neither grant authorizes this branch. No approval code is stored in this file. Push was not attempted.

A later push grant would still not authorize promotion, a crontab edit, enabling `tradeai-n8n-lab-watchdog.timer`, flipping the two registry rows, or a DOF GRANT.

## Promotion packet, for a later decision

| Field | Value |
| --- | --- |
| Merged SHA | none |
| Served SHA now | `18a27ff288894c4e428151d5f385e68522ecd47b` |
| CURRENT | `18a27ff28-main-exact-phase2-20261006-180747` |
| Tests on this branch | focused pytest: classifier, ledger, HTTP boundary, gateway, five contracts, compare, approval receipt, reconciler, watchdog, maturity score, ADR id, wave-5 maturity. Lane-registry gate: 0 structural errors, 0 undeclared |
| Health probes after a future promote | `GET /v3/build-meta.json` must show the merged SHA; do not read git HEAD inside the release directory |
| Natural windows | approval at minute 5 of the next hour after promote; contradiction adjudicator 2026-10-07 19:30 ET only if that timer is still the accepted writer; maturity Monday 2026-10-12 06:40 ET; watchdog has no fire until a scheduler grant enables the proposed timer |
| Owner | cron and systemd remain the live owners. n8n stays a shadow with no workflow |
| Rollback | do not deploy this branch. If a later promote happens, roll back to served SHA `18a27ff288894c4e428151d5f385e68522ecd47b` using the release tool's own rollback, not a hand edit of CURRENT |

## Counts for this pass

Model spend 0. n8n workflows created 0. Production database mutations 0. Telegram or mail sends 0. Grants consumed 0. Crontab and systemd unchanged.

## Status

| Issue | Status |
| --- | --- |
| Spent one-shot classifier | LOCAL_FIXED. Not CLASSIFIER_FALSE_POSITIVE_CLOSED on the served host until this code is what a census runs. The units were not disabled |
| Contradiction adjudicator registry | BLOCKED pending the operator choice in `01-scheduler-truth.md`. Timer left running. Next fire NOT_YET_DUE |
| Maturity registry | BLOCKED as an unapplied ACTIVE proposal. Next Monday NOT_YET_DUE. Score headline not asserted |
| Approval receipt | LOCAL_FIXED. Served natural hour NOT_YET_DUE. Delivery DELIVERY_UNMEASURED |
| Gateway durability | LOCAL_FIXED in sqlite tests. Served path `durable=false`. Not PROMOTED |
| n8n authentication | BLOCKED_POLICY |
| Five pilots | LOCAL_FIXED as fixtures. Natural fires NOT_MEASURED. No workflow |
| Watchdog | LOCAL_FIXED as a script. Timer NOT_INSTALLED |
| DOF role | unchanged. Proposed policy is not a granted rule |
| Push and promote | ACCESS_BLOCKED |

No row is RESOLVED_WITH_PROOF.
