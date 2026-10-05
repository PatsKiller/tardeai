<!-- Lifecycle fact base F — Engineering, runtime and operations. Re-measurement of LIFECYCLE_FACTBASE_F_ENGINEERING_2026-09-14.md. Read-only. -->

# Trade AI — Family F: Engineering, Runtime and Operations Lifecycles (re-measured 2026-10-04)

Status: ACTIVE
as_of: 2026-10-04T21:42:00-04:00
Measured at: 4f932b88a

Measurement: family F (ENGINEERING, RUNTIME AND OPERATIONS). Window: 2026-09-14 to 2026-10-04 21:42 ET.
Served SHA: `4f932b88a` (release `4f932b88a-main-exact-phase2-20261004-202102`, promoted 2026-10-05T00:22:09Z). Dev tree HEAD = `4f932b88a` = origin/main (`rev-list HEAD..origin/main` = 0), detached, `git status` clean.
Method: read-only. Postgres reads ran in a session with `transaction_read_only = on` (confirmed `on`). `check_lane_registry.py --json` and `check_test_coverage.py` were run in report mode. Nothing was restarted, written, pushed or POSTed, and no crontab was edited.
Labels: **MEASURED** means I ran the command and quote its output. **DOCUMENTED** means the claim comes from a commit message, code comment or memory note that I did not re-verify at runtime. **INFERRED** means I derived it from code or config. **BLOCKED** means it cannot be determined read-only.
Baseline: `docs/architecture/lifecycles/LIFECYCLE_FACTBASE_F_ENGINEERING_2026-09-14.md` (the same five lifecycles F1–F5 and the same anatomy (a)–(i)). Maturity uses the same scale: L0 exists · L1 runs + provenance · L2 grounded in prior state · L3 judged or validated · L4 loop closed · L5 unattended and reports its own decay.

---

## Headline deltas since 2026-09-14

