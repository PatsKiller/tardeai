# n8n fabric program — WHAT'S DONE / WHAT'S LEFT (2026-10-15)

```
Status:      ACTIVE (dated tracker; supersedes the status lines of ~/N8N_PROGRAM_BOARD.md as of this time)
as_of:       2026-10-15T02:35:00Z (2026-10-14 22:35 ET)
Measured at: served 5aa61048d (GET 127.0.0.1:7777/v3/build-meta.json git_sha 5aa61048de4a…, CURRENT ->
             5aa61048d-main-exact-phase2-20261014-191424, live since 00:24Z); origin/main 57d8fc3ff;
             n8n 2.43.0 DB (SELECT only); coordination ledger (sqlite mode=ro); crontab sha256 69d544ef…
Owner:       Agent A (program supervisor); operator decides every operator-only item (AGENTS.md §17)
Policy:      AGENTS.md 10.0.0 ACTIVE (#1740; ratified by PR comment 2026-10-14T23:25:56Z). 11.0.0 (§23.24,
             mandatory workflow framework) PROPOSED on branch docs/platform-docs-refresh-20261014 (not pushed).
```

Status labels (defined in
[`N8N_GAP_ASSESSMENT_AND_MATURITY_REVIEW_20261014.md`](N8N_GAP_ASSESSMENT_AND_MATURITY_REVIEW_20261014.md) §0):
**LIVE @sha** · **MERGED-NOT-SERVED** · **PR-OPEN** · **BRANCH-ONLY** · **PLANNED** · **POLICY-ONLY**. "LIVE
(code), OFF (runtime)" means the served code has it and the runtime has it switched off. Every row was re-checked
against the runtime at the time above. The re-check commands are in §4.

## 1. Program rules in force

- **Timer-only cutover freeze (AGENTS.md §23.23 "Migration rule" (1)).** Timer-only leaf-lane cutovers are FROZEN
  until three things exist: the Run Lane sub-workflow, the async run-outcome callback, and 10.0.0 ACTIVE.
  **On 2026-10-15 all three are met.** The Run Lane workflow is LIVE: published, and its P1 end-to-end proof
  passed at 01:15Z. Run outcomes are LIVE: the `run_outcomes` table, gateway op `coordination/run_outcome` and
  relay `GET /run_outcome`. 10.0.0 is ACTIVE. One difference from the text: the callback is `GET /run_outcome`,
  not `GET /runs/{run_id}`. **The freeze stays in force until the operator says it is lifted.** Lifting it does
  not mean timer-only lanes resume being counted.
- **Success metric (§23.23 (2)): business processes owned by n8n, and orchestration owners retired. Lanes moved
  do not count.** Today the count is **0 processes owned**. The first candidate is the hermes learning process,
  PR-OPEN #1746 (row 21). It is inactive, with 3 of 7 steps shadow-ready.
- **Consolidate before migrating (§23.23 (3)):** a WS2 family is folded on the host first, then moved as one
  process.
- **Cutover standard:** §23.21. It lives in 8.0.0 on PR #1727, which is still open, so the cutover rules already
  in force apply: fix, dry run, regression tests and at least one live n8n run. There are no soaks.

## 2. The tracker

