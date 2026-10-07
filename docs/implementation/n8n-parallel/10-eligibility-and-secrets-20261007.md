# Follow-up audit — n8n workload eligibility and secret-management review

Second pass over the live evidence in `09-live-audit-20261007.md` (collected 2026-10-07, host `ms01-openclaw`, read-only). Same labels, same rule: every decision cites the discovered runtime, or says NOT VERIFIED. Nothing here is installed, granted, or changed.

Questions answered: (1) exactly which processes, jobs, services, agents and lanes should run inside n8n; (2) what secret-management architecture to use given that n8n Community Edition cannot use Bitwarden natively.

---

## Section 1 — process-by-process eligibility review

Discovered sources (counts from `crontab -l`, `systemctl --user list-timers --all`, `list-units --type=service --all`, system scope, `~/.openclaw/cron/jobs.json`, `config/lane_registry.json`): 483 cron lines, 92 user timers, 144 user services (27 running), 2 system timers, 13 OpenClaw jobs, 174 declared lanes (137 ACTIVE). The per-line cron ledger is `ledgers/cron_rows_20261007.tsv` (483 rows: schedule, script, tree, registry status, command head). Because 398 of the 483 cron lines are undeclared-baseline debt with no lane row, this review classifies by **lane family** (every family lists its members and evidence) rather than pretending to 483 individually reasoned rows; the TSV is the row-level evidence.

Classes: **A** move fully into n8n · **B** hybrid (n8n coordinates/observes, existing service keeps the effect) · **C** keep outside n8n · **D** retire · **E** needs investigation.

### 1.1 Broker, positions, stops, orders — class C (all 30 items)

| Name | Purpose | Runtime | Frequency | Criticality | Dependencies |
|---|---|---|---|---|---|
| `alpaca_stop_manager.py --apply`, `--repair-oco` | protective stops / OCO repair | cron, CURRENT | `7-59/20 9-16`, `*/15 4-10` Mon–Fri | Tier-1 | Alpaca keys, `market_day_gate`, lock |
| `unified_stop_supervisor.py`, `stop_health_check.py`, `broker_stop_reconcile.py`, `stop_drift_alert.py`, `grok_stop_review.py --apply`, defense fills, `defense_inverse_stoplights.py` | stop supervision | cron | `*/3`, `*/10`, daily | Tier-1 | broker tokens |
| `schwab_position_sync`, `schwab_transaction_ingest`, `schwab_stream_daemon`, `schwab_econfirm_reconcile`, `sweep_schwab_instruments` | Schwab truth | cron | 15-min RTH, daily, Sat | Tier-1 | Schwab OAuth token, `SCHWAB_TOKEN_ENC_KEY` |
| `positions_sync --apply/--diff`, `positions_proof_daily`, `portfolio_reconcile`, `atm_position_reconciler`, `audit_position_basis`, `alpaca_live_read_sync`, `moomoo_live_read_sync`, `snaptrade_sync/activity_ingest`, `fidelity_stop_sync`, `opend_health` | positions and basis | cron | 15-min RTH, daily | Tier-1 | 4 brokers' credentials |
| `tradeai-tax-lots-rebuild.timer`, `tradeai-eod-consolidated-close.timer` | tax lots, EOD close | systemd | 07:15/16:45, 17:15 | Tier-1 | transactions tables |
| `trade-ai-lab-moomoo-opend.service` (OpenD, live $500 account), `tradeai-active-trader-motion.service`, `portfolio-server.service` (hosts order/2FA routes), `tradeai-cio-telegram.service` | broker gateway, motion runtime, API, operator command path | services | continuous | Tier-1 | rendered credentials |
| Paper: `paper_trade_monitor */2`, `paper_execution_sweep */5`, `alpaca_paper_adapter`, `alpaca_paper_reconciler`, paper governance/quality, `reconcile_alpaca_paper_options.sh`, options paper monitor, `microstructure_recorder` | paper training loop | cron | 2–5 min RTH | Tier-2 | Alpaca paper keys |

Why C: AGENTS.md §0 rules 1–2 (no agent or workflow tool holds broker authority; broker code only under a named grant), per-order 2FA is the only live gate, and the interdict drop-in `25-cio-only-live.conf` pins the API. Benefits of moving: none. Risks: a retried or duplicated trigger is an order; a credential copy is a second store. Recovery: today's recovery is lock files plus `market_day_gate` plus broker-side stops; n8n adds a process that cannot see those locks. Cost: zero today. Security: catastrophic on error.

