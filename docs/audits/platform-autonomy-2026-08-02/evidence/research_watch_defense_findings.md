# Research · Watchlist · Defense — Platform Autonomy Audit

**Date:** 2026-08-02 (evidence through live metrics 2026-08-03T02:30Z)  
**Codebase:** `/home/johnclaw/tradeai-wt-cursor-guardrails`  
**Live API:** `http://127.0.0.1:7777` (read-only; evidence from `api_smoke.txt`, `api_smoke2.txt`, `live_metrics.json`)  
**Scope:** Research Intelligence / Hermes research engine · Watch Desk / watchlist · Defense Desk  
**Constraint:** No code changes. Advisory-system autonomy only (execution remains gated).

---

## Executive summary

| System | Autonomy class | One-line |
|--------|----------------|----------|
| **Research Engine** | **Semi-autonomous** (Hermes production loop **mostly autonomous** inside rails) | Discovers, researches, auto-promotes staged rows + embeds; discovery→registry promotion and RI staging remain operator-gated. |
| **Watchlist** | **Semi-autonomous** | Mass intake + ranking + quality labeling automated; MAIN admission / propose / convert require setup identity + operator or allowlisted path. Discovery α vs SPY is **negative**. |
| **Defense Desk** | **Semi-autonomous (structural) / Reactive (proven outcomes)** | Nightly recs, ladders, pairs, oversight compute autonomously in **SHADOW**; live money never auto-submits; outcomes n≈0 — structural ~9–9.5, proven ~4–6. |

**Overall desk stack:** rich automation for *sense → rank → advise*; full closed-loop *discover → select → size → act → grade → retrain* is deliberately incomplete. The platform is an institutional **advisory automation** system, not an autonomous portfolio manager.

---

## 1. Research Engine

### 1.1 Current-state analysis

#### Surfaces and modules
| Layer | Path / module | Role |
|-------|---------------|------|
| Skill canon | `.claude/skills/research-intelligence-desk/SKILL.md` | RI desk + Gain Guardian + Watch/Defense lineage (diagnose live first) |
| Feed aggregator | `scripts/lib/research_intelligence*.py` | Taxonomy, freshness, narrative, portfolio context, stage lifecycle |
| API | `GET /api/v2/research-intelligence` (+ taxonomy, freshness, feedback, staged, rebuild, queue, run-topic) | Desk payload; default views snapshot-first (ETag) |
| Hermes autonomous loop | `scripts/hermes_autonomous_loop.py` | LLM thesis challenges on held / proposals / closed trades; caps + kill switch |
| Coordinator | `scripts/hermes_coordinator.py` | 15-min fleet: autonomous loops, librarian, backlog drain, source auto-approval, **Directive B auto-promote**, embed worker |
| Self-tune | `scripts/hermes_autonomous_self_tune.py` | Outcome-gated weight grafts → **research** weights only (main_setup locked); retention purge |
| Discovery inbox | `scripts/lib/hermes_discovery/*` | Candidate intake: white_space, entity_spikes, tag_lift, analyst_signals, strategy, private_proxy, domains |
| Promotion paths | `scripts/lib/hermes_discovery/promotion.py` | ONLY path out of inbox → topic_monitor / watch_directives / staged ticker / sources — operator-required by domain config |
| Worker pool | `scripts/lib/hermes_discovery/worker_pool.py` | Bounded lanes; `promotion_allowed: false` hard-coded |
| Auto-research | `scripts/auto_research.py` | Reactive: agent conflict, high-impact CIO decision, new ai_discovered without agent results |
| Scope governor | `scripts/lib/hermes_scope_governor/` + `config/hermes_scope_governor.yaml` | Sole owner of `scope_tier`; outcome-aware Hot/Warm/Cold; bus reactions |
| Budget | `config/hermes_research_budget.yaml` | T0–Tn tiering, fail-closed, no paid fallback |
| Domains | `config/hermes_research_domains.yaml` | All domains `requires_operator_for_promotion: true` (defaults) |

#### Capability evaluation

