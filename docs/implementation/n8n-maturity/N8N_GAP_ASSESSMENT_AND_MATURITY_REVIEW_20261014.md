# Final gap assessment and maturity review — platform, n8n and the mandatory workflow framework (2026-10-14)

```
Status:      ACTIVE (dated snapshot; re-measure after each MUST item in §9 lands)
as_of:       2026-10-14T18:45:00-04:00
Measured at: served 3e9dc5e14 (GET 127.0.0.1:7777/v3/build-meta.json, release 3e9dc5e14-main-exact-phase2-20261014-171809);
             origin/main a1b1c5c93; n8n 2.43.0 DB (SELECT only); coordination ledger (sqlite mode=ro); host ms01-openclaw
Owner:       platform (n8n maturity program)
Policy:      AGENTS.md 7.0.0 ACTIVE. 10.0.0 (§23.23, n8n = automation fabric) MERGED AS PROPOSED, NOT ratified.
             11.0.0 (§23.24, the mandatory n8n workflow framework) PROPOSED by the PR carrying this file.
Evidence:    ~/n8n-maturity-verification/arch-review-20261014/ (FINDINGS.csv ids cited as WSn-mm; CANARY_DOUBLE_EFFECT_AUDIT.md)
```

This is the closing assessment the operator asked for on 2026-10-14: current state, target state, remaining work,
risk and next actions, reconciled against what is **served and running**, not against what is designed. The
framework it scores against is §23.24 (PROPOSED) and
[`N8N_CONFIGURATION.md`](N8N_CONFIGURATION.md) §0 (the operational standard).

## 0. Status vocabulary (used in every doc of this refresh)

| Label | Meaning | How to check |
|---|---|---|
| **LIVE** | code is in the served release and the runtime uses it | `curl -s 127.0.0.1:7777/v3/build-meta.json` `git_sha`; `readlink -f ~/trade-ai-releases/portfolio-server/CURRENT` |
| **MERGED-NOT-SERVED** | on `origin/main`, not in the served release | `git merge-base --is-ancestor <sha> <served>` is false |
| **PR-OPEN** | an open pull request | `gh pr view <n>` |
| **BRANCH-ONLY** | a branch or worktree with no PR | `git branch -a` |
| **PLANNED** | a design or a plan; no code | the design doc |
| **POLICY-ONLY** | a rule in AGENTS.md (or a proposed amendment) that no code enforces | the named check does not exist |

A capability that is LIVE in code but switched off at runtime is written "LIVE (code), OFF (runtime)".

## 1. The state of the platform on 2026-10-14 18:45 ET

