# n8n self-healing: how a lane failure is handled, end to end (2026-10-16)

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

## Known limits (operator decisions)

1. **No live heal for an effect-keyed lane yet.** The executor parses the effect slot from a `d:`/`e:` run id.
   A free-form `rem-…-live` request from `host_run_request` therefore ends `RUN_REFUSED effect_slot_unknown`,
   which is fail-closed: nothing runs twice. The diagnoser records that refusal and escalates it once at P1. To
   make the heal actually run, a follow-up gateway and executor PR must let the diagnoser bind its rerun to the
   failed run's slot. The effect claim would then refuse it unless that slot's claim is provably pre-effect.
2. **Nothing reads `digest[]` yet.** P2 items are visible in the receipt and in `diagnoses.jsonl`, but the
   comprehensive digest still has to be wired to read the receipt's `digest[]`.
3. **NO_OUTPUT from a shadow lane does not self-recover.** That lane's dry runs never advance the output, so a
   human or the cutover itself has to close it.
