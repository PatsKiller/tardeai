# n8n parallel program — phase 0 baseline

Status: measured record. Not a cutover, not a production grant, and not proof that n8n owns any Trade AI or DOF job.

> Correction 2026-10-07: two "enabled while retired" rows were spent one-shots, not a second owner. The approval ledger age is explained, the `dof_*` role was queried, and the gateway, ADR correction, and watchdog are in `06-findings-and-gateway.md`. The census figures below are the original measurement. Syslog CMD lines are still not a missed-fire rate and not a consumer receipt.

Census time: 2026-10-07T00:49:34Z (2026-10-06T20:49:34-04:00). Journal day buckets were recounted a few minutes later from the same host journal. Machine-readable copies are in `ledgers/`.

Labels used below: OBSERVED_SERVED, OBSERVED_LAB, WIRED_UNPROVEN, DESIGN_ONLY, BLOCKED, FAILED, EXPECTED_SILENT, NOT_MEASURED.

## Served pin and scope

| Source | Identity | Label |
|---|---|---|
| Trade AI build meta `GET /v3/build-meta.json` | HTTP 200, git_sha `18a27ff288894c4e428151d5f385e68522ecd47b`, built_at `2026-10-06T22:08:40.117Z`, branch `main`, release_label `main-exact-phase2`, ui `3.14+mux8d5sp` | OBSERVED_SERVED |
| portfolio-server working directory | `/home/johnclaw/trade-ai-releases/portfolio-server/18a27ff28-main-exact-phase2-20261006-180747` (active, running) | OBSERVED_SERVED |
| origin/main and this worktree `wt/n8n-parallel-20261007` | same SHA `18a27ff288894c4e428151d5f385e68522ecd47b` | OBSERVED_SOURCE |
| Primary checkout | detached at that SHA, dirty file count 2. This program did not edit it. | OBSERVED_SOURCE |
| DOF dashboard | active, cwd `/home/johnclaw/nyc-dof-auction`, HEAD `1f3186d563076da62c38c4294321b0c65086be50`, branch `master`, clean | OBSERVED_SERVED |
| DOF run scope | `GET /api/run-scope` HTTP 200, limited true, locations `["Bronx"]` | OBSERVED_SERVED |
| n8n lab | `GET /healthz` HTTP 200, image `n8nio/n8n:2.43.0`, digest `sha256:c6a3a0461d1d3ffc16d849adf57606c2b028667ade70cce2faa2ff094734873c`, UI `127.0.0.1:5678` | OBSERVED_LAB |

n8n is running on this host as a lab. It is not the production orchestrator. The discovery note that ms01 was unreachable, and that n8n was not known to be installed, does not describe this machine at the census time.

Database schema version was not read during this census. A later read-only metadata query is recorded in `06-findings-and-gateway.md`. Label for this census section: NOT_MEASURED.

## Policy read

Trade AI `AGENTS.md` in this worktree is Policy-Version 1.5.1, Status ACTIVE. `AI_WORK_POLICY.md` still requires `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` for a push. This program does not set that variable and does not push. `docs/governance/NEW_AGENT_STARTS_HERE.md` is present. The LLM governance ADR and the lane registry were read. The lab agent file under `/home/johnclaw/m8m-bakeoff-lab/docs/AGENTS.md` stays subordinate to Trade AI `AGENTS.md`.

The DOF checkout has no `AGENTS.md`, `AI_WORK_POLICY.md`, or top-level `README.md`. Source is present. A written DOF agent policy was not found. Label for that policy: NOT_MEASURED. GitHub remote `https://github.com/PatsKiller/nyc-dof-auction.git` is configured. Remote reachability was not probed this pass.

Companion filenames named by the work order (`TRADE_AI_N8N_MIGRATION_DESIGN_2026-10-06.md`, `M8M_ORCHESTRATION_DECISION_AND_IMPLEMENTATION_PLAN_v1_0_20261006.md`, `M8M_TRADE_AI_DOF_FULL_EXECUTION_WORK_ORDER_v1_0_20261006.md`) are not in this worktree. They were not treated as canonical. Architecture v3.3 is in `docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md`. Its diagram edges were not re-scored. Label: DESIGN_ONLY.

## Registries (source declarations)

From `config/lane_registry.json` at the served SHA (hash in `ledgers/sha-matrix.json`):