| Area | 09-14 | 10-04 | Label |
|---|---|---|---|
| PRs merged (window) | 39 in 3.2 days | **408** merged since 09-14 (#1002–#1434, plus #162); **39 on 10-03/04 (#1395–#1434)** | MEASURED `gh pr list --search merged:>=2026-09-14` |
| Open→merge latency (PRs created ≥09-14) | median 14.4 min, p90 44 min | median **25.7 min**, p90 **233 min**, max 44 h | MEASURED |
| Required checks on main | `cio-hardening` only, strict, enforce_admins false | **`cio-hardening` + `agent-governance`**, strict false, 0 reviews, **enforce_admins true** | MEASURED `gh api …/branches/main/protection` |
| main CI state | green | **RED: 11 consecutive `cio-hardening` push failures since 2026-10-04 10:57Z**; ci-main-red issue #1251 (open since 09-26, 54 comments) | MEASURED |
| Promote gated on post-merge CI | no | **no**. All 5 promotes on 10-04 shipped SHAs whose push-to-main CI run failed | MEASURED |
| Release dirs / size | 56 dirs, 108 G | **9 dirs (8 exact-main + 1 legacy), 1.2 G** | MEASURED `ls`, `du` |
| Deploy receipt history | 1 file, overwritten; `source_pr: null` | **unchanged**: 1 file, `source_pr: null` | MEASURED |
| Release-write authorization | none | **release-grant binding** (grant must name the PR, SHA or campaign; fail closed), added 09-25 | MEASURED code `cio_phase2_exact_main_deploy.sh:521-535` |
| Dev-tree FF | manual, p90 lag 867 min | automatic in promote (#1025). **142 fast-forwards** since 09-14; dev tree = CURRENT | MEASURED reflog |
| Services re-bound at promote | portfolio-server + health agent | + **cio-governed-bridge + tradeai-cio-telegram**, with each unit's cwd read back | MEASURED code `:724-750`, `/proc/<pid>/cwd` |
| Cron execution root | dev tree (411 lines) | **CURRENT**: `PROJ=…/portfolio-server/CURRENT`; 0 job lines name the dev tree; interpreter `PY` = dev-tree `.venv` | MEASURED `crontab -l` |
| Guard approvals | `grants.json` `{}` | **160 APPROVED via Telegram button** in the 200-entry rolling `remote_requests.json` (09-27→10-05); median approval 8 s | MEASURED |
| AGENTS.md | 1.2.0 | **1.3.0 ACTIVE, effective 2026-09-27** | MEASURED `AGENTS.md:4-8` |
| Worktrees | 454 | **793** (0 prunable, 578 directly under `~`) | MEASURED |
| Health agent score | 70 (11 critical) | **82, 2 critical** (median 64 on 09-23..09-29) | MEASURED `health_agent.jsonl` |
| Remediation success | 0.62 % (7 d) | **1.5 %** (6,144 attempts, 95 ok, 09-27→10-05) | MEASURED |
| portfolio-server | 27 starts in 1.5 d | **275 starts since 09-15**; **65 unexplained self-exits since 09-28**, nearly all at a memory peak ≥1.5 G | MEASURED journal |
| Lane registry | 90 declared; SILENT 8, ORPHANED 2, UNVERIFIABLE 6; baseline 531 | **162 declared**; SILENT 23 (Sunday), ORPHANED 1, UNVERIFIABLE 10; baseline **517** | MEASURED |
| Test files run by CI | ≈378 references / 1,318 files | **770 of 1,696 (45.4 %)**; unlisted NEW 0 | MEASURED `check_test_coverage.py` |
| inotify failures | 20,723 in 7 d | 24,469 from 09-27 to 10-02; **0 since 2026-10-02 04:16** (limit still 65,536) | MEASURED journal |

---

# F1 · CHANGE LIFECYCLE (request → code → gates → PR → CI → merge → deploy → runtime → record)

## (a) Purpose, actors, stores
- **Purpose:** unchanged. Move an operator request into what executes on ms01, with evidence at each hop.
- **Actors:** operator (Telegram approval buttons for grants; release and push intent) · agent sessions (Claude and Cursor) · GitHub Actions (19 workflow files) · systemd and cron.
- **Stores:** git worktrees (793) · `<git-dir>/worktrees/*/tradeai-push-budget.json` (427 files) · `~/.cursor/approvals/grants.json` (one slot per tier, 9 tiers) and `remote_requests.json` (rolling 200 requests; schema includes `approved_by_chat`, `settled_via`, `code_sha256`) · GitHub PRs and runs · `ci-main-red` issue #1251 · `trade-ai-releases/portfolio-server/<sha>-main-exact-phase2-<ts>/` · `CURRENT`, `ACTIVE_RELEASE`, `EXPECTED_RELEASE` · drop-in `20-exact-sha-release.conf` · `~/.local/state/cio-phase2-exact-main/{state.env,deploy_receipt.json}` · dev-tree reflog · memory and `docs/` (MEASURED `ls`).

## (b) State machine: what changed
S0–S15 from 09-14 still hold. Changes:
- **S5 pre-push:** a git-push grant now authorizes only if its reason names the branch or a head-SHA prefix of ≥7 hex characters (`scripts/lib/guard_push_auth.py:57-77`, commit 6c7ddd219). The `TRADEAI_SKIP_SECRETS_SCAN` bypass is still present (`.githooks/pre-push:120`). MEASURED (code).
- **S7 CI:** `cio-hardening` now runs two profiles. On a pull request it runs the **PR profile**: smoke gates, the high-risk tiers the diff touches, and impacted tests; everything else is DEFERRED. On a push to main it runs the **FAST profile** (every registered gate). Nightly at 07:17 it runs the **full serial** profile. A red push run opens or updates the `ci-main-red` issue instead of blocking (`.github/workflows/cio-production-hardening-ci.yml:6-40`, `config/ci_risk_tiers.json`, `scripts/lib/test_impact.py`). MEASURED (code).
- **S9/S10 prepare/promote:** a `release_grant_preflight` step runs before both prepare and promote, fails closed, and can be set to warn with `TRADEAI_RELEASE_GRANT_BINDING=warn` (`:521-535, 550, 622`). A worker pin check runs in warn mode. A conformance gate on promote runs in warn mode (commit 3a9f6d284, DOCUMENTED).
- **S11 dev-tree FF:** done inside promote. A refused FF exits non-zero after PROMOTE OK (`:649-667`).
- **S13 other restarts:** `restart_root_frozen_units` now restarts `tradeai-health-agent`, `cio-governed-bridge` and `tradeai-cio-telegram`, then reads back each unit's `/proc/<pid>/cwd` (`:724-750`).
- **S10 receipt:** still one file, overwritten each time. `source_pr` is filled only from `CIO_SOURCE_PR`, which was unset at the last promote (`"source_pr": null`). MEASURED.

## (c) Flow (delta only)
```
 request ─(Telegram grant: reason names PR/SHA; 160 APPROVED)─▶ worktree (793) ─▶ code+tests (45% CI-run)
   ─▶ local acceptance ─▶ pre-push (grant must name branch/SHA) ─▶ PR
   ─▶ CI PR profile (median 6.4 min; defers non-impacted gates) ─▶ merge (2 required checks, admins enforced)
   ─▶ ┌ push-to-main FAST profile (median 12.8 min) ── red → issue #1251 comment ✗✗▶ does NOT gate promote
      └ prepare ─▶ release-grant binding ─▶ promote ─▶ health ok ─▶ restart 4 units + cwd readback
           ─▶ dev-tree FF (auto) ─▶ cron (CURRENT) ─▶ ✗ unit install (manual; 7 never installed)
```

## (d) Iterations (MEASURED)
| Loop | 10-04 measurement | Closes? |
|---|---|---|
| PR CI red → re-push | `cio-hardening` PR runs 09-30→10-05: 86 runs, **15 failed**, 3 cancelled (18 % of completed) | Yes |
| Post-merge red → fix | push runs: 58, **23 failed (48 % of completed)**, 10 cancelled. Red 09-30 14:39Z→10-01 08:05Z (13 failures), then **10-04 10:57Z → now (11 consecutive)** | **No**: main has stayed red for about 14 h; promotes continued |
| Push budget → override | 281 tranches with a push since 09-14: 133 at 1 push, 81 at 2, 28 at 3, **39 at ≥4** (24 % over the budget of 2); max 64 (`wt/offpeak-armed-docs`, 09-20) | Override counted, still reset per branch |
| Merge → promote → FF | 142 dev-tree FFs since 09-14 (09-27: 22; 10-04: 5) | Yes |
| Grant request → approval | 200 requests 09-27→10-05: release-write 105, git-push 49, service 17, cron 12, maintree 8; 160 APPROVED by `telegram_button`, 40 SUPERSEDED; latency median 8 s, p90 167 s | Yes; durable but rolling (INFERRED cap of 200 from an exact count of 200 and earliest entry 09-27) |

## (e) Questions and decision points
| Decision | 09-14 | 10-04 |
|---|---|---|
| Authorize push | env var or an unscoped grant; ledger `{}` | grant reason must name the branch or SHA; Telegram approval recorded (`approved_by_chat`, `settled_via`). MEASURED |
| Approve production deploy | chat only | **release-write grant naming the PR/SHA**, approved by Telegram (e.g. "Release 4f932b88a (PR 1433 …)"). MEASURED. The receipt still has `source_pr: null` and no approver field |
| Ship while main is red | not applicable | **Nobody decides.** Grant reason "Release PR 1432 once CI is green" was satisfied by the PR check, while the push-to-main FAST run for the promoted SHA failed 3 min after promote (00:22:09Z vs 00:25:48Z). MEASURED |
| Merge with 0 reviews | agent | still agent; `required_approving_review_count: 0`. MEASURED |

## (f) Live measurements

**PRs** (MEASURED)
- Created since 09-14: 436 (#998–#1434 range in the search); MERGED 411, CLOSED 18, OPEN 7. Open: #1330 (09-28), #1350/#1351/#1352 docs (09-29), #1373, #1378 (09-30), #1417 (10-03). Also open: #257 (07-30) and #133 (07-07).
- Merged per ET day: 09-20 **51**, 09-27 **52**, 09-19 26, 09-26 25, 10-03 26, 10-04 13; low 10-01 2, 10-02 5.
- Lines added (PRs created ≥09-14): 299,471. Largest: #1391 +13,735 (66 files), #998 +10,531, #1320 +10,398.
- Branches: 1,470 local, 1,195 remote.

**CI, runs created 2026-09-30T14:29Z → now** (1,000-run cap reached; MEASURED `gh run list`)

| Workflow | Runs | Median min | p90 | Max | Failures |
|---|---|---|---|---|---|
| cio-production-hardening-ci (required) | 148 | 7.3 (PR 6.4 · push 12.8 · nightly 24.1) | 14.0 (PR 8.0 · push 18.4) | 27.9 | **39** (PR 15 · push 23 · schedule 1); 13 cancelled |
| agent-governance (required) | 144 | 0.9 | 1.0 | 1.6 | 0 (15 cancelled) |
| provider-cost-ci / aif-fs-integration / release-readiness | 144 / 143 / 143 | 0.8 / 2.3 / 1.7 | – | – | 0 |
| options-lifecycle-ci | 103 | 1.3 | 1.4 | 2.5 | 2: frontend job, step "typecheck + design guard + build", on `wt/active-trader-live-alerts-ui-20261004` |
| research-governance | 58 | 0.7 | 0.9 | 1.3 | **8, all on `main` pushes**, step "PR scope guard" (a PR-only guard misfires on push) |
| active-trader-live-motion-ui-validation (`focused-playwright`) | 3 | 1.0 | 1.9 | 1.9 | 2: step "Build UI". Node 20 could not run the `.ts` unit tests in `npm run build`; moved to **Node 22** in 6f87baee3 (10-04). `cio-truth-gates-ui-validation` `focused-playwright` was already on Node 22 (21/21 green) |
| 5 others | ≤30 each | | | | 0 |

- PR-profile budget is 5 min wall clock (workflow comment, operator 09-25). Measured PR median 6.4 min, p90 8.0 min: **over budget**.
- **Failure mode on main right now** (MEASURED from the job log of run 37197075866, the first red run, and 37246791684, the current one): `[FAIL] alarm_fires` and `[FAIL] alarm_document_sites_20260922`, raised by `tests/test_alarm_coverage.py::test_no_file_gains_an_untested_alarm`: `scripts/active_trader/momentum_alerts.py: 1 untested send_telegram sites` and `scripts/lib/scalp_advisory_alert.py: 1 untested send_telegram sites`. The PR profile deferred this gate, so it first ran after merge. INFERRED source: #1424 scalp advisory (merged 06:49 ET) and #1431/#1432 Active Trader alerts.
- Earlier failure classes (DOCUMENTED in commits): `psycopg2` missing in CI (stand-in added, c8183b451); CRLF churn (788036394).

**Deploys** (MEASURED)
- Releases on disk: 8 exact-main (10-02 ×1, 10-03 ×2, 10-04 ×5) + 1 legacy (`448c3d3d-pr296…`); **1.2 G total** (was 108 G). Disk `/` 80 %, 90 G free (was 84 %).
- Current receipt: `ok true · mode promote · health ok · rolled_back false · deployed_sha 4f932b88a… · source_pr null · prev afae6a682 · at 2026-10-05T00:22:09Z`.
- **Promotes on red main (10-04):** 956cb4e5f (07:27 ET, push run failed) · b7d5a28f9 (08:47, failed) · c08323704 (10:51, failed) · afae6a682 (18:54, failed) · 4f932b88a (20:22, failed). 5 of 5.

**Runtime binding after the 20:21 promote** (MEASURED `ActiveEnterTimestamp` + `/proc/<pid>/cwd`)

| Unit | Started | Code root |
|---|---|---|
| portfolio-server, tradeai-health-agent, cio-governed-bridge, tradeai-cio-telegram | 10-04 20:21:56–20:22:06 | release 4f932b88a ✓ |
| tradeai-ops-agent | 09-18 03:46 | `~/.openclaw/skills/tradeai-health-inspect/scripts` (outside the release) |
| tradeai-active-trader-motion | 09-18 03:46 | `~/trade-ai-deployments/active-trader/306f81799…` (a separate pinned deployment) |
| grok-oauth-proxy, heartbeat-receiver | 09-12 17:02 (boot) | dev tree (= 4f932b88a on disk, but loaded 22 days ago) |
| chatgpt-oauth-proxy, openclaw-gateway | 09-12 / 09-30 | `~` |

- The research-lane-health checks `current-pin` and `process-freshness` are **ok** now. On 09-14 both were firing. MEASURED `research_lane_health.json`.
- Unit drift (`diff -rq config/systemd/user/* ~/.config/systemd/user/*`, 108 repo entries): SAME 86 · **DIFF 15** · **NOT_INSTALLED 7**, the same 7 as on 09-14 (`tradeai-cio-event-brief.{service,timer}`, `tradeai-cio-whatsapp.service`, `tradeai-memory-consolidator-shadow.service`, `tradeai-memory-shadow-project.service`, `tradeai-portfolio-report-ms.{service,timer}`).
- 60 installed `.service` files still set `WorkingDirectory` to the dev tree; 29 use CURRENT. MEASURED grep.

## (g) Failure paths now
1. **Promote is not gated on post-merge CI.** The PR profile defers gates, the push profile catches them after merge, and nothing connects that result to `promote`. Five red SHAs shipped on 10-04.
2. **main has been red for about 14 h** and alerts only through an issue that has 54 comments.
3. **No change identity yet.** The grant reason names the PR, but the receipt does not (`source_pr: null`). There is still one overwritten receipt, and the grant ledger is a rolling 200 entries.
4. **Unit install is still manual.** The same 7 units have never been installed, and 15 differ.
5. **Out-of-release runtimes:** the ops agent and the Active Trader motion service run code roots that promote never touches. Both started 09-18.
6. **Worktree sprawl grew 75 %** (454 → 793), with none pruned.
7. **Push budget is routinely exceeded:** 24 % of tranches, max 64.
8. **Secrets-scan bypass flag remains.** The repo is PUBLIC and requires 0 reviews.

## (h) Maturity per stage
| Stage | 09-14 | 10-04 | Evidence |
|---|---|---|---|
| S0 request | L0 | **L1** | Grant requests carry reason, PR or SHA, approver chat and time |
| S1 worktree | L1 | L1 | 793, never retired |
| S2–S3 code/tests/registration | L2 | L2 | CI-run share 45.4 %; 920 inherited unlisted |
| S4 local acceptance | L3 | L3 | Not re-measured in runs; script unchanged in role |
| S5 pre-push | L3 | L3 | Grant must name the branch or SHA; 24 % of tranches over budget |
| S6–S7 PR/CI | L3 | L3 | 2 required checks; PR profile over its 5-min budget; deferral lets red reach main |
| S8 merge | L1 | **L2** | enforce_admins on, 2 required checks |
| S9–S10 prepare/promote | L3 | L3 | Grant binding and health rollback, but promotes red SHAs; single receipt |
| S11 dev-tree FF | L1 (L4 after #1025) | **L4** | 142 auto FFs; tree = CURRENT |
| S12 unit install | L0 | L0 | 7 missing, 15 differ |
| S13 other restarts | L0 | **L2** | 4 units re-bound with cwd readback; 4+ runtimes outside |
| S14 verify | L4 | L4 | `current-pin` and `process-freshness` ok; ci-main-red issue |
| S15 record | L1 | L1 | 3 docs PRs open since 09-29 |

## (i) Target and exit conditions
| Exit | 09-14 | 10-04 |
|---|---|---|
| main = release = dev tree | MET | **MET** (4f932b88a ×3) |
| main CI green at the promoted SHA | not measured | **NOT MET** (red) |
| All running units on the current release | NOT MET (8) | **NOT MET** (ops agent, motion, 2 proxies, heartbeat-receiver) |
| Repo units = installed units | NOT MET (20/7) | **NOT MET** (15/7) |
| Deploy history durable, with `source_pr` + approver | NOT MET | **NOT MET** |
| Decisions auditable | NOT MET | **PARTIAL**: Telegram-approved grant ledger, but rolling |

---

# F2 · LLM CALL LIFECYCLE (partially re-measured)

## (a)–(c) Delta
- Global cap **$2.00/day** in `~/.config/tradeai/llm_global_daily_usd_cap.env` (MEASURED value). There are 74 `llm_process_config` rows (was 61). A new store, `llm_deferred_requests` (off-peak deferral), holds done 232 · failed 280 · expired 4 · pending 2 (MEASURED).
- Refusals (`COST_CAP_EXCEEDED`, `INPUT_LIMIT_EXCEEDED`) are **still in no table**. The `information_schema` search for refusal or admission tables returned none (MEASURED).

## (f) Measurements (MEASURED, `llm_consumption_log`, ET days)
| Day | Calls | Fail | Spend $ |
|---|---|---|---|
| 09-21 | 2,056 | 52 | 1.3674 |
| 09-22 | 1,781 | 63 | 1.1491 |
| 09-24 | 1,627 | 0 | 1.0425 |
| 09-27 | 1,433 | 1 | 0.4577 |
| 09-29 | 1,886 | 3 | 1.2770 |
| 10-01 | 1,371 | 10 | 0.7612 |
| 10-03 | 754 | 0 | 0.5262 |
| 10-04 | 656 | 0 | 0.4368 |

- 14 days, 09-21 → 10-04: max $1.37. **Spend stayed under the $2 cap every day.** The 09-14 exit "spend ≤ cap" is now MET against the $2 cap. The old $0.50 cap was replaced on 09-14.
- Reconcile: `latest_reconciliation.json` was rewritten on 10-04 06:40, but it shows `CONSOLE_TOTAL 60.94` and `residual_unattributable_usd 49.77`, **identical to 09-13**. INFERRED: the console export input has not been refreshed, so the daily run re-reports stale data.
- The research-lane-health checks `deepseek`, `grok`, `chatgpt` and `claude` are all ok. The 09-14 contradiction between the monitor and the ledger is gone (MEASURED).

## (h) Maturity
registry→DB L2 · admission L3 (refusals unrecorded) · reservation L2 · lane select L2 · call L1 · validate L3 · log L1 · reconcile **L3→L2** (stale input) · lane-health monitor **L2→L3** (agrees with ledger) · cap change L2. Not re-measured: reservation-vs-ledger parity, registry-vs-DB id drift, cap-change audit.

---

# F3 · SCHEDULED LANE AND SERVICE LIFECYCLES

## (a) Stores (delta)
`config/lane_registry.json` now has **162 lanes** and a 517-entry `undeclared_baseline`. There are **471** active crontab job lines (19 `RETIRED` tags), 92 timers, 25 running user services, 267 files in `~/.config/systemd/user`, 108 in `config/systemd/user`, and `expected_services.json` checks 60 units (MEASURED).

## (b)–(c) Delta
- **Install now has a grant path:** a `cron` guard tier is approved by Telegram (12 cron requests since 09-27), and the crontab is backed up before each edit (DOCUMENTED, memory 10-04: scalp cron installed under grant `c931…`, backup `~/crontab.backup.before-scalp-20261004`). Units are still installed by hand.
- Cron runs from CURRENT: `PROJ=~/trade-ai-releases/portfolio-server/CURRENT`. 312 lines use `$PROJ` and 155 name CURRENT explicitly. MEASURED.

## (f) Measurements (MEASURED)
| Metric | 09-14 | 10-04 |
|---|---|---|
| Declared | 90 (ACTIVE 58) | **162**: ACTIVE 123 · PAUSED 13 · NEVER_SCHEDULED 15 · RETIRED 11 |
| Undeclared beyond baseline | 0 | 0 (`check_lane_registry.py --json`, rc 0, errors []) |
| Baseline | 531 | **517** (−14) |
| Verdicts (RLH 2026-10-05T01:09Z, Sunday) | LIVE 39 · SILENT 8 · SLOW 3 · ORPHANED 2 · UNVERIFIABLE 6 | LIVE 86 · EXPECTED_SILENT 39 · **SILENT 23** · SLOW 3 · **UNVERIFIABLE 10** · ORPHANED 1 |
| `unknown_reason_lanes` | 3 | 3 (deep-overnight-llm, overnight-batch, cio-decision-engine) |
| Expected services | 65 checked, 0 off | **60 checked, 2 off**: `DISABLED:tradeai-due-checkpoints.timer`, `DISABLED:tradeai-iris-taxonomy.timer` |

- **Why SILENT is 23:** about 16 of them are weekday-only (`* * 1-5`) crons judged on a Sunday at ~50–63 h. The weekday is still evaluated in UTC (unchanged; INFERRED from the 09-14 code reference). Real silences (ages are MEASURED): `platform-conformance-audit` 169 h (daily), `approval-package-reminder` 142 h (hourly), `cio-stance-classification-drain` 97.8 h (missed Thu and Fri), `commitment-outcome-sweep` 50.8 h (daily), `resolve-due-checkpoints` 4.8 h (hourly; its timer is DISABLED per expected-services).
- ORPHANED: `alert-quality`. Its registry row exists (#1426) but there is no matching scheduler entry. UNVERIFIABLE (no output signal): 10, including `db-retention`, `disk-hygiene-enforcer`, `due-diligence-questions`, `material-change-digest`.
- RLH `lane-registry` alert is `suppressed: true` (signature `ORPHANED,SILENT`).
- Failed user units: `tradeai-advisory-shadow-session.service` and `mcporter-token-refresh.service` (plus 4 desktop units).

## (g) Failure paths
1. The UTC and weekday evaluation still floods SILENT on weekends, which hides the 5 real silences.
2. Expected services found 2 disabled timers; one of them backs a registry lane that is now SILENT.
3. The lane-registry alert is suppressed while real findings exist.
4. UNVERIFIABLE grew from 6 to 10.

## (h) Maturity
propose **L0→L1** (Telegram cron grant) · declare **L2→L3** (162 rows, gate in CI) · install **L0→L1** (cron under grant with backup; units manual) · evaluate L4 · drift L2 · pause/retire L2 · baseline shrink **L1→L2** (−14) · service detect L4 · service run **L2→L3** (Restart=always; no inotify failures since 10-02) · restart **L1→L2**.

## (i) Exit
| Exit | 10-04 |
|---|---|
| SILENT+ORPHANED = 0 real | NOT MET (≥5 real + 1 orphan) |
| UNVERIFIABLE = 0 | NOT MET (10) |
| baseline shrinking | MET (531→517) |
| expected ⊇ critical units | NOT MET (2 off; portfolio-server/bridge coverage not re-checked) |

---

# F4 · FINDING / INCIDENT LIFECYCLE

## (b) Stores and states (MEASURED, read-only SQL and files)
| Store | 09-14 | 10-04 |
|---|---|---|
| `alert_incidents` | 0 rows | **108, all `open`** (first_seen 09-16 → last_seen 10-04; job_telemetry 74, paper_proposal 8, scanner_candidate 6); acknowledged 0, resolved 0 |
| `alert_events` | active 7,845 · resolved 0 | active **9,066** · acknowledged 42 · **resolved 533** (09-20 → 10-04) |
| `escalation_queue` | pending 13 (oldest 08-28) · expired 21 | pending **17** (oldest 09-21) · expired 15 |
| `hermes_validation_findings` open | 191 | **261** |
| `pipeline_runs` 7 d failed | 224 / 3,559 (6.3 %) | **140 / 4,329 (3.2 %)** |
| `health_manual_remediation_audit` | 49, last 08-31 | 49, last 08-31 (unchanged) |

## (f) Health agent and remediation (MEASURED)
- Score per ET day (from `health_agent.jsonl`): median 70 on 09-14..09-19 · **64 on 09-23..09-29** · 78 on 09-30 · 74 on 10-01 · 78 on 10-02 · 69 on 10-03 · **82 on 10-04**. Latest (01:18Z): **82 "degraded"**, 2 critical (`pipeline_failures`: 6 in 24 h, CIRCUIT_OPEN; `broker_proposals_unrouted`: 9 >48 h), 14 warning, 27 info. `rescored_after_remediation: false`.
- **make_interval fix (#1427, merged 10-04 08:15, live b7d5a28f9 08:47):** the float `ENSEMBLE_STALL_HOURS` raised `function make_interval(hours => numeric) does not exist` on every run (17 errors in 400 log lines). The log-error check escalated that to the last remaining critical (DOCUMENTED, commit message). The score was 82–86 for the rest of 10-04 (MEASURED).
- Remediation 09-27 → 10-05: **6,144 attempts, 95 ok (1.5 %)**. Daily success 0.0–3.3 %. Top attempted: approved_paper_test_stuck 2,555 · pipeline_failures 1,689 · data_source_stale 1,286. Top successes: options_proposals_stale 26 · pipeline_failures 23 · synthesis_processing_stuck 16.
- Ops agent: `"band": "critical"` on **5,609** journal lines since 09-27, still running 09-18 code (MEASURED).

## (h) Maturity
detect L4 · alert/suppress L3 · auto-remediate L2 (1.5 %) · triage L1 (escalations 17 pending, 0 incidents acknowledged) · fix PR L3 · verify L3 · close **L0→L1** (533 alert events resolved; incidents populated but never closed).

## (i) Exit
| Exit | 10-04 |
|---|---|
| incidents table populated | **MET** (108) |
| open critical with owner | NOT MET (0 acknowledged) |
| remediation >50 % or disabled | NOT MET (1.5 %) |
| escalations reviewed before expiry | NOT MET |

---

# F5 · SECRETS, BACKUP AND HOST (plus portfolio-server stability)

## (f) Measurements (MEASURED unless labeled)
| Metric | 09-14 | 10-04 |
|---|---|---|
| SM keys / rendered | 126 / 117 | **128 / 118**; last ok 2026-10-05T00:22:03Z (at promote); last_error 2026-10-03T20:28:56Z |
| Retired-provider keys still rendered | 4 | **4** (FINNHUB, FMP, NEWSAPI, POLYGON key names present) |
| Rotation daemon | unscheduled | **unscheduled** (no crontab line, no unit) |
| Restore drills | 0 | **0** (`report_backup_readiness.py:86` `scores["restore_drill"] = 0  # Not yet implemented`) |
| Daily DB dump | 3.3 GB, same disk | `trade_ai_20261004_023000.sql.gz` 2.97 GB, same disk |
| backup_verify (monthly) | 09-01: 1 FAIL | **10-01: 1 FAIL**: `backup_dir: Backup directory not found: …/portfolio-server/f73d8c6bb-main…`. It points into a pruned release dir (path defect) |
| Uptime / hard cuts | 1 d 7 h; 4 hard cuts 08-21→09-11 | **22 d 4 h since 09-12 17:02**, no boot in window (boot-order fix still unproven) |
| Memory | – | 61 G RAM, 33 G available; **swap 7/7 G used** |
| inotify (`max_user_watches` 65,536, unchanged) | 20,723 / 7 d | 09-27 4,054 · 09-28 3,735 · 09-29 6,076 · 09-30 3,427 · 10-01 5,569 · 10-02 1,608 · **0 after 10-02 04:16** (cause of stop BLOCKED) |
| Postgres idle-in-txn kills/day | 70–180 | 09-27 98 · 09-30 103 · 10-03 52 · 10-04 39 |

**portfolio-server stability** (MEASURED `journalctl --user -u portfolio-server`, `systemctl show`)
- Unit: `Restart=always` (drop-in, added 09-28 after 3 silent deaths; DOCUMENTED memory), `RestartSec=5`, **`MemoryHigh=1.5G`, `MemoryMax=2G`**. `NRestarts=0` now, because the counter resets at each promote restart. Started 20:21:56. RSS 773 MB at 36 min, MemoryPeak 1.14 G.
- Starts per ET day: 09-27 33 · 09-28 23 · 09-29 25 · **09-30 50** · 10-01 6 · 10-02 15 · 10-03 8 · 10-04 8. That is 275 starts from 09-15 to 10-04.
- **Unexplained self-exits** (a `Scheduled restart job` with no preceding `Stopping` line): 09-28 7 · 09-29 8 · **09-30 33** · 10-01 4 · 10-02 9 · 10-03 3 · 10-04 1 = **65**. Exits whose `Consumed …` line shows a memory peak ≥1.5 G: 09-22 onward, 104 in total (09-30: 37). Each exit is logged with no exit status. The memory note for 10-04 records "status 0 = SIGINT path, 09:30:53 at 1.7 GB, cause UNKNOWN" (DOCUMENTED). INFERRED: exits cluster at the MemoryHigh reclaim threshold, but nothing logs the actor or the signal.
- `portfolio_server.log` has 0 `SIGINT` strings, so the shutdown path does not log.

## (h) Maturity
render L4 · consume L3 · rotate L0 · retire L0 · daily backup L4 · off-site L3 (not re-measured) · retention **L3→L4** (108 G → 1.2 G; legacy dirs pruned) · verify L2 (FAIL from a stale path) · restore drill L0 · power detect L1 · boot recovery L2 (unproven; no boot) · resource limits L1 (swap full; inotify quiet) · **API process stability L2** (new row: auto-restart in 5 s, cause of exits unknown).

---

# Family maturity score

Method: the mean of the per-stage levels in each lifecycle, then the mean of the five lifecycles. The 09-14 documents gave no numeric family score, so the baseline is **derived** from the 09-14 per-stage tables using the same method.

| Lifecycle | 09-14 (derived) | 10-04 |
|---|---|---|
| F1 Change | 1.92 | **2.23** |
| F2 LLM call | 2.10 | 2.20 |
| F3 Lane/service | 1.80 | **2.40** |
| F4 Finding | 2.29 | 2.43 |
| F5 Secrets/backup/host | 1.92 | 2.08 |
| **Family F** | **2.0 / 5** | **2.3 / 5** |

Improved: dev-tree FF, release retention, grant authority bound to PR/SHA with Telegram approval, lane declaration (162), restart binding, health score 64 → 82. Not moved: unit install, change identity, restore drill, rotation, incident closure. One regression in practice: CI deferral plus ungated promote put 5 red SHAs live in one day.

## Top 5 risks
1. **Red code ships.** Post-merge `cio-hardening` has been red for 11 consecutive runs since 10-04 10:57Z, and promote does not read it. All 5 of 10-04's releases went live red (untested `send_telegram` alarm sites in Active Trader and scalp advisory alerts that go live to Telegram on 10-05).
2. **API process instability with no cause.** 65 unexplained self-exits since 09-28 at a ~1.5–1.7 G peak against MemoryHigh 1.5 G. Swap is 100 % used. `NRestarts` resets each promote, so the count is invisible on the unit.
3. **Runtime outside the release.** The ops agent (critical every cycle) and the Active Trader motion service run code from 09-18 in separate roots. Proxies and heartbeat-receiver have been loaded since 09-12. 7 repo units have never been installed and 15 differ.
4. **No restore ever tested and no secret rotation.** The repo is PUBLIC, 4 retired keys are still rendered, the DB dump sits on the same disk, and the monthly verify fails on a stale path.
5. **Findings without owners.** 108 open incidents with 0 acknowledged, 17 escalations pending, remediation success 1.5 %, and the lane-registry alert is suppressed while 5 real lanes are silent.

## Top 5 recommendations
1. **Gate promote on post-merge CI.** Have `cio_phase2_exact_main_deploy.sh promote` refuse a SHA whose push-to-main `cio-hardening` run is not `success` (warn mode first). Also run the alarm-coverage gate in the PR profile whenever a diff adds a `send_telegram` site. Fix the current red: add firing tests for `momentum_alerts.py` and `scalp_advisory_alert.py`.
2. **Make deploy history durable and joined.** Append each receipt to `deploy_receipts.jsonl` with `source_pr` (taken from `TRADEAI_RELEASE_PR` or the grant), the grant `request_id`, the approver and the CI run id. Archive the rolling `remote_requests.json` rather than trimming it.
3. **Instrument the portfolio-server exits.** Log signal, exit status and RSS on shutdown. Alert on more than N `Scheduled restart` in 24 h. Decide between raising MemoryHigh and fixing the peak; the 10-03 `/v3/cio/home` halving is the precedent.
4. **Bring every runtime under the release.** Have the deploy diff and install `config/systemd/user` (or retire the 7 never-installed units), and re-bind the ops agent, the motion service and the proxies, or declare them out-of-release in `expected_services.json` with a reason.
5. **Close the ops loops.** Evaluate lane weekdays in the declared TZ. Un-suppress lane-registry when real (non-weekday) silences exist. Re-enable or retire the 2 disabled timers. Route the monthly backup-verify FAIL as IMMEDIATE and fix its path. Schedule one restore drill and the rotation daemon (operator decisions, §17). Prune merged worktrees (793).

Not done (by rule or BLOCKED): deploy, acceptance and push were not run. The logs of 9 failed main runs between 10-04 11:23Z and 23:09Z could not be retrieved through `--log-failed`; job/step names were read for 3 of them, and the job log for 2 (the first and the latest). The actor behind the portfolio-server self-exits is unknown. The reason inotify failures stopped after 10-02 is unknown. F2 reservation and registry parity and F5 off-site stamps were not re-measured.