| Item | Status | Evidence |
|---|---|---|
| Served release | **LIVE 3e9dc5e14** | build-meta `git_sha 3e9dc5e148ee…`; CURRENT → `3e9dc5e14-main-exact-phase2-20261014-171809` |
| #1732 stop alerts never digest | **LIVE** | `scripts/telegram_alert_router.py` `_STOP_FIRING_PATTERN` → P0_INTERRUPT before the v2 router; `tests/test_stop_alert_never_digest_20261014.py` |
| #1733 Schwab paused → fail loud | **LIVE** | `config/schwab_access_mode.yaml` (`mode: forbidden`), `scripts/lib/schwab_access_mode.py`, `stop_health_check._schwab_unavailable_alert` (P1), health agent `schwab_token_revoked` |
| #1735 CC Tailscale identity auth | **LIVE (code), report_only (runtime)** | `config/cc_auth.yaml` `enforce: true, report_only: true`. Enforced in every mode: secret writes 403 (`/api/v2/admin/secrets`), CSRF hard routes, 42 step-up method+path pairs refused ("TOTP unlock not yet enabled"). Not done: operator packet `docs/ops/packets/cc-tailscale-identity-20261014/` (service token file absent; `tailscale serve` still proxies to `localhost:7777`, not the unix socket); 1,681 `would_deny` rows in `~/.local/state/tradeai/cc_auth_decisions.jsonl` |
| #1734 trading read-only lock | **MERGED-NOT-SERVED** (`21692c038`) | `scripts/lib/trading_lock.py` absent from CURRENT; release `a1b1c5c93-…-183100` prepared 18:32, not promoted. Default once served: LOCKED (no unlock file) |
| #1737 health agent: no broker remediation | **MERGED-NOT-SERVED as a release; its policy file is hot-patched into the served release** | CURRENT `config/health_agent_policy.json` mtime 18:11 ET (after the 17:18 build) equals `a1b1c5c93`; `git show 3e9dc5e14:` copy still has the `unified_stop_supervisor.py --apply` map entries. Released directories are meant to be immutable — see §6 item 1 |
| AGENTS policy | **7.0.0 ACTIVE**; 10.0.0 MERGED-AS-PROPOSED (#1736, `3e9dc5e14`), not ratified | AGENTS.md header; 10.0.0 version row PENDING |
| Build 2 — governed bridge OAuth transports + `/v1/llm_step` | **PR-OPEN #1738** (head `9c11ed5c2`), OFF by default (`CIO_BRIDGE_OAUTH_TRANSPORTS` unset) | `gh pr view 1738` |
| Build 1 — run-outcome contract, effect key, Run Lane sub-workflow, error workflow, generator node enablement | **BRANCH-ONLY, IN PROGRESS** (`n8nfab/phase1-primitives-20261014`) | local branch at `3e9dc5e14` with no commits of its own at 18:40 ET; not on origin |

## 2. n8n: what it is today vs the target

**Target (10.0.0 §23.23, PROPOSED):** n8n owns FLOW — sequencing, dependencies, event triggers, retries/backoff/
dead-letter through one Run Lane sub-workflow, error workflows, approval timelines, escalation timers, LLM
judgment steps. The host owns AUTHORITY, EXECUTION and EVIDENCE.

**Today (7.0.0 §23.1, ACTIVE):** n8n is "a scheduler and a requester, never an authority". Measured:

| Fact | Value | Evidence |
|---|---|---|
| Active workflows | **16** (6 generic `tradeai-*` + 10 per-lane) of 43 stored | `SELECT … FROM workflow_entity WHERE active` |
| Trigger | 16/16 schedule-started; one `webhook` node (event-router `tradeai-nudge`, header auth) only nudges a poll | node types per workflow |
| Node types in use | code, httpRequest, scheduleTrigger, set, if, wait (1 s backoff), splitInBatches, stopAndError, errorTrigger, webhook | same; no Execute Workflow, no approval Wait, no AI node |
| Sub-workflows / approval waits / AI nodes | 0 / 0 / 0 | WS1-01, WS1b-02 |
| Error workflow set | 6 of 16 (the generic set except `tradeai-incident-router`, which is the error workflow) | `settings.errorWorkflow` |
| Successful executions saved | **none** (`EXECUTIONS_DATA_SAVE_ON_SUCCESS=none`; successes are soft-deleted, status left `running`) | 53 `running` rows all with `deletedAt` set |
| Errors saved | all (`EXECUTIONS_DATA_SAVE_ON_ERROR=all`, prune 168 h) | container env |
| n8n error executions | 763 on 10-14, 419 on 10-13; 836 in the last 24 h are `tradeai-dispatcher` policy refusals (`=RUNNING`, `=REFUSED`) recorded as errors | WS1b-07 |
| Workflow drift git vs live | **16/16 OK** | `python3 scripts/check_n8n_workflow_drift.py --dry-run` 18:38 ET |
| Drift check scheduled? | **No** — no receipt `n8n_workflow_drift_last.json`, no cron/timer | the "drift pages P1" rule of §23.23 is POLICY-ONLY |
| n8n DB role | `n8n` **superuser** | `pg_roles`; WS1b-12 |
| Ledger runs (24 h) | live 1,628 RUN_DONE / 8 RUN_TIMEOUT / 1 RUN_FAILED; dry_run 2,296 RUN_DONE | coordination ledger `runs` |
| Dead letters / breakers | 48 DLQ rows; 6 breaker rows (5 opened by the 10-12 `/tmp` ENOSPC incident) | ledger `dead_letters`, `breakers` |
| Live-capable lanes | relay live list = 7 lanes; registry `dispatch.mode: live` = 13 rows (12 canary + 1 cutover) | `~/.config/tradeai/n8n-live-lanes.env`; registry |

**The live/dry gap (surprise, high risk):** of the 13 registry rows that say `live`, only `heartbeat-watch` and
`research-insight-extractor` are on the relay live list. The other 11 canary rows (including
`trade-ai-scalp-live`, `material-change-detector-stage1`, `document-mentions-backfill`) **run dry_run** (168
`trade-ai-scalp-live` dry runs in 72 h, 0 live) and the relay logs `relay_live_not_enabled` (227 of the last
400 refusals). The registry, the program trackers and the canary-wave reports read "canary live"; the runtime is
dry. This is WS1-07 (six independent live gates, no reconciler) in production.

## 3. Workflow classification (the 16 active)

Classes from §23.24 (PROPOSED): **BC** business-critical (output the operator or a trading surface acts on),
**RS** resilience (keeps the platform running or recovering), **AI** AI/LLM (an LLM step inside the
workflow), **MC** monitoring/compliance.

| # | Workflow (id) | Class | Mode today | Cadence | What it manages / monitors / validates / reports / escalates |
|---|---|---|---|---|---|
| 1 | `tradeai-dispatcher` | BC | live (fires 2 live lanes, ~70 dry_run rows) | `* * * * *` | manages: asks the relay `GET /due`, posts `POST /run` for every due registry row. Validates nothing itself (the gateway does). Escalates: errors → incident-router |
| 2 | `tradeai-event-router` | BC | live | `* * * * *` + webhook nudge | manages event-sourced due rows; 0 event-triggered registry rows today |
| 3 | `tradeai-digest-scheduler` | BC | live | `*/5` | manages digest-class due rows; the 10/15/17 ET advice digest itself still runs from host cron |
| 4 | `tradeai-heartbeat-watcher` | RS | live (`heartbeat-watch`) | `*/5` | monitors 6 alert-path lanes for freshness (supervisor-breach-detector, fan-in, incident-notifier, siem-bridge, health-tick, n8n-lab-watchdog); escalates via Breach@v1 rows → fan-in |
| 5 | `tradeai-incident-router` | RS | live | `* * * * *` + Error Trigger | reports: shapes n8n workflow errors into relay `POST /event` (lane `n8n-workflow-error`) |
| 6 | `tradeai-momentum-lifecycle-candidate` | MC | shadow validation | `*/5` | validates the momentum lifecycle shadow chain (receipt + last-run projection) |
| 7 | `n8n-incident-fanin` (`722fac0e043ea5c4`) | RS | live (cron retired) | `*/5` | reports: collects incidents from 10 sources (986 open: 18 P1, 943 P2, 25 P3) for the host notifier |
| 8 | `n8n-pilot-dispatch` (`078e8fcbea0c5020`) | MC | live (cron retired) | `*/15` | posts artifact-keyed requests to the gateway |
| 9 | `n8n-research-intake-consumer` (`21fd15d5f8a4c4da`) | BC | live (cron retired) | `*/15` | manages: one `ri_research_queue` row per accepted research request |
| 10 | `crontab-snapshot-for-health-agent` (`c0d4c7845e5c4fcc`) | RS | live (cron retired) | `*/20` | writes the crontab snapshot the health agent reads |
| 11 | `catalyst-calibration-monitor-shadow` (`283ceeb030de5e66`) | MC | shadow — **fails every fire** | `40 5 * * *` | relay: `relay_lane_not_allowlisted`; archive approved 10-10, not applied |
| 12 | `watch-directives-monitor-shadow` (`5966437c872aa18b`) | MC | shadow — **fails every fire** | `20 6 * * *` | same; archive approved, not applied |
| 13 | `source-attribution-monitor-shadow` (`498d749165a93ff9`) | MC | shadow (dry_run) | `0 6 * * *` | archive approved, not applied (superseded by a dispatcher row) |
| 14 | `finviz-view-contracts-shadow` (`2c725c7dfd4ac62f`) | MC | shadow (dry_run) | `5 6 * * 1-5` | 2 RUN_TIMEOUT (300 s) on 10-10 |
| 15 | `generate-analyst-daily-digest-shadow` (`ffa6bbfa93ad4056`) | BC | shadow (dry_run) | `30 7 * * 1-5` | 1 RUN_FAILED 10-12 |
| 16 | `lane-governance-packet-weekly-shadow` (`e6f62397d5ae2aa2`) | MC | shadow (dry_run) | `20 6 * * 1` | weekly governance packet |

**AI/LLM class: 0 workflows.** No n8n workflow contains an LLM step; the LLM work the dispatcher fires
(`llm`-class rows, all dry_run) is host-side, through the governed bridge.

## 4. Per-workflow framework compliance matrix (the core of this assessment)

Scored against the six areas of §23.24 (PROPOSED). **Y** = every check of the area passes, **P** = some pass,
**N** = none pass, **n/a** = the area does not apply (no LLM step). Evidence keys below the table.

| # | Workflow | Monitoring | Alerting | Logging | Recovery | Security | AI/LLM gov. | Score (Y=1, P=0.5) |
|---|---|---|---|---|---|---|---|---:|
| 1 | tradeai-dispatcher | P (m1 m2 m3; contract DRAFT) | P (a1) | P (l1 l2 l5) | P (r1 r2 r4) | P (s1 s2 s3) | P (g0) | 3.0 / 6 |
| 2 | tradeai-event-router | P | P (a1) | P | P (r1) | P (s1 s2 s3, webhook header auth) | n/a | 2.5 / 5 |
| 3 | tradeai-digest-scheduler | P | P (a1) | P | P (r1) | P | n/a | 2.5 / 5 |
| 4 | tradeai-heartbeat-watcher | P (watches others; contract DRAFT) | P (a1; a2 for 6 lanes, but inside n8n — WS1-15) | P | P (r1) | P | n/a | 2.5 / 5 |
| 5 | tradeai-incident-router | P | **N** (no error workflow for the error workflow; task-runner timeouts drop events — 13 errors 10-13) | P | P (r1) | P | n/a | 2.0 / 5 |
| 6 | tradeai-momentum-lifecycle-candidate | P (contract REVIEWED) | P (a1) | P | P (r1) | P | n/a | 2.5 / 5 |
| 7 | n8n-incident-fanin | P (contract DRAFT; ledger) | P (ledger RUN_* → fan-in only; no n8n error workflow; 403 `RUNNING` overlaps recorded as errors) | P | P (r4 slot idempotency; no retry) | P | n/a | 2.5 / 5 |
| 8 | n8n-pilot-dispatch | P | P | P | P | P | n/a | 2.5 / 5 |
| 9 | n8n-research-intake-consumer | P | P | P | P | P | n/a | 2.5 / 5 |
| 10 | crontab-snapshot-for-health-agent | P | P | P | P | P | n/a | 2.5 / 5 |
| 11 | catalyst-calibration-monitor-shadow | **N** (not allowlisted; no run since a manual one 10-11) | **N** | P (errors saved) | **N** | P | n/a | 1.0 / 5 |
| 12 | watch-directives-monitor-shadow | **N** | **N** | P | **N** | P | n/a | 1.0 / 5 |
| 13 | source-attribution-monitor-shadow | P (contract DRAFT) | **N** | P | **N** | P | n/a | 1.5 / 5 |
| 14 | finviz-view-contracts-shadow | **N** (no contract) | **N** | P | **N** | P | n/a | 1.0 / 5 |
| 15 | generate-analyst-daily-digest-shadow | **N** (no contract) | **N** | P | **N** | P | n/a | 1.0 / 5 |
| 16 | lane-governance-packet-weekly-shadow | **N** (no contract) | **N** | P | **N** | P | n/a | 1.0 / 5 |
| | **Fleet** | 0 Y / 11 P / 5 N | 0 Y / 9 P / 7 N | 0 Y / 16 P | 0 Y / 10 P / 6 N | 0 Y / 16 P | 0 Y / 1 P / 15 n/a | **31.5 / 81 = 39%** |

**No workflow is fully compliant in any area.** The ceiling today is P everywhere because three framework checks
fail fleet-wide: successes are not saved (L1), the n8n DB role is superuser (S5), and no workflow has a runbook id
(R5).

**Evidence keys** (each is a §23.24 check; "E" exists, "P" proposed):

- **m1** run evidence joinable by `run_id` — E for relay-dispatched lanes (ledger `runs`, `RunReceipt@v2`); fails in
  n8n itself (successes not saved). **m2** a health contract — E: `config/n8n_health_contracts.json` (120 contracts:
  59 REVIEWED, 61 DRAFT); 4 of the 16 workflows' lanes have none. **m3** `executionTimeout` set — E on the 6 generic
  workflows (50 s; heartbeat 150 s); absent on all 10 per-lane workflows. Performance and capacity baselines are
  contract fields, unmeasured for most.
- **a1** an error workflow — E on 6/16 (`errorWorkflow: tradeai-incident-router`). **a2** SLA (freshness) breach —
  E only for the 6 lanes heartbeat-watch checks. No workflow alerts on performance degradation or LLM exceptions
  (no alert class exists; §5.2).
- **l1** execution log — ledger yes, n8n success no. **l2** error log — E (`SAVE_ON_ERROR=all`). **l5** change log
  — E (generated from git: `scripts/n8n_workflow_templates.py`; drift checker), but the drift check is not scheduled.
- **r1** retry — E on generic HTTP nodes (`retryOnFail`) plus the host `config/n8n_retry_policies.json`; per-lane
  workflows have none. **r2** breaker — E (ledger `breakers`; no half-open, WS1-05). **r4** DLQ — E (ledger
  `dead_letters`, `scripts/n8n_dlq.py`). No workflow names a manual-recovery runbook. The Run Lane sub-workflow
  and the async run-outcome callback are BRANCH-ONLY (Build 1).
- **s1** authN — E: relay bearer (`httpHeaderAuth` credential `tradeai-run-relay`, previous-bearer rotation), gateway
  HMAC claim. **s2** authZ — E: `config/n8n_run_allowlist.json` (96 lanes, never-list) + relay live list. **s3**
  secrets — E: one credential; `N8N_BLOCK_ENV_ACCESS_IN_NODE=true`; no broker or messaging credential; community
  packages off; image pinned `n8nio/n8n:2.43.0`. Fails: `n8n` DB role superuser (WS1b-12); relay bound on the
  docker bridge `172.19.0.1:18092` (ufw rule not verified).
- **g0** the dispatcher fires `llm`-class host lanes (all dry_run today); their governance is the bridge's, not
  the workflow's.

## 5. Gaps by domain

Risk = likelihood × impact for money or for the operator being told: **CRITICAL**, **HIGH**, **MEDIUM**, **LOW**.

### 5.1 Monitoring and observability

| Gap | Risk | Evidence |
|---|---|---|
| No metrics stack (no Prometheus/Grafana; `/metrics` 404); ~10 partial health surfaces disagree | HIGH | WS8-10; `/api/v2/health` score 82 degraded while fan-in reports 18 open P1 |
| Monitoring covers ~22% of scheduled work (118–120 contracts for 524 jobs; 61 DRAFT) | HIGH | WS8-11 |
| n8n successes not saved: n8n cannot show a process view | HIGH | WS1-14, WS1b-06 |
| Unit failures and OOM kills raise no alert | CRITICAL | WS3-27, WS8-15 |
| `/tmp` inodes unmonitored; root disk 85% | HIGH | WS3-31, WS3-32 |
| No run-id log correlation across 4 log roots | MEDIUM | WS8-08 |

### 5.2 Alerting

| Gap | Risk | Evidence |
|---|---|---|
| No off-box dead-man; the "off-host" receiver is localhost `:18798` | CRITICAL | WS3-18; `heartbeat-receiver.service` |
| The dead-man reports through what it watches (heartbeat-watch runs in n8n → fan-in in n8n → notifier) | CRITICAL | WS1-15, WS3-14 |
| One Telegram bot, one chat, no second channel | HIGH | WS3-20 |
| `send_telegram` returns True when nothing was delivered; failed sends not replayed | HIGH | WS3-21, WS3-24 |
| P2 channel saturated by the platform's own incidents (798 of 986 open incidents are diagnoser findings) | CRITICAL | WS1-09; fan-in receipt 18:35 ET |
| No alert class for SLA breach (only reports), performance degradation, or LLM exception | HIGH | `operator_alert_policy_v2.py` `CRITICAL_IMMEDIATE_TYPES`; `check_llm_fleet_alerts.py` not scheduled |
| Fills and position changes appear only as suppressed info | CRITICAL | WS3-09 (stops fixed by #1732; fills not) |
| Schwab auth failure does not page (partly addressed by #1733 while paused) | CRITICAL | WS3-01 |
| Health agent effectively never pages | HIGH | WS3-26 |

### 5.3 AI and LLM governance

| Gap | Risk | Evidence |
|---|---|---|
| Bridge caller identity is self-asserted (`TRADEAI_BRIDGE_CALLER_AUTH` default `report`) | HIGH | `cio_governed_model_bridge.py` ~:1957; AGENTS §23.4 says "bound to the credential" — POLICY-ONLY |
| Egress sanitiser in `report` mode; `sanitise_for_external()` single egress point not built | HIGH | `TRADEAI_EGRESS_SANITISER`; AGENTS §2A |
| Output-schema validation at the bridge applies only to `n8n_*` processes | MEDIUM | `bridge_agent_preconditions.py` |
| Prompt-injection guard not applied at the bridge (applied in 3 callers) | HIGH | `agent_model_pi_guard.scan_model_output`; AGENTS:2297 PARTIAL |
| Global $2.00/day cap not universally enforced (~78 of 84 lanes) | MEDIUM | AGENTS.md §12 |
| No LLM-exception alert class; refusals and 429/503 surface only in ledgers | MEDIUM | §5.2 |
| An LLM agent can write an operator-attributed approval | HIGH | WS7-07 |
| Bridge-side off-peak deferral (§23.4) not implemented | LOW | bridge has no deferral code |
| Prompt files carry no review/approval field; most prompts inline | MEDIUM | `prompts/cio_*` |

### 5.4 Security

| Gap | Risk | Evidence |
|---|---|---|
| One uid for every actor; docker group = root | CRITICAL | WS4-01 |
| A Schwab "read" credential is a trading credential | CRITICAL | WS9-04 |
| Per-order "2FA" proves a database write | CRITICAL | WS4-10 |
| Trading lock merged, not served | CRITICAL until promoted | #1734 |
| CC auth report_only; operator packet not executed; `:8443` DOF still tailnet-served | HIGH | #1735 runtime |
| No DB role separation (`trade_ai` owns everything; `n8n` superuser) | HIGH | WS4-11, WS1b-12 |
| Guard PreToolUse hook documented ACTIVE, not installed | HIGH | `docs/ops/AGENTS_GUARD_HOOK.md`; WS4-07 |
| Self-authorisation stores writable by the agents they constrain | HIGH | WS4-08 |
| Plaintext provider keys and bot tokens in log files | HIGH | WS4-05 |

### 5.5 Operational maturity

| Gap | Risk | Evidence |
|---|---|---|
| Single host, no UPS, 4 hard power cuts; the n8n stack has never cold-booted | CRITICAL | WS8-06; `~/power-watch/README.md` |
| No `trade_ai` restore ever drilled (n8n drill passes weekly) | HIGH | WS6-07; `config/backup_coverage_manifest.json` "NEVER DRILLED"; `n8n_lab_restore_drill_last.json` 10-11 ok |
| No incident lifecycle (record, roles, severity, postmortem) | HIGH | WS8-01 — answered by [`docs/runbooks/INCIDENT_RESPONSE.md`](../../runbooks/INCIDENT_RESPONSE.md) (procedure only) |
| Broker orders the host did not place are invisible | CRITICAL | WS8-02 |
| Release friction leaves money-risk fixes unserved; a fix hot-patched into a release directory | HIGH | WS8-04; §1 #1737 |
| Production executes the dev tree | HIGH | WS7-01 |
| Registry "live" ≠ runtime live (11 canary rows run dry) | HIGH | §2 |

## 6. Documented functionality that does not exist (or is not running)

1. **Release immutability.** The deploy runbook treats a release directory as immutable; on 10-14 at 18:11 ET the
   served release's `config/health_agent_policy.json` was changed in place to the #1737 version. The effect
   (no stop supervisor via remediation) is live; the release identity says 3e9dc5e14.
2. **Canary-live lanes** — 11 registry rows say `live`; they run `dry_run` (§2).
3. **Drift pages P1** (§23.23, PROPOSED) and **the drift check** — the checker exists, is not scheduled, writes no
   receipt.
4. **The Claude Code guard hook** — `docs/ops/AGENTS_GUARD_HOOK.md` says ACTIVE; not installed; rules file `mode: log`.
5. **CC auth enforcement** — designed enforce; runtime report_only; the service token file does not exist.
6. **Bridge caller identity bound to the credential** (§23.4) — report mode.
7. **`sanitise_for_external()` egress point** (§2A) — "Proposed, not built".
8. **TOTP step-up** for the 42 step-up routes — refused with "TOTP unlock not yet enabled".
9. **Off-host dead-man** — the receiver is on localhost.
10. **Bridge-side LLM deferral** (§23.4).
11. **`docs/HEALTH_AGENT.md`** says the agent runs from cron every 30 min; it runs as a systemd daemon plus a
    health-tick step every 15 min.
12. **`docs/architecture/gateway-enforcement.md`** says Phase 2 with ~45 files of Telegram debt; the baseline is
    empty and the gateway is CANARY phase 7 (`owned_classes: ['ops']`).
13. **Archive of three superseded shadow workflows** (approved 10-10) — not applied; two of them fail every fire.
14. **`docs/RESTORE_GUIDE.md`** "all backup files in git", `nohup` server start, retired models — corrected in that
    file's 2026-10-14 section.
15. **Unit descriptions** — the coordination gateway unit says "(proposal only, not installed)" while running;
    `heartbeat-receiver` drop-in says "PROPOSED … Not installed" while active.

## 7. Functionality present but undocumented (before this refresh)

1. The 16 active workflows' classification, owners and per-workflow controls (now §3–§4 and
   [`N8N_CONFIGURATION.md`](N8N_CONFIGURATION.md) §0).
2. `scripts/cio_phase2_exact_main_deploy.sh` prepare / promote / rollback / status — the actual DR rollback tool —
   absent from the restore guide (now in [`RESTORE_GUIDE.md`](../../RESTORE_GUIDE.md) §0).
3. The platform-maintenance timers: nightly n8n backup (`scripts/n8n_lab_backup.sh`, keeps 14) and the weekly
   n8n restore drill; the backup enforcer (one local pg dump) and disk-hygiene keep-10 releases.
4. `config/backup_coverage_manifest.json` — the best backup inventory.
5. Power-watch and the DC-supply risk.
6. The relay bound on the docker bridge `172.19.0.1:18092`; `:8443` DOF tailnet serve.
7. The bridge pipeline steps 4b/5b/6b/9b (agent preconditions, routing-policy ceiling, egress sanitiser, output
   schema + behaviour scan) and `ProviderRequestJournal@v1` (now in
   [`GOVERNED_MODEL_BRIDGE.md`](../../architecture/GOVERNED_MODEL_BRIDGE.md) §0).
8. `config/llm_routing_policy.json` failover chains and per-provider concurrency.
9. The health-tick step list (16 steps) and the user timers that make up the health plane.
10. The `notification_intent_baseline.json` ratchet (49 sends without a declared priority).

## 8. Maturity scores — current vs target

The architecture review's scores (0–10, `SCORES.md`, arithmetic reproducible from FINDINGS.csv) are the baseline;
this refresh changes no finding status, so they stand. The framework compliance score is new.

| Dimension | 2026-10-14 | When in-flight fixes are served (#1734, packet for #1735, #1737 released) | Target for the first n8n-owned process (§9 MUST done) |
|---|---:|---:|---:|
| Security | 2.9 | ~3.0 | ≥ 5.0 |
| Architecture (fitness to the n8n target) | 2.1 | 2.1 (capped at ~5.4 until 10.0.0 is ratified) | ≥ 5.0 |
| Operational readiness | 2.2 | ~2.3 | ≥ 5.0 |
| Technical debt (higher = less) | 5.9 | 5.9 | ≥ 6.5 |
| **Overall** | **2.9** | **~3.0** | **≥ 5.0** |
| Framework compliance, 16 workflows (§4) | **39%** (0 workflows compliant) | 39% | 100% of active workflows, or archived |

## 9. Remaining work and next actions

**MUST, before any further migration (ordered):**

1. Promote `a1b1c5c93` (serves #1734 and #1737) and record the 18:11 hot-patch in the release log — owner:
   operator (release grant naming the SHA).
2. Execute the CC auth packet (`docs/ops/packets/cc-tailscale-identity-20261014/`) and flip `report_only` off.
3. Reconcile live authority: one source for "live" (registry vs relay list vs allowlist `live_arg`); until then the
   registry rows of the 11 dry-running canary lanes say what they do (WS1-07).
4. Archive the three superseded shadow workflows (approved 10-10; one `cron` grant).
5. Ratify or reject 10.0.0 (§23.23) and 11.0.0 (§23.24); land Build 1 (Run Lane, run-outcome callback, error
   workflow on every workflow, effect key) and the framework check `scripts/check_n8n_workflow_framework.py`
   (PROPOSED in §23.24).
6. Host dead-man outside n8n and an off-box dead-man + second channel (WS1-15, WS3-18, WS3-20).
7. UPS and a cold-boot drill; first `trade_ai` restore drill (WS8-06, WS6-07).
8. Save successes with `run_id` custom data; schedule the drift check with P1 on drift; n8n DB role non-superuser.

**SHOULD:** alert classes for SLA breach, performance degradation, integration failure and LLM exception with a
`runbook_id` per PAGE row (ALERT_TAXONOMY §3); bridge caller auth to `enforce`; egress sanitiser to `enforce`;
install the guard hook; health contracts REVIEWED for every active workflow.

**Re-measure:** rerun §2 (SQL in [`N8N_MONITORING_AND_REMEDIATION_STANDARD.md`](N8N_MONITORING_AND_REMEDIATION_STANDARD.md)
§0.3) and §4 after each MUST item; update §8.

## 10. Reproduce the measurements (read-only)

```bash
curl -s 127.0.0.1:7777/v3/build-meta.json | grep git_sha
docker exec m8m-n8n-db psql -U n8n -d n8n -At -c "select id,name,active,settings from workflow_entity where active"
docker exec m8m-n8n-db psql -U n8n -d n8n -At -c "select status, \"deletedAt\" is not null, count(*) from execution_entity group by 1,2"
python3 scripts/check_n8n_workflow_drift.py --dry-run
python3 - <<'EOF'
import sqlite3
c = sqlite3.connect('file:/home/johnclaw/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite?mode=ro', uri=True)
print(c.execute("select mode,state,count(*) from runs where requested_at>datetime('now','-1 days') group by 1,2").fetchall())
EOF
```