- Schema `LaneRegistry@v1`, authority `READ_ONLY_ADVISORY`, seeded `2026-08-30`.
- 173 lanes: 134 ACTIVE, 15 NEVER_SCHEDULED, 13 PAUSED, 11 RETIRED.
- Scheduler kinds: 86 cron, 72 systemd, 14 none, 1 event (`cio-situation-detector`).
- Owners: platform 80, cio 43, portfolio 8, comms 8, scalp 8, watch 6, research 4, defense 3, hermes 3, advisory 2, execution 2, options 2, plus agents, notifications, ops, and signals at 1 each.
- `undeclared_baseline` holds 517 inherited cron-line strings inside the registry file. That list is declared debt, not a fresh host dump.

`config/llm_process_registry.json` has 72 processes. `config/data_source_authority.json` has 51 domains and 22 providers. These counts match the registry files. They are not counts of what fired.

## Host schedule census

johnclaw crontab, recomputed, not copied from September:

| Class | Count |
|---|---|
| Active crontab commands | 482 |
| Comments | 506 |
| Comments marked retired, disabled, or paused | 43 |
| Assignments | 7 |
| Blank lines | 53 |
| Active lines using `$PROJ` or the CURRENT release path | 474 of the 482 |
| Active DOF lines (`rescan_tickets.py` or `run_pipeline.py`) | 2 |
| Active lines whose text matched a secret-like assignment | 3, stored as hashes only |
| `/etc` cron active commands | 7 |
| Active commands across user and `/etc` | 489 |

User timer unit files: 117 (92 enabled, 25 disabled, 0 masked). `systemctl --user list-timers` listed 92. System timers listed: 20. User service unit files: 238 (31 enabled, 25 running). System service unit files: 342, of which 41 were running.

The September triple 469 cron / 117 timers / 27 services was not reproduced as one triple. 117 still matches user timer unit files, and it does not mean 117 enabled timers. No running-service or enabled-service count on this host was 27.

OpenClaw unit names found: `openclaw-gateway.service` only. Schedules inside that gateway were not opened. Label: NOT_MEASURED. No OpenClaw timer unit carried that name.

Masked user timers and services: 0. Disabled Trade AI timers are listed in `ledgers/schedule-census.json`. They were not enabled.

### Journal volume

`journalctl -u cron` retained 19 calendar days, 2026-09-18 through 2026-10-06, not 30. Older days are absent from this journal. CMD lines in that window: 164,687. Timestamps parsed: 164,687 of 164,687.

Completed weekdays in the retained window sit in two bands: about 9,547–9,565 from 2026-09-21 through 2026-09-25, then about 10,154–10,200 from 2026-09-28 through 2026-10-05. Weekend days sit between 5,799 and 6,700. 2026-10-06 was still in progress (9,439 CMD lines by the recount) and 2026-09-18 is the first retained day (8,856). This is a count of syslog command lines. It is not an accepted, artifact, or consumer count, and it is not a missed-fire rate.

DOF script names in the retained journal: `rescan_tickets.py` 19, `run_pipeline.py` 3. In the 7-day slice: 7 and 1. The previously noted Wednesday 2026-09-09 rescan hole is outside this journal. That hole was not remeasured. Label: NOT_MEASURED.

## Lane to host match

Every lane keeps the single owner declared in the registry. Host matching is separate. Full rows are in `ledgers/lane-ledger.json`.

| Host result | Lanes |
|---|---|
| No conflict flag | 132 |
| Unit file retained and disabled | 19 |
| Matcher saw more than one crontab line for the same script tokens | 13 |
| Active in the registry, no matching crontab or timer line | 5 |
| Timer enabled while the registry says RETIRED | 2 (`at-observation-01`, `at-observation-01-closeout`) |
| Timer enabled while the registry says NEVER_SCHEDULED | 1 (`contradiction-adjudicator`) |
| Active crontab line while the registry says NEVER_SCHEDULED | 1 (`maturity-remeasure`) |

Disabled unit files are retained definitions. They were not started. The four enabled-or-cron exceptions above are recorded conflicts. This pass did not disable them and did not revive any retired row.

`tradeai-cio-reactive.timer` is the declared trigger for both `cio-reactive-cycle` and `cio-wake-turn-effects`. That is one shared timer with two declared lanes, not a second owner.

The five active lanes with no token match are `rotation-autopilot`, `code-mirror-drive-sync`, `alert-quality`, `crontab-snapshot-for-health-agent`, and `reconcile-alpaca-paper-options`. Three of those still have a fresh or present output file, so a missed token is not proof the job is dead. Fired, accepted, consumed, failed, and suppressed remain NOT_MEASURED for every lane. File mtime, where the output signal is a file and the file exists, is recorded as artifact age only.