### 1.2 Trading signals and data ingest — class C (≈60 cron lines)

Members: `rotation_autopilot */15 4-16`, `portfolio_repricer */15`, `portfolio_live_monitor */20`, `warm_caches */8`, `indicator_cache_refresh`, `sector_momentum_engine`, `finviz_industry_groups`, finviz momentum scalp early lane `*/5 6-11`, `active_trader/premarket_watch */5 6-9`, `material_change_detector */30`, `identity-sweep */30`, `sec_filings_feed`, `sec_fundamentals_ingest`, `document_mentions_backfill :25`, catalyst graph/impact, quote refresh, screener runners, `schwab_stream_daemon`. Runtime: cron from CURRENT with `$PY` = DEV venv. Frequency: 5–30 min in market hours. Criticality: Tier-1 upstream of stops and alerts. Dependencies: Finviz token/cookie in env, price caches on disk, Postgres. Why C: market-hour cadence (≈9,500–10,200 syslog CMD lines per weekday) and the served-copy/authority rules (`data_source_authority.json` is the registry; never newest-wins). Benefit of n8n: none measurable. Risk: stale prices propagate to stop decisions. Cost: an n8n node process on an 84 %-full host. Security: Finviz token exposure.

### 1.3 Options — class C now, B later for the approval-queue *view*

Members: `options_thesis_lifecycle :07/:22/:37/:52` (lock races with manual runs already recorded), `options_memory_projector :09/:24/:39/:54`, `export_options_runtime_snapshot :03`, `options_intent_matcher :15/:45 9-15`, `options_approval_queue` (2,968 rows: 2,901 blocked, 64 rejected, 1 approved). Why C: writers hold locks and write the thesis store; the approval queue is a human decision surface (operator-confirmed, 48 h abandon). Later B: n8n may *project* "blocked / awaiting operator" from the queue through the gateway `list` op, never write it. Risk of moving: second writer on the queue; lost lock semantics.

### 1.4 Research — class B for handoff receipts, C for execution

| Name | Purpose | Runtime | Frequency | Criticality | Dependencies |
|---|---|---|---|---|---|
| `research_scheduler.py --mode holdings/priority/watchlist/incubator` | enqueue research | cron | 09:05, hourly 10–16, 20:30, Sun 19:00 | Tier-2 | `research_trigger_ledger.jsonl`, caps |
| Hermes 47 cron lines + 17 `hermes-*` units + `tradeai-hermes-cio-worker` (15 min, drains `hermes_research_requests.jsonl` 41 MB) | research execution, scoring, embeddings | cron/systemd | 5–15 min to daily | Tier-2 | DeepSeek key (lanes $0.10–$0.40/day), free OAuth lanes, Ollama |
| `due_diligence_questions --route */20`, `governed_research_producer :45 --execute`, `run_ensemble_worker */3` | governed producers | cron | 3–60 min | Tier-2 | caps, off-peak wrapper |
| `deep_overnight_llm_queue` (3,784 rows, 1,928 pending, lane RETIRED) | dead backlog | none | — | — | — → **class D** |

Why B for the handoff only: pilot `research-scheduler-holdings` already has a contract (`run_id`/`mode` from `research_call_accounting.jsonl`, Hermes result ids, typed refusal otherwise). Why C for execution: spend is reserved and capped in Trade AI (`llm_cost_reservations` 58,823 rows, deferral drain file), and an n8n re-trigger would double-spend or bypass the cap. Benefit: a visible "research requested → run → consumed" chain. Risk: cap bypass. Cost: $0 if observe-only. Security: no provider key leaves Trade AI.

### 1.5 Notifications and operator surfaces — class B (observe receipt/suppression), C for the send

Members (49 cron senders, 11 `--alert` timers, OpenClaw 9 jobs, `tradeai-cio-delivery` 5 min, `tradeai-advisory-notif-broker` hourly, Telegram callback poller `*/2` + watchdog `*/5`): `send_morning_brief 07:30`, `screener_go_alerts --send */15`, `send_telegram_proposal_alert */2`, `notify_material_change --apply 7-59/15` (COMMS_GATEWAY_MODE=CANARY) and `--digest 16:15`, `llm_spend_report --send` daily/weekly/monthly, `p1_digest_sender 0 */4`, `approval_package_reminder :05` + `approval_reminder_reconcile :12`, `hermes_score_alerts :15/:45`, SIEM/freshness/health alerts, OpenClaw announce jobs. Sink: `communication_outbox` 74,400 rows (65,299 recorded / 8,445 suppressed / 450 sent), `telegram_outbox` 8,227. Why B/C: the single-channel chokepoint `telegram_alert.send_telegram` and the outbox suppression are the operator's protection against duplicate and phantom alerts; n8n's `emailSend*` nodes are excluded by env and the gateway forbids send routes. Benefit: one view of "sent / suppressed / withdrawn" with reasons. Risk: a second sender. Cost: none. Security: bot tokens stay rendered from Bitwarden.

