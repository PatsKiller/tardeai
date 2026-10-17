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
  -> diagnoser cycle (every 5 min), for EVERY open occurrence, every cycle
       1. signature    lane + event_type + failure class + normalized error tail (codes kept, volatile tokens not)
       2. closure      this occurrence's OWN evidence (no model call):
            "VERIFIED" = scripts/lib/recovery_validator.validate (one rule, every component): the EFFECTIVE
            mode from the receipt (stage clamp), RUN_DONE exit 0, not a skip, and for live an output verdict
            produced / empty_allowed (architect review of 26fd0518, finding 1)
            lock skip + a VERIFIED run of the same mode AND semantic slot   -> auto-close "covered"
            NO_OUTPUT / STALE_OUTPUT + a later run that EXECUTED live with
              output verdict produced / empty_allowed (a fresh shared file
              alone never counts)                                           -> auto-close "output_recovered"
            other failure + a later run VERIFIED in the failed mode         -> auto-close "self_recovered"
       3. carry        already diagnosed -> cached diagnosis reused; no call, no new action, escalation untouched
       4. episode      attach only to an OPEN episode at no lower severity; a severity upgrade leads (and pages P1
                       for CRITICAL/URGENT); an occurrence after the episode resolved opens episode n+1 (new key)
       5. reaper       RUN_TIMEOUT executor_lost / overdue RUNNING orphan   -> reap_orphan_run (existing handler)
       6. live heal    rerun_live_once if the gate, the retry owner and the effect claim allow it (below)
       7. model        cached diagnosis of the signature if any; else the governed bridge: grok OAuth -> chatgpt
                       OAuth -> one DeepSeek escalation, inside the $0.05/call and $0.10/day caps; at most 3 calls
                       per SIGNATURE per day. The model only selects; it never grants execution.
       8. action       catalogue action (dry rerun / reap) through host_run_request, or escalate; a code defect never
                       reruns: it escalates into the fix -> PR -> CI -> release path (route fix_pr_release)
  -> pending          recovery_requested -> attempt_executed -> output_recovered -> incident_resolved
  -> diagnoses.jsonl  every outcome is a record: signature, class, closure evidence, episode, gates, heal state, and
                      the LLM route / fallback / budget / validation / authority evidence
  -> receipt          escalations[] = P1 only; digest[] = P2
  -> incident fan-in  reads escalations[] (P1)  -> incident notifier -> Telegram, once per (signature, episode)
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
| The failure is not auth | 401/403, `invalid_grant`, an expired token: a rerun cannot fix a credential |
| The lane is on the relay live list | `TRADEAI_N8N_RELAY_LIVE_LANES`; absent = refused (`live_list_unavailable`) |
| The lane is not held, F07 or F09 | `config/lane_cutover_policy.json` `holds`, `families`; P1 = `p1_last` |
| The slot's retry owner is not retrying | Parent receipt `retry`: `host_retry_pending`, budget exhausted, terminal or a non-host owner all refuse; a later attempt of the slot refuses |
| The parent slot's effect claim is pre-effect | FAILED + `pre_effect` (or no claim). DONE, CLAIMED, UNKNOWN, unproven FAILED or past the fence = **held** (P1, no retry, the claim is never released) |

Every row is read again from disk (and the ledger, and the environment) immediately before the request is made
(`_reauthorize_live_heal`). A change between plan and execution refuses. The request carries the FAILED parent
(`parent_run_id`); without it the producer refuses (`live_heal_requires_parent_binding`).
| The lane has a semantic effect key | `config/n8n_effect_keys.json`: the executor's effect claim refuses a duplicate effect (fail closed) |

## Escalation rules

- **One escalation per (lane, signature).** It carries every SIEM id that shares the signature and the attached
  count, and the worst priority wins.
- **P1** goes in `escalations[]` with `route: operator_once`. The detail says what was tried, for example
  `tried=live_heal:no(failure_not_transient:code_error),diag:0.4`. The notifier dedupes on the stable key, so a
  signature pages once; after 24 h the notifier sends one reminder.
