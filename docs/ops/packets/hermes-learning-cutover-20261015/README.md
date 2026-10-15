# hermes-learning on the n8n fabric: cutover packet (learn stage)

```
Status:      DRAFT (operator-run; nothing here is executed by merging it)
as_of:       2026-10-15T12:45:00Z
Measured at: branch n8nfab/hermes-learning-prereqs-20261015 on origin/main 94601ff69; served CURRENT = ea14e1c3a (none of this is served)
```

This packet moves the learn-stage steps of the Hermes learning chain from the cron stage runner to the n8n fabric
process `tradeai-fabric-hermes-learning`. It follows the cutover standard: fix, dry run, regression, and at least one
live n8n run while the cron line is still present. It also uses the fenced single-owner switch from AGENTS.md §23.23
migration rule (4). §23.21 is still PROPOSED (PR #1727), so the rules in force are §23.2 and §23.23.

The flow packet `docs/ops/packets/n8n-hermes-learning-flow-20261015/` covers import, the manual dry-run proof, the
shadow publish and the 5-day dry-run shadow. This packet starts after that shadow.

## What the prerequisite builds changed (all inert at merge)

| Gate | Build | Where | Inert because |
|---|---|---|---|
| G3 | The gateway validates `p:<lane>:<mode>:<slot>[:aN]` server-side. The key must name a runnable step of a registered process, in a mode the spec allows (`live` only when spec `mode` is `live`). The slot must be in the window (not in the future, not older than 3900 s). The slot must be the stage's scheduled slot, or a manual minute, which is allowed for `dry_run` always and for `live` only with `live_manual_slots: true`. The attempt must be within the step budget. A key that fails is refused as `run_process_key_invalid` with a `key_state`. The gateway stores the base key as the row's `slot_key`. The executor claims `fx:<lane>:<slot>:v1` for a live `p:` row only when that marker is present; otherwise it refuses with `effect:effect_process_key_unvalidated`. | `scripts/lib/n8n_process_keys.py`, `scripts/lib/n8n_coordination_gateway.py`, `scripts/n8n_run_executor.py` | spec `mode` is `dry_run`, so a live `p:` key is refused (`MODE_NOT_LIVE`) |
| G4 | Allowlist `offpeak_gate` makes the executor reproduce the cron wrapper's PEAK_SKIP for a LIVE run, using the same `deepseek_offpeak` window. A skipped run finishes `RUN_DONE` with reason `offpeak_skip`, spawns nothing and claims no key. A dry run only records the verdict. The five learn lanes use `bulk` (their cron steps use the default `--gate`). `autonomous_self_tune` declares `offpeak_exempt` because its cron step has no wrapper. | `scripts/n8n_run_executor.py`, `config/n8n_run_allowlist.json` | live_arg null |
| G5a | `hermes_tag_engine` is routed through the governed bridge as `advisory_desk` / `hermes_tag_engine` (bridge map and shared snapshot). The tag-engine lane's `llm_route` makes the executor bind `TRADEAI_LLM_VIA_BRIDGE=1`. `_llm_tags` then calls only `text_via_bridge`. The registry cap of $0.05/day is enforced by the bridge, and the registry row is now `tools_allowed: false`, `advisory_only: true`. A refusal returns no tags and never falls through to an in-process provider. The cron path is unchanged. | `scripts/hermes_tag_engine.py`, `scripts/lib/governed_process_routes.py`, `scripts/lib/cio_governed_model_bridge.py`, `config/llm_process_registry.json` | dry run makes no model call; live_arg null |
| G5b | `hermes_outcome_feedback_agent.py --notify queue` queues each eligible alert as a host comms intent (`research` / `hermes_closed_loop_alert`, producer-bound, in `config/host_comms_intent_routes.json`). The comms-intent consumer turns it into a P2 incident, and the incident notifier sends it. The lane calls no sender. n8n's `comms/intent` route cannot post this route, and the fabric policy hash does not move. | `scripts/lib/host_comms_intents.py`, `scripts/lib/hermes_outcome_bus/alert_notifications.py`, `scripts/lib/n8n_fabric_store.py`, `scripts/lib/n8n_comms_intent_consumption.py` | cron keeps `--notify chokepoint` (the default) |

The live argv for each step at cutover is recorded in `config/n8n_fabric_processes.json` as `cutover_live_arg`:
`--apply` for every step, and `--apply --notify queue` for `outcome_feedback_agent`.

## Scope and decisions

- **LEARN stage only.** The five steps that move are `outcome_grader`, `tag_engine`, `outcome_feedback_agent`,
  `outcome_learning` and `config_governor`.
- **Tune stays at shadow.** The cron step `autonomous_self_tune --apply` runs both the learn half and the purge half.
  An n8n-owned effect key would stop the purge half too. Its cutover needs the manifest split PR first (see "What
  remains").
- **`score_history_retention` stays on cron.** It is excluded: destructive retention, an operator decision.
- **The learn cron line is never retired in this packet.** It keeps running `score_history_retention`. With the five
  owners set to n8n, the runner records `skipped_effect` for those five steps and still runs retention.
- **D1 (operator): retention ordering.** The grader freezes score components before retention may delete them. After C3,
  the cron runner reaches retention within seconds of 10:50 while n8n's grader runs (measured median 6 s, max 7 s).
  Option A (recommended) moves the learn line to `20 11 * * *` in the C2 crontab edit, with its registry `match` in the
  same PR. The effect slot stays `<date>T1050` because it is the manifest minute. Option B accepts the race.
- **D2 (operator): alert delivery.** Under cron, hermes closed-loop alerts are sent at once as P2 (quiet-held). On the
  fabric they become a P2 incident in the incident notifier's batch, which runs every 30 minutes and is quiet-held
  22:00–07:00 ET. The content is the alert's subject and detail (300 characters).

## Sequence (each step is one operator act)

| # | Act | Command | Grant |
|---|---|---|---|
| 0 | Merge this PR. Then prepare and promote it. | release-write grant "PR #N sha <sha>" | release-write |
| 1 | **Dry run.** Regression, served gate check, PR plans, effect owners; `--apply` adds the manual n8n dry-run proof while the process is imported and inactive. | `bash 01_dry_run.sh` then `bash 01_dry_run.sh --apply` | fabric grant |
| 2 | Shadow (flow packet steps 1–4): import, publish, 5 days. The gate is **G1**: `python3 03_parity.py --date <D5> --mode dry_run --days 5` exits 0. | flow packet | fabric grant |
| 3 | **PR-1** sets `cron_claim` true for the five learn lanes. Merge, then serve. | `python3 10_cutover_pr.py --phase claim --write` in a branch, then the regression in step 1 | PR + release-write |
| 4 | **C1**: owner rows = cron. | `bash 02_live_run.sh --step c1` then `--apply` | fabric grant |
| 5 | **C2**: add `PIPELINE_EFFECT_CLAIM=1` to the learn line (and D1 if chosen). Verify one natural run: `fx:` keys DONE, scheduler cron. | `bash 02_live_run.sh --step c2` (prints the edit) | cron |
| 6 | **PR-2** sets spec mode live, `live_arg` = `cutover_live_arg`, and the learn lanes to stage canary. Merge, then serve. Before 10:40 ET. | `python3 10_cutover_pr.py --phase live --write` | PR + release-write |
| 7 | Relay live-lanes += the five learn lanes. | `bash 02_live_run.sh --step relay` (prints the edit) | config-write |
| 8 | **C3** is the recorded act: owners cron → n8n, at a quiet minute before 10:40 ET. | `python3 00_gate_check.py --phase live`, then `bash 02_live_run.sh --step c3 --apply` | fabric grant |
| 9 | **Live run with cron present.** The 10:50 scheduled n8n fire runs live. The cron line still fires, and its five steps come back as `skipped_effect`. | (natural fire) | — |
| 10 | **C4** evidence for that slot. | `bash 02_live_run.sh --step c4 --date <YYYYMMDD>` | — |
| 11 | 5-day live parity, then **PR-3** sets stage cutover. | `python3 03_parity.py --date <D5> --mode live --days 5`, then `python3 10_cutover_pr.py --phase promote --write` | PR + release-write |

Between steps 6 and 8, n8n's live requests are refused `effect_fenced_owner` while the owner is still cron. This shows
up as a process error in the error workflow (P2 DIGEST). To avoid it, do steps 6–8 on the same morning before 10:40
ET.

## Dry-run commands (no writes)

```
bash docs/ops/packets/hermes-learning-cutover-20261015/01_dry_run.sh
python3 docs/ops/packets/hermes-learning-cutover-20261015/00_gate_check.py --phase builds
python3 docs/ops/packets/hermes-learning-cutover-20261015/10_cutover_pr.py --phase live      # prints the PR-2 diff
bash docs/ops/packets/hermes-learning-cutover-20261015/02_live_run.sh --step c3             # prints the owner moves
bash docs/ops/packets/hermes-learning-cutover-20261015/09_rollback.sh                       # prints the rollback
```

## Regression (run in the PR-1, PR-2 and PR-3 branches)

```
.venv/bin/python -m pytest -q tests/test_hermes_learning_prereqs_20261015.py tests/test_n8n_fabric_hermes_learning_20261015.py \
  tests/test_hermes_learning_unblock_20261015.py tests/test_effect_claim_20261014.py tests/test_canary_effect_keys_20261015.py \
  tests/test_n8n_comms_intent_consumer_20261015.py tests/test_n8n_run_route_20261008.py \
  tests/test_n8n_executor_env_allowlist_20261009.py tests/test_alarm_coverage.py tests/test_dark_contract_guard.py
```

Some pins are inert-state pins: `live_arg is None`, `stage == shadow`, `cron_claim false`, `mode dry_run`. Those are in
`tests/test_n8n_fabric_hermes_learning_20261015.py`, `tests/test_hermes_learning_unblock_20261015.py` and
`tests/test_hermes_learning_prereqs_20261015.py`. Each cutover PR updates those pins in the same diff, and the review
reads the pin changes as the change being approved.

## Live-run command

The live run is the natural 10:50 ET scheduled fire after C3 (step 9). A manual live run is refused by design
(`MANUAL_LIVE_REFUSED`). Its effect key would differ from the cron runner's, so a manual live run could double the
effect. Turning `live_manual_slots` on is an operator act in a reviewed PR, and it must be turned off again in the
next PR.

## Parity check and the 5-day criteria

`03_parity.py` is read-only. Each day passes only if every item below holds.

**Shadow (`--mode dry_run`, G1)**, for each of the five learn steps:
- The n8n dry run ended `RUN_DONE` exactly when the cron step ended `ok`.
- The run row carries the gateway-validated `slot_key`.
- The receipt's off-peak verdict was `in_window`.
- Retention's cron step ended `ok`.

**Live (`--mode live`)**, for each step:
- The n8n live run ended `RUN_DONE`, and not `offpeak_skip`.
- The receipt's effect block is `claimed` with `final_state` `DONE`.
- `effect_claims` holds `fx:<lane>:<D>T1050:v1` `DONE` with scheduler `n8n`.
- The same day's cron step is `skipped_effect`, or absent. A cron `ok` here is a double effect, so it fails.

For each day:
- No `RUN_REFUSED`, `RUN_FAILED` or `RUN_TIMEOUT` row for a learn lane.
- Every intent queued by `host.hermes_outcome_feedback_agent` was consumed `DONE`.
- Retention's cron step ended `ok`.

**Gate:** `--days 5` exits 0, meaning five consecutive days of `PARITY`. A missed day, a `NO_PARITY` or a process error
resets the count; find the cause first (§0 rail 10). Read these alongside it:
- The bridge spend for `hermes_tag_engine` stays within its $0.05/day cap, and there is no in-process provider call
  for that process on a live day (llm consumption journal).
- config_governor's `output_signal` `data/runtime/hermes_config_governor_last.json` advances once a day.

## Rollback

`bash 09_rollback.sh --apply` runs R1: owners n8n → cron, compare-and-swap. From the next slot the cron runner owns the
five steps again. The header of `09_rollback.sh` lists R2–R5 in order: unpublish, relay env, revert PR-2, crontab
prefix. They are operator acts under their grants. No cron line is retired here, so rollback never needs an
uncomment. Ledger rows stay, because they are the audit trail (rail 6).

## What remains after this packet

- Tune stage: split `autonomous_self_tune` into a learn step and a purge step in `config/pipelines/hermes_learning.json`
  and the spec. The process plan requires the manifest and spec steps to match, which forces a graph change and a
  re-import. Then cut over the learn half with this same sequence. The purge half stays on cron.
- Retention ordering (D1) and alert delivery (D2) are operator decisions.
- Retire the learn cron line only when retention has its own cron line (crontab edit plus registry row, cron grant).
  The line is commented `# RETIRED <date> n8n-process hermes-learning ...` and never deleted.
- `TRADEAI_N8N_RELAY_LIVE_LANES` edits and every crontab edit are operator-only (§17).
