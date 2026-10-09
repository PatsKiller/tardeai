# n8n as scheduler-of-record — operating model (architecture package part 1, 2026-10-08)

**Status:** PROPOSED — workflow JSON generated and committed; nothing imported, nothing activated, no cron line retired
**Owner:** platform (workstream H, plan `streamed-humming-wolf` 2026-10-08; operator John)
**Scope:** the 70 unique lanes of doc 16 §4.2 tranches N1–N6 (doc 16 counts 71 because `portfolio-backup-cadence` is listed under both N2 and N5)
**Depends on:** run relay + executor + allowlist (workstream B), registry kind `n8n` + `_cutover.py --lane` (D), projection `source=runs` + Migration board (G), AGENTS.md 2.0.0 carve-out + ADR (E) — all in flight on 2026-10-08, none merged when this was written
**Caveat:** the relay host and port (`172.19.0.1:18092` in the plan) are **pending operator permission**; every generated workflow therefore carries the placeholder `http://RELAY_HOST:18092` and cannot reach anything until the operator substitutes the granted address at import time (§5.3)

This document says what n8n changes for THIS estate, in terms of files and receipts that exist or are being built this week, and gives the operator the exact import, activation, cutover and rollback steps. It contains no claim that is not tied to a path.

---

## 1. What is built in this PR

| artifact | path | what it is |
|---|---|---|
| generator | `scripts/n8n_workflow_templates.py` | one template → two workflows per lane (`<lane>-shadow` = `mode=dry_run`, `<lane>` = `mode=live`), deterministic output (`--check` is a CI gate: `tests/test_n8n_workflow_templates_20261008.py::test_committed_files_match_the_generator`) |
| N1 workflows (committed, importable) | `docs/implementation/n8n-parallel/workflows/generated/*.json` | 9 lanes × 2 = 18 files |
| N2–N6 workflows (visible, not yet for import) | `docs/implementation/n8n-parallel/workflows/generated/pending/*.json` | 61 lanes × 2 = 122 files |
| index | `docs/implementation/n8n-parallel/workflows/generated/INDEX.json` | `N8nWorkflowSet@v1`: per lane the tranche, cron, schedule source (the crontab line / timer `OnCalendar` / registry row it was read from), fidelity flag, both file names and both n8n workflow ids |
| checklist | `scripts/n8n_cutover_checklist.py --lane <id> \| --tranche N1 [--write]` | the shadow → canary → cutover → rollback ladder as Markdown checkboxes, ticked only from receipts on disk (§6) |
| CI anchor | `scripts/run_cio_hardening_ci.py` group `n8n_workflow_gen_20261008` | the two test files above |

Schedules were read on 2026-10-08 from `crontab -l` (1,045 lines), `systemctl --user cat <timer>` and `config/lane_registry.json` `scheduler.expression`, then frozen into the generator's `LANES` table so CI does not depend on the host it runs on. For the 18 lanes with an ACTIVE `kind: cron` registry row the test `test_registry_cron_rows_agree_with_the_table` proves the table equals the registry; for systemd lanes the `OnCalendar` → cron conversion is pinned by `test_oncalendar_conversion`.

Workflow shape for an ungated lane (fixed; `test_node_type_allowlist_and_chain_shape` refuses anything else). The four N2 edges in §9 insert a predecessor gate and are the only workflows that add If and Wait:

```
Schedule Trigger (cron, America/New_York)
  → Set "Relay constants"  TRADEAI_N8N_RUN_URL = http://RELAY_HOST:18092
  → HTTP Request v4.2      POST {{ $json.TRADEAI_N8N_RUN_URL }}/run
                           Header Auth credential "tradeai-run-relay", 10 s timeout, fullResponse
                           body {"lane_id": "<lane>", "mode": "dry_run"|"live", "requested_by": "<workflow name>"}
  → Code "Assert REQUESTED" status == 200 and (state == "REQUESTED" or duplicate == true), else throw("[<lane>/<mode>] …")
```

