# Platform Autonomy Chain Audit — End-to-End Investment / Decision Autonomy

**Date:** 2026-08-02 (evidence frozen evening ET; some Hermes overnight jobs ran into 2026-08-03 UTC)  
**Scope:** READ-ONLY. Trees: `tradeai-wt-cursor-guardrails` (audit workspace) + live `trade-ai-v12-rebuild/trade-ai-v12-rebuild`. Live API: `http://127.0.0.1:7777`.  
**Sources:** `ARCHITECTURE.md`, key scripts under `scripts/`, `config/*`, live `crontab_backup.txt` / crons, runtime JSON under rebuild `data/` + `state/`, logs under rebuild `logs/`, `docs/audits/platform-autonomy-2026-08-02/evidence/{api_smoke,env_freeze}.txt`.

**Legend**

| Label | Meaning |
|-------|---------|
| **Auto** | Scheduled/code path runs without a human click; outcome is applied to DB/config/orders as designed |
| **Semi** | Auto produces state or candidates; a human gate, review_mode, SHADOW mode, or operator config is required for capital impact (or only a subset of the hop is automatic) |
| **Human-required** | No autonomous path; operator must act |
| **Broken** | Intended path fails, starves, or is mis-wired in practice (even if design docs claim Auto) |

---

## 0. Deploy reality (multi-tree) — must read first

| Fact | Evidence |
|------|----------|
| Live process is **ad-hoc**, not systemd | `env_freeze.txt`: pid `4044954`, cwd → `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`, cmd `.venv/bin/python scripts/portfolio_server.py --port 7777` |
| systemd `portfolio-server.service` | **inactive (dead)** since 2026-08-02 13:31:43 EDT; last unit pointed at release tree `…/trade-ai-releases/portfolio-server/7ea3db55-cio-propose-block-20260801-1350/` |
| Release pin | `7ea3db55-reentry-decision-desk-20260801-1048` / SOURCE_COMMIT under `7ea3db55-cio-propose-block-…` — **not** the live process |
| Guardrails git | `dcafb411` (feat data-broker watchlist wrappers) |
| Rebuild git (live cwd) | `72b6ddd2` (DeepSeek frontend wiring) — **diverged** from guardrails |
| Live API health | `GET /health` ok; `GET /api/v2/overview` 200; portfolio ~$1.26M |
| Endpoint holes in smoke | Several smoke paths 404 (`/api/v2/agents/maturity`, `/agent-runtime/status`, `/research-intelligence/desk`, `/watch/scoreboard`, `/system/llm`, `/consumption/summary`, `/health/snapshot`) — wrong path and/or missing routes on live tree; **not** a full feature freeze |

**Brutal read:** There is no single authoritative deploy. Crons, ATM, Hermes, and “the UI” all share rebuild’s data/logs, but code/docs live in at least three places (guardrails worktree, rebuild tree, pinned release 7ea3db55). That alone caps trustworthy autonomy: the system can improve in a tree that is not serving traffic.

---

## 1. Hop map (12 hops)

### 1. Discover trends — **Auto** (with intentional shadow feeders)

| | |
|--|--|
| **Verdict** | **Auto** for core intake; some discovery feeders remain SHADOW/config-disabled |
| **What runs** | Finviz screeners (multiple market-hour slots), Finviz market movers, incubator LLM screener, Hermes directive discovery, discovery ingestors (source/trend/ticker/topic), entity-spike + tag-lift, hermes coordinator/worker pool, think-tank, YouTube discovery, social→scalp scan |
| **Evidence (files)** | `scripts/finviz_screener_runner.py`, `scripts/hermes_discovery_ingestors.py`, `scripts/hermes_directive_discovery.py`, `scripts/hermes_entity_spike_discovery.py`, `scripts/hermes_tag_lift_discovery.py`, `scripts/run_finviz_momentum_scalp_scan.py`, `config/hermes_discovery_schedule.json` |
| **Evidence (cron)** | `0 7,8,10,12,14,16,18 * * 1-5` finviz; `*/5 6-11` momentum scalp; `0 */2` hermes_discovery_ingest; `*/30` directive discovery; `15 */3` entity-spike; `50 3` tag-lift; etc. (`crontab_backup.txt` on rebuild) |
| **Evidence (runtime)** | Discovery ingest log shows scheduled runs with caps/skipped_reasons; `config/hermes_discovery_schedule.json`: `enabled: true`, analyst_signal on, **industry_novelty_enabled: false**, **llm_review_enabled: false** |
| **Human** | Operator enables shadow feeders; caps/do-no-harm pause; operator-created candidates bypass caps |