### 1.6 Reporting and digests — class B (three pilots)

`llm_spend_report` (receipt `llm_spend_report_last_daily.json`), `morning-brief-0730` (`morning_brief_semantic_state.json`; the `sent` flag is not persisted by `deliver_morning` today), `material-change-digest` (`material_changes.change_guid` + `notify_outcome`), session reviews, goal-loop baseline, SLO burn rate, `maturity_remeasure`, `report_agent_number_grounding`, platform conformance nightly. Why B: these already write durable receipts n8n can reference by `artifact_ref` (store + path + sha256); nothing needs to move. Recovery: unchanged. Cost: zero.

### 1.7 Memory and learning — class C

`cio-nightly-reflection 21:50`, `cio-memory-shadow-measure 06:20`, `build_lesson_candidates`, outcome reconcilers (exit/pullback/watch, Sundays), `sweep_commitment_outcomes 18:20`, `write_instrument_beliefs 18:50`, `hermes_external_feedback_loop` (cap $2), `advisory_outcome_scorer`, `advisory_lessons reflect`, `resolve_due_checkpoints :20`, `gir_projector`, `edge_fanout_consumer`. Why C: these write the authoritative memory stores (`memory_fact_version`, `cio_decisions` 97,637, `agent_recommendation_registry` 528,350); AGENTS.md §0 rule 5 forbids a second authoritative copy. n8n chat memory / vector store nodes must stay off.

### 1.8 Agent loops — class C

CIO reactive 2 min, wake dispatch 5 min (`WAKE_L3_ALLOW_LIVE_PROVIDER=1`), persistent wake hourly, material scan 10 min, 13 `tradeai-agent-runtime@*` timers (SHADOW prepare-only), OpenClaw gateway + 13 internal jobs, `tradeai-ops-agent`, `watch_review_workers --role maria|cio`, `free_first_circulation`, `holdings-agent-enqueue`, `contradiction-adjudicator`, `aec-command-center-cycle`. Why C: high frequency, wake ledgers and approval gates live in Trade AI, OpenClaw has its own scheduler and Telegram delivery. Risk R11: an n8n copy adds a process without removing cron risk.

### 1.9 Health, monitoring, governance — class B (fan-in view), C for checks

20+ `--alert` timers (`expected-services :12`, `data-source-health :27`, `served-copy-split :42`, `gap-resolution :07/:37`, `operator-answer-quality :22/:52`, `research-lane-health 15 min`, `data-plausibility 06:20`), `supervisor_breach_detector 2 min`, `autonomy_watchdog 5 min`, `cio_bridge_watchdog */5`, `llm_provider_health :20`, `deepseek_balance_snapshot :50`, `postgres-main-watchdog`, conformance nightly, `check_expected_services`. Why B: each writes a receipt file; the gateway `list` op can project them as "waiting / breached / silent" with age. Why C for the checks: they read local state and lock files.

### 1.10 Backups, maintenance, secrets — class C

`tradeai-sm-render 4 h` (Bitwarden → tmpfs), portfolio backup/daily/weekly/monthly/lookthrough cadences (run the DEV tree pipeline), `db_retention`, disk guards, worktree retention, `sync-docs-to-drive :05`, `sync_code_mirror_to_drive :35`, `~/.claude/sync-memory-to-drive 03:10`, crontab snapshot `*/20`. Why C: secrets path and OAuth-bearing syncs. Note: `rotation_daemon.py` is unscheduled (gap, not an n8n matter).

### 1.11 Approvals and release — class B for the reminder pilot, C for authority

`approval_package_reminder :05` + reconcile `:12` (first natural receipts 2026-10-07 00:05/00:12 ET: `NO_ACTION`, served_sha stamped), `bin/guard` grants (9 scopes), Telegram `/approve`, `admin_write_guard`, exact-main deploy (`cio_phase2_exact_main_deploy.sh`, grant-bound, CI-bound). Why B: the reminder is the first pilot with run receipt + reconcile receipt; n8n references both. Why C: approval authority and release are operator-only (§17).

