# R20 Live Runtime / Specialist Office Audit

**Date:** 2026-08-26  
**Evidence class:** SHADOW (read-only host/release inspection)  
**Authority:** `READ_ONLY_ADVISORY`; no broker, order, stop, risk, or 2FA capability was invoked.

## Mission

Establish which Trade AI specialist and Hermes runtimes are actually scheduled, event-driven, callable-only, prepare-only, or unproven. This is an audit and evidence tranche; it does not claim that every configured agent is a continuously resident worker.

## Source and method

The deployed release path was inspected at `/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT`, resolving to release `6088254e-main-exact-phase2-20260826-103201` at source SHA `0e9dbee3e5137c6dd2533f74270dc32162ab7787`. Static unit definitions under `~/.config/systemd/user` were read, along with `config/agents.yaml` and runtime receipts under `CURRENT/data/runtime`. The sandbox could not query the user systemd bus or process table, so enabled/active state and loaded process SHA require host-side confirmation.

Evidence: [`R20_RUNTIME_INVENTORY.json`](../_evidence/r20/R20_RUNTIME_INVENTORY.json).

## Observed runtime

- Hermes has recent receipts for six lanes (strategy, watchlist, holdings, white-space, private-proxy, legal-domain), with lane timestamps from 09:05Z through 13:05Z on Aug 26.
- The event feeder receipt at 14:30Z found five directive events and enqueued four (`ev_65fe0785a8`).
- Scope governance ran at 14:07Z for an 800-symbol live universe (`sg_cd5d2628c4`).
- Holdings lifecycle processed 22 positions (12 watch, 9 healthy, 1 trim candidate); watchlist lifecycle recorded 703 promoted and 3,530 watch entries, with ANGO promotion blocked by the health gate.
- These receipts demonstrate recent execution of Hermes lifecycle/event components, not proof that each component is continuously resident.

## Agent state classification

`hermes` is **LIVE_SCHEDULED_OR_EVENT_DRIVEN** by current receipts and declared timers. Maria, Steph, risk, tax, and the orchestrator are configured capabilities in `config/agents.yaml`, but this audit found no unified natural-run roster receipt proving current wake, task, artifact, latency, and cost for each; classify them **CALLABLE_ONLY_OR_TIMER_DEPENDENT** until such evidence exists.

The templated `tradeai-agent-runtime@.service` and `tradeai-agent-runtime@hermes.timer` explicitly state `DEFAULT-DISABLED / PREPARE-ONLY`, require `/etc/tradeai/agent_runtime_enabled`, set `AGENT_RUNTIME_OPERATOR_AUTH=0`, and require an operator-supplied queue module. They are **not live workers**. The `tradeai-hermes-cio-worker.path` is a path-trigger definition, not proof of an active consumer.

## R20 gaps

1. Host-level active/enabled state and loaded source SHA are not captured in this sandbox.
2. There is no single canonical specialist roster joining agent identity, trigger, last wake, queue, artifact, success/failure, model route, research route, latency, and cost.
3. Natural research-to-thesis-to-CIO lineage is not proven by these receipts alone.
4. Prepare-only agent-runtime units must remain disabled unless separately authorized and maturity-gated.

## Required next proof

Run a host-authorized read-only probe that records `systemctl --user is-active/is-enabled`, `/proc/<pid>/cwd`, loaded module/source SHA, and the latest per-agent wake/artifact receipts. Then execute a bounded shadow office review and label it `SHADOW` or `OPERATOR_REQUESTED_LIVE` according to the actual mode. Do not relabel callable or historical evidence as `NATURAL_CURRENT`.

## Safety and rollback

No application code, scheduler, broker integration, or authority boundary was changed. Rollback is therefore a no-op: discard this documentation branch. Any future activation of prepare-only units requires an explicit operator decision, backup, source-pin verification, and natural execution proof.

## Handoff

Workstream R20 delivers the inventory and closeout document only. Integrator should merge these docs after checking the source SHA and, on the host, replacing unresolved active-state fields with measured values.