- **P2** goes in `digest[]` with `route: digest`. It never enters the fan-in, so it never becomes a Telegram
  message of its own.
- An auto-close (this incident's own recovery evidence) or `incident_resolved` removes **that incident's** SIEM id
  from the episode's escalation; the escalation closes only when no open incident is left on it. A request
  (`recovery_requested`) never clears it.
- **P1 floor.** A CRITICAL or URGENT occurrence is never below P1, whatever the decision branch said: model
  confidence, remediation budget, caps, deferral, a refused model call, or dedupe. An attached or carried CRITICAL
  occurrence lifts the escalation it rides to P1.
- **Monitoring outage.** When `system_health_events` cannot be read (the connection or the SELECT fails), the empty
  row list means *unknown*, not *all closed*. Incident state is preserved: nothing is pruned or resolved, and pending
  reruns are not advanced. The receipt carries a `monitoring_source_unavailable` P1 and
  `incident_state_preserved: true`. A readable source with no open rows still closes old incidents.
- A code defect routes `fix_pr_release` (P2 digest unless already P1) and carries `fix_path`. The diagnosis
  record's `code_defect` (schema `N8nCodeDefect@v1`) is the hook for the code-defect fixer (Claude Code iterative
  fixing, built separately; `consumer_status: pending_consumer`): a stable `defect_id`
  (`cd-<lane>-<signature>-ep<N>`, one per lane, signature and episode) and `evidence` pointers (SIEM id, incident key,
  failed run id in the coordination ledger, the diagnoses store, the receipt, the evidence pack). The diagnoser only
  publishes it; it never edits code or opens a PR.

## Tranche defect fixes (operator directive 2026-10-16)

| # | Rule | Where | Tests |
|---|---|---|---|
| 1 | NO_OUTPUT / STALE_OUTPUT close only when a later run that EXECUTED live produced its expected output (`output_verdict` produced / empty_allowed); a live RUN_DONE alone, an advancing mtime alone, or (since the architect review of 26fd0518, finding 1) a FRESH shared output signal alone never closes | `n8n_self_heal.output_recovered` -> `recovery_validator` | `test_no_output_*` |
| 2 | A lock skip is covered only by a run that completed verified, in the same mode and semantic slot; the mode is the EFFECTIVE one from the receipt, so a live request the stage clamp ran as dry_run never covers a live skip (finding 1) | `lock_skip_cover`, `verified_done` -> `recovery_validator.validate` | `test_lock_skip_*`, `test_architect_review_recovery_ownership_20261016.py` |
| 3 | Fingerprints keep codes and failure classes; only volatile tokens normalize | `signature`, `failure_kind` | `test_meaningful_codes_*`, `test_failure_classes_*` |
| 4 | Severity and lifecycle per occurrence; upgrades are not absorbed; a new episode after recovery is a new incident (`\|epN` key) | `attach_decision`, episodes in state | `test_a_p2_lead_*`, `test_a_recovered_lead_*` |
| 5 | The model-result cache never closes, reopens or suppresses | `diagnosis_cache`, `carry` | `test_cache_reuse_*`, `test_one_incident_closing_*` |
| 6 | Explicit heal states; REQUESTED is never healed | `advance_pending`, `verify_recovery` | `test_a_requested_row_*`, `test_run_done_without_*` |
| 7 | Live heal: parent-bound, re-authorized at execution, held on ambiguous/post-effect claims, one retry owner, code defects to the fix path | `retry_coordination`, `effect_hold`, `_reauthorize_live_heal` | `test_post_effect_*`, `test_host_retry_*`, `test_authorization_*`, `test_code_defect_*` |
| 8 | No act without the parent binding; the model cannot select `rerun_live_once`; the P2 digest consumer stays | `execute_action`, `decide`, `advice_digest` | `test_producer_cannot_act_*` |
| 9 | Each diagnosis record carries route, fallback, budget, validation and authority (`model_grants_execution: false`) | `_llm_evidence` | `test_each_diagnosis_record_*` |

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
