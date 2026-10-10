# N8N configuration — ms01-openclaw (the entry point)

```
Status:      ACTIVE
as_of:       2026-10-10T18:55:00-04:00
Measured at: origin/main 7df77950a (#1674) / live 8ddf2ad59-main-exact-phase2-20261010-183820; host ms01-openclaw
Owner:       platform (n8n maturity program)
Policy:      AGENTS.md 4.4.0 §23 ACTIVE (where this file differs, AGENTS.md wins); 4.4.1 + 4.5.0 PROPOSED in PR #1666;
             4.6.0 PROPOSED (§24 platform rules) on branch n8nmat/agents-4-6-0
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
| [`SEARCH_SOURCE_ROUTING.md`](SEARCH_SOURCE_ROUTING.md) (lands with PR #1676; the link resolves once it merges) | web search: which source answers what, the Brave dollar budget, the scalp-priority pool — policy `config/search_routing_policy.json` (§6.2 below) |
| `~/n8n-maturity-verification/CONSOLIDATION_PLAN.md`, `JOB_REDUCTION_DEEP_PASS.md` (host, operator-approved 2026-10-10) | the data broker as backbone, owners and domains, C1 manifests, job reduction (§6 below) |

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
| `tradeai-n8n-run-relay.service` | `172.19.0.1:18092` (only n8n reaches it; ufw allow 18092, deny rest of `172.19.0.0/16`) | `$PY CURRENT/scripts/n8n_run_relay.py` | `ROUTES` (`scripts/n8n_run_relay.py` :83): `GET /status`, `GET /due`, `GET /runs/<lane_id>/last`, `POST /run`, `POST /event` (lane `n8n-workflow-error` only; #1663, served since the `e8a4a6815` promote 17:13 ET); bearer = n8n credential `tradeai-run-relay`; `TRADEAI_N8N_RELAY_LIVE_LANES` in `~/.config/tradeai/n8n-relay.env` (today: `n8n-pilot-dispatch n8n-incident-fanin n8n-research-intake-consumer crontab-snapshot-for-health-agent maturity-remeasure`); log `$STATE/data/runtime/n8n_relay/relay_log.jsonl`; `--routes` prints the table | `MemoryMax=128M`, `CPUQuota=10%`, `Restart=always` |
| `tradeai-n8n-coordination-gateway.service` | `127.0.0.1:18091` (`GET /healthz`) | `CURRENT/scripts/n8n_coordination_gateway_run.sh` | HMAC keys `TRADEAI_N8N_GATEWAY_HMAC_KEY` (caller `tradeai-dispatch`) and `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N` (caller `n8n-relay`, the only `coordination_run` scope) from `%t/tradeai/env` (Bitwarden SM render); `TRADEAI_N8N_GATEWAY_EXTRA_LANES=incident-fanin research-intake n8n-workflow-error` via drop-in `20-workflow-error-lane.conf` (2026-10-10 16:27 ET); never spawns; `coordination/due` builds the forbidden-token matcher once (#1667, served since `8ddf2ad59` 18:40 ET: one `/due` 510 → 10 ms; §2.1) | `MemoryMax=256M`, `CPUQuota=20%` |
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

### 2.1 Gateway `/due` latency (RC11) and the concurrency lesson

- **What happened.** The W0 re-run (17:14 ET) published four generic workflows. Whenever two or three of them called
  `GET /due` in the same minute the relay answered `relay_gateway_unreachable` (relay log: 10 REFUSED vs 8 OK in the
  first minutes, `packets/w0-import-six/rerun-verify-20261010.txt`); the dispatcher alone was always OK. Mitigation at
  17:20 ET: event router, incident router and digest scheduler unpublished, dispatcher kept (grant c90266247a4c4cd4,
  `rerun-partial-rollback-20261010.txt`).
- **Root cause** (Agent O, REMEDIATION_PLAN §8 RC11). 99% of `/due` CPU was `lane_dispatch.forbidden_text_hits` /
  `_compound_hit` rebuilding ~160 word-form sets for ~560 command texts on every call (~0.5 s CPU). The gateway
  unit's `CPUQuota=20%` stretched that to ~2.3 s wall, and GIL-serialised concurrent calls (all at :00; the ":05"
  stamps were the relay's 5 s `urlopen` timeout expiring) passed the relay timeout. Input loading was 6 ms.
- **Fix** #1667 (`35a95d658`, live in `8ddf2ad59`): matcher built once and keyed on its inputs, split-point compound
  test, per-text memo. Single `/due` 510 → 10 ms; 4 concurrent 1.61 s → 38 ms; at a simulated 20% CPU 40/40 OK (the
  old matcher reproduces the incident). Byte-identical on 2,713 texts, 619 eligibility verdicts and 2,160 `/due`
  responses including the 2026-11-01 DST fold. `tests/test_gateway_due_latency_20261010.py` (8, incl. a CPU-budget
  gate that fails on the old matcher).
- **Lesson — the relay contract check probes one call at a time.** `scripts/check_n8n_relay_contract.py` proves each
  path and lane filter is served; it does **not** fire concurrent calls, so it could not see RC11. Until it gains a
  concurrency probe (open item 19), any change that adds a workflow calling `/due` (or any gateway read) at the same
  minute as another must (a) pass `tests/test_gateway_due_latency_20261010.py` on the candidate, and (b) publish one
  workflow at a time, reading the relay log for `relay_gateway_unreachable` between publishes (the 18:40–18:47 ET
  re-publish did exactly that, §3.1).
- **Measured after the fix** (relay log 22:38Z–22:50Z): one `relay_gateway_unreachable` at 22:40:01Z, during the
  post-promote gateway restart; none after it with four generic workflows live.

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

**W0 state (measured 18:51 ET, `workflow_entity.active`):** **dispatcher, event router, incident router and digest
scheduler are live; heartbeat watcher and approval router are held** (inactive) until their host lanes
`heartbeat-watch` / `approval-escalate` have registry rows (open item 2).

| When (ET) | Step | Grant / evidence (`packets/w0-import-six/`) |
|---|---|---|
| 15:53 | all six imported inactive and published | f9c459a230d3bc58; `apply-20261010.txt`, `publish-20261010.txt` |
| 15:58 | all six unpublished (RC8: 403 `bad_lane_filter`, 404 `POST /event`) | same grant; `rollback-unpublish-20261010.txt` |
| 17:13 | release `e8a4a6815` promoted: relay `POST /event` (#1663), gateway lane (#1664), wave-3 rows (#1665) | release-write grant named the sha (§10) |
| 17:14 | re-run: four re-imported (`W0_REIMPORT=1`) and published, n8n restarted | c90266247a4c4cd4; `rerun-apply-20261010.txt` |
| 17:20 | partial rollback: event router, incident router, digest scheduler unpublished; dispatcher kept (RC11) | c90266247a4c4cd4; `rerun-partial-rollback-20261010.txt` |
| 18:40 | release `8ddf2ad59` promoted (RC11 fix #1667, quick wins #1668, step 1 #1669, desk-loop drain #1670, scalp hot tier #1671 code, flags off) | release-write grant naming the sha |
| 18:40 / 18:44 / 18:47 | event router, incident router, digest scheduler re-published **one at a time**, relay log read between each | 4b3623125f6b6d7e; `republish-20261010.txt` |

Evidence of work is the relay log (`op: due` every minute, `op: event` accepted) and ledger `runs` rows, never an
n8n execution status (§1 "Consequence").

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
single scheduler). **Next archive (approved, not applied):** `283ceeb030de5e66`, `498d749165a93ff9`,
`5966437c872aa18b` — the three shadows their dispatcher rows supersede (operator 2026-10-10 ~17:45 ET, CONSOLIDATION_PLAN
§D.1). Packet `~/n8n-maturity-verification/packets/consolidation-n8n-archive-1/` (`archive-3.sh`: deactivate, then
n8n's archive endpoint, never delete; JSON backup + SHA256SUMS), needs one `cron` grant naming the three ids; after it
the active per-lane count goes 10 → 7 and the `UNGRANTED_ACTIVATION` finding on `283ceeb0…` clears.

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
- **Workflow errors:** Error Trigger → relay `POST /event` → gateway lane `n8n-workflow-error` — **served since 17:13 ET**
  (5 events `ACCEPTED` in the 17:14 re-run, `rerun-verify-20261010.txt`). **The fan-in has no reader for these events
  yet**, so a workflow error reaches neither the SIEM nor Telegram (open item 3).
- **Notifications (operator model, approved 2026-10-10 ~18:40 ET):** n8n orchestrates — it fires the host lanes that
  route, batch digests, escalate and handle buttons — and the host communications gateway (`send_telegram`, the
  delivery ledger, the approved adapters under `scripts/check_comms_gateway_enforcement.py`) is the **only sender**.
  The P1 path never depends on n8n (the notifier L1052 and the SIEM bridge stay on host cron). Sender jobs (~66)
  become notification intents handed to the gateway (migration work; AGENTS.md 4.6.0 §24.1, PROPOSED). Nothing in
  n8n sends, and §23.3 is unchanged.
- **Search spend health:** `scripts/search_spend_report.py` → `data/runtime/search_spend_last.json`, read by the
  incident fan-in as source `search_spend` (P2 at 80% of the $15 target) — lands with PR #1676 (§6.2).
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
- **Release grants name the SHA.** `scripts/lib/release_grant_binding.py` (`ReleaseGrantBinding@v1`, `enforce`)
  refuses a `release-write` grant whose reason names neither the PR (`#NNNN`) nor the target SHA (≥ 9 hex): on
  2026-10-10 ~17:07 ET the generic 6 h grant 7792ff3948d8d2d9 was refused ("no SHA named"); the re-requested grant
  named `e8a4a6815524…` and #1665 and matched (`status-20261010/release-e8a4a6815-promote.log`). Same for
  `8ddf2ad59` at 18:40 ET.
