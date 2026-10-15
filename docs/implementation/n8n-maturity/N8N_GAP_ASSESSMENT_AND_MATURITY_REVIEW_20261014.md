# Final gap assessment and maturity review — platform, n8n and the mandatory workflow framework (2026-10-14)

```
Status:      ACTIVE (dated snapshot; re-measure after each MUST item in §9 lands)
as_of:       2026-10-15T02:35:00Z (re-measured; first measured 2026-10-14T18:45-04:00 at served 3e9dc5e14)
Measured at: served 5aa61048d (GET 127.0.0.1:7777/v3/build-meta.json, release 5aa61048d-main-exact-phase2-20261014-191424,
             live since 00:24Z 10-15); origin/main 57d8fc3ff; n8n 2.43.0 DB (SELECT only); coordination ledger
             (sqlite mode=ro); host ms01-openclaw
Owner:       platform (n8n maturity program)
Policy:      AGENTS.md 10.0.0 ACTIVE (§23.23, n8n = automation fabric; #1740, ratified by PR comment 2026-10-14T23:25:56Z).
             11.0.0 (§23.24, the mandatory n8n workflow framework) PROPOSED by the PR carrying this file.
Evidence:    ~/n8n-maturity-verification/arch-review-20261014/ (ARCHITECTURE_REVIEW_20261014/FINDINGS.csv ids cited as
             WSn-mm; CANARY_DOUBLE_EFFECT_AUDIT.md and DEEPSEEK_LLM_STEP_STALL.md sit beside the package directory)
Tracker:     PROGRAM_TRACKER_20261015.md (what's done / what's left, one row per item)
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

## 1. The state of the platform on 2026-10-15 02:35Z (2026-10-14 22:35 ET)

| Item | Status | Evidence |
|---|---|---|
| Served release | **LIVE 5aa61048d** (since 00:24Z 10-15) | build-meta `git_sha 5aa61048de4a…`; CURRENT → `5aa61048d-main-exact-phase2-20261014-191424` |
| #1732 stop alerts never digest | **LIVE @5aa61048d** | `scripts/telegram_alert_router.py` `_STOP_FIRING_PATTERN` → P0_INTERRUPT before the v2 router; `tests/test_stop_alert_never_digest_20261014.py` |
| #1733 Schwab paused → fail loud | **LIVE @5aa61048d** | `config/schwab_access_mode.yaml` (`mode: forbidden`), `scripts/lib/schwab_access_mode.py`, `stop_health_check._schwab_unavailable_alert` (P1), health agent `schwab_token_revoked` |
| #1734 trading read-only lock | **LIVE @5aa61048d, LOCKED** | `scripts/lib/trading_lock.py` in CURRENT; `status()` → `locked: true` ("no operator unlock file (default: locked)") |
| #1735 CC Tailscale identity auth | **LIVE (code), report_only (runtime)** | `config/cc_auth.yaml` `enforce: true, report_only: true`. Enforced in every mode: secret writes 403 (`/api/v2/admin/secrets`), CSRF hard routes, 42 step-up method+path pairs refused ("TOTP unlock not yet enabled"). Not done: operator packet `docs/ops/packets/cc-tailscale-identity-20261014/` (no service token file; `tailscale serve` still proxies to `localhost:7777`, not the unix socket); 18,208 `would_deny` lines in `~/.local/state/tradeai/cc_auth_decisions.jsonl` |
| #1737 health agent: no broker remediation | **LIVE @5aa61048d** | served `config/health_agent_policy.json` sha256 = origin/main's (`5ba1ddd7…`); the 18:11 ET in-place containment edit is superseded by a release (§6 item 1 stays a finding about the mechanism) |
| AGENTS policy | **10.0.0 ACTIVE** (#1740, `543c39a9e`; ratified by PR comment 2026-10-14T23:25:56Z); 11.0.0 PROPOSED on this branch | AGENTS.md header `Policy-Version: 10.0.0`, `Status: ACTIVE` |
| Build 2 — governed bridge OAuth transports + `/v1/llm_step` (#1738) | **LIVE @5aa61048d, ON for grok + chatgpt** | drop-in `~/.config/systemd/user/cio-governed-bridge.service.d/60-oauth-transports-20261014.conf` `CIO_BRIDGE_OAUTH_TRANSPORTS=grok,chatgpt`. Probes PASS: grok `grok-3-mini` 8.8 s, chatgpt `gpt-6.1-sol` 5.5 s, each with an `LlmStepAudit` row. **DeepSeek proof UNPROVEN**: upstream degraded since ~00:33Z (timeouts, 503s; balance $75; `DEEPSEEK_LLM_STEP_STALL.md`) |
| Build 1 — fabric phase-1 primitives (#1739) | **LIVE @5aa61048d** | 4 fabric workflows imported: `tradeai-fabric-run-lane` and `tradeai-fabric-error` active + published; both probes inactive. **P1 PASS 01:15Z** (Run Lane end to end, `run_outcomes` `fabric-probe-25869-20261014211506` `RUN_DONE`); **P2 PASS 01:37Z** (automatic probe failure → error workflow → `comms_intents` `ci-2a845bc6aa846e66525eb957` `QUEUED`) |
| #1741 Run Lane probe CLI-executable | **MERGED-NOT-SERVED** (`6182aa824`) | Manual Trigger on the probe; packet `--reimport`; every CLI call with `N8N_RUNNERS_BROKER_PORT=5690` |
| #1742 bridge hard deadline, typed read timeouts, stall breaker, provider-health stall alarm | **MERGED-NOT-SERVED** (`5af2f4098`) | P1 when a process has no lane left |
| #1743 provider-journal OOM fix + rotation CLI | **MERGED-NOT-SERVED** (`bff79bbad`) | `latest()` reverse scan, peak 449.6 MB → 3.3 MB; rotation CLI declared unscheduled |
| #1744 comms-intent consumer → incident fan-in, P2 digest | **MERGED-NOT-SERVED** (`57d8fc3ff`), not applied | the one intent above is still `QUEUED` |
| #1745 OAuth fallback (deepseek → grok → chatgpt) for 3 DeepSeek-only processes | **PR-OPEN #1745** (head `67168ec39`, CI green); operator "yes" ~02:10Z | `gh pr view 1745` |
| Hermes learning flow — first business process on the fabric | **PR-OPEN #1746** (head `732309942`, opened 02:36Z; inactive; 3 of 7 steps shadow-ready) | `gh pr view 1746` |

## 2. n8n: what it is today vs the target

**Target (10.0.0 §23.23, ACTIVE since 2026-10-14T23:25:56Z):** n8n owns FLOW — sequencing, dependencies, event triggers, retries/backoff/
dead-letter through one Run Lane sub-workflow, error workflows, approval timelines, escalation timers, LLM
judgment steps. The host owns AUTHORITY, EXECUTION and EVIDENCE.

**Today:** the policy is ACTIVE, the primitives are LIVE (Run Lane, error workflow, run outcomes, `/v1/llm_step`), and
**0 business processes are owned by n8n**: the 16 legacy workflows still schedule and request. The timer-only
cutover freeze (§23.23 migration rule (1)) has all three exit conditions met (Run Lane, run-outcome callback, 10.0.0
ACTIVE); it stays in force until the operator lifts it, and progress is counted as processes owned, not lanes
moved (`PROGRAM_TRACKER_20261015.md` §1). Measured at 02:35Z:

| Fact | Value | Evidence |
|---|---|---|
| Active workflows | **18** (6 generic `tradeai-*` + 10 per-lane + 2 fabric: `tradeai-fabric-run-lane`, `tradeai-fabric-error`) of 48 stored; the 2 fabric probes are inactive | `SELECT … FROM workflow_entity WHERE active` |
| Trigger | 16/18 schedule-started; one `webhook` node (event-router `tradeai-nudge`, header auth) only nudges a poll; run-lane starts from `executeWorkflowTrigger`, error from `errorTrigger` | node types per workflow |
| Node types in use | code, httpRequest, scheduleTrigger, set, if, switch, wait, splitInBatches, stopAndError, errorTrigger, webhook, executeWorkflowTrigger (+ manualTrigger / executeWorkflow on the inactive probe) | same; no approval Wait, no AI node |
| Sub-workflows / approval waits / AI nodes | **1** (Run Lane, `callerPolicy: workflowsFromSameOwner`) / 0 / 0 | WS1-01, WS1b-02 |
| Error workflow set | 6 of 16 legacy (`tradeai-incident-router`) + both fabric workflows (`tradeai-fabric-error`, self-referencing on the error workflow) = 8 of 18 | `settings.errorWorkflow` |
| Successful executions saved | **only the 4 fabric workflows** (`saveDataSuccessExecution: all` per workflow; 6 `success` rows). Instance default `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none`, so the 16 legacy workflows' successes are soft-deleted | 46 `running` rows all with `deletedAt` set |
| Errors saved | all (`EXECUTIONS_DATA_SAVE_ON_ERROR=all`, prune 168 h) | container env |
| n8n error executions | 1,264 stored; 611 in the last 24 h, of which 599 are `tradeai-dispatcher` policy refusals (`=RUNNING`, `=REFUSED`) recorded as errors | WS1b-07 |
| Workflow drift git vs live | **18/18 OK** | `python3 scripts/check_n8n_workflow_drift.py --dry-run` 02:35Z |
| Drift check scheduled? | **No** — no receipt `n8n_workflow_drift_last.json`, no cron/timer | the "drift pages P1" rule of §23.23 is POLICY-ONLY |
| n8n DB role | `n8n` **superuser** | `pg_roles`; WS1b-12 |
| Ledger runs (24 h) | live 933 RUN_DONE / 1 RUN_FAILED / 1 RUNNING; dry_run 1,370 RUN_DONE (lower than 10-14: 15 Schwab cron lines paused) | coordination ledger `runs` |
| Run outcomes / comms intents | `run_outcomes` 189 rows since 00:25Z (new in #1739); `comms_intents` 1 row, `QUEUED` (consumer #1744 not served) | ledger |
| Dead letters / breakers | 48 DLQ rows; 6 breaker rows (5 opened by the 10-12 `/tmp` ENOSPC incident) | ledger `dead_letters`, `breakers` |
| Live-capable lanes | relay live list = 7 lanes (pilot-dispatch, incident-fanin, research-intake-consumer, crontab-snapshot, maturity-remeasure, research-insight-extractor, heartbeat-watch); registry `dispatch.mode: live` = 13 rows (12 canary + 1 cutover) | `~/.config/tradeai/n8n-live-lanes.env`; registry |

**The live/dry gap (surprise, high risk):** of the 13 registry rows that say `live`, only `heartbeat-watch` and
`research-insight-extractor` are on the relay live list. The other 11 canary rows (including
`trade-ai-scalp-live`, `material-change-detector-stage1`, `document-mentions-backfill`) **run dry_run** (168
`trade-ai-scalp-live` dry runs in 72 h, 0 live) and the relay logs `relay_live_not_enabled` (227 of the last
400 refusals). The registry, the program trackers and the canary-wave reports read "canary live"; the runtime is
dry. This is WS1-07 (six independent live gates, no reconciler) in production.

## 3. Workflow classification (the 18 active)

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
| 17 | `tradeai-fabric-run-lane` | RS | live (published 01:14Z 10-15) | called (Execute Workflow; published sub-workflows only) | manages: one lane run — `POST /run` → poll `GET /run_outcome` with a retry budget and backoff waits → result. Escalates: errors → `tradeai-fabric-error` |
| 18 | `tradeai-fabric-error` | RS | live (published 01:14Z 10-15) | Error Trigger | reports: shapes a workflow failure into `POST /intent` (comms intent, DIGEST tier, deduped, `runbook_id n8n-workflow-error`); the intent is queued until the consumer (#1744) is served and applied |

Not scored (inactive): `tradeai-fabric-run-lane-probe` (Manual Trigger, CLI-only) and `tradeai-fabric-error-probe`
(fails on purpose; published once for P2, then unpublished).

**AI/LLM class: 0 workflows.** No n8n workflow contains an LLM step yet. `/v1/llm_step` is LIVE on the bridge
(Build 2), and the first workflow to use it is the hermes learning process (PR-OPEN #1746, inactive). The LLM work
the dispatcher fires (`llm`-class rows, all dry_run) is host-side, through the governed bridge.

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
| 17 | tradeai-fabric-run-lane | P (m1 run outcome by `run_id` + successes saved; m3 3600 s; no health contract) | P (a1 → fabric-error; its intents are queued, not delivered) | P (l1 l2 l5: successes saved, INDEX.json graph hash `--verify`; verify not scheduled) | P (r1 retry budget + backoff, `retryOnFail` ×2; no breaker in-workflow; no runbook id) | P (s1 relay bearer, s2 allowlist, `callerPolicy` same owner; S5 fails) | n/a | 2.5 / 5 |
| 18 | tradeai-fabric-error | P (successes saved; m3 60 s; no contract) | **N** (self-referencing error workflow: its own failure alerts nothing; output queued only) | P (l1 l2; intent row with `routes_sha256`) | P (dedupe key + count; **R5 runbook id `n8n-workflow-error` — the first in the fleet**; `retryOnFail` ×2) | P (S5 fails) | n/a | 2.0 / 5 |
| | **Fleet (18)** | 0 Y / 13 P / 5 N | 0 Y / 10 P / 8 N | 0 Y / 18 P | 0 Y / 12 P / 6 N | 0 Y / 18 P | 0 Y / 1 P / 17 n/a | **36.0 / 91 = 40%** |

**Re-scored 2026-10-15 02:35Z (16 + 2 workflows, SELECT-only).** Rows 1–16 are unchanged against the new
measurement: settings, error-workflow wiring and executionTimeout are byte-for-byte what they were, and shadows 11
and 12 still fail on every fire (1 error each in 24 h). The 16-workflow score stays 31.5 / 81 = 39%. The two fabric
workflows add 4.5 / 10, and the fleet becomes **36.0 / 91 = 40%**. **No workflow is fully compliant in any area.**
What moved is the ceiling, not the score:

- **L1 (successes saved) passes for the first time**, on the 4 fabric workflows (per-workflow
  `saveDataSuccessExecution: all`). It still fails on the 16 legacy workflows (instance default `none`).
- **R5 (runbook id) passes for the first time**, on `tradeai-fabric-error`.
- **S5 (n8n DB role not superuser) still fails fleet-wide.** `pg_roles.rolsuper = t` for `n8n`, so Security is P
  everywhere.
- The Run Lane and error workflow now exist. Wiring the 16 legacy workflows to `tradeai-fabric-error` and calling
  Run Lane from the dispatcher is the largest single lift available: Alerting N→P on 6 rows and Recovery N→P on
  the 6 per-lane shadow rows (+6.0), about 40% → 46%.

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
  and the async run-outcome callback are LIVE (Build 1, #1739, served 5aa61048d; P1 proof 01:15Z).
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
| ~~Trading lock merged, not served~~ — **closed**: #1734 LIVE @5aa61048d, LOCKED | was CRITICAL | #1734 |
| CC auth report_only; operator packet not executed; `:8443` DOF still tailnet-served (→ `localhost:7776`, no auth) | HIGH | #1735 runtime; `tailscale serve status` 02:35Z |
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
| Release friction leaves money-risk fixes unserved; a containment fix applied in place inside a release directory | HIGH | WS8-04; §1 #1737 |
| Production executes the dev tree | HIGH | WS7-01 |
| Registry "live" ≠ runtime live (11 canary rows run dry) | HIGH | §2 |

## 6. Documented functionality that does not exist (or is not running)

1. **Release immutability.** The deploy runbook treats a release directory as immutable. On 10-14 at 18:11 ET, as
   deliberate incident containment, the operator ran a `config-write` grant script (grants `96a0ab8c`, `d3a80ca0`)
   that edited the served release's `config/health_agent_policy.json` in place to the #1737 content. The effect (no
   stop supervisor via remediation) went live at once. From 18:11 ET to 00:24Z, the served release identity
   (3e9dc5e14) did not describe the file that ran. Since 5aa61048d, served #1737 matches the file again (sha256
   equal to origin/main's). The finding is the mechanism, not the decision: there is no recorded,
   release-identity-preserving way to apply a containment change.
2. **Canary-live lanes** — 11 registry rows say `live`; they run `dry_run` (§2).
3. **Drift pages P1** (§23.23, ACTIVE since 10.0.0) and **the drift check** — the checker exists, is not scheduled, writes no
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
this refresh changes no finding status in FINDINGS.csv, so the baseline stands. The 02:35Z column is an estimate
from what is now served; it becomes a score when the review's findings are re-marked. The framework compliance
score is measured (§4).

| Dimension | 2026-10-14 (review baseline) | 2026-10-15 02:35Z (#1734, #1737, Builds 1+2 served; #1735 packet not run) | Target for the first n8n-owned process (§9 MUST done) |
|---|---:|---:|---:|
| Security | 2.9 | ~3.0 | ≥ 5.0 |
| Architecture (fitness to the n8n target) | 2.1 | ~2.4 (10.0.0 ratified, so the ~5.4 cap is lifted; Run Lane + error workflow + run outcomes + `/v1/llm_step` LIVE; 0 processes owned) | ≥ 5.0 |
| Operational readiness | 2.2 | ~2.3 | ≥ 5.0 |
| Technical debt (higher = less) | 5.9 | 5.9 | ≥ 6.5 |
| **Overall** | **2.9** | **~3.1** (0.30·3.0 + 0.25·2.4 + 0.30·2.3 + 0.15·5.9) | **≥ 5.0** |
| Framework compliance (§4) | **39%** (16 workflows, 0 compliant) | **40%** (18 workflows, 0 compliant) | 100% of active workflows, or archived |

## 9. Remaining work and next actions

**MUST, before any further migration (ordered; status 2026-10-15 02:35Z):**

1. ~~Promote `a1b1c5c93` (serves #1734 and #1737)~~ — **DONE**: 5aa61048d served at 00:24Z. Still to do: record
   the 18:11 containment edit in the release log. Next: promote #1741–#1744 (MERGED-NOT-SERVED) — owner: operator
   (release grant naming the SHA).
2. Execute the CC auth packet (`docs/ops/packets/cc-tailscale-identity-20261014/`) and flip `report_only` off —
   **NOT DONE**.
3. Reconcile live authority: one source for "live" (registry vs relay list vs allowlist `live_arg`); until then the
   registry rows of the 11 dry-running canary lanes say what they do (WS1-07) — **NOT DONE**.
4. Archive the three superseded shadow workflows (approved 10-10; one `cron` grant) — **NOT DONE**.
5. ~~Ratify 10.0.0~~ **DONE** (#1740). ~~Land Build 1 and Build 2~~ **DONE** (LIVE). Remaining: ratify or reject
   11.0.0 (§23.24); put `tradeai-fabric-error` on every workflow; apply the comms-intent consumer (#1744) so error
   intents reach the operator; build the framework check `scripts/check_n8n_workflow_framework.py` (PROPOSED in
   §23.24).
6. Host dead-man outside n8n and an off-box dead-man + second channel (WS1-15, WS3-18, WS3-20).
7. UPS and a cold-boot drill; first `trade_ai` restore drill (WS8-06, WS6-07).
8. Save successes with `run_id` custom data on the legacy 16 (the fabric pair already save); schedule the drift
   check with P1 on drift; n8n DB role non-superuser.
9. DeepSeek `/v1/llm_step` proof once upstream recovers and #1742 is served; #1745 OAuth fallback merged.

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