**Honesty:** Discovery throughput is real and continuous. It discovers *candidates*, not investment decisions.

---

### 2. Research trends — **Auto**

| | |
|--|--|
| **Verdict** | **Auto** (budgeted, priority-gated) |
| **What runs** | `research_scheduler.py` (holdings / priority / watchlist / cold-floor / incubator), `process_watchlist_agent_jobs.py`, Hermes research worker pool, news bridge, subject enhance (Grok/ChatGPT), CIO dual consensus backfill, analyst coverage, scalp catalyst researcher |
| **Evidence (files)** | `scripts/research_scheduler.py`, `scripts/process_watchlist_agent_jobs.py`, `scripts/hermes_research_worker_pool.py`, `scripts/hermes_news_bridge.py`, `scripts/hermes_subject_enhance.py` |
| **Evidence (cron)** | Holdings 08:00 / 12:30 / 16:30; priority hourly 10–16; watchlist 20:30; cold-floor 02:00; agent jobs multi-cadence; worker pool hourly |
| **Evidence (API/runtime)** | Outcome bus: `throughput_research_rows_7d: 1329`, `hermes_api_calls_7d: 6724` (`state/hermes/outcome_bus.json`, generated 2026-08-02) |
| **Human** | Budget knobs, `llm_priority_guard`, kill switch `data/runtime/HERMES_DISABLED`, manual `/api/v2/research-intelligence/run-topic` |

**Honesty:** Research is the strongest autonomous leg. It is also where most “intelligence” *stops* before money moves.

---

### 3. Generate investment ideas — **Semi**

| | |
|--|--|
| **Verdict** | **Semi** — auto generation exists; funnel is narrow and multi-gated before a durable idea exists |
| **What runs** | `auto_proposal_generator.py` (strategy signals → PENDING paper proposals); `watchlist_proposal_bridge.py` (BUY/STRONG_BUY → dual-lane proposals); scalp scan `--generate-proposals`; options strategy scanner; defense paper twins; RI staged ideas (API promote) |
| **Evidence (files)** | `scripts/auto_proposal_generator.py` (“Does NOT approve trades or submit orders”); `scripts/watchlist_proposal_bridge.py`; `config/watch_lane_admission.json` `proposal_bridge.require_main_go: true` |
| **Evidence (cron)** | `*/30 9-16` auto_proposal; `*/30 10-15` watchlist_proposal_bridge max-new 5; finviz scalp with generate-proposals |
| **Evidence (logs/API)** | 2026-07-31 auto_proposal: `checked=5 created=0` (all filtered: strategy criteria / no analyst / low score); watchlist bridge sample: `candidates=771 created=11 refreshed=13 skipped=1516`; API paper-proposals summary: **pending=7, ready_count=0** (`api_smoke.txt`) |
| **Human** | RI stage/promote POST; strategy YAML allowlists; MAIN GO admission; operator force paths |

**Honesty:** Idea *machinery* is automated. Idea *yield into execution-ready form* is thin (historical supply audit: 0.7% proposal→paper link rate in June; ATM approvals still rare in July).

---

### 4. Validate ideas — **Auto** (gates) / **Semi** (agent + cloud oversight)