| # | Item | Status | Evidence | Owner | Next action |
|---|---|---|---|---|---|
| 1 | Served release | **LIVE @5aa61048d** (since 00:24Z 10-15) | build-meta `git_sha 5aa61048de4a…`; CURRENT → `5aa61048d-main-exact-phase2-20261014-191424` | operator (release grant) | next release carries #1740–#1744 (rows 7, 13–16) |
| 2 | #1732 stop alerts never digest | **LIVE @5aa61048d** | `telegram_alert_router._STOP_FIRING_PATTERN` → P0_INTERRUPT before the v2 router | — | none |
| 3 | #1733 Schwab paused → fail loud | **LIVE @5aa61048d** | `config/schwab_access_mode.yaml` `mode: forbidden` | — | none while paused |
| 4 | #1734 read-only trading lock | **LIVE @5aa61048d, LOCKED** | `trading_lock.status()` → `locked: true`, "no operator unlock file (default: locked)"; `~/.config/tradeai/trading_unlock.json` absent | operator (unlock file only) | stays locked until R6 (row 31) |
| 5 | #1735 CC Tailscale identity auth | **LIVE (code), report_only (runtime)** | `config/cc_auth.yaml` `enforce: true`, `report_only: true`. Secret writes 403; 42 step-up routes refused. 18,208 `would_deny` lines in `~/.local/state/tradeai/cc_auth_decisions.jsonl`. `tailscale serve` `/` → `http://localhost:7777` (not the unix socket) | operator | run the packet (row 22) |
| 6 | #1737 health agent: no broker remediation | **LIVE @5aa61048d** | served `config/health_agent_policy.json` = merged content. The 18:11 ET in-place containment edit is now superseded by a release | — | record the in-place edit in the release log (gap assessment §6.1) |
| 7 | AGENTS.md 10.0.0 (§23.23 n8n = automation fabric) | **ACTIVE** (#1740 merged `543c39a9e`; PR comment from PatsKiller 2026-10-14T23:25:56Z) | AGENTS.md header `Policy-Version: 10.0.0`, `Status: ACTIVE` | — | none |
| 8 | AGENTS.md 11.0.0 (§23.24 mandatory workflow framework) | **BRANCH-ONLY** (PROPOSED text; branch `docs/platform-docs-refresh-20261014`, not pushed) | `tests/test_agents_policy_11_0_0_workflow_framework.py` | operator ratifies; agent opens the PR | push + PR (row 34), then `APPROVE_AGENTS_POLICY_11_0_0 <pr> <sha>` |
| 9 | Build 2: bridge OAuth transports + `/v1/llm_step` (#1738) | **LIVE @5aa61048d, ON (grok, chatgpt)** | drop-in `cio-governed-bridge.service.d/60-oauth-transports-20261014.conf` sets `CIO_BRIDGE_OAUTH_TRANSPORTS=grok,chatgpt` (unit active since 01:26:56Z). Probes PASS: grok `grok-3-mini` 8.8 s, chatgpt `gpt-6.1-sol` 5.5 s, each with an `LlmStepAudit` row | — | DeepSeek proof (row 23) |
| 10 | Build 1: fabric primitives (#1739) | **LIVE @5aa61048d** | n8n `workflow_entity`: `tradeai-fabric-run-lane` and `tradeai-fabric-error` active + published (`activeVersionId` set); the two probes inactive. **18 active workflows** | — | put the error workflow on the 16 legacy workflows (gap assessment §9) |
| 11 | P1 proof: Run Lane end to end | **PASS 01:15Z** | n8n execution: probe `success` (cli) + run-lane `success` (integrated) 01:15:06–01:15:12Z. Ledger `run_outcomes` `fabric-probe-25869-20261014211506` lane `crontab-snapshot-for-health-agent` dry_run `RUN_DONE` | — | none |
| 12 | P2 proof: automatic failure → error workflow → comms/intent | **PASS 01:37Z** | probe `error` (trigger) 01:37:00Z → `tradeai-fabric-error` `success` (mode error). Ledger `comms_intents` `ci-2a845bc6aa846e66525eb957` `QUEUED`, tier DIGEST, runbook `n8n-workflow-error` | — | the consumer delivers it (row 15) |
| 13 | #1741 probe CLI-executable (Manual Trigger; packet `--reimport`; CLI `N8N_RUNNERS_BROKER_PORT=5690`) | **MERGED-NOT-SERVED** (`6182aa824`); the workflow JSON it generates is the imported probe | the n8n 2.43 facts are in `N8N_CONFIGURATION.md` §3.4 | — | ships with the next release |
| 14 | #1742 bridge hard deadline, typed read timeouts, stall breaker, provider-health stall alarm (P1 when a process has no lane left) | **MERGED-NOT-SERVED** (`5af2f4098`) | `git merge-base --is-ancestor 74afc518f 5aa61048d` → false | operator (release grant) | promote, then re-run the DeepSeek proof |
| 15 | #1743 provider-journal OOM fix (latest() reverse scan, peak 449.6 MB → 3.3 MB) + rotation CLI (unscheduled) | **MERGED-NOT-SERVED** (`bff79bbad`) | `f52420e54` declares `cio_provider_journal_rotate` unscheduled | operator (release) + agent (rotation packet) | row 24 |
| 16 | #1744 comms-intent consumer → incident fan-in, P2 digest | **MERGED-NOT-SERVED** (`57d8fc3ff`); not applied | ledger `comms_intents`: 1 row, `QUEUED`. Packet `docs/ops/packets/n8n-comms-intent-consumer-20261015/` | operator (`--apply` grant) | row 25 |
| 17 | #1745 OAuth fallback (deepseek → grok → chatgpt) for `cio_hermes_research`, `cio_plan_enrichment`, `hermes_cloud_json` | **PR-OPEN #1745**, head `67168ec39`, CI green (22 success, 2 skipped). Operator decision "yes" ~02:10Z | `gh pr view 1745` | agent merges under the operator's yes; operator promotes | merge, then the next release |
| 18 | Canary double-effect audit | **DONE** (read-only) | `~/n8n-maturity-verification/arch-review-20261014/CANARY_DOUBLE_EFFECT_AUDIT.md`: no lane double-runs today; 11 of 13 registry "live" canary rows actually run `dry_run` (relay live list has 7 lanes) | agent | registry and relay agree on "live" (WS1-07) |
| 19 | DeepSeek `/v1/llm_step` stall diagnosis | **DONE** (read-only) | `~/n8n-maturity-verification/arch-review-20261014/DEEPSEEK_LLM_STEP_STALL.md`: upstream stall from 00:33Z, not llm_step; deadline bug + `ConnectionError`-not-`Timeout` bug → fixed by #1742 | — | row 23 |
| 20 | Architecture review | **DONE**: overall 2.9/10, 168 findings | `~/n8n-maturity-verification/arch-review-20261014/ARCHITECTURE_REVIEW_20261014/` (`SCORES.md`, `FINDINGS.csv`) | — | re-score after the MUST list (gap assessment §9) |
| 21 | Hermes learning flow (learn → tune): the first business process on the fabric | **PR-OPEN #1746** (opened 02:36Z, head `732309942`, CI not reported yet); inactive; 3 of 7 steps shadow-ready; companion branch `n8nfab/hermes-learning-unblock-20261015` **BRANCH-ONLY** | `gh pr view 1746` | agent builds; operator imports (inactive) | review → merge → import inactive → **shadow** (row 32) |
| 22 | CC auth operator packet run | **NOT DONE** | `docs/ops/packets/cc-tailscale-identity-20261014/`; no service token file; serve → `localhost:7777` | operator | run the packet, then flip `report_only: false` |
| 23 | DeepSeek proof (`/v1/llm_step` via DeepSeek) | **UNPROVEN**: DeepSeek degraded upstream since ~00:33Z (timeouts, 503s); balance $75 | `DEEPSEEK_LLM_STEP_STALL.md` | agent (probe), once upstream recovers and #1742 is served | re-run the Build 2 DeepSeek probe |
| 24 | Provider-journal rotation | **NOT SCHEDULED** (CLI in #1743, not served) | `f52420e54` | operator (cron/timer grant) | serve #1743; one rotation dry run, then decide on a schedule |
| 25 | Comms-intent consumer `--apply` | **NOT DONE** | 1 QUEUED intent; consumer MERGED-NOT-SERVED | operator (grant) | after the release: dry run (expected incident `wferr:tradeai-fabric-error-probe` P2), then `--apply` |
| 26 | Key rotations | **DECLINED for now** (operator, 10-14) | `docs/runbooks/KEY_ROTATION.md`; findings WS4-05 (keys in logs), keys in git history | operator | operator to revisit; agents never read or copy credentials (§24.7) |
| 27 | Leftover SPCX stops at Schwab | **UNVERIFIED**: the rollover IRA had 5 SPCX stops (~1,900 sh against ~600 held) | incident record [`docs/incidents/INCIDENT_20261014_SPCX_RESTING_STOPS.md`](../../incidents/INCIDENT_20261014_SPCX_RESTING_STOPS.md) | operator (Schwab app / website; the API is off) | check working orders in every Schwab account, cancel leftovers, record the result in the incident |
| 28 | `BROKER_LIVE_ENABLED` env removal | **NOT DONE**: still set | pilot status `env_BROKER_LIVE_ENABLED: true` (`db_control_broker_live_enabled: false`); the name is in `/run/user/1000/tradeai/env` (rendered EnvironmentFile), not in a unit drop-in | operator (config-write) | remove it at its source (the secrets render), restart on the next promote |
| 29 | DOF `:8443` auth | **NOT DONE** | `tailscale serve status`: `:8443` `/` → `http://localhost:7776`, tailnet-only, no app auth (S2 finding) | operator | add auth or stop the `:8443` serve |
| 30 | UPS | **NOT DONE** (CRITICAL; 4 hard power cuts; the n8n stack has never cold-booted) | WS8-06; `~/power-watch/README.md` | operator (hardware) | buy and fit a UPS, then a cold-boot drill |
| 31 | uid separation (exec uid for broker writes, unlock-file ownership) | **PLANNED** | WS4-01; WS10 R1.2 | operator + agent | design in R1 before Schwab re-enable |
| 32 | Schwab re-enable R0–R6 | **R0 holding; R1–R6 PLANNED** | `~/n8n-maturity-verification/arch-review-20261014/WS10_SCHWAB_INTEGRATION.md` §R0–R6. R0.1 held: app off, kill switch `global` ON since 16:03:44 ET. R0.2 done (#1732, #1733 LIVE). R0.3 done: 15 lines `# PAUSED 2026-10-14 schwab-app-deactivated (incident SPCX)`; 3 Schwab lines remain active and are gated by `mode: forbidden`. R0.4 partly done (#1735 report_only). R0.5 open (row 28) | operator gates every phase; agent builds R1 code | finish R0.4/R0.5, then R1 (lock coverage, token getter, access-mode default) |
| 33 | Hermes flow shadow | **PLANNED** (depends on row 21) | — | operator (import + activation grant) | import inactive, run the shadow proof, count it as the first process owned |
| 34 | 11.0.0 ratification | **NOT STARTED** (text on this branch) | row 8 | operator | `APPROVE_AGENTS_POLICY_11_0_0 <pr> <head_sha>` on the PR |
| 35 | Docs-refresh PR (this branch) | **BRANCH-ONLY** (`docs/platform-docs-refresh-20261014`, rebased onto origin/main 57d8fc3ff, not pushed) | `git log origin/main..docs/platform-docs-refresh-20261014` | agent pushes when asked; operator reviews | push + open the PR |
| 36 | coder_dispatch autolaunch cron (L558) | **PAUSED** (WS7-02, grant `a67b8f21`) | crontab line 558 `# PAUSED 2026-10-14 WS7-02 coder-agent autolaunch`; crontab sha256 `69d544ef…` | operator | stays paused until agent boundaries (WS7) land |
| 37 | Pilot / write switches | **DISARMED** | pilot status `armed: false`; `api_write_enabled` false on all 3 Schwab accounts; `canary_session_date: 2099-12-31` | operator | stays disarmed until R6 |
| 38 | Vite preview servers | **STOPPED** (10-14) | — | — | none |
| 39 | Archive the three superseded shadow workflows (approved 10-10) | **NOT DONE**: `catalyst-calibration-monitor-shadow` and `watch-directives-monitor-shadow` still fail on every fire | n8n `execution_entity` errors (24 h) | operator (`cron` grant) | apply the archive packet |
| 40 | n8n drift check scheduled + P1 on drift | **POLICY-ONLY** (checker exists: 18/18 OK at 02:35Z, dry run; no receipt, no timer) | `python3 scripts/check_n8n_workflow_drift.py --dry-run` | agent (PR) + operator (timer grant) | schedule it |

## 3. Counts

- **Processes owned by n8n: 0.** Hermes learning is the first candidate (rows 21 and 33).
- **Active n8n workflows: 18.** These are the 6 generic `tradeai-*` workflows, 10 per-lane workflows, and 2 fabric
  workflows (run-lane, error). There are 48 stored workflows. The two fabric probes are inactive.
- **Framework compliance** (§23.24, PROPOSED): **36.0 / 91 = 40%**. No workflow is compliant in every area.
  Rescored in the gap assessment §4.
- **Ledger, last 24 h:** live 933 RUN_DONE, 1 RUN_FAILED, 1 RUNNING; dry_run 1,370 RUN_DONE. Dead letters 48,
  breakers 6.

## 4. Re-check (read-only)

```bash
curl -s 127.0.0.1:7777/v3/build-meta.json | grep git_sha
docker exec m8m-n8n-db psql -U n8n -d n8n -At -c "select id,active,\"activeVersionId\" is not null from workflow_entity where id like 'tradeai-fabric%'"
docker exec m8m-n8n-db psql -U n8n -d n8n -At -c "select count(*) from workflow_entity where active"
docker exec m8m-n8n-db psql -U n8n -d n8n -At -c "select \"workflowId\",status,mode,\"startedAt\" from execution_entity where \"workflowId\" like 'tradeai-fabric%' order by id"
python3 - <<'EOF'
import sqlite3
c = sqlite3.connect('file:/home/johnclaw/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite?mode=ro', uri=True)
print(c.execute("select intent_id,state,tier from comms_intents").fetchall())
print(c.execute("select run_id,run_state from run_outcomes where run_id like 'fabric-probe-%'").fetchall())
EOF
curl -s 127.0.0.1:7777/api/v2/execution/kill-switches | head -c 400
curl -s 127.0.0.1:7777/api/v2/broker-orders/pilot/status | head -c 600
gh pr view 1745 --json state,headRefOid; gh pr view 1746 --json state,headRefOid
tailscale serve status
```