Why a Set node rather than `$env`: the lab compose sets `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` (`/home/johnclaw/m8m-bakeoff-lab/docker-compose.n8n.yml` line 56), so `{{ $env.X }}` throws inside this container. The Set node is the only way to keep the relay address out of the repo and still editable in one place per workflow. No Execute Command, SSH, email, Telegram, AI or vector node exists in any generated file; the compose `NODES_EXCLUDE` (line 60) additionally refuses executeCommand/ssh/ftp/emailSend at the instance.

---

## 2. The run path n8n plugs into (what it may and may not do)

```
n8n workflow ──POST /run {lane_id, mode}──▶ tradeai-n8n-run-relay.service   (B; binds 172.19.0.1:18092; one bearer; HMAC key stays here)
                                              │ signs claim scope=coordination_run
                                              ▼
                                   coordination gateway 127.0.0.1:18091  POST /v1/coordination route coordination/run
                                              │ validates lane ∈ config/n8n_run_allowlist.json, mode, idempotency key
                                              │ writes RunRequested@v1 → ledger table `runs` (state REQUESTED); NEVER spawns
                                              ▼
                                   tradeai-n8n-run-executor.service  (B; polls the ledger every 5 s)
                                              │ runs bash scripts/safe_flock.sh <lane lock> [market_day_gate.sh] $PY <runner> <dry_run_arg|live_arg>
                                              ▼
                                   RunReceipt@v1 → data/runtime/n8n_runs/*.json and ledger row RUN_DONE | RUN_FAILED | RUN_SKIPPED_LOCK | RUN_REFUSED
                                              ▼
                                   projection /api/v2/coordination/events?source=runs (G) → Command Center "Migration board" tab
```

Invariants the generated workflows respect, and which the plan's tests enforce on the host side:

- **n8n requests; the host executes.** The workflow's only output is the relay's JSON (`state`, `duplicate`, `run_id`). The command, cwd, lock, timeout and arguments come from `config/n8n_run_allowlist.json` on the host, tested against `pipeline_manifest.FORBIDDEN_COMMAND_TOKENS` / `FORBIDDEN_ROUTE_TOKENS` and `data_source_authority.json` writers. A workflow cannot name a command.
- **One credential in n8n**, the relay bearer (`tradeai-run-relay`, Header Auth), valid only at the relay. The HMAC key, provider keys, broker and Telegram credentials never enter the container (`docs/architecture/n8n/ADR_COORDINATION_SECRETS.md`, being rewritten by E).
- **The lane's existing lock is reused** (`scripts/safe_flock.sh <lock>`), so a cron line and an n8n trigger firing in the same minute produce one run and one `RUN_SKIPPED_LOCK` receipt — that receipt is the canary's double-run proof.
- **Receipts are the only evidence** (AGENTS.md §0 rule 8). A green n8n execution means "the relay accepted the request"; the lane ran only if `data/runtime/n8n_runs/<…>.json` says `RUN_DONE` and the lane's `output_signal` (registry row) moved.
- **Broker, send, memory, secret and deploy authorities are unchanged.** The 30 broker/positions/stops lanes, every sender, `sm-render`, guard and release deploy are in doc 16's "Never" row and are not in `LANES`.

---

## 3. What n8n improves here, concretely

Each row names the mechanism and the file or receipt that proves it. "Today" is the 2026-10-08 state.

### 3.1 Workflow reliability

| today | with n8n as scheduler-of-record | evidence |
|---|---|---|
| A crontab line that fails leaves a log line nobody reads; the lane monitor notices only when the `output_signal` goes stale past `expected_cadence_hours` (lane registry) | Every fire is an n8n execution with a status; a non-200 or non-REQUESTED answer fails the execution with `[<lane>/<mode>]` in the error (Code node). The executor's `RunReceipt` records exit code, duration and `output_signal` mtime before/after independently of the log | `generated/<lane>.json` Code node; `data/runtime/n8n_runs/*.json` |
| Minute-offset "implicit dependencies" between pipeline stages (`after-close` 16:05 → 17:25 → 17:35; `hermes-overnight` 23:13 → 02:20) are invisible and un-gated (doc 16 §4.2, citing Codex §7.3) | The four N2 edges in §9 gate stage k on `GET /runs/<stage k-1>/last` (`RUN_DONE` on the same America/New_York calendar day). The lane lock still serialises a double fire. Schedules are unchanged | §9; `INDEX.json` rows with `after` |
| A re-fire (manual + scheduled) runs twice unless the script locks | The gateway's idempotency key makes a re-fire answer `duplicate: true`, which the Code node accepts without creating a second run | plan §B "run operation … idempotency key"; Code node `duplicate === true` |