| | |
|--|--|
| **Verdict** | **Auto** for deterministic gates; **Semi** for multi-agent / cloud second opinion on promote path |
| **What runs** | `proposal_enrichment_loop.py` (price/technicals/catalyst/readiness); `proposal_decision_gate.py` (states: APPROVE_READY_PAPER_TEST … BLOCKED_BY_RISK_GATE); `proposal_route_risk_gate.py` fail-closed; Finviz technical gate in ATM; LLM review worker (analysis-only); agent reviews Maria/Risk/Steph for broker promote; `broker_promote_oversight.py` |
| **Evidence (files)** | `scripts/proposal_decision_gate.py`, `scripts/proposal_route_risk_gate.py`, `scripts/proposal_enrichment_loop.py`, `scripts/proposal_llm_review_worker.py` (“LLM is ANALYSIS ONLY — cannot approve”), `scripts/broker_promote_oversight.py` |
| **Evidence (cron)** | enrichment `*/10 4-19`; LLM review worker `*/30 6-19`; **no dedicated `proposal_agent_review` cron line** in `crontab_backup.txt` (agents appear to be queued from enrichment / API paths — fragile coupling) |
| **Evidence (logs)** | ATM often defers `not yet enriched, status=IN_PROGRESS` (validation incomplete → no auto-approve) |
| **Human** | First-sample override env; force_approve/skip; cloud oversight env flags; options desk manual review |

**Honesty:** Validation is real and fail-closed. It is also the choke: incomplete enrichment + technical gates convert “generated ideas” into permanent PENDING.

---

### 5. Prioritize opportunities — **Semi**

| | |
|--|--|
| **Verdict** | **Semi** — ranking/scoring is automatic; the weights that sort **MAIN** trading setup are **locked** against learning |
| **What runs** | Hermes watchlist scorer (tier cadence); unified edge score in auto_proposal; strategy priority list; scope tiers S0–S3; defense rec ranking; rec-intel lineage analytics |
| **Evidence (files)** | `scripts/hermes_watchlist_scorer.py`; `config/hermes_score_weights.yaml` **`locked: true` + `graft_forbidden: true`**; research profile `config/hermes_score_weights_research.yaml` (last auto-grafted 2026-07-17) |
| **Evidence (cron)** | scorer `*/15 * * * *`; scope governor `7,37 * * * *` |
| **Evidence (API)** | rec-intel summary: watchlist **5015 tickers / 0 executed**, scan **763 / 0 executed**, proposal **640 / 64 executed** — prioritization produces volume; capital follow-through is almost only from the proposal lane |
| **Human** | Locked main weights; operator suppressions in defense config; defensive lean directives |

---

### 6. Update watchlists — **Semi**

| | |
|--|--|
| **Verdict** | **Semi** — scoring + scope_tier updates auto; lifecycle promote/demote largely **review_mode** |
| **What runs** | scope governor sole owner of `watchlist_items.scope_tier`; watchlist enrichment sweep; hygiene; TOS ingest; entry planner; materialize strategy cards; bridge rejects when rating drops below BUY |
| **Evidence (files)** | `scripts/hermes_scope_governor.py`, `scripts/lib/hermes_scope_governor/watchlist_lifecycle.py` (default `review_mode: true`), `scripts/watchlist_enrichment_sweep.py`, `scripts/watchlist_hygiene.py` |
| **Evidence (cron)** | scope governor every 30m; enrichment `*/30 9-15` + post-close; hygiene weekly |
| **Evidence (runtime)** | Scope governor snap 2026-08-03: lifecycle `watch=3039 promoted=728 demoted=253 blacklisted=245`, **`pending_count=155`, `review_mode: true`**; holdings lifecycle also `review_mode: true` |
| **Human** | Lifecycle review backlog; star/hide/dismiss on desks; operator directives; ToS file drops |

---

### 7. Adapt to sector rotation — **Semi** (detect Auto / act Human+SHADOW)

