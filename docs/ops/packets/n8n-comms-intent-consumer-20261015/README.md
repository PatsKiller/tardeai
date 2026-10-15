# n8n comms-intent consumer — operator packet (2026-10-15)

Branch `n8nfab/comms-intent-consumer-20261015` (base origin/main `6182aa824`). Local commit only; nothing pushed,
installed, imported or activated.

## What it does

Build 1 (PR #1739, live at `5aa61048d`) queues n8n send-intents in `comms_intents` in the coordination ledger. Nothing
sends them. You chose the incident fan-in route, so this build makes them incidents, not messages:

```
n8n error workflow --comms/intent--> gateway: comms_intents (QUEUED)
      scripts/n8n_comms_intent_consumer.py --apply
          claim QUEUED -> CLAIMED -> DONE | FAILED          (compare-and-set, attempts, last_error)
          route table (config/n8n_comms_intent_routes.json) -> tier -> severity (DIGEST -> P2)
          comms_intent_incidents: one OPEN row per workflow + kind (a repeat updates it)
      scripts/n8n_incident_fanin.py   reads the OPEN rows; a workflow_error joins wferr:<workflow_id>
      scripts/incident_notifier.py    the existing P2 batch (30 min, quiet-held 22:00-07:00 ET): the only sender
```

- **No new page.** A `(fabric, workflow_error)` intent uses the fan-in's own identity (`n8n_workflow_error` /
  `wferr:<workflow_id>`). When the relay already opened that incident, the intent is folded into it (count and
  intent ids added, severity = the higher of the two). Otherwise it is a P2 line in the batch.
- **No send in the consumer.** It imports no Telegram, notifier, HTTP or subprocess module (ratchet test). The
  fan-in and the notifier are unchanged as senders (AGENTS.md §24.1, §23.23).
- **Refusals.** No route = `intent_unrouted`; a PAGE tier = `page_tier_never_from_n8n` (the P1 path never depends
  on n8n). Both are FAILED and terminal, never retried and never sent.
- **Dead letters.** FAILED 3 times or refused, and QUEUED more than 2 h, each become ONE aggregated P2 fan-in finding
  (`n8n_comms_intent_dlq` / `dead_letter`, `queued_stale`). They are aggregated because WS1-09 found the channel
  already saturated.
- **Idempotent.** A DONE intent is never reclaimed. A repeat that the gateway folds into a DONE intent (count + 1)
  refreshes the incident once. Incidents close when `open_until` passes (the later of the intent's `last_at` and
  its consumption time, plus the route table's 3600 s window), and re-open with `generation + 1`.
- **Per-run cap.** The cap defaults to the route table's `max_per_hour` (30), oldest first. The rest is `deferred`
  on the receipt.
- **Receipt.** `LaneRunReceipt@v1` `data/runtime/n8n-comms-intent-consumer_last.json`, written only by `--apply`.
  `ok_at` advances only on success.

Ledger changes are additive. Two new tables, `comms_intent_consumption` and `comms_intent_incidents`, are created by
the first `--apply`. In `comms_intents`, only the `state` column moves. The gateway's schema and code are unchanged.

## Lane staging (nothing active)

| Item | State |
|---|---|
| `config/lane_registry.json` `n8n-comms-intent-consumer` | `NEVER_SCHEDULED`, `scheduler.kind none`, no `dispatch`, output_signal `json_key ok_at` |
| `config/n8n_run_allowlist.json` | shadow: `dry_run_arg ["--dry-run"]`, `live_arg null`, `env_allowlist_mode enforce`, own flock lock |
| Health contract | `health_contract_draft.json` (DRAFT; validated by the test). It is not in `config/n8n_health_contracts.json`, because a non-grandfathered DRAFT fails that gate. The owner marks it REVIEWED in the registry PR that stages shadow. |
| Remediation catalogue | Not regenerated. `build_remediation_catalogue.py --check` was already not up to date on main (7 unrelated `stage` diffs), and regenerating here would carry them. The lane would gain one auto-rerun action, and it stays excluded until shadow. |

## Files

- `scripts/lib/n8n_comms_intent_consumption.py` holds the state machine, the mapping, the fan-in readers and the dead-letter rule.
- `scripts/n8n_comms_intent_consumer.py` is the CLI (`--dry-run` is the default; `--apply`).
- `scripts/n8n_incident_fanin.py` gains the `_comms_intent_findings` source (`TRADEAI_FANIN_COMMS_INTENT=0` opts out).
- `tests/test_n8n_comms_intent_consumer_20261015.py` is registered in GATES as `n8n_comms_intent_consumer_20261015`.
- `tests/test_n8n_executor_env_allowlist_20261009.py` raises the enforced-lane count from 11 to 12.
- This packet holds `02_dry_run_live.txt`, `03_apply.md`, `04_rollback.md`, `evidence.py` and `health_contract_draft.json`.

## Order

1. Review and merge the PR. Promote as usual. The fan-in reads the new tables only from the served release on.
2. Run `03_apply.md`: the backup, a dry run from the served tree, `--apply` once, then the evidence.
3. Later, in a registry PR: the REVIEWED contract, stage shadow (and the Run Lane workflow), then canary with
   `live_arg ["--apply"]`.

Note: once the fan-in change is served, any intent still QUEUED for more than 2 h raises one P2 `queued_stale` line.
`ci-2a845…` was queued at 01:37Z, so apply soon after promoting, or that line appears once in the batch. That is
the dead-letter rule working as designed.
