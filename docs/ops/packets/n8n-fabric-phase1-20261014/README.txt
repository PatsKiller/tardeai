N8N FABRIC PHASE 1 PRIMITIVES — OPERATOR ACTIVATION PACKET (2026-10-14)
=======================================================================

Branch: n8nfab/phase1-primitives-20261014 (local commit only; nothing pushed, merged, served or imported).
Design contract: AGENTS.md §23.23 (10.0.0 PROPOSED) and §23.21; arch-review-20261014 REFACTOR_PLAN B4, B5, B6 and
the addendum (effect key, fenced owner, trusted deployer, Error Trigger acceptance).
Every script here is a DRY RUN that prints what it would do unless given --apply. Nothing here touches a broker,
crontab, a systemd unit, config/n8n_run_allowlist.json or the relay live-lanes env.

WHAT THE BRANCH ADDS
--------------------
Host side (inert until a release serves it):
  * executor     scripts/n8n_run_executor.py records a terminal outcome per run in the ledger table run_outcomes
                 (run_id, lane_id, status success|failed|refused_policy|skipped_lock, exit code, receipt path,
                 duration, effect key). v1 drain and v2 workers both. A refusal is a status, never an error.
  * effect key   scripts/lib/effect_claim.py: fx:<process>:<slot>:<input_version> claimed in effect_claims before a
                 LIVE run of a lane listed in config/n8n_effect_keys.json, under an owner-epoch fence
                 (effect_owners). The file is EMPTY at merge, so no lane's behaviour changes. A cron line can claim
                 the same key with `python3 scripts/lib/effect_claim.py run ... --scheduler cron -- <command>`.
  * gateway      read op coordination/run_outcome (read scope; RunOutcome@v1) and op comms/intent (new scope
                 comms_intent, relay key only; dedupe 3600 s, 30 new intents per hour, closed route table
                 config/n8n_comms_intent_routes.json, no PAGE row). An intent is QUEUED in comms_intents; nothing
                 sends it yet (see OPEN QUESTIONS: the host consumer is the next PR).
  * relay        GET /run_outcome?run_id=<id> and POST /intent (bearer, bounded, cleaned text).
n8n side (generated JSON in git; docs/implementation/n8n-maturity/workflows/fabric/, INDEX.json = manifest):
  * tradeai-fabric-run-lane         Execute Workflow Trigger -> POST /run -> Wait/poll GET /run_outcome (5 s doubling
                                    to 60 s, until outcome_timeout_s <= 1000) -> Switch on status -> retry budget
                                    (<= 3, backoff 30 s doubling to 120 s) -> RunLaneResult@v1.
  * tradeai-fabric-error            Error Trigger -> send-INTENT {domain fabric, kind workflow_error} -> POST /intent.
  * tradeai-fabric-run-lane-probe   inactive; Manual Trigger -> calls Run Lane once, dry_run, lane
                                    crontab-snapshot-for-health-agent (its dry_run writes only a shadow crontab copy;
                                    30 s timeout). No schedule: it runs only when the operator executes it.
  * tradeai-fabric-error-probe      inactive; throws on every scheduled fire (automatic-failure proof).
  Every one: active false, settings.errorWorkflow = tradeai-fabric-error, saveDataSuccessExecution all,
  saveManualExecutions false, only node types in FABRIC_ALLOWED_NODE_TYPES, only credential tradeai-run-relay.
  The six generic workflows are byte-unchanged (no live drift).

