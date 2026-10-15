# Rollback

Nothing is deleted (AGENTS.md §0 rail 6). Each step is independent. Use the smallest one that fixes the problem.

| Problem | Rollback |
|---|---|
| The fan-in should stop reading intents | Set `TRADEAI_FANIN_COMMS_INTENT=0` in the fan-in's environment. That is a config-write on its unit or allowlist env, so it needs a grant. Or revert the `scripts/n8n_incident_fanin.py` hunk by PR and promote. |
| The consumer should stop | It is not scheduled. Stop running `--apply`. |
| An incident should not be open | `UPDATE comms_intent_incidents SET state='CLOSED', closed_at=<now>, updated_at=<now> WHERE incident_key='<key>'`. The fan-in drops it on its next run and records a recovery. |
| Re-queue intents (undo a consumption) | `UPDATE comms_intents SET state='QUEUED' WHERE intent_id IN (<ids>)`, then `UPDATE comms_intent_consumption SET state='QUEUED', terminal=0, attempts=0, last_error='requeued by operator <date>' WHERE intent_id IN (<ids>)`. The next `--apply` consumes them again. A dead-lettered intent is re-queued the same way after its cause is fixed. |
| Undo the whole apply | Restore the step-0 backup only with the gateway stopped, and only if you accept losing every ledger write made since the backup. Prefer the two rows above. Or archive the two tables: `ALTER TABLE comms_intent_consumption RENAME TO comms_intent_consumption_archived_<date>` (and the same for `comms_intent_incidents`), and set the consumed intents back to QUEUED. |
| Code | Revert the merge commit by PR. Without the tables, the fan-in source reads `incidents_table:absent`, and the gateway never reads either table. |
| Registry / allowlist staging | A PR removing the `n8n-comms-intent-consumer` row and entry. Both are inert: `NEVER_SCHEDULED` with `live_arg null`. |

Run SQL through `python3 -c "import sqlite3; c=sqlite3.connect('<ledger>', timeout=5); c.execute(...); c.commit()"`
while the gateway runs: the ledger is WAL, with a 5 s busy timeout. Take the step-0 backup first.