| Capability | Status | Evidence |
|------------|--------|----------|
| **Independent topic discovery** | **Partial–strong** | White-space engine = covered∖demand set-diff (`white_space.py`); entity spikes, tag_lift, analyst signals, YouTube discovery; worker pool writes candidates only. Live: `/api/v2/hermes/discovery-inbox` **200** (~746KB). |
| **Trend detection** | **Semi** | TREND_CANDIDATE types + sector/industry Finviz novelty (schedule flag often off); Hermes score alerts dominate alert volume historically (~65% hermes_rank_surge). Not a market-regime forecast engine. |
| **Sector expansion** | **Semi** | Domain registry includes sectors; white-space MISSING_SECTOR; defense sector_momentum is separate. No autonomous “open a new sector book sleeve.” |
| **Prioritization** | **Strong (rules)** | Held/proposal > closed reflection (`hermes_autonomous_loop`); research budget T0–T1; scope governor edge score (outcome_yield weight 30); RI `_priority_from` + lane demotion of stop noise. |
| **Noise filtering** | **Strong (deterministic)** | QA lint (`research_intelligence_qa_lint`); universe_guard at write; near-dup Jaccard; stop-noise demotion; discovery min recurrence/cross-source; do-no-harm pause on schedule. |
| **Actionable insights** | **Semi** | Staged ideas require operator promote + E3 exit/stop note; auto-promote promotes **research rows** into insight/RAG, not trades. RI → watchlist/directive/paper is operator-clicked. |

#### Live API / metrics (2026-08-02/03)
- `GET /api/v2/research-intelligence` → **200**, ~2.0MB (full desk payload; keys include taxonomy, items, queued_research, hermes_wire, priority_lanes, portfolio_context).
- `GET /api/v2/research-intelligence/freshness` → **200**.
- Note: `…/desk?lane=all` is **404** (wrong path; correct is bare `/research-intelligence` or lane query on same).
- `GET /api/v2/hermes/maturity-dashboard` → **200**; gates: scope **4/4**, research **1/3**, tagging **2/3**, efficiency **2/4**, closed_loop **3/4**, autonomy **2/3**.
- `GET /api/v2/hermes/discovery-inbox` → **200**.
- Rec-intel: hermes_research **638** tickers, **0** executed (advisory).

#### Production autonomy already present
1. **Directive B** (`hermes_coordinator.auto_promote`): staged → promoted with confidence thresholds from graded outcomes + embed backpressure; audited + reversible SQL.
2. **Autonomous loop** prioritizes capital-exposed names every tick (cap 3 LLM rows).
3. **Self-tune** grafts research profile weights from outcome ledger when persistence gates pass; purges stale queues.
4. **Scope governor** autonomously rebalances Hot/Warm/Cold under total_cap 800.
5. **Source auto-approval** path runs without operator queue (coordinator step).

#### What is still human
- Discovery candidate → registry promotion (all domains require operator).
- RI stage → watchlist / directive / paper proposal.
- Custom domains hard-force `auto_promote: false`.
- Closed-trade reflection drain mode (policy: manual only so held research isn’t starved).
- Main Hermes score weights file locked against auto-graft.

### 1.2 Gap analysis (research)

| Gap | Impact | Module(s) |
|-----|--------|-----------|
| Discovery promotion is operator-gated end-to-end | Independent discovery cannot expand the monitored universe without a click | `hermes_discovery/promotion.py`, `hermes_research_domains.yaml` |
| Research maturity gate research **1/3** | Throughput / quality SLOs not fully met | maturity dashboard dimensions |
| Auto-research is **reactive** (conflict/decision/new find), not horizon scanner | Misses proactive multi-day thematic campaigns | `auto_research.py` |
| RI desk is aggregator + curator, not a planner | No autonomous “research program” that sets weekly themes from white-space outcomes | `research_intelligence.py`, queue drain cron |
| Journal ↔ discovery attribution incomplete | Learning which research → P&L is broken past proposal hop | skill: trade_journal has no source keys |
| Embedding backlog vs promote rate | Autonomy gap flagged by maturity (`embedding_backlog`) | coordinator CAP_EMBED vs CAP_PROMOTE |

### 1.3 Autonomy classification — Research

**Semi-autonomous** overall.  
Sub-score: **Hermes fleet production (research→stage→promote→embed) ≈ Mostly autonomous** inside kill-switch, budgets, and caps; **discovery intake → platform coverage expansion ≈ Semi / operator-gated**; **RI human desk UX ≈ Reactive-to-Semi** (curation stars/hide/stage).

