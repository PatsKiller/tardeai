# comms-intent consumer LIVE on the n8n fabric (2026-10-17)

```
Status:      PACKET (config + code + tests in the PR; the live list, units and n8n are NOT CHANGED: operator)
as_of:       2026-10-17
Authority:   operator decision D2 2026-10-17 "Queue reader first"; AGENTS.md §23.3, §23.23, §24.1
Target:      lane n8n-comms-intent-consumer -> TRADEAI_N8N_RELAY_LIVE_LANES; relay + gateway restart; no cron, no workflow import
Live apply:  cutover.sh relay --apply under a config-write + service grant; cutover.sh rollback --apply reverses it
```

Operator decision **D2, 2026-10-17, "Queue reader first"** (`docs/ops/packets/hermes-learning-cutover-20261015/README.md`):
put lane `n8n-comms-intent-consumer` live on the n8n fabric at `*/5`. Then the comms intents that hosts and n8n
queue in the coordination ledger's `comms_intents` table become incidents and reach the operator. This has to happen
before hermes `outcome_feedback_agent` can move to `--apply --notify queue`. That move is a separate, later PR and is
not made here.

## What --apply does, end to end (traced 2026-10-17)

```
comms_intents QUEUED   (n8n gateway comms/intent; host lanes via scripts/lib/host_comms_intents.py)
  -> scripts/n8n_comms_intent_consumer.py --apply   (this lane; claim QUEUED -> CLAIMED -> DONE|FAILED by CAS)
  -> comms_intent_incidents OPEN (one per workflow+kind; DIGEST -> P2; OPEN for dedupe_window_s = 3600 s)
  -> scripts/n8n_incident_fanin.py _comms_intent_findings (mode=ro)     n8n dispatch-live, */5
  -> scripts/incident_notifier.py --live, P2 batch (the only sender)    host cron */5
```

Downstream was verified running on 2026-10-17 at 17:05Z (read-only):

- `n8n_incident_fanin_last.json` was rewritten at 17:05Z from served `7b07774ad`. Its `comms_intent_source` note
  reads `incidents:ok:open=0:merged=0:dlq:ok:dead_letter=0:queued_stale=3`.
- `incident_notifier_last.json` was rewritten at 17:05Z: mode live, status OK. Messages 58854 and 58855 were SENT.

## Shape (mirrors heartbeat-watch)

| item | value |
|---|---|
| registry `scheduler` | `{kind n8n, expression dispatcher, match scripts/n8n_comms_intent_consumer.py, cadence */5, stage canary, wave W1}` |
| registry `dispatch` | `{mode live, cron [*/5 * * * *], class monitor, priority 1, retry_policy transient-2}` |
| allowlist | `live_arg ["--apply"]`, `dry_run_arg ["--dry-run"]`, own flock `/tmp/tradeai_n8n_comms_intent_consumer.lock`, 60 s, `output_receipt v2`, env enforce |
| health contract | REVIEWED, canary, `expected_output` `empty_allowed` (`no_new_input`, `nothing_due`), fatal `dependency_unavailable` |
| effect key | none: there is no cron side to fence, and every live effect is idempotent per intent (CAS). No owner row is needed |
| workflow | **none new**. The lane is fired by the already-active `tradeai-dispatcher`, and `build-generic`, `build-fabric` and per-lane `--check` are all clean |
| run ids | `d:n8n-comms-intent-consumer:live:<YYYYMMDDTHHMM>` |

## The 4 QUEUED intents (read-only, 2026-10-17 17:05Z)

These are not host-lane intents and not test alerts. All four are `fabric/workflow_error`, caller `n8n-relay`,
workflow `tradeai-fabric-hermes-learning`, node `Assert process`. Each one is a real hermes-learning slot failure:

