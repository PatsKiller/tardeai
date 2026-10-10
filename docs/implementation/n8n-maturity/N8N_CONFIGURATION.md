# N8N configuration — ms01-openclaw (the entry point)

```
Status:      ACTIVE
as_of:       2026-10-10T17:45:00-04:00
Measured at: origin/main 2aa2cc37d (#1664) / live af292381c-main-exact-phase2-20261010-113824; host ms01-openclaw
Owner:       platform (n8n maturity program)
Policy:      AGENTS.md 4.4.0 §23 (where this file differs, AGENTS.md wins)
Secrets:     none in this file — variables and credential ids are named, never valued (AGENTS.md §2A, §23.5)
```

Operator, 2026-10-10 ~16:50 ET: *"start a separate document just for n8n configuration that will include all of this."*

This is the single reference for how n8n is configured on this host, and the entry point to the procedures:

| Read | For |
|---|---|
| [`N8N_ONBOARDING_STANDARD.md`](N8N_ONBOARDING_STANDARD.md) | the mandatory checklist for adding anything to n8n (gates, grants, row shapes, import procedure, testing, rollback) |
| [`N8N_MONITORING_AND_REMEDIATION_STANDARD.md`](N8N_MONITORING_AND_REMEDIATION_STANDARD.md) | per-lane monitoring, SIEM, Telegram routing, LLM auto-remediation, R6 validation, the per-lane template |
| same, §3 | the **workflow health contract** schema (`config/n8n_health_contracts.json`) |
| [`02-six-workflow-architecture.md`](02-six-workflow-architecture.md) | the design of the six generic workflows, `coordination/due`, executor v2 |
| [`cron-inventory/README.md`](cron-inventory/README.md) | the cron inventory (system of record) and its change log |
| [`00-MASTER-PROGRAM.md`](00-MASTER-PROGRAM.md) | program index and maturity scorer |

---

## 1. Platform — the n8n container