### 1.4 Gaps preventing full autonomy
1. Operator promotion required for all discovery domains.
2. No auto-link from white-space GAP_CANDIDATE → topic_monitor without human.
3. No closed-loop that increases research budget on sectors with proven positive α.
4. Outcome grading of research rows exists (`hermes_outcome_grader`) but does not drive autonomous domain expansion.
5. Kill switch + Directive B are policy knobs — full autonomy would still need explicit operator risk acceptance beyond advisory.

---

## 2. Watchlist

### 2.1 Current-state analysis — idea lifecycle

```
External demand / screeners / news / SEC / YouTube / Hermes
        │
        ▼
agent_watchlist_engine (whiteboard L0→L4)  OR  finviz_screener_runner (source=ai_discovered)
        │
        ▼
watchlist_items / watchlist_proposals (propose adds) / watch_candidate_events (emissions ledger)
        │
        ▼
Hermes scorer + scope_governor (S0–S3) + hermes_rank
        │
        ▼
watch_lane_admission (MAIN cap 60 · setup-shaped · source allowlist)
        │
        ├── coverage / research / legacy_hermes lanes
        └── MAIN GO → proposal bridge → paper_trade_proposals (operator/ATM path)
        │
        ▼
watch_directive_gate (family dedup, active cap 150) · directives · hits
        │
        ▼
reconcile_watch_outcomes (Sun) → α vs SPY · quality_gate low_efficacy label
        │
        ▼
Operator cull / star / alert  (skill: evidence renders, operator culls — no automation on α)
```

| Stage | Automation | Human |
|-------|------------|-------|
| **Discovery** | Screener inserts `ai_discovered`; whiteboard promote; hermes discovery candidates | Operator adds, stars, pins |
| **Candidate** | `watch_candidate_events` on emission; intelligence whiteboard | Review proposals (`watchlist_proposals`) |
| **Watchlist / directive** | Hygiene, TTL expire, family_gate alias, scope tiers | Create/confirm directives; tier-3 merges |
| **Rank** | Hermes composite + scope edge + MAIN rules | Star grants M1 authority |
| **Propose** | Entry planner / CIO synthesis / ticket review (async jobs) | Propose POST; MAIN GO required for bridge |
| **Outcome feedback** | `reconcile_watch_outcomes` + quality gate fold | Cull; config edit of α floor (no auto-tune) |

#### Key files
- `scripts/agent_watchlist_engine.py` — promote / propose / discovery summary
- `scripts/lib/watch_directive_gate.py` — creation-time family fence
- `config/watch_quality_gate.json` — α floor −2%, min_n 30, 90d window; **visibility only**
- `config/watch_lane_admission.json` — MAIN allowlist **excludes** raw `ai_discovered`
- `scripts/lib/hermes_scope_governor/*` — universe lifecycle
- `apps/command-center-v3/src/.../WatchHub*` (UI; Card v4 locked)
- `scripts/reconcile_watch_outcomes.py` — 21d/63d α vs SPY

#### Live API
| Endpoint | Status | Note |
|----------|--------|------|
| `/api/v2/watchlist/items` | 200 | e.g. ANET `source=ai_discovered` score 95; limit returns top band |
| `/api/v2/watchlist/summary` | (supported) | by_source / by_status / jobs |
| `/api/v2/watchlist/quality-board` | (supported) | MAIN vs legacy_hermes admission metrics |
| `/api/v2/watch-directives` | 200 | ~731KB payload |
| `/api/v2/watch/scoreboard` | **404** | Scoreboard is embedded via finds track-record / quality gate helpers in `api_v2`, not this path |

#### How ideas enter
1. **Finviz / screeners** → `ai_discovered` rows (high volume; warehouse-scale).
2. **Qualified intel pipeline** → multi-source whiteboard → `watchlist_proposals` when ≥2 mentions and not on list.
3. **Operator / personal_watchlist / portfolio / pullback_macd / hermes / trade_ai_go** → MAIN-eligible sources.
4. **Hermes discovery promotion** → directives / topics (operator).
5. **Defense soft-auto** → SCHD / defensive lean symbols as MAIN WAIT only (`watch_lane_admission.json`).

