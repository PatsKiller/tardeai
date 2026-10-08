# Review of "Design Review and Architecture Assessment by Codex" (7–8 Oct 2026)

**Reviewer:** Claude Code (this session). **Reviewed artifact:** the Codex assessment emailed 2026-10-07 23:37 ET (813 scheduler records, 646 service entries, 63 process assessments, appendices A–F). **Evidence basis for this review:** live host checks run 2026-10-07 ~23:50 ET against the served release `ebda6ab2a`, plus the registry in that release. **Status:** PROPOSAL. Nothing in this document changes production.

## 1. Verdict

I agree with the Codex assessment on its facts and on its authority boundaries. I disagree with it on two points that matter to the operator:

1. **Timeline.** Codex places the coordination plane in 0–30 days and consolidation in 30–90. The operator's standing instruction is "implement and test this week". Codex itself concedes the roadmap "does not cancel or silently replace an already approved execution schedule" (§14). The approved execution-week packet (`14-execution-week-20261008.md`) governs; the Codex horizons are advisory.
2. **Ambition.** Codex recommends n8n for "coordination, receipt tracking, incident correlation and selected low-frequency workflows" and leaves every schedule in cron. That is also what my own blueprint (`11-target-state-blueprint-20261007.md`) did. The operator is right that both are light. §4 below is the correction: a concrete list of lanes where **n8n can become the scheduler-of-record** without touching a secret, a send, a broker call or an authoritative write.

## 2. Where I agree (claims I re-verified on the host)

| Codex claim | Verified tonight | Note |
|---|---|---|
| 444 active user-cron rows | `crontab -l` active rows = 444 | My ledger said 450 after tranche B; Codex's parser excludes `@reboot` and prose-tagged rows differently. 444 is the number to carry forward. |
| 4 n8n workflows, all inactive, 0 credentials | `workflow_entity`: 4 rows, `active=f`; `credentials_entity` = 0 | Correct. The two monitor workflows were deactivated 10-07 by design. |
| n8n owner MFA disabled, application role is superuser | `"user".mfaEnabled = f`; `pg_roles.rolsuper = t` | Real finding. Hardening item H2 in the execution week; not yet done. |
| Mixed release identity: active-trader-motion on `a032116e7` | 4 units on `a032116e7`: active-trader-motion, chatgpt-oauth-proxy, grok-oauth-proxy, heartbeat-receiver. Core 6 on `ebda6ab2a`. | Codex found one; there are four. Promote does not restart these units. Needs a service grant to restart them from CURRENT. |
| Failed units: mcporter-token-refresh, advisory-shadow-session, firmware notifier, two desktop portals, fancontrol | `systemctl --user --failed`: 6 (adds `ubuntu-report.path`) | mcporter fails hourly on Google token refresh; shadow-session failed 09:15 ET after 8.5 min CPU. Both are owner triage items. |
| Nightly maintenance latest receipt failed `report_db_hygiene` on `b18d8087b` | Confirmed | That receipt was my manual 22:12 ET fire. The hygiene step fails by design while the DB is 24.4 GB against a 16 GB budget; the next natural fire is 01:15 ET on `ebda6ab2a`. Not a regression. |
| GitHub main: strict=false, 0 required reviews, admins enforced, 2 required checks | `gh api …/protection`: strict false, reviews 0, admins true, force-push false | Correct. The engineering standard says strict; the repo does not. Operator decision. |
| Coordination gateway durable on 18091 | `/healthz` → `durable: true` | Correct. The unit's Description string still says "proposal only, not installed"; cosmetic drift to fix. |
| `lane-governance-packet-weekly` NEVER_SCHEDULED, `served_sha` null in the packet | Registry confirms NEVER_SCHEDULED | Flip scheduled for Thursday after the first live draft. |
| `db-hygiene-nightly` declared-unscheduled | Registry: NEVER_SCHEDULED, no `superseded_by` | Registry defect: the work runs inside `platform-maintenance-nightly`. Should be RETIRED with `superseded_by`. |
| Empty table / zero-scan index is not proof of safe removal; 7-year retention is not a legal conclusion | Agreed | Matches the operator's "archive never delete" rail and the DELETE-policy fix already in `data_retention_policy.json`. |
| n8n Community lacks multi-main, native Git, external secrets, projects, SSO; queue mode only on measured need | Agreed | Matches `10-eligibility-and-secrets-20261007.md`. |