### 3.2 Visibility

| today | with n8n | evidence |
|---|---|---|
| 1,045 crontab lines plus ~60 user timers; the only consolidated view is `crontab_snapshot.txt` and the lane monitor's SILENT/ORPHANED verdicts | One workflow list per lane, each with its execution history (red/green, duration, error text); on the host, one row per run in the ledger `runs` table and one receipt per run; the Migration board tab shows per lane the scheduler-of-record, phase, last run mode/exit/duration, `output_signal` age and rollback-ready flag | projection `source=runs` (G); `data/runtime/n8n_migration_board_last.json` (G); `scripts/n8n_incident_fanin.py` already fans in coordination events every 5 min and gains `RUN_FAILED` (G) |
| "Did it run from n8n or from cron?" cannot be answered | `requested_by` in the run body is the workflow name (`<lane>-shadow` vs `<lane>`); the receipt carries it | HTTP node `jsonBody`; `RunReceipt@v1.caller_id` |

### 3.3 Error recovery

| today | with n8n | evidence |
|---|---|---|
| Rollback of the tranche-B cutover tool is a wholesale crontab restore (`scripts/pipelines/cutover/_cutover.py`) | `_cutover.py rollback --lane <id> --apply` re-enables exactly one commented line (`# RETIRED <date> n8n-cutover <lane>`) or re-enables one timer, and the workflow is deactivated; target < 5 min, receipt `CutoverReceipt@v1` under `data/runtime/n8n_cutover/` (D) | plan §D; checklist steps `rollback_dry`, `rollback_real` |
| A double scheduler (cron line present while n8n also fires) is silent | registry kind `n8n` with the cron line still present raises `CRON_PRESENT_WHILE_SCHEDULER_N8N` in `n8n_lane_host_conflict.classify_cron` and counts in `lane_state_drift` (D); it is a rollback trigger (§7) | `scripts/lib/n8n_lane_host_conflict.py` (D) |
| An outage of the scheduler host is the outage of everything | n8n down → no requests, cron (still present until cutover) keeps running during shadow and canary; after cutover the lane monitor's SILENT verdict and `n8n-lab-watchdog` (host-side, every 5 min, `data/runtime/n8n_lab_watchdog_last.json`) are the alarm | registry row `n8n-lab-watchdog` |

### 3.4 Maintenance

| today | with n8n | evidence |
|---|---|---|
| A schedule change is a crontab edit under a 30-minute cron-write grant, mirrored by hand into `lane_registry.json` (AGENTS.md §9.3 "a crontab line edit is a lane registry edit") | A schedule change is one row in `LANES`, a regenerated JSON file (diff reviewable in the PR), an import, and the registry row's `scheduler.expression` = workflow id; the crontab shrinks towards the plan's ≤ 300-line target | `scripts/n8n_workflow_templates.py` `LANES`; `--check` in CI |
| 44 of the 71 candidate lanes have no registry row at all (plan, "what exploration established"); 29 of the 70 generated lanes have none today | Every generated lane is named in `INDEX.json` with its schedule source, so D's registry PRs have an exact list; a lane cannot be cut over without its row (checklist step `registry_row`) | `INDEX.json` `schedule_source` strings ending "(no registry row…)" |
| Five timers (`governance-pipeline`, `portfolio-*-cadence`) run from the dev tree | Their n8n equivalents are generated (N2) but the executor runs from `CURRENT`; the re-pin stays a config-write grant item (D) | `INDEX.json` notes "dev tree, re-pin pending" |