### 1.12 DOF (nyc-dof-auction) — class E, conditional B

`rescan_tickets.py 18:00`, `run_pipeline.py Sat 20:00`, `dof-dashboard.service` (Flask 0.0.0.0:7776, **no auth**, DSN uses the production `trade_ai` role), 22 `dof_*` tables in the production DB (`dof_ticket_events` 118,603, `dof_manual_queue` 1,775, `dof_enrichment_queue` 244 all pending), LLM router uses xAI grok-3-mini / Groq. Policy branch `wt/n8n-dof-policy-20261007` adds two docs only. Until (a) auth or loopback binding, (b) `dof_reader` role, (c) merged policy: `ACCESS_BLOCKED:no_separate_role`. After: B for queue-status projection and enrichment-run receipts; never the DB write routes.

### 1.13 Retire — class D

`deep_overnight_llm_queue` backlog (RETIRED lane, 1,928 pending rows), `at-observation-01` elapsed one-shots, stale n8n `instance.firstProductionSuccess`, `aegis-*` duplicates already RETIRED in the registry, `tradeai-reprice.timer` (inactive system timer). Also to reconcile, not retire: `tradeai-continuous` (PAUSED in registry, enabled at system scope), `alert-quality` (ACTIVE in registry, no cron line).

### 1.14 Class A — items to move fully into n8n

**None.** No discovered automation is better owned by n8n than by its current runtime once credentials, locks, caps, memory authority and send chokepoints are weighed. The lab's own two HTTP monitors are the only workflows that belong wholly in n8n, and they already run there.

---

## Section 2 — candidate pipeline inventory

| Tier | Item | Complexity | Risk | Value | Migration effort | Recommendation |
|---|---|---|---|---|---|---|
| **1 Immediate (shadow)** | Approval reminders (`approval-package-reminder`) status view | Low | Low | High (first lane with run + reconcile receipts) | 0.5 ed | Pilot 1, observe-only |
| 1 | LLM cost reporting (`llm-spend-report-daily`) receipt view | Low | Low | Medium | 0.3 ed | Pilot 2 |
| 1 | Morning brief delivery receipt (`morning-brief-0730`) | Low | Low (needs a persisted `sent` flag) | Medium | 0.5 ed | Pilot 3; add the flag in Trade AI first |
| 1 | Ops digests fan-in (OpenClaw `ops_daily_digest`, `ops_weekly_learning`, the 20 `--alert` receipts) | Low | Low | High | 1 ed | gateway `list` projection |
| 1 | n8n lab self-monitoring (healthz watchdog, nightly dump receipt) | Low | Low | Required | 0.3 ed | do first |
| **2 After pilot** | Material-change digest coordination (`material-change-digest`, detector event + suppression) | Medium | Medium (live notifier stays in code) | High | 1 ed | Pilot 4 |
| 2 | Research intake/routing receipts (`research-scheduler-holdings`, Hermes `run_id`) | Medium | Medium (cap bypass if it ever triggers) | High | 1 ed | Pilot 5 |
| 2 | Incident management view (`siem_critical_notify`, breach detector, bridge watchdog) | Medium | Low | Medium | 1 ed | after fan-in |
| 2 | Release evidence packets (deploy receipt, conformance gate receipt, CI receipt as artifact refs) | Low | Low | Medium | 0.5 ed | read-only assembly |
| 2 | Governed AI draft: material-change digest draft (`n8n_material_digest_draft`, $0.10/day) | Medium | Medium (registry PRO→Flash defect) | Medium | 1 ed | Phase 4 |
| **3 Future** | Case review queues (`options_approval_queue` blocked view, `high_llm_job_queue` 12 queued_for_review) | Medium | Medium | Medium | 1.5 ed | after a read DSN decision |
| 3 | Memory review queues (`escalation_queue`, `operator_review_queue`, `iris_hygiene_pending`) | Medium | High (memory authority) | Low | 2 ed | view only, maybe never |
| 3 | Document processing receipts (SEC filings feed, document mentions) | Medium | Low | Low | 1 ed | artifact refs only |
| 3 | DOF enrichment/manual queue view | Medium | High until role + auth | Medium | 1 ed | conditional |
| **4 Never** | Broker/positions/stops/orders (30 items), paper loop, options writers, memory writers, CIO/persona/OpenClaw loops, Telegram/Drive senders, secrets render, guard approvals, release deploy, DB retention/backups, price ingest | — | — | — | — | class C permanently |