## Five pilot lanes, still owned by cron

| Lane | Schedule found | Artifact file |
|---|---|---|
| `morning-brief-0730` | one `$PROJ` line, `30 7 * * 1-5`, `send_morning_brief.py` | age 13.33h, within 2× the 24h cadence |
| `research-scheduler-holdings` | one `$PROJ` line, `5 9 * * 1-5`, `--mode holdings` | shared ledger file age 0.29h |
| `material-change-digest` | one `$PROJ` line, `15 16 * * *`, `notify_material_change.py` | registry signal is a database max; NOT_MEASURED |
| `llm-spend-report-daily` | one `$PROJ` line, `5 7 * * *`, `--period daily` | age 13.74h, within 2× cadence |
| `approval-package-reminder` | one `$PROJ` line, `5 * * * *` | not under CURRENT; persistent-state copy age 189.74h, late versus a 1h cadence |

Syslog CMD lines that name the script, 7-day slice: morning brief 5, research scheduler (all modes) 46, material-change notifier (digest and 15-minute sender together) 679, llm spend report (all periods) 9, approval reminder 168. Five weekday morning-brief command lines in seven days matches the weekday clock. One hundred sixty-eight approval-reminder command lines in seven days matches an hourly clock. The approval artifact file is still about eight days old. A command line is not a consumer receipt. None of these lanes was moved.

## API inventory

Coverage is partial and is labeled that way in `ledgers/api-ledger.json`.

`scripts/portfolio_server.py` plus `scripts/control_plane_api.py` contain 56 distinct quoted `/api`, `/v2`, and `/v3` paths. Effect class is a name heuristic only: 10 read-like, 9 mutation-or-send-like, 37 unknown. Whether a read handler also sends or writes is NOT_MEASURED.

Auth-exempt prefixes in `portfolio_server.py` include `/v2/`, `/v3/`, `/v3-next/`, `/data/`, `/archive/`, `/reports/`, `/assets/`, and `/api/health`. Ports 7776 and 7777 listen on `0.0.0.0`. That is a boundary fact for any later workflow, not a change.

The August 26 control-plane inventory (`docs/_evidence/r21/CONTROL_PLANE_API_INVENTORY.json`, source SHA `e683e90f9a24b9cd56399054da33cc6c3b4ba8bb`) lists 8 canonical read routes, 9 v3 CIO routes, 12 proposed contracts, 12 proposed read-only routes, and 9 contract gaps. It is not this served release.

DOF `dof_server.py` exposes 22 Flask routes, including POST promote, target, and enrichment-run paths. Those are human or pipeline mutations. An n8n workflow is not authorized to call them.

## Model-id drift

OBSERVED_SOURCE at this SHA, not a live provider call:

- `config/llm_model_registry.json` model ids include `deepseek-flash`, `claude-haiku-4-5-20251001`, and `claude-sonnet-4-5-20250929`.
- `scripts/lib/deepseek_client.py` names `deepseek-flash` and calls `reject_legacy_model_id`.
- `docs/architecture/cio/ADR_LLM_GOVERNANCE_BOUNDARY.md` still contains `deepseek-v4-flash` and `deepseek-v4-pro`.

No model was called. No registry or ADR file was edited. OpenRouter was not checked for a live credential. Label for OpenRouter liveness: NOT_MEASURED.

## DOF data boundary

`dof_server.py` `get_db()` builds a connection to database `trade_ai` on `localhost:5432` using `DB_USER` (default `trade_ai`) and `DB_PASSWORD` from the environment. The listener on `127.0.0.1:5432` was observed. Production was not queried, so table presence and role separation are NOT_MEASURED. Source code writes `dof_auction_runs`, `dof_vehicles`, `dof_ticket_lookups`, `dof_vehicle_scores`, and `dof_ticket_events`. Those names are source declarations.

`dof_llm_router.py` is tracked on this master checkout and is imported by `scripts/stage5_score.py`. A literal `sk-` key was not found in that file. It reads the environment. It was not executed. DOF pricing stays in DOF code.

## What this baseline does not claim

No lane has a measured accepted/consumed/failed/suppressed fraction. No missed-fire rate was computed. No backup restore of Trade AI or DOF was run. The n8n lab restore drill from 2026-10-06T22:11:01Z to 22:12:06Z (157 of 157 tables, production Postgres not touched) is an OBSERVED_LAB fact and is not a scheduled backup.