### 3.5 Automation scale

| today | with n8n | evidence |
|---|---|---|
| Adding a job = a crontab line + a registry row + a lock + a log path, each by hand | Adding a lane = one `LANES` row + one allowlist entry + one registry row; the template supplies the rest. 70 lanes produced 140 workflows from one function (`build_workflow`) | `tests/test_n8n_workflow_templates_20261008.py` |
| The two in-n8n monitor workflows (`n8n-monitor-trade-ai`, `n8n-monitor-dof`) lost their targets when S1/S2 bound the API and DOF to loopback | They become relay-triggered lanes like any other (N1), so n8n never needs a path to a Trade AI listener other than the relay | `INDEX.json` notes on both lanes |

### 3.6 Operational execution

| today | with n8n | evidence |
|---|---|---|
| Cutover evidence is assembled by hand from logs | `scripts/n8n_cutover_checklist.py --tranche N1 --write` renders twelve boxes per lane and ticks each only from a file: dry-run receipt, live receipt with no `RUN_SKIPPED_LOCK`, readiness verdict, cutover dry/apply receipts, registry kind, rollback receipts, board row, post-cutover `output_signal` freshness | `data/runtime/n8n_cutover_checklist_N1.md` |
| Grants are requested per line | ONE cron-write grant per tranche, all lane cutovers batched in one 30-minute window (plan §H) | §5.5 |

---

## 4. What n8n does not do in this design (limits stated once)

- **It never runs a command.** `NODES_EXCLUDE` at the instance and the four-node allowlist in the generator both refuse it; the executor is the only process that spawns, on the host, from the allowlist.
- **It is not the source of truth for "ran".** The `RunReceipt` and the lane's `output_signal` are.
- **DAG gating is the four edges in §9, and nothing else.** Every other lane still fires by its cron offset alone. The gate is generated; it is not imported or activated by this change.
- **Cron OR-semantics.** `portfolio-lookthrough-cadence` (`OnCalendar=Sun *-*-01..07`, first Sunday) becomes `30 6 1-7 * 0`, which Vixie-style cron and n8n evaluate as (day 1–7) OR (Sunday) — extra fires. `openclaw-claude-plan-reminder-last-day` (`0 9 L * *`) becomes the 28th. Both are flagged `APPROXIMATE` in `INDEX.json` with the alternative (keep that one entry where it is).
- **One-shots.** The two OpenClaw `at` jobs (SuperGrok 2026-10-20, SentinelOne 2026-12-07) are generated as yearly crons flagged `ONE_SHOT`; deactivate after they fire.
- **Retired lanes.** `n8n-lab-backup` and `n8n-lab-restore-drill` are RETIRED (steps of `platform-maintenance-nightly/weekly` since 2026-10-07) and generated only so the N5 list is complete; do not activate them.
- **Execution data retention.** The compose still has `EXECUTIONS_DATA_SAVE_ON_SUCCESS=all`. The generated workflows' node outputs hold only `lane_id`, `mode`, `state`, `run_id` — no secret — but E's compose diff (`none` + 168 h prune) is a prerequisite of the ADR and should land before N2.
- **Name clash.** Two workflows named `n8n-monitor-trade-ai` / `n8n-monitor-dof` already exist in the lab; rename them `-legacy` or deactivate before importing the N1 set (n8n allows duplicate names, which would confuse the execution list).

---

## 5. Operator procedure

Everything below is an operator action; the agent that wrote this file does not run docker, import, create credentials, or edit the crontab.

### 5.1 Prerequisites (once)