Codex's evidence vocabulary (OBSERVED / CONFIGURED / HISTORICAL / INFERRED / PROPOSED / UNKNOWN) and its refusal to turn "no receipt" into "not running" are the right discipline. Its correction pass on 15 child rows that had inherited parent timestamps is the kind of self-audit I want from any agent touching this estate.

## 3. Where I disagree with Codex, or where it is stale

1. **"Keep monitors inactive absent reviewed read-only contract" (PR-054, blocked).** The read-only contract exists: the two monitor workflows only call the gateway `status`/`list` routes, which are allowlisted and HMAC-bound. They should be reactivated this week as the first n8n-owned schedules, not left as fixtures.
2. **MCP read-only tools at 90+ days (PR-060).** The gateway already exposes `status`/`list`/incident projection; an MCP Server Trigger in n8n over those routes is a 1–2 day item once the secrets ADR is decided. Deferring it three months gives up the single most useful thing n8n can give Claude Code and OpenClaw.
3. **"n8n engine blocked" and "coordination works independently of n8n."** True today, and it is an indictment of both plans: the host dispatcher, gateway, ledger and projection do all the work and n8n contributes nothing. The fix is not to leave it that way; it is §4.
4. **Counts.** Codex's "263 user service entries" and "646 service entries" include aliases, templates and desktop units; its own text says so. Carry 58 expected units (the `expected_services.json` denominator) in any operator conversation, not 646.
5. **"Research intake: OBSERVED selected stage; full completion not implied."** We have the full chain: request event → consumer → `ri_research_queue` row 420 → CONSUMED ledger row (10-07 ~22:30 ET). Codex collected before that run completed.
6. **Retention of `safe_flock` histories as "wrapper outcomes only."** Correct but under-used: `hermes_scope_governor.py` with 2,025 nonzero exits versus 524 zero exits is a real anomaly and should be an open incident, not a review candidate.

## 4. What can actually move to n8n (the operator's point)

### 4.1 The enabler Codex and my blueprint both missed

n8n cannot own a schedule today because the only path from n8n into Trade AI is an *event* (`accept_event`). To move a workflow, n8n needs a *run* path: one new gateway route, `POST /v1/run/{lane_id}`, that

- accepts only lane IDs on a `RUN_ALLOWLIST` in `config/n8n_run_allowlist.json` (each entry: lane_id, runner command, flock path, timeout, `dry_run_default`),
- is HMAC-signed and nonce-bound like `accept_event`,
- spawns the existing runner under the lane's existing `/tmp` flock and `market_day_gate` (so a cron line and an n8n trigger can never double-run),
- returns a `run_id` and writes a `RunRequested@v1` receipt; the runner's own receipt closes it.

Secrets stay in Trade AI (the runner reads `/run/user/<uid>/tradeai/env`); sends stay in `telegram_alert.send_telegram`; broker, memory and authoritative writers are never on the allowlist (the allowlist test asserts this against `data_source_authority.json`). n8n gains: cadence ownership, dependency DAGs, prerequisite gating, bounded retries, per-step timing, one visual status surface. Estimated effort: 2 engineer-days plus one cron-write grant per tranche.

### 4.2 Move tranches (scheduler-of-record moves to n8n; execution stays native)