---

## Section 3 — agent and LLM workflow placement

| Workload | Classification | Why |
|---|---|---|
| DeepSeek calls | SHOULD REMAIN EXTERNAL (Trade AI bridge) | Caps, reservations, off-peak pricing, circuit breaker and provenance live in `cio_governed_model_bridge` on loopback 8766; n8n cannot reach it, and must not hold the key |
| OpenRouter calls | n/a | ABSENT from the estate |
| Claude / OpenAI / Gemini calls | SHOULD REMAIN EXTERNAL; today CONFIGURED_NOT_PROVEN (0 cost events) | Keys exist in the rendered env only; adding them to n8n creates a second store for a path that is not even used |
| Local LLM (Ollama) | SHOULD REMAIN EXTERNAL | `*:11434` is already over-exposed; embeddings policy is an allowlist in Trade AI; the n8n bridge cannot reach it (timeout) and should stay unable to |
| RAG pipelines | SHOULD REMAIN EXTERNAL | pgvector unused, jsonb embeddings owned by Hermes; n8n vector-store nodes would create a second index |
| Reflection loops | SHOULD REMAIN EXTERNAL | write memory; nightly units exist |
| Research workflows | SAFE WITH GUARDRAILS (receipts only) | pilot 5 contract: `run_id` + `mode` or typed refusal; never a trigger |
| Multi-agent workflows | SHOULD REMAIN EXTERNAL | OpenClaw + bridge personas already orchestrate; n8n AI Agent node stays off (no credential, no memory) |
| Memory promotion workflows | SHOULD REMAIN EXTERNAL | `hermes-embedding-promotion-review`, `memory_fact_version` authority |
| Outcome evaluation workflows | SHOULD REMAIN EXTERNAL | outcome reconcilers and `advisory_outcome_scorer` write ledgers |
| Advisory generation | SAFE WITH GUARDRAILS, one job | `model_job` → `n8n_material_digest_draft` (nonfinancial, schema-validated, manual mode, $0.10/day, cost-joined). The only LLM call n8n may *request*; Trade AI makes it |
| Governed status/evaluation reads (`list`, `status`) | SAFE FOR N8N | read-only, signed, ledgered, forbidden-route list, no effects |

---

## Section 4 — can Bitwarden be used today?

**As the platform's master secret store: yes, it already is.** OBSERVED_SERVED: `bws` 2.1.0 at `~/.local/bin/bws`; `scripts/secrets/render_env.py` renders Bitwarden **Secrets Manager** project `trade-ai-prod` (128 SM keys → 118 shell keys) to tmpfs `/run/user/1000/tradeai/env` (dir 0700, file 0600) every 4 h (`tradeai-sm-render.timer`, last 14:03:52Z) and dual-writes the 0600 repo `.env` for legacy cron; 14 systemd units consume it by `EnvironmentFile`; 30 cron lines source `.env`; OpenClaw consumes a bws token via a drop-in and a `secrets.providers.bws` exec provider; `secret_registry.yaml` tracks 19 secrets with max ages; `check_no_secrets.py` runs in pre-commit, pre-push and `fast_check.sh`.

**Natively by n8n: no.** n8n's External Secrets feature is "available on self-hosted Business and Enterprise plans" (docs, community-edition-features page), and its provider list (docs reference HashiCorp Vault and Infisical for timeout behaviour; the full provider set beyond those two is NOT VERIFIED this session) does not include Bitwarden at any tier. The only Bitwarden integration n8n ships is an app node (`n8n-nodes-base.bitwarden`) for the organisation API, not Secrets Manager injection. On this instance `N8N_EXTERNAL_SECRETS*` is absent and `credentials_entity` is 0.

What specifically blocks it: (1) edition — Community has no external-secrets subsystem; (2) provider — Bitwarden SM is not an n8n external-secrets provider even on Enterprise; (3) policy — ADR `ADR_COORDINATION_SECRETS.md` (PROPOSED) and R2 forbid a native n8n credential becoming a second store.

Limitations of the current Bitwarden path (for completeness): rotation daemon unscheduled; one `~/.config/bws/state` file is 0664; disk `.env` dual-write means a 0600 copy exists outside tmpfs; token files live under `~/.openclaw/credentials` (0700/0600).

---

## Section 5 — open-source secret-store alternatives

Assumption: free/self-hosted n8n Community Edition, so **no** candidate can be wired into n8n's External Secrets feature. The comparison is therefore about replacing or complementing Bitwarden SM for the *platform*, with n8n fed only through the gateway (or at most one rendered credential).