1. Workstream B merged, released and promoted: `tradeai-n8n-run-relay.service` and `tradeai-n8n-run-executor.service` installed from `CURRENT` under the config-write grant; `TRADEAI_N8N_RELAY_BEARER` and `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N` in Bitwarden SM and `env.manifest.json`; `curl` from inside the container to the relay with the bearer returns a `RunRequested` row for `n8n-lab-watchdog` in `dry_run` (plan "Verification").
2. ufw rule: `172.19.0.0/16 → 18092` only (E's proposal).
3. Workstream D merged: `lane_registry.SCHEDULER_KINDS` includes `n8n`; `_cutover.py --lane` exists.
4. The one n8n credential, created in the n8n UI (`http://127.0.0.1:5678`, owner account): **Credentials → Add → Header Auth**, name `tradeai-run-relay`, header *Name* `Authorization`, header *Value* `Bearer <TRADEAI_N8N_RELAY_BEARER>` (paste from SM; never from a file in the repo or a chat). Exactly one credential of this type must exist with this name: the import matches the nodes' credential reference by type and name.

### 5.2 Render with the granted relay address (keeps the repo IP-free)

```bash
REPO=/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
STAGE=$HOME/.local/state/tradeai/n8n-import-$(date -u +%Y%m%dT%H%M%SZ)
cd "$REPO" && python3 scripts/n8n_workflow_templates.py --lanes N1 --out "$STAGE" --relay-url http://<GRANTED_HOST>:18092
# the repo copy keeps http://RELAY_HOST:18092; the staged copy carries the granted address
python3 scripts/n8n_workflow_templates.py --lanes all --check     # repo copy still clean
```

### 5.3 Import (N1: 18 files, all inactive)

```bash
docker cp "$STAGE/." m8m-n8n:/tmp/tradeai-workflows/
docker exec m8m-n8n n8n import:workflow --separate --input=/tmp/tradeai-workflows/
docker exec m8m-n8n n8n list:workflow            # 18 new rows, active=false; ids match INDEX.json
docker exec m8m-n8n rm -rf /tmp/tradeai-workflows
```

`--separate` imports every `*.json` in the directory (top level only, so `pending/` is never swept in by accident). Workflow ids are deterministic (`INDEX.json` `shadow_workflow_id` / `live_workflow_id`), so a re-import of a regenerated file updates the same workflow instead of creating a twin. If a node shows "credential not found", open it once and pick `tradeai-run-relay`.

After import, export the lab back into the repo so the history matches: `python3 scripts/n8n_export_workflows.py --write` (existing tool; strips credential refs).

### 5.4 Activate in ladder order (per lane; one tranche per window)

| phase | n8n action | host state | proof required before the next phase |
|---|---|---|---|
| shadow | activate `<lane>-shadow` only (`docker exec m8m-n8n n8n update:workflow --id=<shadow_workflow_id> --active=true`, or the UI toggle) | cron line / timer live | `data/runtime/n8n_runs/` has a `mode=dry_run` `RUN_DONE` receipt for the lane; the execution is green; the cron lane's own receipt unchanged |
| canary | deactivate `-shadow`; activate `<lane>` | cron line / timer still live | a `mode=live` `RUN_DONE` receipt with the same `output_signal` path, exit 0, and no `RUN_SKIPPED_LOCK` inside one cadence; for weekly/monthly lanes one manual natural-equivalent fire (UI "Execute workflow") |
| cutover | nothing in n8n | `_cutover.py --lane <id>` dry-run, then `--apply` under the tranche's cron-write grant: line commented `# RETIRED <date> n8n-cutover <lane>` (or `systemctl --user disable --now <timer>`), registry row → `kind: n8n`, `CutoverReceipt@v1` written | `check_lane_registry --fail-on-new --state-drift` clean; board row phase CUTOVER |
| rollback drill | deactivate `<lane>` | `_cutover.py rollback --lane <id>` dry-run (every lane) and `--apply` (first lane of each tranche), then re-cut | rollback receipt; the exact line is back, uncommented |
| acceptance | — | — | the next natural fire's `RunReceipt` and a fresh `output_signal` |

`scripts/n8n_cutover_checklist.py --tranche N1 --write` after each phase shows which boxes the receipts have ticked.

### 5.5 Day 0–4 sequence (plan "Schedule", unchanged)

| day | tranche | lanes | grants (one per tier, batched per tranche) |
|---|---|---|---|
| 0 Thu 10-08 | N1 | 9: `n8n-pilot-dispatch`, `n8n-incident-fanin`, `n8n-research-intake-consumer`, `crontab-snapshot-for-health-agent`, `n8n-lab-watchdog`, `lane-governance-packet-weekly` (first scheduler; needs its registry state flipped from NEVER_SCHEDULED), `maturity-remeasure` (weekly: manual natural-equivalent canary), `n8n-monitor-trade-ai`, `n8n-monitor-dof` | config-write (2 units + alert units + 5 timer re-pins); one cron-write for the N1 cutovers; tranche-B cutovers at 17:40 ET per their own packet |
| 1 Fri | N2 | 17 pipelines and cadences (`pending/` → move to top level by regenerating with `COMMITTED_TRANCHES` extended, in the N2 PR) | cron-write N2; service grant for the bridge restart (C) |
| 2 Sat | N3 + N4 | 12 + 20; needs D's registry rows and the `--receipt` flags for the five scripts that write nothing (`alert_daily_digest`, `ops_daily_digest`, `desk_suggestions_digest`, `job_coverage_monitor`, `youtube_cookie_health_check`) | cron-write + config-write (audit timers) |
| 3 Sun | N5 + N6 | 6 + 6; DOF lanes only if `dof_reader` is granted, else N6 ships the four OpenClaw reminders | cron-write; DOF role decision |
| 4 Mon | — | acceptance report; architecture package 17 (this) / 18 (C) / 19 | final signoff |

---

## 6. Checklist semantics (what a tick means)

`scripts/n8n_cutover_checklist.py` ticks a box only when it can name a file. It never writes outside `data/runtime/n8n_cutover_checklist_<lane|tranche>.md`, and every input is optional:

| box | source | tick rule |
|---|---|---|
| workflows | `workflows/generated/INDEX.json` + both files | both files exist |
| registry_row / registry_n8n | `config/lane_registry.json` | row exists / `scheduler.kind == "n8n"` |
| shadow / canary | `data/runtime/n8n_runs/*.json` with `lane_id` | ≥ 1 `mode=dry_run` ok / ≥ 1 `mode=live` ok and **zero** live receipts not ok (`RUN_FAILED`, `RUN_SKIPPED_LOCK`, `RUN_REFUSED`) |
| readiness | `data/runtime/n8n_lane_readiness_last.json` | lane verdict in {READY, GO, GREEN, PASS} |
| cutover_dry / cutover_apply / rollback_dry / rollback_real | `data/runtime/n8n_cutover/*.json` with `lane_id` | `action` and `dry_run` fields |
| board / natural_fire | `data/runtime/n8n_migration_board_last.json` | phase CUTOVER + `rollback_ready` / `output_signal_fresh` |

The readers are tolerant of the exact field names B, D and G ship (`state` or `status`, `dry_run` or `apply`, `lanes` as list or dict); if a producer uses something else the box simply stays unticked and names the file, which is the safe direction.

---

## 7. Rollback triggers (plan, verbatim in substance)

Automatic finding → operator decision, per lane: `RUN_FAILED` where the last three cron runs succeeded; `output_signal` older than 2× cadence after cutover; `CRON_PRESENT_WHILE_SCHEDULER_N8N`; relay bearer failures; n8n `/healthz` down > 10 min (`n8n-lab-watchdog`); any `RUN_REFUSED` row.

Rollback = `python3 scripts/pipelines/cutover/_cutover.py rollback --lane <id> --apply` (re-enables the exact line or timer, writes the receipt) + deactivate the n8n workflow (`n8n update:workflow --id=<live_workflow_id> --active=false`). Target < 5 minutes. The shadow workflow may stay active through a rollback: it only requests dry runs.

---

## 8. Open items (not done in this PR)

1. Relay address: placeholder until the operator grants the bind; §5.2 is the substitution step.
2. 29 generated lanes have no registry row (`INDEX.json` says which); D's tranche PRs create them. No lane is cut over without its row.
3. `lane-governance-packet-weekly` is NEVER_SCHEDULED; n8n would be its first scheduler — the registry state change is part of its cutover PR.
4. Activating the §9 gate (import is still an operator step). The overnight edge accepts the previous evening; see §9.
5. Moving N2–N6 out of `pending/` is one line per tranche (`COMMITTED_TRANCHES`) in the generator plus a regeneration, in that tranche's PR.
6. The two `APPROXIMATE` schedules and the two `ONE_SHOT` reminders need an operator choice at import (§4).
7. `n8n_export_workflows.py` strips `credentials` from nodes; after the first import, the exported copy of a generated workflow will differ from the generated one by that key only. A later PR can teach the export to keep the credential *name* (no secret) so the two copies compare equal.

---

## 9. N2 DAG gate

Stage k of a pipeline fires only after stage k−1's newest run row is `RUN_DONE` for the same America/New_York calendar day, or for the previous day when the predecessor's single fire is later in the ET day than this lane's. Four edges, and only these, carry `after` (on the lane in `config/n8n_migration_tranches.json` tranche N2 and on the matching `LANES` row). `premarket-data-pipeline`, `platform-maintenance-*`, `governance-pipeline`, the portfolio cadence lanes, and `portfolio-backup-cadence` (counted in N5 by the tranche note, generated with the N2 rows) have no predecessor.

| stage | fires only after |
|---|---|
| `after-close-pipeline-broker-truth` | `after-close-pipeline-close-capture` |
| `after-close-pipeline-planning` | `after-close-pipeline-broker-truth` |
| `hermes-learning-pipeline-tune` | `hermes-learning-pipeline-learn` |
| `hermes-overnight-pipeline-night` | `hermes-overnight-pipeline-close` |

The relay route is read-only `GET /runs/<lane_id>/last` (bearer, the same check as `GET /status`; a bad bearer is `relay_bad_bearer` / 401). During weekly rotation the relay accepts `TRADEAI_N8N_RELAY_BEARER` or `TRADEAI_N8N_RELAY_BEARER_PREVIOUS`, and the gateway verifies an `n8n-relay` claim with `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N` or `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N_PREVIOUS`. `scripts/secrets/render_env.py` copies a replaced value into the `overlap_previous` name from `config/secret_registry.yaml`. A missing previous value is the pre-rotation state; a short one refuses process start. Neither value is written to a receipt. The lane id is letters, digits, and `.` `_` `-` only; any other path, including an extra segment, is `relay_bad_path` / 404. The handler calls the coordination projection `project_runs(path, lane_id=..., limit=1)` and returns that newest row. It does not run an allowlist command and it does not POST to the gateway. A missing ledger or a lane with no row is HTTP 200 with `last: null` and the projection's `status`. The body stays within 1024 bytes.

Both the shadow workflow and the live workflow for a gated lane are:

```
Schedule → Set relay constants
  → HTTP GET {{ $json.TRADEAI_N8N_RUN_URL }}/runs/<after>/last   (Header Auth credential tradeai-run-relay)
  → Code: state == RUN_DONE and finished_at falls on the same America/New_York calendar day
         as new Date() at execution (the day is not written into the JSON). When the predecessor's
         single minute-of-day is later than this lane's, the previous America/New_York date counts too.
  → IF gate_ok → POST /run → Assert REQUESTED
  → else Wait 60 seconds and GET again
```

`MAX_GATE_RETRIES` is 5: that many failed waits, then the Code node throws, and the message includes the lane id. Ungated workflows stay Schedule, Set, POST, Assert.

`hermes-overnight-pipeline-close` is 23:13 ET and `hermes-overnight-pipeline-night` is 02:20 ET. The generator does not name that pair. It compares the two crons: when the predecessor's single minute-of-day is later than this lane's, `CROSSES_MIDNIGHT` is true and a `RUN_DONE` from the previous America/New_York calendar day satisfies the gate, as does one from today. The other three N2 edges fire later in the same day, so they stay on today only. A cron that is not one hour and one minute does not cross.
