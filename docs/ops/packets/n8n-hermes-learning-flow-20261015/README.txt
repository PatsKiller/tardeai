N8N FABRIC PROCESS hermes-learning (learn -> tune) — OPERATOR ACTIVATION PACKET (2026-10-15)
=============================================================================================

Branch: n8nfab/hermes-learning-flow-20261015 (local commit only; nothing pushed, merged, served or imported).
Design: AGENTS.md §23.23 (10.0.0 ACTIVE): n8n owns FLOW, the host owns authority and evidence; cutover keeps the
§23.21 standard (fix + dry run + regression + one live n8n run with cron still present under a shared lock) plus the
fenced single-owner switch. arch-review-20261014 WS1b-03 / WS1b §"2. First process": hermes_learning as the pilot.
Every script here is a DRY RUN unless given --apply. Nothing here edits the crontab, a systemd unit, the relay
live-lanes env or broker code; 05/09 write only effect_owners rows, and only with --apply.

WHAT THE BRANCH ADDS
--------------------
  config/n8n_fabric_processes.json   process spec: workflow id, manifest, mode dry_run, per-step lane, depends_on,
                                     blocked reason. The single source the generator and the tests read.
  tradeai-fabric-hermes-learning     generated (build-fabric), INACTIVE, in docs/implementation/n8n-maturity/workflows/
                                     fabric/ + INDEX.json (graph 44c35ad3374f... after the 2026-10-15 unblock, was 573444e1e8f7; policy hash unchanged, so the four
                                     Build 1 imports still verify). Graph:
      Manual run -> Plan manual (stage all) --\
      Schedule learn 50 10 * * * -> Plan learn ---> Process context (slot, mode) -> Route stage (Switch)
      Schedule tune  0 17 * * *  -> Plan tune  --/
      per step: Gate <step> (blocked? every dependency `success`?) -> Run? <step> (If)
                -> Run <step> (Execute Workflow -> PUBLISHED tradeai-fabric-run-lane, waits) -> Result <step>
      learn:  outcome_grader -> { tag_engine -> outcome_feedback_agent ; outcome_learning -> config_governor ;
                                  score_history_retention } -> Join learn (Merge, 3 inputs) -> Done learn
              -> Then tune? (manual run only) -> tune: autonomous_self_tune -> Done tune -> Process result
      Process result (FabricProcessResult@v1: every step's run_id + status, in manifest order) -> Assert process
      (throws when a step failed / was refused: the execution is an error -> errorWorkflow tradeai-fabric-error ->
      host intent). settings: errorWorkflow tradeai-fabric-error, saveDataSuccessExecution all, timeout 3600 s.
      Idempotency key per step: p:<lane>:<mode>:<slot>, slot = <YYYYMMDD>T<stage cron HHMM> for a scheduled stage
      (the same string the stage runner's effect-key claim uses), the current minute for a manual run.
      Retries: Run Lane's budget (max_attempts 1 per step since the 2026-10-15 unblock, was 2; outcome_timeout =
      step timeout + 120 s capped at 1000 s, autonomous_self_tune capped at 600 s by the spec's outcome_timeout_s);
      the generator refuses a spec whose worst case exceeds 3600 s (six runnable steps: 3580 s).
      n8n v1 execution order runs branches one after another: "parallel" = a failure in one branch never stops a
      sibling. Concurrency would need waitForSubWorkflow false, which loses the per-step result: not used.
  Host side (inert until served):
      allowlist  hermes-learning-outcome-grader / -outcome-learning / -config-governor: dry run only (live_arg null),
                 lock = the step command's own lock, timeout = the manifest step timeout, env report mode.
                 blocked_reasons for the four BLOCKED step lanes (no entry).
      registry   three kind-n8n rows, expression = the process workflow id, stage shadow, NO dispatch block (the
                 generic dispatcher never emits them), state NEVER_SCHEDULED until the publish.
      contracts  config/n8n_health_contracts.json REVIEWED (agent-reviewed against source; the operator's REVIEW
                 pass is still owed, SW4 precedent).
      effect keys config/n8n_effect_keys.json: one per runnable step (process = lane id, input_version v1,
                 pipeline/stage/step_id, cron_claim false). Executor: inert for dry_run.
      runner     scripts/pipelines/_manifest_runner.sh: claims fx:<process>:<slot>:<ver> as scheduler cron before a
                 step ONLY when the cron line sets PIPELINE_EFFECT_CLAIM=1 AND the lane has cron_claim true
                 (both off). Refused claim (75) or unreadable ledger: the step runs nothing, status skipped_effect.
                 Finish: ok -> DONE, failed -> FAILED (re-claimable), timeout -> UNKNOWN (operator release).
                 pipeline_manifest.py --effect-spec / --effect-slot.

STEP MAP
--------
  (updated 2026-10-15 by the unblock branch n8nfab/hermes-learning-unblock-20261015)
  step                     lane                                     depends_on        dry run              state
  outcome_grader           hermes-learning-outcome-grader           -                 SAFE (SELECT only)   shadow lane
  tag_engine               hermes-learning-tag-engine               outcome_grader    SAFE (--dry-run: no  shadow lane
                                                                                      model call, r/o, no DDL)
  outcome_feedback_agent   hermes-learning-outcome-feedback-agent   tag_engine        SAFE (--dry-run: r/o, shadow lane
                                                                                      never notifies)
  outcome_learning         hermes-learning-outcome-learning         outcome_grader    SAFE (no commit)     shadow lane
  score_history_retention  hermes-learning-score-history-retention  outcome_grader    safe; DESTRUCTIVE    EXCLUDED
                                                                                      (cron retention, operator decision)
  config_governor          hermes-learning-config-governor          outcome_learning  SAFE (--dry-run,     shadow lane
                                                                                      read-only session)
  autonomous_self_tune     hermes-learning-autonomous-self-tune     - (tune stage)    SAFE (--learn        shadow lane
                           (lane runs --learn only)                                   --dry-run: r/o, no DDL, no file)
  Dependencies are data flow read from the scripts (ledger -> tags / calibration -> governor; retention after the
  grader freezes score components) and every one points to an EARLIER manifest step, so the shell runner's serial
  order stays a valid topological order and shadow parity is comparable.
  2026-10-15 UNBLOCK (code changes; the cron lines and their flags are unchanged):
    tag_engine               scripts/hermes_tag_engine.py --dry-run: no model call (rows the live run would classify
                             are counted in retag.llm_would_call), read-only session, tag_efficacy skips its DDL.
    outcome_feedback_agent   lib/hermes_outcome_bus/alert_notifications.py: every send is a declared intent through the
                             host chokepoint (send_telegram priority P2 critical/warning, P3 info, producer
                             hermes_outcome_feedback_agent; bypass_router dropped, its BYPASS_ALLOWLIST entry removed).
                             --dry-run (read-only, never notifies); --notify record calls no sender (intents returned).
    autonomous_self_tune     --learn = auto-graft only; the purge helpers raise LearnOnlyViolation in that mode.
                             --dry-run (read-only, no CREATE TABLE, no weights write). Historical flags byte-identical.
    score_history_retention  NOT changed: stays on cron as retention, excluded from the fabric process.
  Original blocked reasons (2026-10-15 flow branch; now resolved except score_history_retention):
    tag_engine               dry run still calls lib.governed_cloud_generation.generate_cloud (_llm_tags): needs a
                             --dry-run that skips the LLM + an llm_route (§23.18 llm class). Code PR.
    outcome_feedback_agent   --apply sends Telegram (alert_notifications -> send_telegram): never-list sender; the
                             send must become a host comms intent (§24.1). Code PR.
    score_history_retention  DELETE FROM hermes_score_history: never-list destructive retention. Operator decision.
    autonomous_self_tune     self_purge (archived DELETEs) in the same --apply as the auto-graft: split --learn from
                             --purge (code PR); the learn half can then be a lane, the purge half stays host.

PREREQUISITES (operator acts, in order)
---------------------------------------
  P1 Branch reviewed, CI green on the exact head, merged (operator word).
  P2 release-write grant naming the merged SHA and "PR #N sha <sha>": prepare + promote (the gateway, relay and
     executor restart on the new allowlist/registry; without it Run Lane gets 403 run_lane_not_allowlisted ->
     refused_policy -> the process fails at Assert process).
  P3 Build 1 state holds: tradeai-fabric-run-lane and tradeai-fabric-error PUBLISHED (00_preflight.sh step 3).
  P4 One grant naming tradeai-fabric-hermes-learning for import + publish (config-write or cron, the operator's
     scope; N8N_CONFIGURATION.md §3.3). Export it as TRADEAI_FABRIC_GRANT.

STEPS
-----
  1 IMPORT INACTIVE   bash 01_import_inactive.sh [--apply]       preflight, import (inactive), export + --verify.
  2 VERIFY            bash 02_verify.sh [--apply]                CLI run from the Manual Trigger: stage all, dry_run.
                      Pass: CLI exit 0; its last node prints FabricProcessResult@v1 overall `partial` with
                      outcome_grader / outcome_learning / config_governor `success` (run_id p:...:dry_run:<minute>)
                      and the other four `blocked`; 04_evidence.py --manual shows three RUN_DONE dry_run ledger rows.
  3 PUBLISH (SHADOW)  bash 03_publish_shadow.sh [--apply]        arms 10:50 (learn) and 17:00 (tune) ET, dry_run, NEXT
                      TO the stage runner, which keeps every effect. Same day: the registry PR flipping the three
                      step rows to ACTIVE + the active-workflow snapshot refresh (check_lane_registry).
  4 EVIDENCE          python3 04_evidence.py --date <YYYYMMDD> --stage learn   after every 10:50 fire (read-only).
                      SHADOW PLAN: 5 CONSECUTIVE daily learn slots, each "verdict": "PARITY": every runnable step's
                      n8n dry run RUN_DONE when the cron step ended ok (and both unhealthy together), no n8n run for a
                      blocked step. Compare per step: status, n8n dry-run duration vs cron live ms (a dry run is
                      shorter: it writes nothing), and the dry run's stdout tail (ledger counts / detectors_fired)
                      against the cron step's log. Also read the saved n8n execution of each fire (execution_entity
                      deletedAt IS NULL, custom data process_id/stage/slot/overall): it must show every step.
                      A missed day, a NO_PARITY or a process error resets the count (find the cause first, §0 rail 10).
                      Tune: NO_RUNNABLE_STEP while autonomous_self_tune is BLOCKED (its fire still proves the trigger).
  5 CUTOVER           bash 05_cutover.sh (read-only gate check), then C1..C5 in its header:
                      C1 --owner cron --apply; C2 crontab PIPELINE_EFFECT_CLAIM=1 on both stage lines (cron grant);
                      C3 --owner n8n --apply = the one recorded act; the live n8n run with cron still present (cron's
                      claim is refused, skipped_effect; n8n claims the same key; the step lock is shared);
                      C4 evidence; C5 comment the stage cron line `# RETIRED <date> n8n-process hermes-learning ...`.
                      CANNOT MOVE YET (gates G2-G5):
                        G2 (after the 2026-10-15 unblock) ONE excluded step, score_history_retention, plus the purge half
                           of autonomous_self_tune: both are destructive retention that stays on cron, so neither stage
                           line can be commented out as is. Learn: the stage line must keep (or be replaced by) a cron
                           line for score_history_retention. Tune: the cron line becomes `--purge --apply` when the
                           fabric lane goes live with `--learn --apply`. Both are crontab edits under a cron grant.
                           Original text: four BLOCKED steps: retiring a stage line would stop them. Path A (recommended): the three
                           code PRs + one operator decision above, then cut over whole stages. Path B (partial, not
                           recommended): owners of the three runnable steps -> n8n while the runner keeps the blocked
                           four; the runner skips the three at once (skipped_effect) and runs tag_engine while n8n may
                           still be running outcome_grader, so the learn stage loses its order. Operator decision.
                        G3 the gateway does not validate p: keys yet; a LIVE p: run is refused by the executor
                           (effect:effect_slot_unknown, fail closed). Next host PR: gateway check_process_key (lane is
                           a step of a spec process, mode == spec mode, slot == today's stage slot or a manual minute
                           under an operator flag) and the executor's slot parse for p: keys. Then spec mode live,
                           allowlist live_arg ["--apply"], registry stage cutover, cron_claim true, relay live-lanes.
                        G4 the cron steps run inside run_with_deepseek_offpeak.sh (a PEAK_SKIP gate); the executor does
                           not apply it. Reproduce it on the n8n path (a lane gate or the schedule window) first.
                        G5 (2026-10-15 unblock) per-step live prerequisites: tag_engine needs an llm_route (process
                           hermes_tag_engine has no governed_process_routes route and generate_cloud runs in-process, not
                           via cio-governed-bridge; AGENTS.md §23.18 llm class) before a live_arg; outcome_feedback_agent
                           live must run with --notify record and the intents reach the operator through the n8n
                           send-intent route (needs a hermes route in config/n8n_comms_intent_routes.json, which moves the
                           fabric policy hash: re-verify the imported fabric workflows) or the notify half stays on cron;
                           autonomous_self_tune live is --learn --apply (a weights-file writer in the release tree, the
                           checkout-survival trap in tests/test_runtime_state_survives_checkout.py) with its outcome
                           wait capped at 600 s against an executor timeout of 1800 s.
  9 ROLLBACK          bash 09_rollback.sh [--apply]   unpublish (+1 restart), owners n8n -> cron (CAS); uncomment
                      a retired stage line (cron grant). Shadow rollback is unpublish only: cron never stopped.
                      Host: previous release under a release-write grant; ledger rows stay (rail 6).

RISKS AND HOW THEY ARE BOUNDED
------------------------------
  * Double effect: impossible in shadow (n8n requests dry_run; stage shadow clamps live; live_arg null). At cutover
    the effect key + owner epoch fence it (tests: test_n8n_fabric_hermes_learning_20261015.py runner section).
  * Executor load: three dry runs at 10:50 next to the cron stage (single worker; each a few seconds).
  * Lock contention: a dry run takes <lock>.dryrun, never the cron step's lock (executor lock_path_for).
  * n8n down: the stage runner is unaffected (shadow); at cutover the P1 path never depends on n8n (§23.23).
  * CLI start node: `n8n execute` must start from the Manual Trigger; if n8n 2.43 picked a Schedule Trigger the CLI
    refuses ("Missing node to start execution") and nothing runs — report it, do not publish to work around it.