| Item | Value | Source |
|---|---|---|
| Compose file | `~/m8m-bakeoff-lab/docker-compose.n8n.yml`, project `m8m-n8n` (run compose **only from that directory**: it reads that directory's `.env`; elsewhere the encryption key and DB password resolve empty) | `packets/n8n-network-pin.md` dry run |
| Containers | `m8m-n8n` (image `n8nio/n8n:2.43.0`, `mem_limit 768m`, `pids_limit 256`, `no-new-privileges`), `m8m-n8n-db` (`postgres:16.15-alpine`, `mem_limit 256m`, healthcheck `pg_isready`) | compose |
| Volumes | `m8m-n8n_n8n-data` (`/home/node/.n8n`), `m8m-n8n_n8n-pg`; survive `down` (never pass `-v`) | compose |
| Port | `127.0.0.1:5678` only (editor reached over an SSH tunnel on Tailscale; owner MFA waived on that basis, §23.5) | compose, AGENTS.md §23.5 |
| Health | `GET http://127.0.0.1:5678/healthz`; probed every 5 min by `tradeai-n8n-lab-watchdog.timer` (reports only). The container has **no compose healthcheck** (V8 W6) | V8 |
| Network | `lab` → docker network `m8m-n8n_lab`, `172.19.0.0/16`, gateway `172.19.0.1` (relay bind). **No `ipam` block** yet, so the subnet is not pinned (packet `packets/n8n-network-pin.md`, candidate `packets/candidate-compose-pin.yml`, PREPARED, needs `config-write` + `service`) | V8 F2 |
| Relay name | `extra_hosts: ["tradeai-relay:172.19.0.1"]` (added 2026-10-10 01:57Z, grant 1beea8a48b03a87b). Workflows still use the bare IP (design 02 §4); not `host.docker.internal` (that is 172.17.0.1) | compose comment |
| Egress | container internet egress **blocked** (DOCKER-USER), host reach only `172.19.0.1:18092`; DNS still resolves through the host resolver (V8 W13, accepted risk) | AGENTS.md §23.3 |
| Timezone | `GENERIC_TIMEZONE=America/New_York`; every workflow sets `settings.timezone`; container `TZ` unset (UTC in Code-node `Date()` and logs, V8 W7) | compose |
| Execution data | `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none`, `..._ON_ERROR=all`, `..._SAVE_MANUAL_EXECUTIONS=false`, `EXECUTIONS_DATA_PRUNE=true`, `EXECUTIONS_DATA_MAX_AGE=168` (h) | compose; §23.5 precondition |
| **Consequence** | a successful execution is soft-deleted and keeps `status = 'running'` with a `deletedAt` value. **Always filter `"deletedAt" IS NULL`**; prove success from the coordination ledger and receipts, never from n8n status (W0 RC8) | W0 README |
| Executions mode | n8n default (`regular`, no queue mode, no concurrency limit set) | compose (no `EXECUTIONS_MODE`) |
| Hardening | public API and Swagger off, community packages off, AI / MCP / agents / chat modules disabled (`N8N_DISABLED_MODULES`), `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`, Python off, `NODES_EXCLUDE` drops execute-command, SSH, FTP, every email / Telegram / Slack / chat / messaging node, LangChain agent / tool / memory / vector-store nodes | compose |
| Credentials in n8n | exactly one: `tradeai-run-relay` (type `httpHeaderAuth`, the relay bearer). No provider, broker, DB or messaging credential (§23.5) | W0 README |
| DB role | `n8n` is still a **superuser** (V8 F5; §23.10 P13 `n8n_app` role open) | V8 |
| Owner account | one owner; its password still sits in the lab `.env` by name (V8 F6, open) | V8 |
| Backups | nightly `pg_dump` by the platform-maintenance timer to `~/trade-ai-releases/persistent-state/backups/n8n/n8n-lab-<UTC>.dump` (latest `n8n-lab-20261010T051506Z.dump`), 5 kept, restore drill passed 2026-10-07; encryption key escrowed separately; same disk (V8 W16) | V8, `ls` 2026-10-10 |

**Restart / upgrade** (operator, grants `config-write` for a compose edit and `service`): pick a quiet minute
(hh:07 or hh:37, clear of :00/:15/:30/:45 fires); back up the compose file beside it
(`docker-compose.n8n.yml.bak-<UTC>`); `cd ~/m8m-bakeoff-lab && docker compose -f docker-compose.n8n.yml config --quiet`;
`docker compose ... up -d` (never `down -v`); wait for `/healthz`; check `SELECT id, active FROM workflow_entity
WHERE active` matches the pre-change list; check the relay `op: due` lines resume. A CLI `publish:workflow` /
`unpublish:workflow` takes effect only after `docker restart m8m-n8n`.

---

## 2. Host bridge services

| Unit | Listens | Runs | Key config | Limits |
|---|---|---|---|---|
| `tradeai-n8n-run-relay.service` | `172.19.0.1:18092` (only n8n reaches it; ufw allow 18092, deny rest of `172.19.0.0/16`) | `$PY CURRENT/scripts/n8n_run_relay.py` | `ROUTES` (`scripts/n8n_run_relay.py` :83): `GET /status`, `GET /due`, `GET /runs/<lane_id>/last`, `POST /run`, `POST /event` (lane `n8n-workflow-error` only; on main via #1663, not yet served); bearer = n8n credential `tradeai-run-relay`; `TRADEAI_N8N_RELAY_LIVE_LANES` in `~/.config/tradeai/n8n-relay.env` (today: `n8n-pilot-dispatch n8n-incident-fanin n8n-research-intake-consumer crontab-snapshot-for-health-agent maturity-remeasure`); log `$STATE/data/runtime/n8n_relay/relay_log.jsonl`; `--routes` prints the table | `MemoryMax=128M`, `CPUQuota=10%`, `Restart=always` |
| `tradeai-n8n-coordination-gateway.service` | `127.0.0.1:18091` (`GET /healthz`) | `CURRENT/scripts/n8n_coordination_gateway_run.sh` | HMAC keys `TRADEAI_N8N_GATEWAY_HMAC_KEY` (caller `tradeai-dispatch`) and `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N` (caller `n8n-relay`, the only `coordination_run` scope) from `%t/tradeai/env` (Bitwarden SM render); `TRADEAI_N8N_GATEWAY_EXTRA_LANES=incident-fanin research-intake n8n-workflow-error` via drop-in `20-workflow-error-lane.conf` (2026-10-10 16:27 ET); never spawns | `MemoryMax=256M`, `CPUQuota=20%` |
| `tradeai-n8n-run-executor.service` | — | `$PY CURRENT/scripts/n8n_run_executor.py` | **v2**: `TRADEAI_N8N_EXECUTOR_WORKERS=3` via drop-in `10-executor-v2.conf` (13:07 ET); class caps `config/n8n_retry_policies.json#class_caps` (global 3, heavy 1, llm 1, ingest 1, send 1, pipeline 2, learn 1, reserved priority ≤ 1); stage clamp (`scripts/lib/lane_stage_clamp.py`); reaper (`started + timeout_s + 120 s`, stale heartbeat 90 s → `RUN_TIMEOUT executor_lost`); status file `$STATE/data/runtime/n8n_run_executor_last.json` (`ExecutorStatus@v1`); `RunReceipt@v2` per run; `LLM_DEFER_OFFPEAK=1` | `MemoryMax=1G`, `Restart=always` |
| `tradeai-n8n-lab-watchdog.timer` | — | n8n `/healthz` every 5 min | reports only | — |

| Store / config | Path |
|---|---|
| Coordination ledger (runs, events, dead letters) | `~/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite` (read with sqlite `mode=ro`) |
| Run allowlist | `config/n8n_run_allowlist.json` (`N8nRunAllowlist@v1`; argv, lock, timeout, dry/live args, output_signal, env names, `never` list) |
| Lane registry (the schedule) | `config/lane_registry.json` |
| Retry policies / caps | `config/n8n_retry_policies.json` |
| Executor limits | `config/n8n_executor.json` |
| Health contracts | `config/n8n_health_contracts.json` |
| Remediation catalogue | `config/n8n_remediation_catalogue.json` |
| LLM processes | `config/llm_process_registry.json` |

**Repo unit vs installed unit vs drop-ins.** Repo copies live in `config/systemd/user/`; installed copies in
`~/.config/systemd/user/`; drop-ins in `~/.config/systemd/user/<unit>.service.d/`. Measured 2026-10-10: the relay
and executor installed units equal the repo; the installed **gateway** unit is older than the repo (description
still "proposal only, not installed", `EXTRA_LANES` without `n8n-workflow-error`) — the drop-in supplies the value,
and the repo unit (#1664) carries the same value. Drop-ins: executor `10-executor-v2.conf`, gateway
`20-workflow-error-lane.conf`. Promote restarts the bound units (`TRADEAI_CURRENT_BOUND_UNITS`) with whatever the
installed unit and its drop-ins say; it does not reinstall units.

**Reinstall a unit without losing drop-ins** (operator, `config-write` + `service`): `install -m 0644
CURRENT/config/systemd/user/<unit>.service ~/.config/systemd/user/` (this replaces only the unit file; the
`<unit>.service.d/` directory is untouched), `systemctl --user daemon-reload`, then `systemctl --user show <unit>
-p Environment` must still show the drop-in values before the restart. Never delete a drop-in; roll a value back by
editing it (executor `1`, gateway without `n8n-workflow-error`).

**Known unit findings** (V8): units run the dev-tree venv Python (W11); `~/.config/tradeai/n8n-gateway.env` is
referenced but absent (W12, harmless); inotify watch exhaustion on restarts (W4); the relay has no unauthenticated
health route (W5: a 401 `relay_bad_bearer` from `/status` means alive).

---

## 3. Workflows

### 3.1 The six generic workflows (§23.11)

Generated by `python3 scripts/n8n_workflow_templates.py build-generic` into `workflows/` (`--check` verifies;
`workflows/INDEX.json` holds ids, sha256, triggers, relay calls). Declared to `check_lane_registry` by INDEX (#1650).

| id | Purpose | Trigger | Relay calls | errorWorkflow |
|---|---|---|---|---|
| `tradeai-dispatcher` | posts `/run` for every registry lane the gateway says is due | `* * * * *` | `GET /due?source=schedule&limit=40`, `POST /run` | incident-router |
| `tradeai-event-router` | same for event-triggered lanes | `* * * * *` + webhook `tradeai-nudge` | `GET /due?source=event&limit=40`, `POST /run` | incident-router |
| `tradeai-heartbeat-watcher` | runs host lane `heartbeat-watch` (no registry row yet → out of W0) | `*/5` | `GET /due?…&lane=heartbeat-watch`, `POST /run`, `GET /runs/heartbeat-watch/last?mode=live` | incident-router |
| `tradeai-incident-router` | runs `n8n-incident-fanin`, `incident-notifier`; Error Trigger → `POST /event` | `* * * * *` + error trigger | `GET /due?…&lane=n8n-incident-fanin,incident-notifier`, `POST /run`, `POST /event` | — (itself) |
| `tradeai-digest-scheduler` | digest-window lanes | `*/5` | `GET /due?source=digest&limit=40`, `POST /run` | incident-router |
| `tradeai-approval-router` | runs host lane `approval-escalate` (no registry row yet → out of W0); read-only guard projection | `*/5` | `GET /due?…&lane=approval-escalate`, `POST /run` | incident-router |

All six: relay `http://172.19.0.1:18092` through one `Relay` Set node, credential `tradeai-run-relay`,
`executionTimeout` set, `saveManualExecutions: false`, no lane constants beyond the system filter lanes.

**W0 state:** imported inactive and published 2026-10-10 15:53 ET, unpublished 15:58 ET (grant f9c459a230d3bc58)
after 403 `bad_lane_filter` and 404 `/event` (RC8). Rows exist inactive. Re-run: after the release carrying #1663 and
#1664 is promoted, `W0_REIMPORT=1` with the four served ids (dispatcher, event router, incident router, digest
scheduler), under a new `cron` grant naming them.

### 3.2 Per-lane workflows (2.0.0 shape) still active — 10

| id | name | Note |
|---|---|---|
| `722fac0e043ea5c4` | n8n-incident-fanin | live; cron L1025 retired `n8n-cutover` |
| `078e8fcbea0c5020` | n8n-pilot-dispatch | live; cron retired |
| `21fd15d5f8a4c4da` | n8n-research-intake-consumer | live; cron retired |
| `c0d4c7845e5c4fcc` | crontab-snapshot-for-health-agent | live; cron retired |
| `283ceeb030de5e66` | catalyst-calibration-monitor-shadow | shadow (dry_run) |
| `2c725c7dfd4ac62f` | finviz-view-contracts-shadow | shadow; **activation UNGRANTED** |
| `ffa6bbfa93ad4056` | generate-analyst-daily-digest-shadow | shadow |
| `e6f62397d5ae2aa2` | lane-governance-packet-weekly-shadow | shadow |
| `498d749165a93ff9` | source-attribution-monitor-shadow | shadow; **activation UNGRANTED** |
| `5966437c872aa18b` | watch-directives-monitor-shadow | shadow; **activation UNGRANTED** |

All ten still carry `saveManualExecutions: true` (V8 F4; fixed only in the generic generator) and no
`errorWorkflow` / `executionTimeout` (V8 W8). They are replaced by dispatcher rows, not edited. **Archived:** 16
`RELAY_HOST` workflows (2026-10-09 22:55 ET, grant ee4dfdf11479cd3c, `packets/archive-16.sh`); `maturity-remeasure`
live workflow `e18d7849b4142927` unpublished (D1, 2026-10-09 22:30 ET, grant 26b8747d6cc949bb; cron L1000 is its
single scheduler).

### 3.3 Commands (operator, under a `cron` grant naming the ids)

```bash
docker exec m8m-n8n n8n import:workflow --input=<file>            # imports inactive (packet import-six.sh does checks first)
docker exec m8m-n8n n8n publish:workflow --id=<id>                # activate
docker exec m8m-n8n n8n unpublish:workflow --id=<id>              # deactivate
docker restart m8m-n8n                                            # CLI publish/unpublish load at start
# archive (never delete): n8n's own /rest/workflows/<id>/archive, as packets/archive-16.sh and w0-import-six/rollback.sh do
docker exec m8m-n8n-db psql -U n8n -d n8n -tAc "SELECT id, name, active FROM workflow_entity WHERE active ORDER BY name"
docker exec m8m-n8n-db psql -U n8n -d n8n -tAc "SELECT \"workflowId\", status, count(*) FROM execution_entity WHERE \"deletedAt\" IS NULL GROUP BY 1, 2"
python3 scripts/check_n8n_activation_grants.py                     # every activation vs guard log
python3 scripts/check_lane_registry.py --n8n-live --fail-on-new    # UNDECLARED_N8N_WORKFLOW etc.
python3 scripts/check_n8n_relay_contract.py --workflows docs/implementation/n8n-maturity/workflows   # before any import
```

---

## 4. Monitoring, SIEM, Telegram, LLM remediation, health contracts

One-line summaries; the procedure is in [`N8N_MONITORING_AND_REMEDIATION_STANDARD.md`](N8N_MONITORING_AND_REMEDIATION_STANDARD.md).

- **SIEM:** `scripts/n8n_siem_bridge.py` → `system_health_events` `n8n:<lane>` (single writer, deduped,
  self-resolving); registry row merged PAUSED (#1657), not installed. RUN_* lands WARN until registry `severity` is set (L6).
- **Telegram:** `scripts/incident_notifier.py` (cron L1052, live) on the SYSTEM ops family — P1 at once, uncapped;
  P2 batched, held 22:00–07:00 ET; 24/day cap; P3 never.
- **LLM remediation:** `scripts/n8n_failure_diagnosis.py`, process `n8n_lane_failure_diagnosis` (grok → chatgpt →
  deepseek; $0.05/call, $0.10/day), catalogue `config/n8n_remediation_catalogue.json` (53 lanes, 8 auto dry-run
  reruns), scalp excluded; row merged PAUSED (#1657), install ~2 h after the bridge.
- **Workflow errors:** Error Trigger → relay `POST /event` → gateway lane `n8n-workflow-error` (fan-in reader not built).
- **Health contracts:** `config/n8n_health_contracts.json` (68 DRAFT), gate `scripts/check_n8n_health_contracts.py`.

---

## 5. Governance

- **AGENTS.md §23** (4.4.0 ACTIVE): §23.1 scope (this compose project only); §23.2 workflows are scheduler entries;
  §23.3 the only trigger path (relay → `coordination/run`, allowlisted lanes, host-side execution; no sends from n8n;
  `trade-ai-scalp-live` the one live-lane exception); §23.4 governed LLM (capability, never a provider); §23.5 at most
  two credentials, execution data on success not retained; §23.6 n8n is replaceable; §23.11 registry-driven dispatch,
  dispatcher row expression `dispatcher`; §23.12 wave ladder; §23.13 program window (push budget, standing merge
  approval to `2026-10-11T17:30:03-04:00`); §23.14 never dispatcher-eligible (broker, order, secret, daemon); §23.18 R1
  classes `ingest` / `llm` / `learn`, and (4.4.0) the cron-row shape at shadow and canary.
- **Grants per action:** n8n import / publish / unpublish / archive / edit and every cutover — `cron` naming the
  workflow ids or lane ids; host unit drop-ins and on-disk config — `config-write`; restarts — `service`; DB rows —
  `db-write`; a dispatcher-row PR — none (the merge is the decision). ≤ 12 h each; one per scope.
- **Cron freeze:** no cron job, timer, health-tick step or n8n workflow is migrated, modified, disabled, consolidated
  or retired until its inventory row is approved (operator 2026-10-09 ~21:50 ET; `cron-inventory/README.md`).
- **Never eligible:** broker, order, stop, position, paper execution, every sender, secret render, guard write,
  release deploy, destructive retention, daemons. **Exception:** `trade-ai-scalp-live` (4.0.0 terms), also excluded
  from LLM diagnosis.

---

## 6. Change log — n8n configuration

| When (ET) | Change | Authority / evidence |
|---|---|---|
| 2026-10-09 21:57 (01:57Z 10-10) | compose `extra_hosts: tradeai-relay:172.19.0.1` (F2); backup `docker-compose.n8n.yml.bak-20261010T0157Z-pre-extrahosts` | grant 1beea8a48b03a87b |
| 2026-10-09 22:30 | `maturity-remeasure` n8n workflow `e18d7849b4142927` unpublished; cron L1000 single scheduler (D1) | grant 26b8747d6cc949bb |
| 2026-10-09 22:55 | 16 `RELAY_HOST` workflows archived (F1) | grant ee4dfdf11479cd3c; `packets/archive-16.sh` |
| 2026-10-09 23:34 | incident notifier installed (cron L1052) | cron grant 2db296cd0e9e6a10 |
| 2026-10-10 10:00 | `data/state/finviz_throttle.json` future timestamp repaired (RC1) | grant a9c50183a5ab42b4; #1648 |
| 2026-10-10 ~12:00 | orphan ledger run `-1552` closed `RUN_TIMEOUT executor_lost` (RC2) | backup `packets/ledger-1552/…before-1552-close.20261010T160012Z.sqlite` |
| 2026-10-10 12:54 | dispatch shadow wave 1: 22 cron rows `stage: shadow`, `dispatch.mode: dry_run` (merge #1656) | registry PR |
| 2026-10-10 13:07 | executor v2, 3 workers (drop-in `10-executor-v2.conf`) | service grant eebd4ca0a6b31bd2; `packets/executor-v2-evidence/enable-20261010.log` |
| 2026-10-10 15:53 / 15:58 | W0: six generic workflows imported inactive + published, then unpublished (RC8) | grant f9c459a230d3bc58; `packets/w0-import-six/` |
| 2026-10-10 15:58 | waves 2+3: 14 shadow rows + 19 R1 rows staged `r1_pending` (merge #1661) | registry PR |
| 2026-10-10 16:20 | `flock -n` on crontab L318, L314, L427 (wave-3 learn lanes) | cron grant 08c0bb77ec898136; `packets/wave23-flock/` |
| 2026-10-10 16:27 | gateway lane `n8n-workflow-error` (drop-in `20-workflow-error-lane.conf`) | config-write 8c235faa82733127, service 7752d1c23506de55 |
| 2026-10-10 16:27 | `llm_process_config` row `n8n_lane_failure_diagnosis` synced to the registry | `packets/llm-seed-sync/apply-20261010.txt` |
| pending | wave-3 activation: 19 R1 rows to `stage: shadow` (#1665 OPEN) | registry PR |

---

## 7. Open items

| # | Item | Owner / authority |
|---|---|---|
| 1 | W0 re-run with 4 ids after the #1663/#1664 release is promoted | operator promote + `cron` grant |
| 2 | Registry rows for `heartbeat-watch` and `approval-escalate` (heartbeat watcher / approval router out of W0 until then) | registry PR |
| 3 | Fan-in reader for `n8n-workflow-error` events (they reach neither SIEM nor Telegram yet) | agent PR |
| 4 | Install SIEM bridge, then diagnoser ~2 h later; flip rows PAUSED → ACTIVE | `cron` grants + registry PR |
| 5 | L6: registry `severity` per lane (RUN_* all WARN today) | registry PR |
| 6 | Health contracts: owner review (68 DRAFT); wire bridge / fan-in / diagnoser to read them | owners; agent PRs |
| 7 | 3 ungranted shadow activations (finviz-view-contracts, source-attribution-monitor, watch-directives-monitor) | operator: grant retroactively or unpublish |
| 8 | `TRADEAI_N8N_RELAY_LIVE_LANES` still lists `maturity-remeasure`, whose n8n workflow was unpublished (D1) | operator `config-write` to drop it |
| 9 | Network pin (`ipam`) | `config-write` + `service`, packet ready |
| 10 | DB role superuser (F5), owner password in lab `.env` (F6) | operator |
| 11 | Drift check unscheduled (F7); `saveManualExecutions: true` on the 10 per-lane workflows (F4) | operator `cron` grant / replaced by dispatcher rows |
| 12 | Container healthcheck (W6), `TZ` (W7), runner timeout (W9), log rotation (W10) | operator `config-write` |
| 13 | Units use the dev-tree venv (W11); missing `n8n-gateway.env` + stale installed gateway unit text (W12) | operator `service` / `config-write` |
| 14 | inotify watch exhaustion (W4) | operator (root) |
| 15 | Off-host n8n backup copy (W16) | operator |
| 16 | Older off-peak wrapper copy in `~/.config/tradeai/bin` used by 17 crontab lines | inventory row + cron grant |
| 17 | Remediation catalogue stale vs host inventory; regenerate before activation | agent PR |
| 18 | #1665 merge (wave-3 activation) | operator / §23.13 |