#### Ranking and refresh
- Hermes rank + composite; scope governor demotes cold names (ai_discovered grace 14d).
- Decision desk refresh: `POST /api/v2/watch/decision/refresh` (enqueue).
- Agent jobs: Maria priority OAuth is top consumer (1594 calls / 30d) — research automation is heavy on watchlist tail.

#### Decision framework
- MAIN requires source allowlist **or** star/pin **and** setup-shaped context **and** actionable/plan signals.
- Proposal bridge: `require_main_go: true`.
- Quality gate: low_efficacy_source fold for sources with median 21d α < −2% and n≥30 — **does not block insert**.

### 2.2 Evidence: ai_discovered α vs SPY

**Canonical first evidence (Watch Desk v3/v4, skill + WATCH_DESK_V4.md):**
- **ai_discovered median 21d α: −4.82% (n=385)**
- **operator_add: −6.67% (n=13)**
- **Converted-to-proposal α: −11.0% (n=4)** vs all −4.82% (n=385); 123 converted total, only 4 scored at write-up
- Unanchored directive hits → NOT_EVALUABLE; journal hop unlinkable
- Gate config: folds new emissions from low-efficacy sources into collapsed UI band

**Live rec-intel (2026-08-03):** watchlist source **5015 tickers, 0 executed** — enormous advisory warehouse, almost no trade conversion.

**Interpretation:** Discovery is automated and prolific; **edge is not proven**. Autonomy without efficacy is noise amplification. The platform correctly surfaces this and throttles **visibility**, not **intake**.

### 2.3 Gap analysis (watchlist)

| Gap | Impact |
|-----|--------|
| MAIN excludes raw ai_discovered (by design) | Full autonomy would need proven filters before auto-MAIN |
| Quality gate does not reduce screener emission volume | Warehouse keeps growing; compute spent on −α sources |
| Outcome feedback does not auto-reweight screeners | Operator must edit config / cull |
| Journal missing source keys | End-to-end attribution stops at proposal |
| Converted α n=4 | Cannot safely auto-promote discovery→trade |
| Directive-hit α often n/a | Theme/directive efficacy unproven |
| Watch agent job backlog | Maturity gap: scale, not policy |

### 2.4 Autonomy classification — Watchlist

**Semi-autonomous.**  
Intake + score + scope + hygiene = mostly autonomous; **selection for action** and **learning response to α** = operator / config. Not reactive-only (too much automation) and not fully autonomous (no self-pruning of losing sources into non-emission).

### 2.5 Recommendations for fully autonomous watchlist

1. **Close the quality loop:** when `low_efficacy` holds for N weeks, auto-lower screener cadence / max inserts for that `source_type` (still advisory; never delete).
2. **Auto-MAIN only on dual gates:** setup-shaped + rolling α ≥ 0 with min_n ≥ 30 (or operator star).
3. **Proposal bridge auto-draft** for MAIN GO with hard size caps → paper only; require outcome ledger before live.
4. **Thread `discovery_trace_id`** through all proposal writers (skill flagged traceless writers).
5. **Add journal source keys** so converted α and R can grade discovery lanes.
6. **Cap warehouse growth:** scope governor already archives; couple with quality gate so low_efficacy sources stop earning S1.
7. **Screener portfolio optimization:** treat screeners as strategies with Kelly/α budget; pause losers automatically.
8. **Wire Hermes backlog deprioritization** (api_v2 comment: Engine Room WS-4 hook) to low_efficacy sources.

**Target architecture (watchlist autonomy):**
- Emitters write candidates with mandatory anchors.
- Weekly reconciler grades all sources.
- Source governor adjusts emission budgets from α (config file write with audit, same pattern as hermes_autotune).
- Lane admission reads source efficacy + setup identity.
- Proposal factory auto-opens paper tickets for MAIN GO; live remains 2FA.
- Attribution bus links discovery → directive → proposal → fill → journal.

---

## 3. Defense Desk

### 3.1 Current-state analysis