- **No push from scheduled work.** A cron line, timer or n8n lane never pushes, opens a PR or writes a remote
  (#1672, §6.5). A checkpoint is a local commit (AGENTS.md §0 rule 4).
- **Agents never read, copy or symlink `.env`** or any credential file; a worktree has no `.env` link
  (`scripts/new-worktree.sh`). Tests run with `TRADE_AI_CI=1` and temp roots and never touch production state
  (RC1, RC7). Proposed as AGENTS.md 4.6.0 §24.6–§24.7.
- **AGENTS.md 4.6.0 (PROPOSED, branch `n8nmat/agents-4-6-0`)** adds §24 (notifications, search routing and the Brave
  dollar budget, data-broker owners and consumers, other applications, no push from scheduled jobs, test isolation,
  no `.env`, release grants name the SHA, Supabase / n8n-Cloud portability). It grants nothing until ratified with
  `APPROVE_AGENTS_POLICY_4_6_0 <pr_number> <head_sha>`, and it is numbered after this PR's 4.5.0.

---

## 6. Platform decisions of 2026-10-10 that every n8n change must respect

All approved by the operator on 2026-10-10 (CONSOLIDATION_PLAN §D 1–14 at ~17:45 ET; search ~18:03 ET; C1, cutover,
cron pushes and DOF ~18:28–18:35 ET; "Yes, from one to six" and "I approved everything you have submitted" ~18:40 ET;
later the same evening: C1 takes the 22 shadow lanes, L184/L243 to the consolidation plan, stage-runner env fix,
premarket parallelisation, DOF runner and DB login). Approval is not installation: each row says what is live.

### 6.1 The data broker is the backbone (consolidation)

```mermaid
flowchart LR
  P[Providers: Finviz, yfinance, SEC, StockTwits, Alpha Vantage, Brave/SearXNG, brokers (read-only)] --> O[Owner lane per provider and universe: the single declared writer, data_source_authority.json]
  O --> S[Broker domain store: rows stamped as_of + source]
  S --> J[Projection scripts/lib/data_broker/*: BrokerReadEnvelope@v1 as_of / age / stale / no_coverage]
  J --> C1[Consumers: cron lanes, n8n dispatcher lanes, Command Center API, scalp path, governed LLM jobs]
  S -. as_of advances .-> E[n8n event router fires the consumer (target; not built)]
```

- **Rule (AGENTS.md §7A; 4.6.0 §24.3 PROPOSED):** one owner lane per provider and universe writes; every consumer
  reads a projection; a stale or missing value gets the domain's declared `no_coverage` or a budgeted `on_gap` through
  the owner — never a silent provider call from the consumer. **Measured gap [C]:** ~45 lanes fetch providers
  themselves (~36 of them consumers), only 3 read through `data_broker`, ~27 read stores by direct SQL or raw cache;
  `check_data_source_authority.py` counts direct reads in hub files only, so lane scripts are invisible to it.

| Domain | Owner (single writer) | Read path | State 2026-10-10 |
|---|---|---|---|
| `finviz_enrichment` | `scripts/finviz_enrichment.py` (`save_cache` locked, merged, atomic) | `data_broker/finviz_enrichment_snapshot.py` | **Live** in `8ddf2ad59` (#1669, step 1). Directive servicer L442 reads via the broker and refreshes in one batch: 426 requests vs 8,490 per run (dry run, live cache). Kill switches `DIRECTIVE_ENRICH_VIA_BROKER=0`, `DIRECTIVE_ENRICH_PREFETCH=0`. Store of record `data/state/ticker_enrichment_cache.json`; the 4,500-entry `data/portfolios/state` copy is archived and merged (ADD 3,524 → 4,511) by packet `enrichment-cache-merge/` — dry run done, apply needs `release-write` |
| `scalp_list` | L1050 (RTH list) and the premarket hot-list owner | `data_broker/scalp_list.py` (fresher list, `as_of`/`age`/`stale`) | Code live, knob OFF (#1671, §6.3) |
| `social_posts` | `social_ingest.py` | — | Domain approved (§D.5); StockTwits limits to be declared (§D.14) |
| `latest_quote` (Q1) | quote owner (L92/L128 absorbed); `market_quote_snapshots` retired after | `market_quote` projection, TTL + envelope; `broker_trade_plan_gate.py` untouched | Branch `n8nmat/broker-domains-q1` (local; packet `broker-domains-q1/`): 200 symbols, same prices, 0.325 → 0.0078 s; replayed quote-only reads 200/200 from the store, 0 provider calls |
| `earnings_calendar`, `news_sentiment` | `scripts/lib/alpha_vantage_owner.py` (only file naming the AV host) | `data_broker/earnings_calendar.py`, `news_sentiment.py` | PR #1675 open; scope rows a proposal until merged with the grant (§6.2) |
| `yfinance_info_snapshot` | yfinance-reference owner (new) | — | Approved (§D.13), not built |

- **Also approved, not applied:** L185 + L186 merged into L184's union line and L324 retired (packet
  `consolidation-cron-1/`, crontab 422 → 419 entries, `install.sh` refuses unless the live crontab equals the snapshot;
  registry side on branch `n8nmat/consolidation-registry`); end dates for the `cio-memory-shadow-measure` and
  `advisory-shadow-seed` timers; the three per-lane shadow archives (§3.2); W4 owners as `ingest` dispatcher rows.

### 6.2 Web search routing, the Brave dollar budget, Alpha Vantage

Full design: [`SEARCH_SOURCE_ROUTING.md`](SEARCH_SOURCE_ROUTING.md) (lands with **PR #1676**, open). Policy
`config/search_routing_policy.json` (`SearchRoutingPolicy@v1`), engine `scripts/lib/search_router.py`, **OFF by
default** (`SEARCH_ROUTING_ENGINE=1`, or `SCALP_HOT_TIER=1` for `route_search` only).

- **Order:** cache → free lane (internal news projection, SearXNG with explicit engine lists, the Alpha Vantage news
  store) → paid Brave only when the class allows it and the free answer is measurably insufficient → a declared
  `no_coverage`. Unknown callers are refused (`UNKNOWN_CALLER`).
- **Dollars (operator ~18:03 ET: "$20 maximum a month on Brave ... trying not to use it all ... prioritize the search
  for scalps that are about to fire"):** account cap $20/month; local hard ceiling **$18**; working target **$15**
  (scalp-priority pool may run to it); non-priority stop **$12**; P2 alert at 80% of $15. Pools of $15: scalp 50%,
  operator reserve 20%, catalyst 20%, other 10%; daily pacing over NYSE trading days.
- **Request breaker** (`providers.brave.budget` in `config/data_source_authority.json`): operator approved raising it
  to ≥ 3,000/month so the dollar lines bind (target 300/day, 3,600/month = $18 at $0.005); **measured on the #1676
  branch it is still 120/day, 1,500/month** (+200 on-demand reserve) — the raise is its own registry change.
- **SearXNG must never name a Brave engine.** Its `braveapi` engine (the paid API) answered `categories=general`
  queries outside the ledger: 2,357 requests 2026-10-01..10, every one HTTP 422; whether Brave bills a 422 is UNKNOWN.
  #1676 makes SearXNG clients name engines explicitly. Disabling `braveapi` in the live config is approved (item 1);
  packet `searxng-braveapi-off/` dry run done 18:35 ET, apply pending a `config-write` grant.
- **Ledger hygiene:** 33 future-dated keys (2026-10-11 … 12-25) written into the production `search_budget.json` by
  `tests/test_research_heartbeat_20260914.py` (fixture fixed on #1676, with a regression test). Archive approved
  (item 2); packet `search-budget-archive/` (flock + compare-and-set + byte copy + manifest; never delete) dry run done,
  apply pending `release-write`.
- **Alpha Vantage** (PR #1675 open): one owner `scripts/lib/alpha_vantage_owner.py`, hard cap **23/day** of the free 25
  (counted on both the UTC and ET day, ≥ 12 s spacing, refusals never counted); stores
  `data/runtime/alpha_vantage/{earnings_calendar_latest,news_sentiment_latest}.json`. Scope A1–A3 (earnings calendar,
  news sentiment) and B1 (`earnings_date` backup), B2 (`catalyst_news` backup) approved ~18:40 ET; until the registry
  rows merge with the grant, the owner refuses those jobs up front. The phantom-spend bug is fixed (#1668: ~4,650
  counted-but-refused calls/week → 0). NewsAPI.org tested (key valid, ~24 h delayed) and **stays retired**.

### 6.3 Scalp hot tier (#1671, code live in `8ddf2ad59`, knob OFF)

Data side only: nothing sizes, orders, stops, submits or sends; L1050 and L323's paper path are untouched.

- **Flags:** behaves exactly as before unless `SCALP_HOT_TIER=1` **and** no kill file
  `persistent-state/data/runtime/SCALP_HOT_TIER_DISABLED`; market days only.
- **Stages once switched on:** premarket list owner `run_finviz_momentum_scalp_scan.py --hot-list-only --apply`
  (`*/2 6-9`, acts 06:00–09:30); RTH list L1050 unchanged (`*/5 9-15`); enrichment `finviz_enrichment.py --scalp-hot`
  (`*/5 6-15`, `hot_*` fields only); social `social_ingest.py --source stocktwits --scalp-list` (`*/10 6-10`); Hermes
  L708 `--on-list-advance`; L636 proposal stage and L246 social scanner fire on list advance
  (`lib/scalp_list_trigger.py`: `FIRE_NEW_SYMBOLS`, `FIRE_ADVANCE`, `FIRE_STALE_LIST` falls back to the old cadence,
  `FIRE_LEGACY_CLOCK` with the knob off). Research goes only through the routing engine (§6.2) and is inert until
  #1676 lands.
- **SLOs** (market days 06:00–16:00 ET; social 06:00–11:00): scalp list ≤ 5 min, enrichment ≤ 10 min, catalyst
  ≤ 30 min, social ≤ 15 min — `scalp_hot_tier_report.py --freshness [--strict]` (healthy / late / degraded / failed;
  `NO_SLO` outside hours); `--budget` for the provider math.
- **Budget:** Finviz +4,500/week; all-in after step 1 and the hot tier 12,560/week = 5.2% of the 241,920/week
  ceiling (~8.6× headroom at peak). StockTwits 25 names × 6/h = 3,750/week (limit undeclared, §D.14).
- **Switch-on:** staged cron/registry changes in packet `scalp-hot-tier/` (PREPARED, not applied), each under its
  grant, with the health-contract entries in `health_contract_entries.json`.

### 6.4 C1 manifests, multi-line cutover, stage runner, premarket

- **`_cutover.py` multi-line (#1673, merged `ca922a6ee`, not yet promoted):** one lane may retire up to
  `DISPATCH_CRON_MAX_SLOTS = 8` cron lines — a `scheduler.match` list (each item must hit exactly one line) or a
  string with `--expect-lines K`; one `# RETIRED` tag per line; the receipt lists every line; `dispatch.cron` must
  equal the retired slots; per-lane rollback refuses a double schedule; single-line output is byte-identical.
  **Limit:** only `_cutover.py` reads a `match` list today; `check_lane_registry` and three report scripts treat
  `match` as a string.
- **C1 (#1674, merged `7df77950a`, not yet promoted):** 75 cron lines absorbed into 4 existing pipeline manifests —
  `hermes_learning` 7, `hermes_overnight` 5, `after_close` 26, `premarket` 37 (job count 528 → 453; fires unchanged,
  they move inside the stages). Flip order hermes_learning → hermes_overnight → after_close → premarket, one at a time
  after a natural-schedule receipt; packets `~/n8n-maturity-verification/packets/c1-manifest-flips/` PREPARED, not
  installed (`install.sh` refuses unless the live crontab equals its snapshot; rebuilt after the L556 edit).
  **C1 takes the 22 dispatcher shadow lanes** among the 75 (operator ruling): each manifest's registry edit moves those
  rows to `dispatch_retired`; #1674 did it for `hermes_learning` (`hermes-config-governor` left wave D1b; 54 shadow
  rows remain on main). **L184 and L243 stay out of C1** (consolidation plan: C-IDENT-01, social owner).
- **Before flips 3–4:** (a) the stage runner sources the whole `$PROJ/.env` into every step
  (`_pipeline_common.sh load_env`, `set -a`) while most absorbed lines do not — fix to a per-step env before after_close
  and premarket flip (operator yes); (b) parallelise or split the premarket stage: Σ median 3,303 s and Σ p95 5,899 s
  of a 6,000 s window before the 07:30 brief (operator yes); (c) readiness `report_tranche_b_readiness.py --dry-run`
  is NO_GO for after_close planning and premarket until the D3 lane receipts appear on Monday 10-12's natural runs.

### 6.5 No push from scheduled work (#1672, merged `dbadb9c1b`, not yet promoted)

L556 `coder_dispatch` in PR mode commits to a local branch; push and `gh pr create` need PR mode **and** `--allow-push`
**and** `TRADEAI_REMOTE_PUSH_AUTHORIZED=1` **and** not `--from-queue` (the cron line runs `--from-queue`, so it can
never push). L541 `backup_generated_docs.sh` commits to local `generated-docs-backup`; push needs `--push` and the
flag. Interim live stop: `CODER_DISPATCH_MODE=advisory` on L556 (cron grant 4b3623125f6b6d7e, in the crontab now).
Side finding: the backup branch's latest commit (10-09 23:50) holds 0 files — `git add --ignore-errors` aborted on an
unmatched glob; #1672 fixes it.

### 6.6 CIO desk-loop drain (#1670, live in `8ddf2ad59`)

Root cause of operator questions refused all day: 7 pending rows with an empty `chat_id` were re-curated by the model
on every background pass and dropped with no status row, using all 400/day `cio_operator_reply` calls by ~03:30 ET
(610–4,034 refusals/day 10-05..10-10). Fix: chat-less rows close as expired before any model call; ≤ 3 answer
attempts per row per day; the background pass may use at most 25% of the daily cap; counters persist by NY day.
#1668 adds the cost-cap backoff (`CIO_DESK_COST_CAP_BACKOFF=0` disables). Optional one-time close packet
`desk-loop-drain/` (dry run only; `db`/state write grant if used). Routing doc: `docs/OPERATOR_REPLY_ROUTING.md`.

### 6.7 NYC DOF is a separate application

DOF (`/home/johnclaw/nyc-dof-auction`, its own repo; crontab L145 `rescan_tickets.py` daily 18:00, L152
`run_pipeline.py` Saturdays 20:00; `dof-dashboard.service`) is **not Trade AI**. It moves to **its own n8n instance
and a DOF-only runner** — never the Trade AI relay, gateway, dispatcher, allowlist, registry, credentials or this n8n
instance — and leaves the Trade AI inventory counts as "other application" rows. Its DB login is fixed first: every
DOF stage connects to Postgres `trade_ai` as role `trade_ai` (the 22 `dof_*` tables are owned by it), and the weekly
pipeline has failed all six stages since 2026-08-29 on password authentication while exiting 0. A dedicated role
`dof_app` is approved. Design packet `~/n8n-maturity-verification/packets/nyc-dof-n8n/DESIGN.md` (PROPOSED; nothing
installed). Moving the two crontab lines is still a crontab change under a `cron` grant, dry run first, comment never
delete. §23.3's never-list entry "DOF SQL" is unchanged.

### 6.8 Database retention and Iris — OPEN

`trade_ai` is 24.95 GB against a 16 GB budget and grows ~0.18 GB/day net although nightly retention deletes rows
(study `~/n8n-maturity-verification/DB_RETENTION_AND_IRIS_STUDY.md`, read-only, 2026-10-10). `content_embeddings` is
12.37 GB (~50%), 72% of its rows junk `fused_signal` vectors; ~9.4 GB is reclaimable without code changes, and space
returns to disk only after `VACUUM FULL` / `pg_repack`. The registry says `db-retention-timer` ACTIVE while the unit
is off or absent; `tradeai-iris-taxonomy.timer` is disabled (operator O-4) and `agent-runtime@iris` was disabled in
retire batch 1. Recommended model, **not decided**: a per-table retention policy file, a governed host runner
(archive before drop, never delete without archive and tripwire, partitioning for large time series), n8n
orchestration only (weekly dry-run digest via the communications gateway → approval → apply → verify). Each step is
an operator decision.

### 6.9 Portability — Supabase and n8n Cloud

Operator, 2026-10-10 evening: *"One day I may move this to Supabase and the hosted version of N8N, so we want to
consolidate as much as we can."* Every n8n change keeps that move open: authoritative stores in Postgres tables rather
than new persistent-state JSON files; retention by Postgres-native means (`pg_cron`, partitioning / `pg_partman`,
standard extensions); the relay/gateway contract stays HTTP + auth so a cloud n8n could reach it through a secure
ingress later; workflows carry no host paths and no credentials, and the relay address lives only in the one `Relay`
Set node; the DB stays lean (size drives Supabase cost). A design that would block the move says so in its PR
(AGENTS.md 4.6.0 §24.9, PROPOSED; it reinforces §23.6 "n8n is replaceable").

---

## 7. Change log — n8n configuration

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
| 2026-10-10 16:40 | wave-3 activation: 19 R1 rows to `stage: shadow` (merge #1665 `e8a4a6815`; live once promoted) | registry PR |
| 2026-10-10 ~17:07 | release grant 7792ff3948d8d2d9 refused by the SHA binding ("no SHA named"); re-requested naming the sha and PRs | `ReleaseGrantBinding@v1`; `status-20261010/release-e8a4a6815-promote.log` |
| 2026-10-10 17:13 | release `e8a4a6815` promoted: relay `POST /event` (#1663), gateway lane in the repo unit (#1664), 19 R1 rows live in shadow (#1665) | release-write grant naming the sha |
| 2026-10-10 17:14 | W0 re-run: dispatcher, event router, incident router, digest scheduler re-imported and published | grant c90266247a4c4cd4; `packets/w0-import-six/rerun-*` |
| 2026-10-10 17:20 | W0 partial rollback: event router, incident router, digest scheduler unpublished; dispatcher kept (RC11) | grant c90266247a4c4cd4 |
| 2026-10-10 before 18:20 | crontab L556 `CODER_DISPATCH_MODE=advisory` (interim stop of push-from-cron) | cron grant 4b3623125f6b6d7e |
| 2026-10-10 18:40 | release `8ddf2ad59` promoted: `/due` matcher fix (#1667, RC11), quick wins (#1668), consolidation step 1 (#1669), desk-loop drain (#1670), scalp hot tier code with the knob off (#1671) | release-write grant naming the sha; `status-20261010/release-8ddf2ad59-*.log` |
| 2026-10-10 18:40 / 18:44 / 18:47 | event router, incident router, digest scheduler re-published one at a time; four generic workflows live | grant 4b3623125f6b6d7e; `packets/w0-import-six/republish-20261010.txt` |
| 2026-10-10 (merged, not promoted) | #1672 no push from cron; #1673 `_cutover.py` multi-line; #1674 C1 manifests + `hermes_learning` registry flip (54 shadow rows on main) | registry / code PRs |

---

## 8. Open items

| # | Item | Owner / authority |
|---|---|---|
| 1 | ~~W0 re-run with 4 ids~~ **done** 18:40–18:47 ET (four live); keep the publish-one-at-a-time rule until item 19 | — |
| 2 | Registry rows for `heartbeat-watch` and `approval-escalate` (heartbeat watcher / approval router out of W0 until then) | registry PR |
| 3 | Fan-in reader for `n8n-workflow-error` events (served since 17:13 ET; they reach neither SIEM nor Telegram yet) | agent PR |
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
| 18 | ~~Promote #1663/#1664/#1665~~ **done** (`e8a4a6815`, 17:13 ET). Next promote carries #1672, #1673, #1674 | operator promote |
| 19 | Concurrency probe in `check_n8n_relay_contract.py` (RC11 lesson, §2.1) | agent PR |
| 20 | Apply approved packets: SearXNG `braveapi` off (`config-write`), `search_budget` future-key archive (`release-write`), enrichment-cache merge (`release-write`), 3 per-lane shadow archives (`cron`), consolidation crontab L184/L185/L186/L324 (`cron`) | operator grants (§6) |
| 21 | Brave request breaker raise to ≥ 3,000/month (registry change, approved) | registry PR |
| 22 | Merge #1675 (Alpha Vantage owner + scope rows with the grant) and #1676 (search routing engine, `SEARCH_SOURCE_ROUTING.md`) | review + operator word |
| 23 | Scalp hot tier switch-on (packet `scalp-hot-tier/`), after #1676 | staged `cron` / registry grants |
| 24 | C1 flips 1–4 (one at a time); stage-runner per-step env and premarket parallelisation before flips 3–4 | `cron` grants + code PRs |
| 25 | `scheduler.match` lists read by `check_lane_registry` and the report scripts (today only `_cutover.py`) | agent PR |
| 26 | Data-broker lane-script direct-read check (`check_data_source_authority.py` scans hub files only) | agent PR (AGENTS 4.6.0 §24.3) |
| 27 | Notification intents: migrate ~66 direct senders to the communications gateway | per-sender PRs |
| 28 | NYC DOF to its own n8n instance + DOF-only runner; `dof_app` DB role first | operator (DOF design packet) |
| 29 | DB retention / Iris (§6.8) — decisions pending | operator |
| 30 | AGENTS.md 4.5.0 (this PR) and 4.6.0 (branch `n8nmat/agents-4-6-0`) ratification | `APPROVE_AGENTS_POLICY_4_5_0` / `_4_6_0 <pr> <sha>` |