| | |
|--|--|
| **Verdict** | **Semi** trending **Human-required** for real capital |
| **What runs** | `rotation_autopilot.py` (IWM/SPY RS → small-cap bridge + auto_proposal + Telegram); `sector_momentum_engine.py`; `finviz_sector_research.py`; industry groups; `defense_recommendations.py` (get_into / protect / short_side / income cards + paper twins); rotation rebalance digest |
| **Evidence (files)** | `scripts/rotation_autopilot.py`, `linux_launchers/run_rotation_autopilot.sh`, `scripts/defense_recommendations.py` (“Advisory/paper only”), `config/defense_recommendations.json`, `config/promote_criteria.json` **`criteria_locked: true`** |
| **Evidence (cron)** | rotation autopilot `*/15 4-16`; sector momentum 17:25; defense recs 17:50; finviz sector 10:15/16:15 |
| **Evidence (API/runtime)** | `GET /api/v2/defense/recommendations`: **`mode: "SHADOW"`**, shadow_note “all groups SHADOW — 10-trading-day window from 2026-07-18; Telegram only after promote”; momentum snapshot as_of **2026-07-31** (stale into weekend audit). Paper twins created (PSQ, NGG, CMS) but ATM then deferred **`account alpaca_paper disabled`** |
| **Human** | Promote criteria adjudication; operator suppressions (e.g. BND/SPCX hold); defensive lean panel 2026-07-18; cost-basis export; options_level config; any live trim/rotate |

**Honesty:** Sector intelligence is sophisticated and largely autonomous. **Zero autonomous portfolio rebalancing** against real accounts. Ladders fire in shadow while positions sit until a human sells.

---

### 8. Surface recommendations (UI) — **Semi** (partial Broken surface)

