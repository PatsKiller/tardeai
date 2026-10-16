# n8n self-healing: how a lane failure is handled, end to end (2026-10-16)

**Status:** PROPOSED (open PR; not released)
**Created:** 2026-10-16

This page answers the operator's "yes make self healing now". The code is in
`scripts/n8n_failure_diagnosis.py` (lane `n8n-failure-diagnosis`) and `scripts/lib/n8n_self_heal.py`.

**Why it changed.** On 2026-10-16 the diagnoser wrote 612 diagnosis events. 12 were diagnosed and none led to a
remediation run, while 695 escalations were open. There were four causes:

1. The cap of 3 model calls per lane per day was spent re-asking about the same failure.
2. Every catalogue action was a dry-run rerun, so nothing could heal a live lane.
3. Known patterns were still sent to the model.
4. Each P2 became its own incident.

## The path of one failure

```
SIEM row (n8n:<lane>, written by the SIEM bridge)
  -> diagnoser cycle (every 5 min)
       1. signature    lane + event_type + normalized error tail
       2. dedupe       first incident of a signature today = LEAD; the rest are ATTACHED (no call, no escalation)
       3. deterministic tier (no model call)
            lock skip + another run of the same slot finished RUN_DONE   -> auto-close "covered"
            later RUN_DONE of the same lane (same mode; NO_OUTPUT needs
            a live run or an advanced output signal)                     -> auto-close "self_recovered"
            RUN_TIMEOUT executor_lost / overdue RUNNING orphan           -> reap_orphan_run (existing handler)
       4. live heal    rerun_live_once if the gate passes (below)        -> one live request, no model call
       5. model        governed bridge: grok OAuth -> chatgpt OAuth -> DeepSeek
                       (invalid answer falls through; low confidence is re-asked once on DeepSeek, inside the
                        $0.05/call and $0.10/day caps); at most 3 calls per SIGNATURE per day
       6. action       catalogue action (dry rerun / reap) through host_run_request, or escalate
  -> diagnoses.jsonl  every outcome is a record: signature, deterministic verdict + evidence, attach, gate reason
  -> receipt          escalations[] = P1 only; digest[] = P2
  -> incident fan-in  reads escalations[] (P1)  -> incident notifier -> Telegram, once per signature
                      digest[] is not an incident: it is for the operator digest (10/15/17 ET), never one message
```

## The live-heal gate (`rerun_live_once`)

The gate allows one live rerun per lane per day. It is requested only through `host_run_request` (the gateway's
`coordination/run` path). **Every** condition below must hold, and all of them are checked again when the request
is made:

| Condition | Source |
|---|---|
| The effect owner is `n8n` | `effect_owners` in the coordination ledger, read-only |
| The stage is `canary` or `cutover`, and the state is ACTIVE | `config/lane_registry.json` |
| The lane is not a sender | Dispatch class, or a send/telegram/notify word in the lane id |
| The lane is not broker, order, stop, options-execution, scalp or F09 | Lane id words and family |
| The lane is not P1 | `config/lane_cutover_policy.json` when present; otherwise dispatch priority ≤ 1 |
| Severity is Low or Medium | The catalogue |
| The failure is classified **transient** | Timeout, connection reset or closed by the server, `dependency_unavailable`, HTTP 5xx |
| The failure is not a code error | A Python bug class, including psycopg2 `InterfaceError` |
| The lane has a semantic effect key | `config/n8n_effect_keys.json`: the executor's effect claim refuses a duplicate effect (fail closed) |

## Escalation rules

- **One escalation per (lane, signature).** It carries every SIEM id that shares the signature and the attached
  count, and the worst priority wins.
- **P1** goes in `escalations[]` with `route: operator_once`. The detail says what was tried, for example
  `tried=live_heal:no(failure_not_transient:code_error),diag:0.4`. The notifier dedupes on the stable key, so a
  signature pages once; after 24 h the notifier sends one reminder.
- **P2** goes in `digest[]` with `route: digest`. It never enters the fan-in, so it never becomes a Telegram
  message of its own.
- An auto-close or an executed action clears the signature's open escalation.

## Slot-bound retry (follow-up, 2026-10-16)

`rerun_live_once` names the FAILED live `d:`/`e:` run it retries, as `parent_run_id`:

1. **Diagnoser.** It picks the parent with `n8n_self_heal.slot_parent`: the incident's own run, or the lane's newest
   RUN_FAILED live slot run. When there is no such run, the gate reason is `no_failed_live_slot_parent` and nothing
   is requested.
2. **Gateway** (`host_run_request` → `check_retry_parent`). It refuses with `run_retry_parent_invalid`, giving
   `retry_parent_missing`, `_lane_mismatch`, `_mode_mismatch`, `_not_failed` or `_not_slot_key`. Otherwise it queues
   the retry with `parent_run_id` set.
3. **Executor** (`EffectGate.begin`). It derives the effect slot from the parent, so the retry claims the **same**
   key, `fx:<process>:<slot>:<ver>`.
4. **Effect ledger.** A FAILED claim that is proven pre-effect is re-claimed at `attempt + 1`. This is the attempt
   counter; the owner epoch does not move. A slot that is DONE, CLAIMED (a second retry), UNKNOWN or an unproven
   FAILED is refused with `effect_already_claimed`. One effect per slot.

## Known limits (operator decisions)

1. **Most live failures are not reclaimable today.** A RUN_FAILED claim is pre-effect only when the spawn failed,
   or when the lane is `late_write_fenced` and exited before `assert_fence`. Today no keyed lane calls
   `assert_fence`, so a lane that ran and then failed is held as unproven: its retry is refused, and the refusal
   escalates once at P1.
2. **The digest is wired.** `scripts/lib/advice_digest.py` reads the receipt's `digest[]` (P2 only, receipt no more
   than 24 h old) into a LANE HEALTH section of the 10/15/17 ET advice digest.
3. **NO_OUTPUT from a shadow lane does not self-recover.** That lane's dry runs never advance the output, so a
   human or the cutover itself has to close it.
4. **The SLA seed file is stale (2026-10-09).** The breach detector now derives a registry SLA row for any lane
   newer than the seed (`seed_supervisor_sla.merged_sla_rows`). Re-seeding stays an operator command:
   `python3 scripts/seed_supervisor_sla.py --json-out data/runtime/supervisor_sla_seed.json`.