| Option | OSS | Free | Self-hosted | Mature | n8n native (Community) | n8n native (Enterprise) | Rotation | Audit trail | RBAC | API | Fit here | Rank |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **External gateway model** (Bitwarden SM → `render_env` → Trade AI gateway; n8n holds nothing) | yes (Trade AI code) | yes | yes | served, tested | n/a (no secret in n8n) | n/a | via `render_env` + `_PREVIOUS` key overlap | gateway ledger (SQLite WAL) + `secret_registry.yaml` | guard scopes | HMAC claims | Already built, already served, zero new store | **Recommended** |
| Bitwarden Secrets Manager (keep) | client OSS; server SaaS | paid tier in use | no (SaaS) | yes | no | no | yes (API) | yes | yes (projects/access tokens) | yes | Master store today; one bws token per consumer | **Recommended** (keep as master) |
| Local encrypted env-file model (tmpfs render + 0600 disk copy) | yes | yes | yes | in use | indirect (compose `env_file`) | indirect | by re-render | file mtimes only | filesystem | none | The delivery layer, not a store | Acceptable (as delivery only) |
| OpenBao (Vault fork, MPL) | yes | yes | yes | maturing (2024+) | no | likely via Vault-compatible API (NOT VERIFIED) | yes | yes | yes | yes | Would replace Bitwarden SM; adds an unseal/HA burden on one host | Acceptable (only if leaving Bitwarden) |
| HashiCorp Vault (BSL since 2023) | source-available, not OSI | community free | yes | yes | no | yes | yes | yes | yes | yes | Licence changed; OpenBao is the OSS line | Not recommended |
| Infisical OSS (MIT core) | yes | yes | yes | yes | no | yes | yes | yes | yes | yes + agent/CLI env render | Closest drop-in for `render_env`; still no Community n8n hook | Acceptable |
| Doppler | no (SaaS; no OSS self-host) | tier | no | yes | no | no (not a listed provider; NOT VERIFIED) | yes | yes | yes | yes | cloud; violates "prefer self-hosted" | Not recommended |
| Kubernetes secrets | yes | yes | yes | yes | no | no | manual | k8s audit | k8s RBAC | k8s API | No Kubernetes on this host | Not applicable |
| SOPS + age (Git-encrypted files) | yes | yes | yes | yes | no | no | manual re-encrypt | git history | git | none | Good for versioned config secrets (compose `.env`), not runtime injection | Acceptable (narrow) |
| Vaultwarden (Bitwarden-compatible server, AGPL) | yes | yes | yes | yes | no | no | manual | limited | org-level | password-manager API only | Password vault for humans; **no Secrets Manager API** for machines | Not recommended for this purpose |
| n8n built-in credential store (AES at rest, `N8N_ENCRYPTION_KEY`) | yes (n8n) | yes | yes | yes | yes | yes | manual | execution logs | owner only (Community) | internal | Becomes a second store the moment it holds one value | Not recommended beyond the ADR's single scoped key |

Discovered on host: none of OpenBao, Vault, Infisical, Doppler, SOPS, age, Vaultwarden (`docker images`, `which`, `/opt`, `/usr/local/bin` — all empty). Installing any of them is new infrastructure.

---

## Section 6 — best secret-management architecture for this environment

Requirements met: lowest cost (no new service), open source where new code is written (Trade AI), self-hosted (everything but the Bitwarden SM master, which is already licensed and in use), production-suitable (tmpfs render, 0600, grant-bound), scales (one bws access token per consumer project), supports AI workflows (bridge caps), API integrations (HMAC claims), workflow automation (gateway ops).