| intent | first_at (UTC) | summary |
|---|---|---|
| ci-b7f1b2b745f7ea73e3480c4e | 2026-10-16 16:37 | slot 20261016T1237: failed outcome_grader, autonomous_self_tune |
| ci-cd4cb79d9a45c52825836e9a | 2026-10-16 21:00 | slot 20261016T1700: failed autonomous_self_tune |
| ci-ae38ac42ca77c462f84ed566 | 2026-10-17 14:50 | slot 20261017T1050: failed outcome_feedback_agent |
| ci-255f2885d6419609eda92377 | 2026-10-17 16:00 | slot 20261017T1200: failed outcome_feedback_agent |

The served `--dry-run` against the live ledger (mode=ro) gives this result. All 4 fold into **one** P2 incident
`n8n_workflow_error / wferr:tradeai-fabric-hermes-learning` (`inc-f6a7fd5438b5afe0dd74`). The first intent is
`create_or_reopen` and the other three are `update_open`. The expired 10-15 probe incident `inc-7b246a5388b496801e92`
would close.

The operator therefore gets one P2 batch line, not four pages. It reads:
`4 n8n intent(s) fabric/workflow_error tier DIGEST exec 41010 · Assert process: ... slot 20261017T1200 ...`.
That line carries the current failure, so no expiry rule is proposed. Rows are never deleted.

## Delivery gap (read before `relay --apply`)

A comms incident stays OPEN for only 1 h after it is consumed (`open_until = max(last_at, now) + 3600 s`). The
notifier sends only incidents that are open when it sends. So an intent consumed in either of these two cases closes
without ever being notified:

- during quiet hours (22:00-06:59 ET), because P2 is held until 07:00;
- after the notifier's daily cap is used (24/24 was already reached at 13:05 ET on 10-17).

Today the backlog does surface eventually, as the persistent `queued_stale` P2. Going live replaces that with a 1 h
incident, so outside the delivery window the gap moves rather than closes.

`relay --apply` refuses while the notifier cannot deliver, unless you set `ACCEPT_DELIVERY_GAP=1`. That makes the
first batch (the 4 intents above) land. Later intents still carry the gap.

**Operator decision proposed (separate PR):** keep a comms incident OPEN until the notifier has delivered it. Either
gate `close_expired` on `incident_notifier_state.json notified[incident_key].last_notified_at >= opened_at`, with a
24 h ceiling, or extend `open_until` past quiet hours. This must land before `outcome_feedback_agent --notify queue`
relies on this path overnight.

## Operator steps

1. Merge the PR, then promote it so CURRENT serves it. Main must be CI-green on the exact SHA, with a release grant
   that names the PR and SHA.
2. `bash cutover.sh pre` (read-only). Every check must read `ok` and the output must say "PR SERVED". It also shows
   the backlog and the served dry run, and warns when the notifier cannot deliver.
3. Between 07:00 and 21:59 ET, with notifier cap headroom:
   `TRADEAI_FABRIC_GRANT=<config-write grant> bash cutover.sh relay`, then the same command with `--apply`. This
   needs a config-write and service grant. It backs up the live list, reads it back, and restarts the relay and the
   gateway.
4. `bash cutover.sh publish` (read-only). It must report that no import is needed and that `tradeai-dispatcher` is
   active.
5. Wait for the next `*/5` slot. Then run `bash cutover.sh proof --since <UTC ISO of step 3>`. It needs all three:
   - live `RUN_DONE` with verdict `produced` or `empty_allowed`;
   - no QUEUED intent older than 15 min;
   - for each incident, the notifier state shows DELIVERED (the P2 batch can take up to 30 min).
6. Rollback: `TRADEAI_FABRIC_GRANT=<grant> bash cutover.sh rollback --apply`. This takes the lane off the live list
   and restarts both units, so the dispatcher fires become `dry_run`. Then send a config PR that sets `dispatch.mode`
   to `dry_run` and `live_arg` to null. **Never deactivate `tradeai-dispatcher`**, because it fires every other
   dispatch-live lane. Ledger rows stay.

Between step 1 and step 3, the gateway demotes each fire to `dry_run` with reason `relay_live_not_enabled`. A dry run
is mode=ro and writes no receipt, so the lane's `ok_at` stays at 10-14. Do steps 1 to 3 in one window.