| | |
|--|--|
| **Verdict** | **Semi** — core hubs work; several “maturity/ops” smoke paths 404; recommendations are advisory UI |
| **What runs** | Command Center v3 hubs (portfolio, trading, watch, hermes, rotation, rec-intel, intelligence); card v4; Hermes closed-loop panel; defense desk; paper/broker proposals |
| **Evidence (files)** | `ARCHITECTURE.md` §3; `apps/command-center-v3`; `scripts/api_v2.py` (hermes, paper-proposals, defense, rec-intel, research-intelligence) |
| **Evidence (API)** | 200: overview, watchlist/items, defense/posture, defense/recommendations, hermes/maturity-dashboard, rec-intel/summary, paper-proposals, atm/status. 404: agents/maturity, agent-runtime/status, research-intelligence/**desk** (route is `/api/v2/research-intelligence` without `/desk`), watch/scoreboard, system/llm, consumption/summary, health/snapshot |
| **Human** | Operator must open UI / Telegram to act; no auto-execution from recommendation cards |

**Honesty:** Surfacing works for the main trading narrative. Ops/maturity endpoints and path mismatches create a **false sense of broken intelligence** vs. missing route aliases. Multi-tree UI build (`ui_version` 3.14+…) may not match guardrails source.

---

### 9. Monitor outcomes — **Auto**

| | |
|--|--|
| **Verdict** | **Auto** (grade → bus → alerts; capital changes still human) |
| **What runs** | Nightly: outcome grader → tag engine → outcome feedback agent → outcome learning; score history retention; health agent; pipeline freshness; journal analytics; options paper outcomes; round-trip / ladder state for defense; rec-intel lifecycle |
| **Evidence (files)** | `scripts/hermes_outcome_grader.py`, `hermes_tag_engine.py`, `hermes_outcome_feedback_agent.py`, `hermes_outcome_learning.py`, `scripts/health_agent.py` |
| **Evidence (cron)** | grader 02:50; tags 03:05; feedback 03:25; learning 03:35; maturity snapshot 07:20 |
| **Evidence (runtime)** | `outcome_bus.json`: 25 324 graded claims / 90d; promotion hit-rate 0.41; research actioned hit-rate 0.832; trade hit-rate 1.0 on tiny sample (`avg_realized_r_trades_90d: 0.539`) |
| **Human** | Journal annotation quality; holdings share-count imports for real-book truth |

---

### 10. Improve future decisions (does learning CHANGE behavior?) — **Semi / mostly No for money path**

| | |
|--|--|
| **Verdict** | **Semi** — learning **does** change research ranking / source retirement / lane usefulness / scope edges; it **does not** rewire MAIN setup weights or live gates. Threshold learning is **review_mode: true** |
| **What runs** | `hermes_outcome_learning.py` (weights suggestions, promotion thresholds, source retire/reinstate, lane usefulness); `hermes_autonomous_self_tune.py` (auto-graft + purge); scope governor reactions; journal coach/critique (advisory) |
| **Evidence (files)** | Learning header: “Advisory-only”; self-tune: “Main weights stay locked; graft research_intel only”; `config/hermes_thresholds.yaml` `learning.review_mode: true`; `config/hermes_score_weights.yaml` locked |
| **Evidence (logs)** | 2026-08-02 learning run retired low-yield domains (apnews, cnbc, …); lane hit-rates recorded; self-tune produced eligible graft deltas on research profile factors; purge truncated dead tables |
| **Evidence (config)** | Research weights `auto_grafted_at: 2026-07-17` — **not freshly grafted on every night**; main weights frozen |
| **Does it change behavior that allocates capital?** | **No for live. Weak for paper MAIN.** Paper ATM still uses locked gates + fixed strategy filters + min_classifier_health temporarily 0.0. Research scoring drift may change what gets researched/watched, not what ATM auto-buys tomorrow. |

**Brutal answer to the audit question:** Learning changes **Hermes research behavior and watchlist pressure**, not the **investment decision policy** that would matter for a 9/10 autonomous allocator. Calling this a “closed loop” without main-weight or gate adaptation is marketing over engineering.

---

### 11. Paper execute — **Broken** (design: Auto; practice: starved / mis-accounted)

| | |
|--|--|
| **Design** | **Auto** when ATM `mode=active`: `atm_auto_approver` → `approve_proposal` → `submit_paper` → `alpaca_paper_adapter` (paper-api only, `ENABLE_ALPACA_PAPER=true`) |
| **Live ATM status** | API: `mode: "active"`, last state change 2026-05-22 by `john-approved` |
| **Env** | rebuild `.env`: `ENABLE_ALPACA_PAPER=true`, `ALPACA_MODE=paper` |
| **Evidence (files)** | `scripts/atm_auto_approver.py`, `scripts/alpaca_paper_adapter.py` (hardcodes paper URL), `scripts/proposal_paper_submitter.py` (“Live trading is permanently blocked”), `config/atm_config.yaml` (tradeai_automated enabled) |
| **Evidence (cron)** | `*/15 4-19 * * 1-5` atm_auto_approver via market_day_gate |
| **Evidence (logs)** | Last session 2026-07-31: cycles with **0 approved**; defense twins PSQ/NGG/CMS deferred **`account alpaca_paper disabled`** (target not in ATM enabled accounts — only `tradeai_automated` is); many cycles deferred enrichment. Full `atm.log` grep for `1 approved`: **handful of cycles across June–July** (e.g. 2026-07-02, 07-21, 07-23) |
| **Historical funnel** | `docs/audits/PROPOSAL_SUPPLY_AUDIT_2026-06-26.md`: ATM approved 2 in 5 days; 0.7% link to paper trade |
| **Verdict** | **Broken** as an autonomous paper-validation engine: the wire exists, flags are on, but **supply + account routing + enrichment** prevent steady autonomous fills. Architecture claim “paper trading is fully autonomous” is **true as a code path, false as an operating system**. |

Options paper lane is a separate **Human-required** confirm for Alpaca options paper (`alpaca_paper_options_executor` needs operator confirm; validation gate never auto-enables live).

---

### 12. Live execute — **Human-required** (by design; not a defect)

| | |
|--|--|
| **Verdict** | **Human-required** |
| **What blocks** | `brokers/execution_guard.py`: Schwab default **`BROKER_DISABLED`**; live unlock needs env + DB controls + standing approvals + **per-order 2FA** (`approval_service.py`, `REQUIRED_CHANNELS` default 1 of web/Telegram); `broker_promote_oversight` before queue; SnapTrade Fidelity **read-only**; 401k never tradeable |
| **Evidence** | Guard module docstring; ARCHITECTURE.md § maturity; `BROKER_LIVE_ENABLED=true` in env is **insufficient alone** (guard still fail-closed without standing unlock + 2FA + mode path) |
| **Protective stops** | Standing unlock path exists for protective sells only; still per-order 2FA |
| **Human** | Every live order confirmation; promote-from-paper decisions; unlock/arm ceremonies |

---

## 2. System-by-system summary (from ARCHITECTURE.md keys)

| System | Autonomy | Notes |
|--------|----------|-------|
| **atm_auto_approver** | Design Auto / Practice Broken | mode=active; rare approvals; wrong-account deferrals |
| **alpaca_paper_adapter** | Auto if reached | Paper-only, env-gated, live endpoint hard-blocked |
| **proposal pipeline** | Auto generate+enrich; Semi approve | LLM cannot approve; ATM is approver for paper |
| **execution_guard** | Fail-closed Human | BROKER_DISABLED default |
| **approval_service / 2FA** | Human | Per-order; required channels=1 |
| **Hermes** | Auto advisory | Never touches orders/status/gates/2FA |
| **proposal_decision_gate** | Auto advisory to ATM | States drive readiness, not live |
| **broker_promote_oversight** | Semi | Agents + optional cloud before live queue |

---

## 3. Complete human intervention point list

1. **ATM global mode** — enable/pause/disable (`atm_state`; last change operator 2026-05-22).  
2. **ATM force_approve / force_skip / force_reject** per proposal.  
3. **Account automation policies** — which accounts are AUTO_PAPER / enabled for ATM.  
4. **ENABLE_ALPACA_PAPER / ALPACA keys** — paper adapter arming.  
5. **Broker live unlock stack** — `BROKER_LIVE_ENABLED`, `broker_live_enabled` control, standing unlock, pilot arm, live approvals rows.  
6. **Per-order 2FA** — web typed-ticker and/or Telegram code (`approval_service`).  
7. **Paper→broker promote** — oversight agents complete + operator promote action.  
8. **Hermes discovery promote** — operator transitions to `APPROVED_RESEARCH_*` / strategy config accept.  
9. **Options strategy paper submit** — desk two-step / CLI `--confirm`; live options path locked.  
10. **Options validation gate met** — still “operator decision required”; no auto-enable.  
11. **Defense / GG / move-out / ladder Telegram promote** — SHADOW until promote criteria met + operator decision (`promote_criteria.json` locked).  
12. **Defense operator suppressions** — mute trim cards (BND, SPCX, etc.).  
13. **Defensive lean / sector destination policy** — operator panel directives.  
14. **Hermes threshold proposals** — `review_mode: true` (no auto-apply).  
15. **Watchlist / holdings lifecycle promotions** — `review_mode: true` backlog (155 pending snapshot).  
16. **Main Hermes score weights** — locked; human would have to unlock to let learning drive MAIN.  
17. **Strategy config edits** — YAML strategies, ATM whitelist/blacklist, admission policy.  
18. **Discovery schedule toggles** — industry novelty, llm review, pause.  
19. **HERMES_DISABLED kill file**.  
20. **Holdings share-count truth** — `/api/import` only; broker sync does not rewrite shares.  
21. **Cost basis / fund lookthrough / options_level config** — defense desk operator checklist items.  
22. **Protective stop standing enable** + still 2FA per submit.  
23. **Fidelity / SnapTrade** — read-only; any future trade path commit + confirm.  
24. **Systemd release deploy / server process ownership** — human restarts ad-hoc vs unit.  
25. **RI staged idea promote** — POST promote (human or explicit agent action).  
26. **Journal coaching adoption** — lessons do not auto-change gates.  
27. **Telegram action on advisories** — most high-signal channels still notify rather than act.  
28. **Cloud oversight env** — require cloud opinions for live.  
29. **First-sample / backtest override** — opt-in env for thin history.  
30. **KEY ROTATION / secrets** — called out on defense operator_items (repo publicity).

---

## 4. Autonomy scorecard (weighted)

Weights reflect contribution to **investment intelligence that can reallocate capital**, not research vanity metrics.

| Hop | Weight | Score 0–10 | Weighted |
|-----|-------:|-----------:|---------:|
| 1 Discover trends | 8% | 9 | 0.72 |
| 2 Research trends | 10% | 8.5 | 0.85 |
| 3 Generate ideas | 10% | 5 | 0.50 |
| 4 Validate ideas | 10% | 6.5 | 0.65 |
| 5 Prioritize | 8% | 5 | 0.40 |
| 6 Watchlists | 7% | 6 | 0.42 |
| 7 Sector rotation | 10% | 3.5 | 0.35 |
| 8 Surface UI | 5% | 6 | 0.30 |
| 9 Monitor outcomes | 7% | 8 | 0.56 |
| 10 Learn → behavior | 12% | **2.5** | 0.30 |
| 11 Paper execute | 8% | **3** | 0.24 |
| 12 Live execute | 5% | 1 (intentional) | 0.05 |
| **Total** | 100% | | **~5.3 / 10 raw → round 5/10** |

### Overall investment-intelligence autonomy: **5 / 10**

**Why not higher**

- Sensing + research autonomy is genuinely strong (7–9).  
- The chain **breaks at convert-to-capital**: idea yield, enrichment readiness, ATM account routing, SHADOW defense, locked main weights.  
- Learning is **not** allowed to change the scoring policy that sorts the trade desk (main weights locked; thresholds review-only).  
- Live is deliberately non-autonomous (correct safety posture, but it caps “platform autonomy”).  
- Multi-tree deploy means “what the code says” and “what runs” are not the same machine of record.

**Why not lower**

- Paper path is real code with real occasional fills.  
- Scope/source/lane learning does change research resource allocation.  
- Fail-closed live design is mature and intentional, not accidental incomplete work.

**One-line brutal summary:**  
Trade AI v12 is an **autonomous market research and proposal factory** with a **sputtering paper validation lane** and a **deliberately human live broker**. It is **not** yet an autonomous investment manager.

---

## 5. Architecture changes required to reach **9+/10**

Concrete, not aspirational. Ordered by leverage.

### A. Single runtime spine (unblock trust)

1. **One deploy root:** systemd unit always owns port 7777; kill ad-hoc servers; pin `WorkingDirectory` + `SOURCE_COMMIT` + health self-report of git SHA.  
2. **Cron PROJ == server PROJ == release tree** (or documented immutable artifact).  
3. **API contract smoke** that fails deploy if critical routes 404.

Without this, every other autonomy claim is non-auditable.

### B. Make paper the real closed loop (target: hop 11 = 9)

1. **Unify paper account keys:** map defense/inverse twins and bridge to `tradeai_automated` only; ban orphan `alpaca_paper` targets or add them to ATM enabled set.  
2. **SLA on enrichment:** proposal not “PENDING forever” — auto-expire or auto-fast-track curated sources; alert if `ready_count=0` for N sessions while pending>0.  
3. **ATM throughput KPIs:** min N paper fills/week per strategy or auto-widen **only inside paper** (size caps stay).  
4. **Daily paper funnel dashboard** (screener → signal → proposal → ATM decision → fill → close) with owner alerts.  
5. Keep live human; **paper must burn real sample size** for 6-month gate (55% WR / 1.3 PF) to be meaningful.

### C. Let learning change paper behavior (hop 10 = 8+)

1. **Unlock a paper-only weight profile** (not live) with clamp/weekly drift already in `hermes_outcome_learning.yaml`; graft nightly when eligible.  
2. **Wire outcome_bus gates into ATM / auto_proposal** (pause_eligible symbols blocked; edge_penalty/boost applied to ranking). Today bus → scope/research; **not** into approve_proposal.  
3. **Auto-apply threshold proposals only in paper** after holdout gates; keep `review_mode` for live.  
4. **Strategy enable/disable from graded outcomes** (min sample + precision floor) for ATM whitelist.  
5. Journal lessons → **structured feature flags**, not prose.

### D. Sector / defense: promote path without silent live (hop 7 = 8)

1. Finish SHADOW window adjudication (`promote_criteria.json`) with dated PROMOTE/EXTEND.  
2. On PROMOTE: auto-create **paper twins + ATM path** for every move-out/get-into card (already partial); **never** auto Schwab.  
3. Optional later: “paper-perfect” defense strategies can propose live intents into the **existing 2FA queue** only (still human click).  
4. Fix stale sector snapshots (weekend grace already exists for freshness monitors — apply same honesty in UI).

### E. Idea supply quality (hops 3–5)

1. Relax **MAIN GO** only for paper_atm lane; keep live_2fa strict.  
2. Schedule explicit **proposal_agent_review** worker (today coupling is opaque).  
3. Cap watchlist size or raise promotion bar — 5k watchlist names with 0 rec-intel executions is intelligence theater.

### F. Live remains human — but instrumented (hop 12 stays ≤3 auto by design)

For a **9/10 investment-intelligence** score, live need not be auto-fire. Definition of 9 here:

- **Autonomous: discover → research → propose → paper-execute → grade → adapt paper policy → re-propose**  
- **Human: any real-money order + policy unlocks**

That is a coherent product. Claiming 9 while main weights are locked and paper is starved is incoherent.

### G. Explicit non-goals (do **not** do for 9/10)

- Auto-live equities without 2FA.  
- Hermes writing orders.  
- Silent promote of defense trims to Schwab.  
- Grafting locked main weights without paper shadow proof.

---

## 6. Hop verdict table (quick reference)

| # | Hop | Verdict | Primary evidence |
|---|-----|---------|------------------|
| 1 | Discover trends | **Auto** | hermes_discovery_* + finviz crons; schedule enabled |
| 2 | Research trends | **Auto** | research_scheduler + agent jobs + outcome bus throughput |
| 3 | Generate ideas | **Semi** | auto_proposal + bridge; low create/ready rates |
| 4 | Validate ideas | **Auto/Semi** | enrichment + decision/risk gates; agent/cloud semi |
| 5 | Prioritize | **Semi** | scorer Auto; main weights locked |
| 6 | Update watchlists | **Semi** | scope Auto; lifecycle review_mode + pending |
| 7 | Sector rotation | **Semi** | engines Auto; recommendations SHADOW; capital Human |
| 8 | Surface recommendations | **Semi** | CC v3 + API 200s; some routes 404 |
| 9 | Monitor outcomes | **Auto** | nightly grader→bus→learning |
| 10 | Improve decisions | **Semi / weak** | research graft + source retire; **MAIN locked**; thresholds human |
| 11 | Paper execute | **Broken** | ATM active but rare fills; alpaca_paper disabled targets |
| 12 | Live execute | **Human-required** | execution_guard BROKER_DISABLED + 2FA |

---

## 7. Evidence index (absolute paths)

- Architecture: `/home/johnclaw/tradeai-wt-cursor-guardrails/ARCHITECTURE.md`  
- Guardrails tree: `/home/johnclaw/tradeai-wt-cursor-guardrails`  
- Live tree: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild`  
- Env freeze: `/home/johnclaw/tradeai-wt-cursor-guardrails/docs/audits/platform-autonomy-2026-08-02/evidence/env_freeze.txt`  
- API smoke: `/home/johnclaw/tradeai-wt-cursor-guardrails/docs/audits/platform-autonomy-2026-08-02/evidence/api_smoke.txt`  
- Outcome bus: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/state/hermes/outcome_bus.json`  
- Defense recs: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/runtime/defense_recommendations_latest.json`  
- ATM log: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/logs/atm.log`  
- Crontab backup: `/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/crontab_backup.txt`  
- Key scripts: `scripts/atm_auto_approver.py`, `scripts/brokers/execution_guard.py`, `scripts/hermes_outcome_learning.py`, `scripts/hermes_autonomous_self_tune.py`, `scripts/defense_recommendations.py`, `scripts/rotation_autopilot.py`, `scripts/watchlist_proposal_bridge.py`, `scripts/broker_promote_oversight.py`  

---

*End of autonomy chain findings. No code was modified.*