#### Stack (v1–v9)
| Component | Module | Function |
|-----------|--------|----------|
| Sector momentum | `scripts/sector_momentum_engine.py` | RS 5/20/60 vs SPY; LEADING/WEAKENING/LAGGING/IMPROVING; 2-close debounce |
| Recommendations | `scripts/defense_recommendations.py` | get_into / protect / short_side / income; field-guard complete-or-absent |
| Trim ladders | `scripts/defense_trim_ladders.py` | Factor+GG arithmetic; sell tickets |
| Rotation pairs | `scripts/defense_rotation_pairs.py` | Same-account funded out→in cards |
| Execution | `scripts/defense_execution.py` | Stage → approve → 2FA → paper auto / live ticket; `autonomous_live_submit_allowed` stays False |
| Oversight | `scripts/defense_oversight.py` | Free seats (ChatGPT/Grok) critique recs; informs only |
| Adjudication | `scripts/defense_adjudication.py` | Zero LLM; promote_criteria machine eval; seat league; tuning proposals (min-n 20) |
| Core registry | operator_core_registry | Operator-owned ★CORE; never full-exit language |
| UI | DefenseHub (CC v3) | Posture, recs, ladders, review console |

#### Live API (smoke + live_metrics)
| Endpoint | Status | Live fact |
|----------|--------|-----------|
| `/api/v2/defense/posture` | 200 | Momentum generated **2026-07-31**; 11 sector rows; e.g. Technology XLK rs5 −2.29, rs20 −2.83 |
| `/api/v2/defense/recommendations` | 200 | **`mode: SHADOW`**; generated **2026-07-31T21:50Z**; 4 groups; shadow_note: all groups SHADOW, 10-trading-day window from 2026-07-18 |
| `/api/v2/defense/industries` | 200 | ~53KB |
| `/api/v2/defense/core` | 200 | Operator core registry |
| Workspace snapshot files | missing in tree | `defense_recommendations_latest.json` / `sector_momentum_latest.json` not present under this worktree’s `data/runtime/` (API still served live snapshot from host process path) |

#### Autonomy questions
| Question | Answer |
|----------|--------|
| **Auto sector rotation?** | **Compute yes / execute no.** Pairs + rotate-in cards built nightly from underweight LEADING sectors; buy legs → PENDING paper; live blocked. |
| **Risk-off?** | **Advisory yes.** Inverse ETFs (PSQ/SH…), taxable short cards, hedge state machine on Home (armed/in_play/stand_down); inverse stoplights. No autonomous live hedge submit. |
| **Adaptive recs?** | **Partially.** Config-driven knobs; style spreads steer SCHD for growth-heavy sources; GG modifiers on trim %; oversight critiques. Tuning_proposal_engine proposes but never auto-adjusts (min-n 20). |
| **Research/watchlist leverage?** | **Yes, one-way.** Hermes composites / sector pulse color momentum; industry_momentum candidates; soft-auto MAIN for defensive destinations. Research desk does not drive defense recs as primary author. Rec-intel shows rotation source 16 tickers / 646 executed (historical rotation executions elsewhere — not Defense SHADOW paper twin alone). |

#### Execution boundary (hard)
- `defense_execution.py`: stages and arms; **live = ARMED ORDER TICKET after 2FA**; paper via Alpaca; pilot place_order fence not widened.
- Caps: kill file, whitelist, $25K/order, 6/day (`defense_execution_caps.json`).
- Telegram advisory class suppressed until promote decision.

### 3.2 Structural vs proven score (honest)

| Dimension | Structural | Proven (live n / outcomes) |
|-----------|------------|----------------------------|
| Sector RS + debounce | High | Live rows as-of 2026-07-31 (11 sectors) |
| Rec field guards / rails | High | Day-1 rails caught LDOS short-while-held, MNTS stop garbage (skill) |
| Trim arithmetic + ladders | High | QCOM T2 fired on GIVEBACK-BREACH (skill) |
| Rotation pairs | High | 4 live pairs day one (skill); unit outcomes need closes |
| Oversight memos | High | Substantive ChatGPT/Grok objections (skill); paid seat budget-gated |
| Adjudication / promote criteria | High | `criteria_locked: true` 2026-07-18; **decisions: {}** still empty in config |
| Outcome profitability | Scaffold | **n≈0** at v9 ship; Jul 30–31 = process not performance |
| Seat league accuracy | Scaffold | Needs ≥10 closed outcomes/seat (months) |
| Gain Guardian promote | Shadow | Outcomes table for SIGNAL_WRONG; shadow window design |

**Honest score (aligned with skill v8–v9):**
- **Structural: ~9.0–9.5 / 10**
- **Proven: ~4–6 / 10** (machinery exercised; **α / P&L / agreement rates thin**)

