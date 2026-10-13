# n8n momentum-scalp activation — 2026-10-13

## Live changes and verification

- Activated the exact reviewed, read-only workflow `tradeai-momentum-lifecycle-candidate` (`tradeai-momentum-lifecycle-candidate`). Its source SHA-256 is `fd64f5848dff85bf27e0f42657e5094f5f8d6fc67f84d2708483069674437fc0`; the file in served CURRENT and the database export agree on IDs, nodes, connections, settings and static data. Its operative health contract is `REVIEWED` and its Schedule Trigger is every five minutes in `America/New_York`.
- Restarted only `m8m-n8n` so the activation took effect. The container returned to `Up`; `/healthz` and `/healthz/readiness` returned `{"status":"ok"}`.
- A natural scheduled execution began at `2026-10-13 13:25 ET`, but remained `running` at the time of this report with only the Schedule node recorded. A later n8n dispatcher execution at `13:27 ET` reached its error handler and reported `momentum-cache-reconcile=REFUSED`. Thus workflow activation and trigger delivery are proven; successful completion of the lifecycle observer is not.

## Scalp runner admission remains incomplete

- `trade-ai-scalp-live` is present in the registry and executor allowlist, with a `REVIEWED` operative contract. The lane remains `scheduler.stage=shadow`, `dispatch.mode=dry_run`; the relay live-lane admission is not enabled. Its generated workflow ID `537142069dd5b352` is not installed. No live scalp cycle has been run by n8n.
- The `06:00–11:55 ET` producer `finviz-momentum-scalp-early-lane` has no dispatch block, executor allowlist row, or operative reviewed contract. The registry command contains `--submit-validation`, while the installed host trigger does not. n8n's dispatcher eligibility rejects the `submit` token, so this lane cannot be admitted as written.
- A config-write request was sent for the exact files and correction: `42f88a8b4f8ba61e`. It was accepted for delivery; no corresponding grant was active at the last `guard show`. The existing config grant covers only relay live-lane admission for `trade-ai-scalp-live` after contract review and canary; it does not cover early-lane configuration.
- Host schedules are unchanged. Their triggers remain authoritative until the corresponding n8n lane is admitted and passes acceptance. In particular, the distinct scalp hot-list, proposal and early producer schedules are not interchangeable with the RTH scalp runner.

## n8n execution health finding

At `2026-10-13 13:30 ET`, the n8n database reported 76 executions in `running` state, oldest started at `13:12 ET`. Both observed natural lifecycle fires (`13:25` and `13:30 ET`) remained `running` with only the Schedule node recorded. The dispatcher also produced an explicit `REFUSED` for `momentum-cache-reconcile`; that refusal is separate from the scalp runner admission. n8n health endpoints return 200, but that does not establish execution completion. Treat n8n scheduled execution health as **DEGRADED / acceptance NOT_MEASURED** until the stuck executions are diagnosed and natural runs finish with receipts.

## Next actions

1. Diagnose why scheduled executions remain in `running` state and why `momentum-cache-reconcile` is refused; verify completion through workflow execution, relay receipt and business output.
2. Complete owner review of an exact early-lane contract. Do not mark a draft reviewed or add it to `grandfathered_draft` to bypass the admission gate.
3. Under an approved exact config grant, remove the stale `--submit-validation` registry argument, mirror the installed command and shared lock/timeout, add the executor mapping, and stage a dry-run through the existing n8n Schedule Trigger dispatcher.
4. For `trade-ai-scalp-live`, verify dispatcher/relay canary execution and correlated host lock receipt before relay live admission. Keep the host line until the lane acceptance criteria are met.
5. Comment only the exact replaced host trigger after acceptance; preserve the original line as the rollback record.

No n8n Cron node was added; scheduled work is routed through the existing n8n Schedule Trigger dispatcher.

## Refusal cause and execution counts (2026-10-13, after the 13:23 ET restart)

The relay is listening on `172.19.0.1:18092`. A GET from inside `m8m-n8n` returned immediately. The hang is not a dead relay port.

Since that restart the database had zero `success` executions at the time of the check. `running` rows were split between executions that started before the restart (still not marked crashed) and executions that started after it. The lifecycle candidate rows stored about 1.2 KB, the trigger only. The HTTP node's 10 second timeout never ran.

Dispatcher executions that reached `error` stopped on `momentum-cache-reconcile=REFUSED`. The relay reason is `relay_live_not_enabled`: the registry dispatches that lane `live`, and the lane is not in `TRADEAI_N8N_RELAY_LIVE_LANES`. The due list now emits that lane as `dry_run` with reason `relay_live_not_enabled` until the env names it. Acceptance of the lifecycle workflow stays **NOT_MEASURED**. This does not mark the stuck rows crashed and does not restart n8n.