```
                 Bitwarden Secrets Manager (master; project trade-ai-prod)
                               │  bws access token per consumer (0600 files)
          ┌────────────────────┼─────────────────────────┐
          ▼                    ▼                         ▼
  render_env.py (4h timer)   OpenClaw bws exec        n8n-gateway.env render
  → /run/user/1000/tradeai/   provider (gateway)       (TRADEAI_N8N_GATEWAY_HMAC_KEY
    env  0700/0600                                      + _PREVIOUS) 0600, tmpfs
          │                                                   │
  systemd EnvironmentFile (14 units)                tradeai-n8n-coordination-gateway.service
  cron `. ./.env` (30 lines)                        127.0.0.1:18091  (PROPOSAL; not installed)
  cio-governed-bridge 127.0.0.1:8766                 ├ HMAC claim: v, caller_id, project, iat,
          │                                          │   exp (≤300 s), nonce ≥8, scope=coordination_read
  providers: DeepSeek key, broker keys,              ├ forbidden routes: broker/order, grant, 2fa, promote, bid…
  Telegram tokens — never leave this side            ├ ops: status, accept_event, claim, start, artifact(ref),
                                                     │   consumer_ack, refuse, cancel, list, model_job
                                                     └ SQLite WAL ledger (nonces, events, effects, receipts)
                                                                   ▲ signed requests, opaque references only
                                                  n8n 2.43.0 (127.0.0.1:5678, bridge 172.19.0.0/16)
                                                  0 credentials  ──or──  ONE Header-Auth credential
                                                  (ADR decision 1: scope coordination_read, 5 lanes, weekly rotation)
```

**Credential flow.** Secrets are created and rotated in Bitwarden SM. `render_env.py` pulls them into tmpfs; systemd and cron read the rendered file; provider calls happen only inside Trade AI. n8n receives no provider, broker, DB or messaging credential. If ADR decision 1 is accepted, n8n holds exactly one Header-Auth credential whose value is the gateway HMAC seed, stored in n8n's AES-encrypted credential table (`N8N_ENCRYPTION_KEY`, itself escrowed in Bitwarden SM). If rejected, the source-side dispatcher signs every claim and n8n stays a reader with zero credentials.

**Authentication flow.** Caller → signed claim (HMAC over v/caller_id/project/iat/exp/nonce/scope) → gateway verifies signature, rejects replayed nonces from the ledger, ignores peer address and proxy headers, enforces `expected_origin_sha`, refuses forbidden routes by name, and records a typed receipt. Loopback is not an identity (ADR threat model).

**Rotation flow.** Weekly: new seed minted in Bitwarden SM → `render_env` writes `TRADEAI_N8N_GATEWAY_HMAC_KEY` and moves the old value to `_PREVIOUS` → gateway accepts both for one overlap window → n8n credential updated (if it exists) → previous removed. Platform secrets: `secret_registry.yaml` max ages (90/180 d) enforced by scheduling `rotation_daemon.py` (today unscheduled).

**Backup flow.** Bitwarden SM is the backup of record for values. Locally: nightly `pg_dump` of the n8n DB (encrypted credential rows are useless without the escrowed key, which is the point), weekly drill, dumps under `persistent-state/backups/n8n/` and mirrored by the existing hourly Drive sync of docs only if explicitly added. The tmpfs render is not backed up by design; it is reproducible from SM.

**Recovery flow.** Host loss: reinstall bws, restore the access-token files from Bitwarden, run `render_env.py --now`, start units; n8n: recreate compose, restore the dump, set `N8N_ENCRYPTION_KEY` from escrow, re-render the gateway env, verify `/healthz` reports `durable: true`. Compromise: revoke the bws access token in SM (one consumer at a time), rotate affected secrets, re-render, restart.

**Why this is superior here.** It adds no service to a single 84 %-full host; it keeps one authority (`data_source_authority.json`, Bitwarden SM) per fact; it is the only design that works with n8n Community at all; it is already written, tested (durable ledger, nonce replay, forbidden routes, typed refusals) and served at 60863d207; and its single open decision (one scoped key or none) is small enough to be reversible in a day. OpenBao or Infisical would be justified only if Bitwarden SM licensing ends, and even then n8n's integration would not change.

---

## Section 7 — final recommendations

**Q1 Which exact processes should move into n8n immediately?** None as owners. Immediately as *shadow coordination*: `approval-package-reminder`, `llm-spend-report-daily`, `morning-brief-0730` (after persisting the `sent` flag), plus the health `--alert` fan-in and the lab's own watchdog/backup receipts.

**Q2 Which processes should never move into n8n?** The 30 broker/positions/stop/order items (§1.1), paper trading, options writers, data ingest, memory/learning writers, CIO/persona/OpenClaw loops, every sender (Telegram, Drive), `sm-render`, guard approvals, release deploy, retention/backups.

**Q3 Which LLM workflows belong inside n8n?** Only the request for `n8n_material_digest_draft` through the gateway `model_job` op, executed by Trade AI under the $0.10/day cap, and read-only `status`/`list`.

**Q4 Which LLM workflows should stay external?** All provider calls (DeepSeek, Grok/ChatGPT OAuth lanes, Anthropic/OpenAI/Gemini if ever used, Ollama), RAG, reflection, memory promotion, outcome evaluation, multi-agent orchestration.