**Live classification for autonomy:**
- Nightly compute & SHADOW cards: **Semi-autonomous**
- Live portfolio protection actions: **Reactive / operator-mediated**
- Learning/tuning: **Reactive** (proposals only)

### 3.3 Gap analysis (defense)

| Gap | Module |
|-----|--------|
| Stuck in SHADOW past original 10d window (started 2026-07-18; still SHADOW as of 2026-07-31 snapshot) | `defense_recommendations.py` mode hardcode + promote_criteria decisions empty |
| No performance-based auto-promote of advisory classes | `defense_adjudication.py`, `promote_criteria.json` |
| Outcome tables empty → cannot adaptive-weight factors | round_trips, oversight_seat_outcomes, exit_advisory_outcomes |
| Research white-space does not feed rotate-in universe | discovery vs `defense_recommendations` rotate_in |
| autonomous_live_submit_allowed = False (by design) | `defense_execution.py` |
| Core registry operator-owned (correct for risk, blocks full auto rebalance) | operator_core_registry |
| Disk snapshots absent in this worktree runtime dir | ops / deploy path drift |

### 3.4 Autonomy classification — Defense

**Semi-autonomous structurally; Reactive on capital.**  
Full autonomy would require: outcome-positive shadow, locked promote decisions, and still (likely) operator 2FA for live — so “fully autonomous defense” in this codebase means **fully autonomous advisory + paper**, not unsupervised live rotation.

---

## 4. Cross-cutting findings (P0–P2)

### P0 — Blockers / material risk to “autonomous desk” claims

| ID | Finding | Modules | Why P0 |
|----|---------|---------|--------|
| **P0-1** | **ai_discovered 21d median α −4.82% (n=385)**; converted α worse on tiny n; quality gate is visibility-only | `reconcile_watch_outcomes.py`, `config/watch_quality_gate.json`, `api_v2._watch_quality_gate`, Finviz intake | Automating further intake without emission budget control scales negative edge |
| **P0-2** | **Defense remains SHADOW** with empty `promote_criteria.decisions` despite locked criteria and elapsed review window | `config/promote_criteria.json`, `defense_recommendations.py`, `defense_adjudication.py` | Structural automation without promote decision → no operational autonomy |
| **P0-3** | **Journal ↔ discovery attribution unlinkable** | trade_journal schema, watch_candidate_events, proposal writers | Closed-loop learning and true autonomy impossible without credit assignment |
| **P0-4** | **Live submit autonomy intentionally false** for Defense (and ATM live accounts disabled) | `defense_execution.py`, ATM status in live_metrics | Correct safety; any “full platform autonomy” claim must exclude live money |

### P1 — High leverage gaps

| ID | Finding | Modules |
|----|---------|---------|
| **P1-1** | Discovery promotion always operator-gated; white_space cannot expand coverage alone | `hermes_discovery/promotion.py`, domains yaml |
| **P1-2** | MAIN allowlist excludes ai_discovered; warehouse (5k+ rec-intel watchlist tickers) not action-shaped | `watch_lane_admission.json`, quality-board delta note |
| **P1-3** | Hermes maturity research **1/3**, autonomy **2/3**, efficiency **2/4** | `hermes_maturity_dashboard.py` live gates |
| **P1-4** | Outcome auto-graft targets research weights only; main setup locked | `hermes_autonomous_self_tune.py` |
| **P1-5** | Defense outcomes / seat league n insufficient for adaptive tuning | `defense_adjudication.py`, tuning_proposal_engine |
| **P1-6** | Watch agent backlog / Maria OAuth cost dominant | consumption overview, maturity watchlist_jobs gap |

### P2 — Medium / hygiene

| ID | Finding | Modules |
|----|---------|---------|
| **P2-1** | Wrong smoke paths 404 (`/research-intelligence/desk`, `/watch/scoreboard`) | docs / probes |
| **P2-2** | Runtime snapshot files not in this worktree `data/runtime/` | deploy layout |
| **P2-3** | Industry novelty discovery disabled in schedule | `hermes_discovery_schedule.json` |
| **P2-4** | LLM ambiguous scope review off | scope_governor.yaml |
| **P2-5** | Gain Guardian still shadow-first design; cost-basis LT/ST unverified | skill GG section |

---

## 5. Target architecture bullets (autonomy)