| Tranche | Lanes (ACTIVE in registry) | Count | Why it is safe | Week |
|---|---|---|---|---|
| **N1 coordination-only** | n8n-pilot-dispatch, n8n-incident-fanin, n8n-research-intake-consumer, crontab-snapshot-for-health-agent, n8n-lab-watchdog, lane-governance-packet-weekly, maturity-remeasure, the two existing monitor workflows | 9 | No secret, no send, no authoritative write; receipts already typed | this week |
| **N2 pipeline orchestration** | premarket-data-pipeline, after-close-pipeline ×3, hermes-learning ×2, hermes-overnight ×2, platform-maintenance ×3, governance-pipeline, portfolio cadences ×5 | 17 | Manifest runner stays the executor; n8n owns the DAG, prerequisite receipts and timeouts, which is exactly the "minute-offset implicit dependency" problem Codex §7.3 names | after tranche B cutovers (from Thu 17:40 ET) |
| **N3 reports and digests** | llm-spend-report ×3, material-change-digest, alert_daily_digest, ops_daily_digest, ops_weekly_learning_report, system_rollup_snapshot, generate_weekly_docx, generate_analyst_daily_digest, desk_suggestions_digest, rotation_rebalance_digest | 12 | Renderers write files; delivery goes through the native outbox; n8n tracks generated → delivered → consumed | week 2 |
| **N4 audits and monitors** | expected-services, data-source-health, served-copy-split, data-plausibility, gap-resolution, source-litmus, finviz-view-contracts, operator-answer-quality, research-lane-health, agent-runtime-health, job_coverage_monitor, llm_retry_monitor, catalyst_calibration_monitor, source_attribution_monitor, watch_directives_monitor, hermes_pipeline_health, youtube_cookie_health_check, finviz_health_check, crawl_v3_dashboard, alert_missing_conditions | 20 | Read-only measurement; the `--alert` send is a native call inside the script; the five systemd `--alert` units are first (they are the ones still pointing at the dev tree) | week 2 |
| **N5 backups and syncs** | drive-syncs-hourly, backup_generated_docs, sync-memory-to-drive, commit_hermes_daily, n8n-lab-backup, n8n-lab-restore-drill, portfolio-backup-cadence | 7 | OAuth stays in `gog`/OpenClaw; n8n records manifest hash and verify receipt | week 2 |
| **N6 other projects** | DOF `run_pipeline.py` six stages + `rescan_tickets.py`; OpenClaw reminder jobs (Claude plan ×2, SuperGrok expiry, SentinelOne earnings) | 6 | DOF runner is idempotent by docstring, needs one receipt per stage; reminders are pure schedules | week 3, after DOF read-only role |
| **Never** | broker/positions/stops/orders/paper (30 lanes), every sender, `sm-render`, guard, release deploy, destructive retention stages, memory/learning writers, CIO/persona/OpenClaw agent loops, price and research ingest writers | — | Rails §0 and §17 | — |

That is 71 lanes where n8n becomes the scheduler-of-record, against 5 pilots in the blueprint and "selected low-frequency workflows" in Codex. The 155 data-writer and LLM-spending lanes stay native as *executors* but can still be triggered through the run route once their receipts are typed; that is a later decision, not a rail.

### 4.3 Acceptance per moved lane (same bar as tranche B)

Dry-run from n8n first (`dry_run_default: true`), quote the receipt; one natural fire from n8n with the cron line still present (flock proves no double-run); disable the cron line under a cron-write grant; registry flip to `scheduler: n8n` with `superseded_by`; `check_lane_registry --fail-on-new --state-drift` clean; rollback is the cutover script's `--rollback`, which re-enables the cron line.

## 5. Codex items to act on now (not n8n-related)

1. Restart the four `a032116e7` units from CURRENT (service grant) and add a post-promote check that every expected unit's cwd equals CURRENT.
2. Triage `mcporter-token-refresh` (hourly Google token failure since at least 10-07) and `tradeai-advisory-shadow-session` (status 1 after 8.5 min).
3. n8n lab: enable owner MFA, replace the superuser role with a least-privilege role on the next compose recreate (execution-week H2/H3).
4. Registry: `db-hygiene-nightly` → RETIRED `superseded_by: platform-maintenance-nightly`; fix the gateway unit Description string.
5. Operator decision: set `strict` on main branch protection to match the engineering standard, or amend the standard.
6. Open an incident for `hermes_scope_governor.py`'s 2,025 nonzero exits.

## 6. What this review does not do

It does not adopt Codex's 0–30/30–90 horizons, does not treat Codex's 813-record inventory as 813 active jobs, and does not move any lane. The run route and tranche N1 need a PR, CI, a release and a cron-write grant like every other change this week.
