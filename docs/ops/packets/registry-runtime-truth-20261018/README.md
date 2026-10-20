# Registry / runtime truth — packet (review 2026-10-18, built 2026-10-19)

Status: LIVE 2026-10-20 — merged (#1867, served from release `720fce06c` 08:58 ET, then `f6f56e365`); lane
`registry-runtime-truth` added to `TRADEAI_N8N_RELAY_LIVE_LANES` 10:23:28 ET (backup
`n8n-live-lanes.env.bak-20261020T142328Z-registry-truth`). First live run PENDING: the next `20 7 * * *` dispatcher
slot; no `data/runtime/registry-runtime-truth_last.json` existed at 14:35 ET. Built 2026-10-19. Authority:
READ_ONLY_ADVISORY. Summary: `docs/ops/LIVE_CHANGES_20261020.md` §3.

Branch `fix/registry-truth-evidence-v2-20261019` (base `origin/main` `baeda8d16`). Nothing here changes the host: no
crontab, systemd, n8n, relay live-list or effect-owner change; no DB write; the coordination ledger was read
`mode=ro`. The lane added below is live only after the operator adds it to the relay live list.

## 1. The finding

External review 2026-10-18: `config/lane_registry.json` declared the six Hermes fabric steps `NEVER_SCHEDULED`
("workflow not imported") and `config/n8n_health_contracts.json` held their contracts at `shadow`, while
`config/n8n_fabric_processes.json` had process `hermes-learning` at mode `live`. Every gate was green.

Host evidence re-verified read-only on 2026-10-19 (not trusted from the 10-17 notes):

* n8n `workflow_entity` (docker exec psql SELECT): `tradeai-fabric-hermes-learning` **active** (19 active workflows).
* coordination ledger `effect_owners`: outcome-grader, tag-engine, outcome-learning, config-governor owner `n8n`
  epoch 2 since 2026-10-16T17:20:08Z ("hermes-learning cutover c3 (4 live lanes; feedback agent held)");
  autonomous-self-tune owner `n8n` epoch 2 since 2026-10-17T05:58:26Z; outcome-feedback-agent owner `cron` epoch 1.
* ledger `runs`: 3 live `RUN_DONE` per step, requested by `n8n:workflow:tradeai-fabric-run-lane` — learn steps
  `20261017T1050`, `20261017T1200` (manual slot), `20261018T1050`; self-tune `20261017T1200` (manual),
  `20261017T1700`, `20261018T1700`. `effect_claims` `fx:<lane>:<slot>:v1` DONE, scheduler n8n, for each.
* `data/runtime/pipeline_hermes_learning_learn_last.json` 2026-10-18T15:20Z: the four n8n-owned steps
  `skipped_effect` rc 75; `outcome_feedback_agent` and `score_history_retention` ran (rc 0).
  `pipeline_hermes_learning_tune_last.json` 2026-10-18T21:20Z: `autonomous_self_tune` `skipped_effect` rc 75,
  `executed_any false`.
* relay live list (`TRADEAI_N8N_RELAY_LIVE_LANES`, names only): the five steps present, the feedback agent absent.
* Output proof, honestly: self-tune's 10-18 run is `produced` (produced_count 7, LaneRunReceipt@v2). The four learn
  steps' live runs carry output verdict `declared_not_enforced` (their allowlist entries are not `output_receipt: v2`),
  so their usefulness rests on the stdout summaries in the run receipts and config-governor's receipt mtime — an open
  gap, recorded in each row's `reason_evidence`.

Overlap check against main (`git log -p 3af0a8bdd..origin/main -- config/ scripts/check_lane_registry.py`): only
#1859 touched Hermes registry state (the feedback agent's hold, preserved here). Nothing reconciled the five steps.

## 2. What changed

1. **Reconciliation.** The five steps: `state ACTIVE` since 2026-10-17 with run-id evidence and a `canary` block;
   `scheduler.stage` stays `canary` (not `cutover`: their parent cron line still fires and is fenced by the effect key,
   unlike the CW lanes whose cron lines were retired). Contracts `shadow -> canary` (already REVIEWED). Parent rows
   `hermes-learning-pipeline-learn` / `-tune` gain an `effect_ownership` block (partial ownership; tune is a fenced
   fallback that runs nothing) and lose the stale "Pending: first natural run" evidence. The feedback agent is unchanged.
2. **Gate fix found on the way.** `check_lane_registry --n8n-live` on main reported `tradeai-fabric-run-lane` and
   `tradeai-fabric-error` as UNDECLARED_N8N_WORKFLOW: the fabric INDEX was not in the known-id set.
   `lane_registry.n8n_fabric_workflow_ids` adds it (same precedent as the six generic workflows), and the committed
   `active_workflows_snapshot.json` is refreshed from a read-only SELECT (14 -> 19), which the five ACTIVE rows need.
3. **Checker + lane.** `scripts/check_registry_runtime_truth.py` and n8n lane `registry-runtime-truth` (dispatcher
   daily 07:20 ET, stage canary, measure-only, REVIEWED contract, LaneRunReceipt@v2, route
   `fabric/registry_runtime_contradiction` DIGEST in `config/host_comms_intent_routes.json`). It queues through
   `CommsIntentStore` directly because `lib/host_comms_intents.py` imports the coordination gateway, whose closure
   reaches broker modules (`scripts/audit_lane_transitive_capabilities.py --check`: new 0).
4. **Output-signal coverage.** `docs/ops/OUTPUT_SIGNAL_COVERAGE_20261018.md`; 9 explicit `SIGNAL_FREE_EXEMPT`.

## 3. Runs (read-only)

* `01_first_run.txt` — the checker `--dry-run` against the real host after the reconciliation: all four sources ok,
  **29 contradictions**: 28 `CONTRACT_STAGE_MISMATCH` (registry canary/cutover, contract still shadow — the CW wave
  lanes; one reverse: `news-to-catalyst` registry shadow, contract canary) and 1 `LIVE_LIST_REGISTRY_NOT_LIVE`
  (`maturity-remeasure` is on the relay live list but its row is at stage shadow, so the stage clamp demotes every
  live fire to dry_run). 5 grandfathered DRAFT contracts on the live list are listed as accepted debt.
* `02_pre_fix_replay.txt` — the same checker with the registry and contracts of `baeda8d16` (current allowlist and
  fabric spec): the five Hermes steps each fire `DECLARED_OFF_BUT_RUNS_LIVE`, `EFFECT_OWNER_N8N_NOT_LIVE`,
  `LIVE_LIST_REGISTRY_NOT_LIVE` and `PROCESS_LIVE_STEP_NOT_ACTIVE` (20) — the finding would have been caught.

## 4. Operator steps (propose and stop)

* DONE 2026-10-20 10:23 ET (the relay and gateway were also restarted by the 12:52 ET promote): add
  `registry-runtime-truth` to `TRADEAI_N8N_RELAY_LIVE_LANES` and restart the relay (same procedure as
  `docs/ops/packets/comms-intent-consumer-live-20261017/cutover.sh relay`). Until then the dispatcher's fires are
  demoted to dry_run and nothing is written.
* Decide the 28 stale contract stages (a reviewed contract PR per wave) and `maturity-remeasure` (promote its row or
  drop it from the live list).
* Rollback of the lane: revert the registry/allowlist/contract/route commit; the live list entry, if added, removed.