FINDINGS FROM THE OPERATOR'S LIVE RUN (2026-10-15 ~00:55 UTC) AND THE FIX (branch n8nfab/probe-manual-trigger-20261015)
-----------------------------------------------------------------------------------------------------------------
  State before the fix: the four workflows were IMPORTED INACTIVE with ids tradeai-fabric-run-lane,
  tradeai-fabric-error, tradeai-fabric-run-lane-probe and tradeai-fabric-error-probe; their graph hashes matched
  INDEX.json. 02 --probe then failed twice:
  F1 `n8n execute` -> "n8n Task Broker's port 5679 is already in use". Every n8n CLI process starts its own task
     broker and the live instance holds 5679. Fix: 02_proofs.sh runs EVERY n8n CLI call (execute, and the
     publish:workflow / unpublish:workflow of --error-proof) as `docker exec -e N8N_RUNNERS_BROKER_PORT=5690 ...`;
     01_import_inactive.sh (import/export) and 09_rollback.sh (unpublish) do the same, harmlessly, so no packet
     CLI call can collide with 5679.
  F2 with the port moved: "CliWorkflowOperationError: Missing node to start execution. Please make sure the
     workflow you're calling contains an Execute Workflow Trigger node". The CLI starts only from a Manual Trigger
     or an Execute Workflow Trigger; the probe started from a never-firing Schedule Trigger. Fix: the generator
     gives the probe a Manual Trigger ("Manual run") wired to "Probe input" and drops its schedule.
     n8n-nodes-base.manualTrigger joins FABRIC_RELAXED_NODE_TYPES (it runs only on an explicit CLI or editor
     execution and never on its own; the generic set does not gain it; live NODES_EXCLUDE does not exclude it).
     The ERROR probe is unchanged: it must fail AUTOMATICALLY on its schedule (addendum item 9).
  Hashes: the probe's graph hash changes (INDEX.json). The other three graph hashes do NOT change; only the policy
  hash (allowlist +1 type) and each file's meta.policy_sha256 do. The imported copies are therefore stale for the
  probe graph and for the policy stamp, so all four are re-imported: 01_import_inactive.sh --reimport.
  CLI-run executions: manual/CLI runs may not be stored in n8n (compose: manual executions are not saved), so for
  P1 the durable proof is the ledger runs + run_outcomes rows and the relay log (03_evidence.py), not n8n's list.

WHAT ACTIVATION NEEDS (in order; each is an operator act)
---------------------------------------------------------
  1. AGENTS.md 10.0.0 ratified and merged: APPROVE_AGENTS_POLICY_10_0_0 <pr_number> <head_sha> (§20).
     Until then §23.1 / §23.11 / §24.1 govern and this packet stops at step 0.
  2. This branch reviewed, CI green on the exact SHA, merged (operator word; it edits no AGENTS.md text).
  3. release-write grant naming the merged SHA: prepare + promote, which restarts the gateway, relay and executor
     units on the new code. (Without this the relay answers 404 relay_bad_path for /run_outcome and /intent.)
  4. config-write grant naming the four workflow ids for the n8n import (01) and the one-fire publish of the error
     probe (02 --error-proof). N8N_CONFIGURATION.md §3.3 historically names a `cron` grant for import/publish;
     the operator picks the scope, the grant reason must name the ids and "PR #N sha <sha>".
  Not needed now: no compose edit (live NODES_EXCLUDE does not exclude Execute Workflow / Switch / Merge, measured
  2026-10-14 in ~/m8m-bakeoff-lab/docker-compose.n8n.yml); no credential; no crontab or unit change.

STEPS
-----
  00_preflight.sh            read-only. build-fabric --check, --verify of the files, check_n8n_import_ready,
                             check_n8n_relay_contract (static + scratch-relay probe), the served release has the new
                             relay routes (relay --routes from CURRENT), and the four ids are absent from n8n.
                             --reimport: instead of absent, every row matching a fabric id or name must BE one of the
                             four ids, inactive (active false), unpublished (activeVersionId NULL), not archived;
                             prints the plan (CREATE / REPLACE per id).
  01_import_inactive.sh      --apply: docker cp + `n8n import:workflow` for the four files (inactive), then
                             `n8n export:workflow` of each and build-fabric --verify on the export (TRUSTED DEPLOYER:
                             the graph hash of what n8n holds must equal the manifest). Nothing is published.
  01_import_inactive.sh --reimport [--apply]: the same import OVER the inactive fabric set (preflight --reimport).
                             --apply exports each existing row to <stage>/before first (pre-image, kept), re-checks
                             the inactive rule, imports, then the same state check + export + --verify. Dry run (no
                             --apply) prints the plan and the graph hashes the exports must match.
  02_proofs.sh --probe       --apply: `docker exec -e N8N_RUNNERS_BROKER_PORT=5690 m8m-n8n n8n execute
                             --id=tradeai-fabric-run-lane-probe` (a CLI run of an inactive workflow from its Manual
                             Trigger; publishes nothing). Prints the CLI exit code, then 03_evidence.py either way.
  02_proofs.sh --error-proof --apply: at a quiet minute (hh:07 or hh:37), publish tradeai-fabric-error-probe,
                             restart n8n (CLI publish loads at start), wait for ONE fire (<= 75 s), unpublish,
                             restart. Then 03_evidence.py. Two n8n restarts: read the relay log for `op: due` between.
  03_evidence.py             read-only (sqlite mode=ro + relay log tail). Prints the rows the proofs must produce.
                             Usage: 03_evidence.py --since <ISO-8601 UTC, e.g. 2026-10-15T14:07:00+00:00>
                             [--ledger PATH]; with no arguments it prints this help (02_proofs.sh passes --since).