**Q5 Can Bitwarden remain the master secret store?** Yes. It is the master today for 128 keys and should stay so. It cannot be wired into n8n Community, and nothing in the recommended design needs it to be.

**Q6 If not, what open-source replacement?** Not needed. If Bitwarden SM were abandoned: OpenBao (OSS Vault line) or Infisical OSS as the master, with the same `render_env`/gateway delivery; neither improves n8n integration on Community.

**Q7 Best free/open-source secret architecture?** Section 6: Bitwarden SM master → tmpfs render → systemd/cron → Trade AI gateway with HMAC claims → n8n holds zero or one scoped credential.

**Q8 Lowest-risk migration strategy?** No migration of ownership. Observe-only pilots with two natural fires each, refusals proven at the gateway, weekly per-lane reports for four weeks, then coordinator-of-record for the status view only. Close S1 (`:7777` open auth) and S2 (DOF) before the gateway unit is installed, because the lab bridge can reach both.

**Q9 Top 20 implementation tasks**
1. Set `API_AUTH_TOKEN` from Bitwarden SM; make unset fail closed on `:7777`.
2. DOF: auth or loopback bind on `:7776`; `dof_reader` role; merge the policy branch.
3. Install `tradeai-n8n-lab-watchdog.timer`.
4. Compose: healthcheck, `SAVE_ON_SUCCESS=none`, prune 168 h, `N8N_WEBHOOK_URL`, PG17 on recreate, non-superuser DB role, `internal` network + explicit gateway alias.
5. Nightly n8n `pg_dump` + weekly restore drill; escrow `N8N_ENCRYPTION_KEY` in SM.
6. Owner MFA; owner password into SM.
7. Decide ADR decision 1 (one scoped Header-Auth key, or none).
8. Render `n8n-gateway.env` from SM; install the gateway unit (service grant).
9. Pilot dispatcher cron (`n8n_pilot_dispatch.py`) for five lanes (cron grant).
10. Persist the morning-brief `sent` flag in `deliver_morning`.
11. Workflow JSON export script → `docs/implementation/n8n-parallel/workflows/`.
12. Error workflow → lab ledger row (no send).
13. Command Center projection page from `/api/v2/coordination/events`.
14. Health `--alert` receipt fan-in through the gateway `list` op.
15. Pilot 4 material-change digest (detector event + suppression) and pilot 5 research handoff.
16. Phase 4 model job on held-out fixtures; fix the PRO→Flash registry mapping first.
17. Schedule `rotation_daemon.py`; fix the 0664 bws state file; re-pin units on `a032116e7`/`6b9a6226c`; fix `/etc/tardeai` typo.
18. Registry truth: `tradeai-continuous` (PAUSED vs enabled), `alert-quality` (ACTIVE vs absent), declare the 29 agent-runtime/hermes timers.
19. Retire the `deep_overnight_llm_queue` backlog and the stale n8n settings row.
20. Weekly per-lane report ×4 → Phase 5 decision packet.

**Q10 First 30 days, starting tomorrow (2026-10-08)**
- Days 1–3: tasks 1–6 (hardening; each needs one operator grant); two nightly dumps and watchdog receipts observed.
- Days 4–7: tasks 7–9, 11–12; gateway `/healthz durable: true`; first ledger rows from pilots 1–2.
- Days 8–14: tasks 10, 13, 14; pilots 1–3 each with two natural fires; first weekly report.
- Days 15–21: task 15 (pilots 4–5); refusal proof with a deliberately misconfigured workflow; second weekly report.
- Days 22–30: tasks 16–19; model-job fixtures on served; third and fourth weekly reports; Phase 5 decision packet drafted. Not in 30 days: any lane cutover, any credential beyond the ADR's one key, DOF in n8n unless tasks 2 is complete.

### Final architecture and migration roadmap

```
 Phase 0 census ──► Phase 1 harden (S1,S2, lab baseline) ──► Phase 2 gateway unit + dispatcher + projection
     done               days 1–3                                   days 4–14
                                                                        │
                           Phase 3 shadow pilots 1–5 (two natural fires each, refusal proof)  days 8–21
                                                                        │
                           Phase 4 one governed model job (manual → automated on evidence)   days 22–30
                                                                        │
                           Phase 5 coordinator-of-record for STATUS only, after 4 weekly reports
                           (execution, sends, memory, broker, secrets: unchanged, forever class C)
```