### Research
- **Program planner:** weekly white_space gaps → auto topic_monitor drafts with TTL; auto-promote only if recurrence≥k and universe_guard clean.
- **Outcome-weighted domains:** increase budget on domains whose graded research led to positive proposal α.
- **Unified intelligence bus:** every brief carries `discovery_trace_id` into RI stage → watch → paper.
- **Backpressure everywhere:** promote rate ≤ embed rate; research budget reads quality gate.

### Watchlist
- **Source governor** (sibling of scope governor): emission budgets from rolling α.
- **Two-lane truth:** warehouse vs MAIN; only dual-gated names auto-propose paper.
- **Mandatory anchors** on 100% of candidate events.
- **Journal source keys** + weekly auto-cull digests that pause screeners.

### Defense
- **Paper-first autonomy:** auto-stage paper twins for all SHADOW cards; fill poller already advances state.
- **Promote console completion:** operator locks decisions once; machine re-eval continues; Telegram classes unstick from eternal SHADOW.
- **Performance criteria v2** when n≥20 per card class — then adaptive size_band / factor thresholds via tuning_proposals auto-apply within ±20%.
- **Research feedback:** sector LAGGING + white_space MISSING_THEME jointly raise research priority (not auto-trade).

### Shared rails (keep)
- Advisory / paper / 2FA live boundary.
- Kill switches (HERMES_DISABLED, defense caps disabled).
- Fail-closed budgets and field guards.
- Honest n and NOT_EVALUABLE (never fabricate α).

---

## 6. Autonomy classification matrix (final)

| System | Reactive | Semi-autonomous | Fully autonomous | Chosen |
|--------|:--------:|:---------------:|:----------------:|--------|
| RI desk UI (star/stage/hide) | ● | ◐ | | **Semi** (feed auto; actions human) |
| Hermes research loop + promote + embed | | ● | ◐ | **Mostly / Semi-high** |
| Hermes discovery → registry | | ● | | **Semi** (operator promote) |
| Watch intake + score + scope | | ● | | **Semi** |
| Watch MAIN → proposal → outcome learn | ● | ◐ | | **Semi-low** |
| Defense nightly recs / ladders / pairs | | ● | | **Semi** (SHADOW) |
| Defense live risk actions | ● | | | **Reactive** |
| Outcome-driven self-tune (research weights) | | ● | | **Semi** |
| Outcome-driven self-tune (defense / main watch) | ● | | | **Reactive** |

**Legend:** ● primary · ◐ partial

---

## 7. Evidence index

| Artifact | Path |
|----------|------|
| API smoke | `docs/audits/platform-autonomy-2026-08-02/evidence/api_smoke.txt` |
| API smoke 2 | `…/api_smoke2.txt` |
| Live metrics | `…/live_metrics.json` |
| Skill | `.claude/skills/research-intelligence-desk/SKILL.md` |
| Watch quality gate | `config/watch_quality_gate.json` |
| Watch lane admission | `config/watch_lane_admission.json` |
| Scope governor | `config/hermes_scope_governor.yaml` |
| Defense recs config | `config/defense_recommendations.json` |
| Promote criteria | `config/promote_criteria.json` (locked; decisions empty) |
| Architecture | `docs/architecture/WATCH_DESK_V4.md`, `DEFENSE_DESK_V9.md` |
| Code | `scripts/lib/research_intelligence*.py`, `hermes_autonomous_*.py`, `auto_research.py`, `agent_watchlist_engine.py`, `lib/watch_directive_gate.py`, `lib/hermes_discovery/*`, `defense_*.py`, `sector_momentum_engine.py` |

---

## 8. Bottom line

Trade AI v12’s research/watch/defense stack is a **mature semi-autonomous advisory plant**: it discovers, ranks, fences, shadows, and grades at scale. It is **not** fully autonomous because (1) **discovery edge is negative on the measured sample**, (2) **promotion and MAIN action stay human or allowlist-gated**, (3) **Defense SHADOW + empty promote decisions + zero outcome n** block proven adaptive risk management, and (4) **live capital paths are intentionally non-autonomous**.

Closing P0-1–P0-3 (efficacy-linked emission control, adjudication decisions, attribution) is the shortest path from “impressive desk automation” to **credible full advisory autonomy**. Live trading autonomy remains a separate, later policy decision.