DRY-RUN PROOF PLAN (what "done" looks like; quote 03_evidence.py output in the PR)
----------------------------------------------------------------------------------
  P1 Run Lane success path (02 --probe):
     - ledger runs row run_id fabric-probe-<exec>-<ts>, lane crontab-snapshot-for-health-agent, mode dry_run,
       state RUN_DONE (or RUN_SKIPPED_LOCK if the cron snapshot held the lock: still a pass, status skipped_lock);
     - run_outcomes row for the same run_id: status success|skipped_lock, receipt_path that exists, duration_s;
     - relay_log.jsonl: one POST /run line (state REQUESTED) and >= 1 `op: run_outcome` line for that run_id;
     - n8n: `n8n execute` exits 0 and prints the probe's last node output (probe_ok true); IF n8n stored the CLI
       run, the probe and Run Lane executions show status success with Run Lane custom data run_id and lane_id
       (not guaranteed: see FINDINGS, CLI-run executions);
     - $STATE/data/runtime/n8n_runs/shadow/crontab_snapshot.txt mtime moved; the live snapshot did NOT move.
  P2 Error Trigger from an automatic failure (02 --error-proof; REFACTOR_PLAN addendum item 9):
     - n8n: one tradeai-fabric-error-probe execution, status error; one tradeai-fabric-error execution, success;
     - comms_intents row: domain fabric, kind workflow_error, workflow_id tradeai-fabric-error-probe, tier DIGEST,
       state QUEUED, count 1;
     - relay_log.jsonl: one `op: intent` line, state ACCEPTED;
     - NO Telegram message (no host consumer drains comms_intents yet; that is intended for Phase 1).
  P3 Refusal is data (hermetic in CI today; live once a matrix probe exists): tests/test_n8n_fabric_*.py and the
     node.js harness prove refused_policy / failed / skipped_lock / outcome_timeout branches and the retry-key rule.
  Exit criterion of the timer-only cutover FREEZE (§23.23 migration rule 1) is NOT met by P1-P2 alone: it also needs
  §23.23 ACTIVE and the REFACTOR_PLAN B5 fault-injection matrix (refusal, timeout, exit != 0, executor restart) run
  live with ledger parity. Propose that matrix probe as the next PR.

ROLLBACK
--------
  09_rollback.sh --apply: unpublish every fabric id that is active, restart n8n once, print the archive command
  (n8n's own /rest/workflows/<id>/archive, as packets/archive-16.sh does; never delete). Host side: promote the
  previous release SHA (release-write grant). The new ledger tables (run_outcomes, effect_claims, effect_owners,
  comms_intents) are additive and inert without the new code; leave them (rail 6, never delete).
  config/n8n_effect_keys.json is empty, so no live run is ever gated by this branch until a reviewed PR adds a lane.

RISKS AND HOW THEY ARE BOUNDED
------------------------------
  * A compromised n8n can now POST intents: bounded by the closed route table (DIGEST only), dedupe and 30/hour,
    and by having no consumer yet. It still cannot send, read a secret, or reach a broker route.
  * Run Lane polls the relay: <= 1 GET per 5-60 s per in-flight run; the relay logs each poll (op run_outcome).
  * Executor: one extra sqlite upsert per finished run; a failed upsert is logged and never fails the run.
