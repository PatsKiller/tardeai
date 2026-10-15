# Runbook — `tradeai-reference-mature-workflow` (runbook id `n8n-reference-mature-workflow`)

```
Status:   REFERENCE (the workflow is INERT: never imported or activated)
as_of:    2026-10-15
Owner:    research (lane owner); platform (fabric)
Design:   docs/architecture/n8n/N8N_REFERENCE_ARCHITECTURE.md; docs/architecture/n8n/N8N_CONTRACTS_DESIGN.md §13
Contract: tradeai-reference-mature-workflow.health_contract.json (beside this file)
```

This is the runbook shape every workflow's `meta.framework.runbook_path` must point to. It is written for the
reference workflow; copy it for a real one and replace the lane facts.

## What it does

19:00 ET (or a Manual run from the CLI): builds the step context (`p:aegis-nightly-ingestion:dry_run:<ET minute>`),
calls `tradeai-fabric-run-lane`, records `run_id`/`lane_id`/`process_id`/`slot` as execution custom data, and routes
the result: `success` → step result; `refused_policy` / `skipped_lock` → step result as data (no error);
`failed` or an unrouted status → the execution fails → `tradeai-fabric-error` → one send-intent
(`fabric:workflow_error`, DIGEST, runbook `n8n-workflow-error`).

## Symptoms and first checks (read-only)

| Symptom | Check | Meaning |
|---|---|---|
| Digest shows `wferr:tradeai-reference-mature-workflow` | `run_outcomes` for the lane (contract `evidence.verify[0]`) | the step failed after Run Lane's retries |
| `run_outcomes.reason = empty_output` (P) | receipt `produced_count`, `skipped_reasons` | **exit 0 but nothing produced**: treat as a failure, never as success |
| `reason = outcome_timeout` | executor status `n8n_run_executor_last.json`; ledger `runs` row state | outcome lost; the run may still finish — do not re-fire, check the effect key |
| `refused_policy` with `effect:*` | `python3 scripts/lib/effect_claim.py show --process <process> --key <key>` (read-only) | another scheduler owns the slot (fence working) |
| `relay_lane_not_allowlisted` | `config/n8n_run_allowlist.json` | lane removed from the allowlist; the workflow must be archived or the row restored by PR |
| receipt stale > 50 h | contract `baseline` | two slots missed: P2 |

## Recovery

1. **Never re-run by hand in live mode.** The lane has no `live_arg` here; a real workflow's live re-run goes through
   the operator and the effect key (`effect_claim.py release` only by the operator for an `UNKNOWN` key).
2. Dead letter: `python3 scripts/n8n_dlq.py list`; release with `python3 scripts/n8n_dlq.py release` after the cause is
   fixed (DLQ release is a state change: dry run first, AGENTS.md §0 rule 7).
3. Empty output (`empty_output`): read `skipped_reasons`. A fatal reason (`no_runner`, `no_credentials`, `disabled`,
   `unconfigured`) is a configuration fault of the lane — open an incident, fix the lane, then let the next slot run.
   Do not relax the contract's `expected_output` to make it green; changing the rule is a reviewed contract PR.
4. Rollback: unpublish the workflow (`docs/ops/ROLLBACK_COMMANDS.md`, under the grant that published it); the lane's
   cron line remains the owner.

## Escalation

P2 by default (contract `alerting`). A business-critical workflow that stalls in market hours is P1 through the
host notifier, never through n8n (AGENTS.md §24.1).
