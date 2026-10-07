# n8n target-state blueprint — baseline status, gap analysis, process inventory, operating model

Status as of 2026-10-07 15:25Z on `ms01-openclaw`. This is the single authoritative scope document for n8n in the Trade AI estate. It supersedes the scattered observations in `09-live-audit-20261007.md`, `10-eligibility-and-secrets-20261007.md` and the roadmap plan, and it cites them for evidence. Every status is one of: **VERIFIED** (runtime evidence seen today), **BUILT_UNPROVEN** (merged code, no served run yet), **PROPOSED** (file exists, not applied), **BLOCKED** (needs an operator action named here), **MISSING** (nothing exists), **N/A** (not available in Community edition or not wanted).

Operating principle, unchanged and decided: **n8n coordinates and observes; Trade AI executes.** "Move into n8n" in this document means n8n becomes the owner of the *coordination record* for that process (waiting, in progress, artifact, consumed, refused, acknowledged). Execution, sends, broker calls, paid model calls, memory writes and secrets never move. Decision taken 2026-10-07: **zero credentials inside n8n** (ADR to be marked ACCEPTED with that option).

---

## Part 1 — baseline status and gap analysis

Served Trade AI release: 60863d207 (promote of cb1bdfa98 = PR #1476 in progress at the time of writing, waiting on main CI). n8n lab: `n8nio/n8n:2.43.0`, Docker Compose project `m8m-n8n`, loopback 5678, restarted 15:12Z after the DOF monitor was deactivated.

| Component | Status | Evidence | Configuration state | Validation | Remaining work | Pri | Effort |
|---|---|---|---|---|---|---|---|
| Core installation | VERIFIED | `docker ps`, `n8n --version` 2.43.0, `/healthz` ok after restart 15:12Z | Compose, `unless-stopped`, mem/pids limits, no-new-privileges | Running 1 active workflow (`n8n-monitor-trade-ai`), 384+ executions | Add compose healthcheck (PROPOSED in `proposals/docker-compose.n8n.hardened.yml`) | P1 | 0.2 ed + operator apply |
| Database configuration | VERIFIED (degraded) | PG 16.15, role `n8n` superuser, 157 tables, migrations head 300 | Dedicated container, no host port | Dump + restore drill passed 14:40Z | PG17 image and non-superuser `n8n_app` role on a fresh volume (PROPOSED, needs dump→restore cutover) | P1 | 0.5 ed + operator |
| Queue mode | N/A (not needed) | `EXECUTIONS_MODE` absent → regular; ≈288 executions/day | — | — | Revisit only above ~5,000 executions/day | P3 | — |
| Redis | N/A | none on host | — | — | Only with queue mode | P3 | — |
| Worker scaling | N/A | single main, internal JS runner (deprecated mode per log) | — | — | `N8N_RUNNERS_MODE=external` sidecar when convenient | P3 | 0.3 ed |
| Webhooks | VERIFIED closed | `webhook_entity` 0; port loopback | `N8N_WEBHOOK_URL` proposal replaces deprecated `WEBHOOK_URL` | — | Keep closed; inbound to production refused by gateway forbidden routes | P2 | 0.1 ed |
| Authentication | BLOCKED (operator) | 1 owner, `mfaEnabled=false`, owner password in lab `.env` (0600) | email+password | — | Owner MFA in UI; move `N8N_OWNER_PASSWORD` to Bitwarden SM (step 6) | P1 | operator 10 min |
| RBAC / projects | N/A (edition) | Community: personal project only | — | — | Separate instance per tenant if ever needed; DOF stays out of this instance | P3 | — |
| Backup and recovery | VERIFIED, unscheduled | `scripts/n8n_lab_backup.sh` first live run 14:40Z: 624,124 B, 157 TOC entries; `n8n_lab_restore_drill.sh` 157/157 tables, 4 workflows, drill DB dropped; `N8N_ENCRYPTION_KEY_ESCROW` rendered from SM | Scripts merged (#1476); receipts under `persistent-state/backups/n8n/` | One manual cycle | Cron lines `30 3 * * *` and `0 4 * * 0` (cron grant), registry rows → ACTIVE | P0 | 0.2 ed + grant |
| Monitoring | PROPOSED | `tradeai-n8n-lab-watchdog.{service,timer}` in repo; `/healthz` 200 | Not installed | Script recorded HTTP 200 on 10-07 01:22Z in an earlier manual run | `systemctl --user enable --now` (service grant); compose healthcheck | P0 | 0.1 ed + grant |
| Alerting | BUILT_UNPROVEN (host side, by design) | `scripts/n8n_incident_fanin.py` dry-run: 45 open findings, 2 P1 (merged #1476) | n8n sends nothing (emailSend excluded, forbidden routes) | 7 hermetic tests | Gateway running + cron `*/5`; operator ack hook (#1477) | P1 | 0.3 ed + grants |
| Workflow versioning | VERIFIED | `scripts/n8n_export_workflows.py` → `workflows/*.json` (4) merged #1476 | Manual run after each lab change | Export matches DB; no credentials in files | Re-run after each workflow change; add to the weekly report | P2 | 0.1 ed/run |
| Git integration | N/A (edition) | Community has no source control | — | — | Export is the substitute (done) | — | — |
| Secrets management | VERIFIED (decision taken) | Bitwarden SM master; `TRADEAI_N8N_GATEWAY_HMAC_KEY`, `N8N_ENCRYPTION_KEY_ESCROW`, `DOF_READER_PASSWORD` rendered to tmpfs 14:55Z/15:00Z; n8n `credentials_entity` 0 | Gateway unit reads `%t/tradeai/env` | Names verified, values never read | Mark ADR ACCEPTED (zero credentials); schedule `rotation_daemon.py`; fix the 0664 bws state file | P1 | 0.3 ed |
| API integrations (coordination gateway) | BUILT_UNPROVEN | gateway + ledger + projection served since 60863d207; `--allow-lane` and wrapper extra-lanes in #1476; unit PROPOSED | `tradeai-n8n-coordination-gateway.service` not installed; `/api/v2/coordination/events` answers `NO_LEDGER` | 60+ hermetic tests | Install unit (service grant); first `durable: true` receipt; dispatcher cron | P0 | 0.2 ed + grants |
| Pilot dispatcher | BUILT_UNPROVEN | `scripts/n8n_pilot_dispatch.py` dry-run: 3 of 5 pilots fired today (approval reminder, LLM spend, morning brief) | NEVER_SCHEDULED lane `n8n-pilot-dispatch` | 8 tests incl. idempotent re-run | Cron `*/15` + registry flip; first ledger rows | P0 | 0.2 ed + grant |
| LLM integrations | BUILT_UNPROVEN | `model_job` op + `n8n_model_job.py` + process `n8n_material_digest_draft` ($0.10/day, manual) served; bridge caller map `n8n_model_job` served | Zero runs | fixtures: valid / invalid JSON / over-cap / outage | First governed draft after pilot 4 has receipts; fix registry PRO→Flash mapping first | P1 | 1 ed |
| Agent integrations | MISSING (design) | none; `agent_handoffs` 729 rows exist in Trade AI | — | — | Handoff receipt events through the dispatcher (Phase 2) | P2 | 3 ed |
| Google Workspace | E (outside) | OAuth lives in OpenClaw `gog`; no Google credential in n8n | — | — | "report ready" events only (Phase 3) | P3 | 0.3 ed |
| Google Drive | E (outside) | hourly Drive sync crons exist (`sync-docs-to-drive :05`, `sync_code_mirror_to_drive :35`) | — | — | Drive-sync receipt event | P3 | 0.3 ed |
| Email | E (outside) | `emailSend*` nodes excluded by env; no mail credential | — | — | none | — | — |
| Telegram | BUILT_UNPROVEN | ack hook `ack:<key>` in `telegram_callback_handler.py` + `ack_keyboard()` (#1477, CI running) | Sender stays `telegram_alert.send_telegram` | 3 tests | Merge #1477, promote, first operator ack row | P1 | 0.1 ed |
| Slack / Teams | N/A | not in the estate | — | — | none | — | — |
| MCP support | MISSING (bundled, unused) | `@n8n/mcp-*` in image; `mcp_registry_server` 79 catalog rows; no server configured | — | — | Read-only MCP Server Trigger for `status`/`list`/incidents, Header auth on loopback/tailscale (Phase 2) | P2 | 1.5 ed |
| Error handling | MISSING | `n8n-bench-error` inactive; no production error workflow | — | — | Error workflow → gateway `refuse` row (needs gateway + the one-key question: with zero credentials the error workflow can only write a lab-DB row; design it that way) | P2 | 0.3 ed |
| Audit logging | PARTIAL | execution log (payloads `all`, 336 h); SQLite ledger is the coordination audit (WAL, receipts, nonces, effects) | Retention proposal: `SAVE_ON_SUCCESS=none`, 168 h | — | Apply retention; weekly per-lane report (`report_lane_fire_ledger.py`) | P1 | 0.2 ed |
| Disaster recovery | PARTIAL | dump + drill + key escrow; recovery procedure written (`10-…` §6) | No schedule, no off-host copy | one drill | Schedule; add the dump dir to the existing Drive mirror (operator choice); PG17 cutover rehearsal | P1 | 0.5 ed |
| Command Center projection | BUILT_UNPROVEN | `/v3/coordination` page + `coordinationEvents.ts` (26 tests) in #1477 | route ledger rows added | tsc + vite build pass | Merge, promote, first rows | P1 | 0 |
| S1 (`:7777` open auth) | BLOCKED (after promote) | `PORTFOLIO_SERVER_BIND` env merged (#1476), default unchanged | drop-in not yet installed | — | Drop-in + restart after cb1bdfa98 is served; deactivate `n8n-monitor-trade-ai` | P0 | 0.1 ed |
| S2 (DOF exposure + role) | VERIFIED | `dof_reader` created 15:10Z (reads 5,470 `dof_vehicles`, INSERT refused); `DOF_BIND=127.0.0.1` drop-in, restart 11:11:35 ET; `:7776` loopback only; LAN and n8n bridge refused; tailnet `:8443` confirmed by operator; DOF PRs #3/#4 merged | done | done | none (DOF views in n8n remain Phase 3, read-only, through the gateway) | — | — |

**Summary.** Implemented and verified: core lab, database (degraded), closed webhooks, secrets model, backup/restore scripts, workflow export, S2. Built but unproven on a served run: gateway, dispatcher, incident fan-in, model job, Telegram ack, Command Center page. Proposed, awaiting operator grants: watchdog, gateway unit, four cron lines, compose hardening, S1, MFA. Missing: agent handoff events, MCP surface, error workflow. N/A by edition or by design: queue mode, Redis, workers, RBAC, Git, SSO, email, Slack, Teams.

---

## Part 2 — complete workflow and process inventory

Columns: **Owner now → proposed** · **Fit** (why n8n is / is not right) · **Dependencies** · **I/O** · **Freq** · **Risk** · **Cx** (complexity) · **Effort** · **Disp.** (A immediate · B Phase 2 · C Phase 3 · D hybrid · E keep outside permanently · F review). For A–D the proposed owner is "n8n (coordination record)" unless stated; the effect stays where it is.

### 2.1 Workflows and automations already contracted (the five pilots)

| Name | Purpose | Owner now → proposed | Fit | Dependencies | I/O | Freq | Risk | Cx | Effort | Disp. |
|---|---|---|---|---|---|---|---|---|---|---|
| Approval-package reminder | tell the operator what awaits approval | cron `:05` + reconcile `:12` → n8n record | run + reconcile receipts exist since 10-07 00:05 ET; first lane with a consumer receipt / not: authority stays with guard + Telegram | gateway, dispatcher | in: `approval_package_reminder_last.json`, reconcile receipt · out: ledger rows CONSUMED | hourly | Low | Low | 0.2 ed | **A** |
| LLM spend report (daily/weekly/monthly) | cost visibility | cron `07:05/07:10/07:15` → n8n record | receipt file with `sent` flag / not: the send stays in code | gateway | in: `llm_spend_report_last_*.json` · out: ARTIFACT_WRITTEN rows | daily+ | Low | Low | 0.1 ed | **A** |
| Morning brief delivery | 07:30 operator brief | cron → n8n record | semantic-state claim + persisted `sent` flag (new in #1476) / not: send is `deliver_morning` | gateway, #1476 served | in: `morning_brief_semantic_state.json` · out: rows with `send_receipt OBSERVED` | weekdays | Low | Low | 0.2 ed | **A** |
| Material-change digest | 16:15 digest of detector events | cron → n8n record | detector `change_guid` + `notify_outcome` are durable / not: CANARY notifier stays in code | read-only DB query in dispatcher (`TRADEAI_READ_DSN`, not yet set) | in: `material_changes` row · out: rows or typed refusal `live_notifier_stays_in_code` | daily | Medium | Medium | 0.5 ed | **B** |
| Holdings research handoff | 09:05 research trigger for holdings | cron → n8n record; execution Hermes | `run_id`/`mode` from `research_call_accounting.jsonl` / not: re-trigger would bypass caps | gateway | in: accounting rows · out: rows or `no_holdings_run_in_window` | weekdays | Medium | Medium | 0.5 ed | **B** |

### 2.2 Operational, incident and governance processes

| Name | Purpose | Owner now → proposed | Fit | Dependencies | I/O | Freq | Risk | Cx | Effort | Disp. |
|---|---|---|---|---|---|---|---|---|---|---|
| Incident fan-in | one list of open findings with ack state | 20+ `--alert` timers, breach detector, watchdogs → n8n record | receipts already exist; nobody joins them / not: the checks themselves read local state | gateway `--allow-lane incident-fanin`, cron `*/5` | in: receipts · out: incident rows, recovery acks | 5 min | Low | Medium | built | **A** |
| Operator acknowledgement | human ack on an incident or artifact | Telegram inline → `consumer_ack` | the tap is a receipt, not an approval / not: approvals stay with guard | #1477 served | in: callback · out: CONSUMED row with `operator-telegram:<id>` | on demand | Low | Low | built | **A** |
| Lane-registry truth | 174 lanes vs host state | `check_lane_registry --state-drift` in CI → n8n record | drift events between CI runs / not: CI stays the gate | dispatcher extension | in: drift JSON · out: events per conflict | daily | Low | Low | 0.5 ed | **B** |
| Platform conformance | nightly silo scores (11/14 below floor) | cron 02:30 → n8n record | receipt file exists / not: scoring stays in Trade AI | — | in: `platform_conformance_latest.json` · out: artifact row | nightly | Low | Low | 0.2 ed | **B** |
| Weekly per-lane report | fire coverage, refusals, consumed | `report_lane_fire_ledger.py` (manual) → n8n record + weekly artifact | the ledger is the input / not: journal-bounded | ledger rows | out: `ledgers/fire-ledger.json` | weekly | Low | Low | 0.3 ed | **A** |
| Release evidence packet | deploy + conformance + CI receipts per promote | manual → n8n record | artifact refs only / not: release authority is operator-only | promote receipts | in: `deploy_receipt.json`, gate receipts · out: artifact rows | per release | Low | Low | 0.5 ed | **B** |
| Monthly governance packet | registry, conformance, maturity, rotation receipts | none → n8n record + Trade AI renderer | fan-in of existing reports / not: n8n renders nothing | Phase 2 events | out: `docs/.../ledgers/governance-YYYY-MM.json` | monthly | Low | Low | 1 ed | **C** |
| Secrets rotation receipts | prove rotation happened | `rotation_daemon.py` unscheduled → cron + n8n record | receipt only / not: values never leave SM | cron grant | out: rotation receipt rows | weekly | Medium | Low | 0.3 ed | **B** |
| n8n lab self-care (backup, drill, watchdog) | keep the coordinator alive | scripts (merged) → cron + timer | the lab must monitor itself; receipts feed the fan-in / — | grants | out: backup + drill receipts, watchdog receipt | nightly/weekly/5 min | Low | Low | built | **A** |
| Expected-services / data-source / served-copy / gap / plausibility audits | health checks | timers → stay; receipts → fan-in | — / checks read local files | — | — | hourly–daily | Low | — | — | **D** (check outside, record inside) |
| Platform ops digests (OpenClaw `ops_daily_digest`, weekly learning) | operator summaries | OpenClaw cron → stay; receipt → n8n record | — / OpenClaw owns Telegram delivery | — | — | daily/weekly | Low | Low | 0.3 ed | **D** |

### 2.3 Notifications and reporting

| Name | Purpose | Owner now → proposed | Fit | Dependencies | I/O | Freq | Risk | Cx | Effort | Disp. |
|---|---|---|---|---|---|---|---|---|---|---|
| Notification outbox projection | sent / suppressed / withdrawn with reasons | `communication_outbox` (74,400 rows) → n8n record | audit trail for the single-channel rule / not: never a sender | read-only query | in: outbox rows · out: events | hourly | Low | Low | 1.5 ed | **B** |
| 49 Telegram senders (proposal alerts, screener GO, SIEM critical, freshness, digests, briefs) | operator alerts | cron / timers → stay | — / sends are the chokepoint `telegram_alert.send_telegram` | — | — | 2 min–daily | High if moved | — | — | **E** |
| CIO delivery worker, advisory notification broker, Telegram callback poller | operator surfaces | systemd/cron → stay | — / authority paths | — | — | 2–60 min | High | — | — | **E** |
| OpenClaw announce jobs (9 enabled) | persona messages to Telegram | OpenClaw scheduler → stay | — / OpenClaw owns delivery | — | — | daily–monthly | Medium | — | — | **E** |
| Analyst daily digest, desk suggestions, options lifecycle digest, closed-trade digest, session reviews | reports | cron → stay; receipts → n8n record | receipt files exist / renderers stay | — | out: artifact rows | daily | Low | Low | 0.5 ed | **C** |
| Drive syncs (docs, code mirror, memory) | off-host copies | cron → stay; receipt → n8n record | — / OAuth in `gog` | — | out: sync receipt rows | hourly/daily | Low | Low | 0.3 ed | **C** |

### 2.4 Research, knowledge and document processes

| Name | Purpose | Owner now → proposed | Fit | Dependencies | I/O | Freq | Risk | Cx | Effort | Disp. |
|---|---|---|---|---|---|---|---|---|---|---|
| Research intake routing | one `research_request` event from CIO wake / operator / Maria → Trade AI consumer enqueues under caps | scattered (`research_scheduler`, Hermes crons, `ri_research_queue`) → n8n record; execution Trade AI | request→run→consumed chain is invisible today / not: n8n must never trigger Hermes directly | gateway, consumer script | in: request events · out: `ri_research_queue` rows via consumer, run receipts | continuous | Medium | Medium | 2 ed | **D** |
| Hermes research execution, scoring, embeddings (47 cron lines, 17 units) | research runs | cron/systemd → stay | — / caps, off-peak deferral, provider keys | — | — | 5 min–daily | High | — | — | **E** |
| Due-diligence questions, governed research producer, ensemble worker | governed producers | cron → stay | — / reservations and caps live in Trade AI | — | — | 3–60 min | High | — | — | **E** |
| Deep overnight LLM queue backlog (1,928 pending, lane RETIRED) | dead backlog | none → retire rows | — | — | — | — | — | — | 0.2 ed | **F** (retire; operator confirms) |
| SEC filings feed, SEC fundamentals, document mentions backfill/prune | document ingest | cron → stay; receipts → n8n record | artifact refs / ingest stays | — | out: artifact rows | daily/hourly | Low | Low | 0.5 ed | **C** |
| Operator "drop a PDF" pipeline | ingest an operator document | none → Drive sync delivers, Trade AI ingests, n8n tracks state | state tracking only / no Drive credential in n8n | Drive sync, ingest script | in: Drive receipt · out: state rows | ad hoc | Low | Medium | 1.5 ed | **C** |
| RAG / knowledge retrieval (pgvector activation for 1.31 M jsonb embeddings) | faster retrieval | Trade AI → Trade AI | not an n8n capability; n8n gets a retrieval receipt | disk headroom (84 % used) | — | — | Medium | Medium | 3 ed | **E** (Trade AI work) |
| Memory promotion review, lesson candidates, outcome reconcilers, instrument beliefs | memory/learning writers | cron/systemd → stay; receipts → n8n record (Phase 3) | — / authoritative memory | — | out: receipt rows | daily/weekly | High | — | 0.5 ed | **E** (record only in C) |
| Nightly reflection, persona reflection | reflection loops | systemd → stay; weekly yield count on the projection | — / memory writes | — | — | nightly | Medium | Low | 0.3 ed | **C** |

### 2.5 Agent orchestration and LLM

| Name | Purpose | Owner now → proposed | Fit | Dependencies | I/O | Freq | Risk | Cx | Effort | Disp. |
|---|---|---|---|---|---|---|---|---|---|---|
| Material-change digest draft (`model_job` #1) | nonfinancial AI draft under caps | none → n8n requests, Trade AI executes | schema-validated, cost-joined, typed refusals / not: never a provider key in n8n | gateway running, pilot 4 receipts, registry PRO→Flash fix | in: `artifact_ref` + schema id · out: draft artifact + cost receipt | daily | Medium | Medium | 1 ed | **B** |
| Weekly ops summary draft (`model_job` #2) | summary of incidents/approvals | none → same pattern | — | #1 four weeks of receipts | out: `ops_summary_draft/v1` | weekly | Medium | Medium | 1 ed | **C** |
| Agent handoff events (`agent_handoffs` 729) | show persona handoffs waiting/claimed/consumed | agent runtime → n8n record | the bus is the gateway / execution stays in `tradeai-agent-runtime@*` | dispatcher extension | in: handoff rows · out: events | 5–30 min | Low | Medium | 3 ed | **B** |
| CIO reactive/wake loops, 13 persona runtimes, OpenClaw agents, ensemble/critics | agent execution | systemd/cron/OpenClaw → stay | — / high frequency, wake ledgers, approvals | — | — | 2 min–daily | High | — | — | **E** |
| n8n AI Agent node chains, chat memory, vector-store nodes, MCP Client Tool | — | none → none | second orchestrator, second memory, second store | — | — | — | High | — | — | **E** |
| Read-only MCP server (`status`, `list`, incidents) for Claude Code / OpenClaw | tool surface over the ledger | none → n8n MCP Server Trigger, Header auth, loopback/tailscale | n8n ships the node; zero credentials still holds if the auth header is a gateway-issued reference / F until that design is reviewed | gateway, ADR | in: tool calls · out: read answers | on demand | Medium | Medium | 1.5 ed | **F** |

### 2.6 Human approval, trading, broker, data and secrets (the permanent exclusions)

| Name | Owner now | Disp. | Why |
|---|---|---|---|
| Guard grants, Telegram `/approve`, approval packages, admin-write token, per-order 2FA | `bin/guard`, callback poller, `api_v2` | **E** | AGENTS.md §17 operator-only; n8n may reflect state, never decide |
| Exact-main release (prepare/promote/rollback) | `cio_phase2_exact_main_deploy.sh` | **E** | grant-bound, CI-bound, operator-run |
| Broker/positions/stops/orders (30 items), paper loop, OpenD, active-trader motion | cron/systemd/services | **E** | §0 rules 1–2; a duplicate trigger is an order |
| Options lifecycle writers, approval queue writes | cron | **E** | lock semantics, human decision surface (view only in C) |
| Price/data ingest (repricer, live monitor, warm caches, finviz lanes, momentum engines) | cron | **E** | market-hour cadence, authority registry |
| Secrets render (`sm-render` 4 h), rotation, bws tokens | systemd | **E** | one store, one render path |
| DB retention, portfolio backup cadences, disk guards, worktree retention | systemd/cron | **E** | destructive maintenance stays with its locks |
| DOF scraping/pipeline crons and dashboard (`rescan_tickets`, `run_pipeline`) | DOF repo | **E** (views **C**) | separate project; read-only queue views through `dof_reader` in Phase 3 |

Totals: **A = 7** (5 pilots' first three + incident fan-in + operator ack + weekly report + lab self-care, counted as processes), **B = 9**, **C = 10**, **D = 3**, **E = 20 families (≈ 560 scheduled items)**, **F = 2**.

---

## Part 3 — strategic answers and the operating model

**1. What exactly belongs in n8n?** The coordination record for: the five pilots, incident fan-in with operator acks, lane-registry drift, conformance and release evidence, the weekly and monthly packets, the notification outbox projection, research intake routing (as the request/receipt chain), agent handoff receipts, document and report artifact references, and two governed nonfinancial AI drafts requested through the gateway. Plus n8n's own self-care receipts.

**2. What exactly does not belong in n8n?** Every effect: sends (Telegram, email, Drive), broker and position work, stops and orders, paper trading, options writers, price ingest, memory and learning writers, CIO and persona loops, OpenClaw delivery, Hermes execution, provider calls, secrets, approvals, release. Also every credential: the decision is zero.

**3. Complete migration roadmap**
- **Phase 1 (now → 2026-10-21):** merge #1477; promote; S1 drop-in; install watchdog + gateway unit; four cron lines + registry flip; first `durable: true` receipts; pilots 1–3 two natural fires each; incident fan-in live; first operator ack; MFA; ADR marked ACCEPTED (zero credentials); weekly report #1.
- **Phase 2 (2026-10-22 → 2026-12-31):** pilots 4–5 (needs `TRADEAI_READ_DSN` for the digest query, read-only role); outbox projection; lane-registry drift events; release evidence packet; secrets rotation receipts; agent handoff events; `model_job` #1 automated on evidence; compose hardening applied incl. PG17 cutover; four weekly reports → coordinator-of-record decision for the status view.
- **Phase 3 (2027-01 → 2027-03):** report/document/Drive receipts; monthly governance packet; `model_job` #2; DOF read-only queue views; retire dead backlogs; MCP read-only surface only after the F review clears the zero-credential constraint.
- **Never:** lane cutover of an owned effect without its own packet (work order Phase 8B).

**4. End-state architecture**
```
Operator ── Telegram inline ack ──► callback poller ──► gateway consumer_ack ──┐
Operator ── Command Center /v3/coordination (waiting · in progress · artifact · consumed · refused · incidents)
                                                                               │
Trade AI (owner of every fact and effect)                                      ▼
  483 cron lines · 92 timers · bridge :8766 · guard · Bitwarden SM → render_env (tmpfs)
  dispatcher (*/15) + incident fan-in (*/5) ── signed claims ──► gateway 127.0.0.1:18091 ──► SQLite WAL ledger
  consumers: research enqueue, outbox projection, recovery acks, model_job (bridge caller n8n_model_job)
                                                                               │ projection /api/v2/coordination/events
n8n 2.43.0 lab (0 credentials, loopback, watchdog + nightly dump + weekly drill)
  schedule → gateway status/list reads → lab rows · error workflow → lab row · workflows exported to Git
  (Phase 3, after review) MCP Server Trigger exposing read-only status tools
```

**5. Business capabilities n8n provides:** one honest answer to "what is waiting on whom", with age, reason and evidence; proof that reminders, digests and briefs were produced and consumed; an acknowledged incident list; a weekly evidence trail that lanes fired; nonfinancial AI drafts produced under caps with their cost attached.

**6. Operational capabilities:** coordination ledger with replay-proof claims and typed refusals; incident fan-in with recovery auto-close; lane-registry drift visibility; release and conformance evidence packets; self-monitoring (watchdog, dump, drill); workflow definitions under version control.

**7. Agent and LLM capabilities:** requests for governed model jobs (schema-validated, capped, cost-joined) executed by Trade AI; visibility of persona handoffs and reflection yield; no agent execution, no chat memory, no vector store, no provider keys.

**8. Integrations:** inbound only from the Trade AI gateway (signed) and the dispatcher; outbound only to the gateway; projection consumed by the Command Center and the Telegram ack hook; Phase 3 candidate: read-only MCP tools. No Google, email, Slack, Teams, CRM or broker integrations, ever.

**9. Implementation phases:** as in answer 3; effort ≈ 12 ed (Phase 1, mostly done) + 15 ed (Phase 2) + 8 ed (Phase 3).

**10. Remaining blockers before "complete"**
1. Operator grants: service (gateway unit, watchdog), cron (4 lines), config-write (S1 drop-in), compose apply.
2. Promote of cb1bdfa98 (in progress) and merge+promote of #1477.
3. Owner MFA and the owner-password move; ADR status line.
4. `TRADEAI_READ_DSN` (read-only role for the digest query) — needs a `tradeai_reader` role like `dof_reader`.
5. Registry defects that every job inherits: PRO→Flash mapping; `tradeai-continuous` and `alert-quality` state truth; 29 undeclared timers.
6. Four weeks of weekly reports with ≥ 95 % fire coverage and zero unexplained refusals.
7. Disk headroom (84 %) before the PG17 cutover and any pgvector work.
