# Redeploy Desk — Institutional Capital-Allocation Design

**Status:** **Approved with required changes** — Phase A implementation in progress  
**Created:** 2026-07-14  
**Review:** Operator verdict 2026-07-14 — Phase A authorized; Phases B–E not approved for production merge
**Policy source:** Operator questionnaire (45 answers, 2026-07-14)  
**Related runbook:** `docs/runbooks/post-sale-redeploy-sync-2026-07-14.md` (v1 as-built ops)  
**Related commits:** `b2bccfef` → `de5131f1` (deploy detect, intelligence engine, UI)  
**Author:** Grok (with John Whiting)

> **Scope:** Transform Portfolio → **Redeploy** from a single-score symbol list into an institutional post-sale capital-allocation workbench: exposure decomposition, competing multi-leg plans, entry staging, scenario/risk analysis, exportable trade plans, and post-entry monitoring. **Advisory only** — no broker execution from this desk.

---

## 1. Motivation

The v1 Redeploy Desk (Jul 2026) detects broker sells and surfaces ranked ETF/stock targets. For a major sale such as **FCNTX ($107,023)**, the operator sees:

```
Top pick: JEPQ — Score: 124.5 — replaces Nasdaq 100 exposure
```

That is insufficient for institutional-grade portfolio transition:

- No sector/factor/income/holdings decomposition of what was lost
- No distinction between **sale replacement** vs **portfolio rotation** (ITA/XAR appear for Defense gaps, not FCNTX)
- No competing plan types (strategic, diversified, income, defensive, tactical, cash)
- No entry targets, staging, or quote timestamps
- No proceeds settlement verification (FCNTX: $107k proceeds, $17.5k visible cash)
- No before/after portfolio impact, rejected alternatives, or exportable trade plan
- `deploy_plans` table exists but is **unused**; plans live in mutable JSON on `deploy_events`

This design specifies v2.

### Formal approval (2026-07-14)

```text
Operator review: APPROVED WITH REQUIRED CHANGES.

The Redeploy Desk Institutional Capital-Allocation Design is approved as the
target architecture. Phase A — Data Truth is authorized for implementation,
provided all P0 corrections below are incorporated before merge.

This approval does not authorize broker execution, production deployment of
later phases, autonomous recommendations, or modification of unrelated
unstaged local files. Fidelity remains manual-ticket only. No autonomous
broker submit is authorized.
```

---

## 2. Approved operator policy (questionnaire 2026-07-14)

| Domain | Decision |
|--------|----------|
| Objective | Preserve lost exposure when it fits; otherwise improve portfolio (**Q1 C**) |
| No-redeploy / cash | Both may be **primary** plans (**Q2 A**, **Q3 A**) |
| Competing plans | Sale-specific vs portfolio-gap side-by-side; no auto-override (**Q4 C**) |
| Strategic vs tactical | Plan **A** strategic · Plan **E** tactical (**Q5 C**) — see §2.1 archetypes |
| Plan archetypes | Seven concepts **A–G**; staging (**F**) separate from defensive (**D**) (**Q6 A** + P0-1) |
| Leg count | No cap; warn at **10+** legs (**Q7 D+C**) |
| Sizing display | Operator toggles **% or $** per plan (**Q8 D**) |
| Partial deploy | Normal (**Q9 A**) |
| Min leg size | None (**Q10 D**) |
| Account rules | Informational only; any account (**Q11 D**) |
| Tax location | Taxable sales only (**Q12 C**) |
| Wash-sale | Mandatory taxable only (**Q13 B**) |
| Gain/loss urgency | Taxable only (**Q14 C**) |
| Income → retirement | Strong preference (**Q15 A**) |
| Qualified div → taxable | No preference (**Q16 D**) |
| Concentration caps | Position **8%** · sector **25%** · industry **15%** · ETF **12%** · sleeve **22%** · issuer **5%** (**Q17 A**) |
| Look-through | Always pro forma; penalize overlap (**Q18–19 A**) |
| Concentrated funds | Soft penalty unless “closest replacement” (**Q20 B**) |
| Geopolitical | Flag only — no sizing/ranking change (**Q21 C**) |
| Vol/drawdown | Hard reject if portfolio vol **>+1.5%** or basket DD **>−15%** (**Q22 A**) |
| Entry package | Full fields every leg (**Q23 A**) |
| Entry method | Technicals + regime-dependent (**Q24 B+D**) |
| Staging | Default **25/25/50** + ATR-based level spacing (**Q25 A+C**) |
| Reserve leg | First-class, tracked (**Q26 A**) |
| Stale quotes | Always show timestamp; never block (**Q27 D**) |
| Replacement dimensions | Growth, sector, factor, income, benchmark, risk — all (**Q28 G**) |
| JEPQ | Acceptable as **one of many** options (**Q29 A**) |
| Option-income ETFs | Dual-label growth restore + income (**Q30 B**) |
| Unmet exposure | Required on major sales only (**Q31 B**) |
| Plan tags | Multiple tags + composite rank (**Q32 B+C**) |
| Rejected alts | 3–5 with reason codes, major sales (**Q33 A**) |
| Hermes | Narrative only; engine owns structure; primary + 2–3 alternates (**Q34 A+C**) |
| Multi-LLM oversight | Required for major before operator-ready (**Q35 A**) |
| Confidence | Draft vs operator-ready tiers (**Q36 C**) |
| Monitoring | Track all fields; open until stages done (**Q37–38 A**) |
| Re-eval triggers | Price, earnings, regime, geopolitical, thesis, stale, target change (**Q39 A**) |
| Hermes learning | Always with evidence gates (**Q40 A**) |
| Execution | Advisory forever; exportable trade plan; whole shares (**Q41–45 A**) |

### 2.1 P0 corrections (incorporated 2026-07-14 review)

| # | Correction | Resolution |
|---|------------|------------|
| P0-1 | Plan-archetype conflict (B tactical vs diversified; D defensive vs staged) | **Seven archetypes A–G**; **F = staged deployment** (orthogonal); **G = hold**; questionnaire Q5 maps A=strategic, E=tactical |
| P0-2 | Settled-cash truth | `deployable_cash_usd = min(net_proceeds, settled_available_cash)`; excess is **planned-not-actionable** until verified |
| P0-3 | Income missing ≠ $0 | `income_status`: `known` \| `unknown` \| `estimated`; FCNTX = **unknown** |
| P0-4 | Risk mathematics | Vol Δ in **absolute percentage points** (252d daily, sample covariance); reject when `estimated_max_drawdown_pct <= -15` |
| P0-5 | Major sale + readiness | Major if any: proceeds ≥$25k, mutual_fund, ≥1% of portfolio equity, ≥1% exposure impact; `operator_ready` requires confidence ≥70, evidence ≥3, oversight (major), fresh quotes for **export** |
| P0-6 | Account funding | Default legs to **sale account**; cross-account = explicit `transfer_scenario` |
| P0-7 | Stale display vs readiness | Stale quotes **visible** with watermark; **export/operator-ready limits** require fresh quote confirmation |
| P0-8 | Auditability | SQL tables `redeploy_exposure_loss` (+ sector/holding children), `redeploy_portfolio_context_snapshots`; lineage: `policy_version`, `generator_version`, `holdings_snapshot_id`, `input_hash`, `source_as_of`, `created_by`, `version` |
| P0-9 | FCNTX fixture | Equity MV **$984,179** (holdings); cash separate (**$1,117,827** total); staging % = **of leg dollars**; sector sum **~100%** + residual bucket; BRK share-class note |
| P0-10 | API write semantics | Phase B: `plan_id`, `version`, idempotency keys, optimistic concurrency, audit on lock/fill/recompute; `record-fill` = manual evidence only |

**Proceeds reconciliation statuses**

| Status | Rule |
|--------|------|
| `verified` | `settled_available_cash >= 95% × net_proceeds` |
| `partial` | `50%–95%` of net visible in source account |
| `unsettled` | `< 50%` visible (FCNTX: $17,541 / $107,023) |

---

## 3. v1 as-built (reference)

### 3.1 Pipeline

```
trade_transactions (SELL, ≥$500)
    → sale_event_detector.py → deploy_events
    → deploy_intelligence_engine.py → redeploy_plan JSON + metadata
    → GET /api/v2/deploy/events → RedeployPanel.tsx
```

**Scripts:** `deploy_detect.py`, `deploy_backfill.py`, `deploy_recompute.py`  
**Tables:** `deploy_events` (live), `deploy_plans` (unused), `deploy_oversight_runs` (PR-4 pending)

### 3.2 v1 gaps (why redesign)

| Capability | v1 status |
|------------|-----------|
| Exposure decomposition | Single theme via proxy (FCNTX→SCHG→Nasdaq 100) |
| Multi-plan alternatives | Ranked symbol list only |
| Entry targets / staging | Score-weighted dollar range only |
| Proceeds verification | Heuristic; FCNTX unsettled |
| Plan versioning | Recompute overwrites JSON |
| Post-redeploy monitoring | None |
| Export trade plan | None |

### 3.3 Source-of-truth matrix

| Topic | Git | Runtime | Authority for v2 |
|-------|-----|---------|------------------|
| Sale detection | runbook | `sale_event_detector.py` | Code |
| Fund sector/holdings | `phase3_lookthrough_*` | `fund_lookthrough.json` | **fund_lookthrough** for decomposition |
| Theme gaps | `rotation_sector_targets.json` | `lookthrough_themes.json` | Config + lookthrough |
| Fund proxy (technicals) | `holding_proxies.py` | FCNTX→SCHG | Proxy for technicals only |
| Income | — | `dividend_calendar.json` | dividend_calendar |
| Account/tax | `portfolio_accounts.yaml` | Not in deploy engine | portfolio_accounts + tax modules |
| Execution | `PROPOSAL_EXECUTION_PATHS.md` | No redeploy execution | PROPOSAL_EXECUTION_PATHS |

---

## 4. Target architecture

```
trade_transactions (SELL)
    → sale_event_detector → redeploy_events (deploy_events extended)
    → exposure_decomposer (fund_lookthrough + themes + income)
    → portfolio_context_builder (gaps, overlap, regime, tax flags)
    → redeploy_plan_engine (plans A–F, verify, scenarios)
    → entry_planner_adapter (technical_snapshot + watchlist_entry_planner patterns)
    → deploy_plans + redeploy_plan_legs + redeploy_scenarios (versioned)
    → optional: deploy_oversight_runs (Grok/ChatGPT — required major)
    → API + Redeploy Desk v2 UI + export
    → redeploy_monitor → Hermes outcome bus
```

**Component ownership**

| Component | Role |
|-----------|------|
| `deploy_intelligence_engine.py` | v1 scorer → becomes **candidate feeder** only |
| `redeploy_plan_engine.py` (new) | Multi-plan generation, verification, versioning |
| `watchlist_entry_planner.py` | Per-leg entry math via adapter |
| `strategy_planner.py` | Manual Declare/Impact/Advise — linked, not merged |
| Hermes / OAuth | PM memo + oversight verdict; does not change leg structure |

---

## 5. Data model

### 5.1 `redeploy_events` (extend `deploy_events`)

| Column | Notes |
|--------|-------|
| Existing | `event_key`, `symbol`, `account`, `sold_at`, `proceeds_usd`, `proxy_*`, `status`, … |
| **New** | `settlement_date`, `average_sale_price`, `gross_proceeds`, `net_proceeds`, `tax_lot_summary` (jsonb) |
| **New** | `reconciliation_status`: `unsettled` \| `partial` \| `verified` |
| **New** | `operator_status`: `open` \| `reviewing` \| `executing` \| `completed` \| `dismissed` |
| **New** | `plan_locked_at` — recompute creates new version when set |

### 5.2 `redeploy_exposure_loss` (**SQL tables** — P0-8)

Header: `redeploy_exposure_loss` · children: `redeploy_exposure_loss_sector`, `redeploy_exposure_loss_holding`.

Per event `version`. Populated from `fund_lookthrough.json`. Income uses `income_status` (`known`|`unknown`|`estimated`) — never coerce missing to $0.

### 5.3 `redeploy_portfolio_context_snapshots` (**SQL table** — P0-8)

Immutable per `deploy_event_id` + `version`. Includes `portfolio_equity_usd`, `portfolio_total_with_cash_usd`, `deployable_cash_usd`, `overlap_analysis`, `concentration_limits`, lineage fields.

### 5.4 `redeploy_plans` (activate existing `deploy_plans` table)

| Column | Notes |
|--------|-------|
| `deploy_event_id`, `version` | Monotonic; immutable when locked |
| `plan_type` | See §6.1 archetypes A–G |
| `plan_archetype` | A \| B \| C \| D \| E \| F \| G |
| `staging_profile` | Optional — plan may also use **F staged deployment** overlay |
| `tags[]` | Multiple: strategic, income, diversification, … |
| `total_deployable_usd`, `reserve_usd`, `deploy_pct` | |
| `confidence`, `evidence_factor_count` | Draft vs ready (**Q36**) |
| `operator_status` | `draft` \| `operator_ready` \| `approved` \| `dismissed` |
| `oversight_status` | `pending` \| `passed` \| `failed` — required major (**Q35**) |
| `composite_rank` | Underlying sort |
| `rejected_alternatives` (jsonb) | 3–5 with reason codes |
| `unmet_exposure` (jsonb) | Major sales only |
| `hermes_narrative`, `advantages[]`, `compromises[]`, `risks[]` | |
| `generated_at`, `expires_at` | Stale trigger |

### 5.5 `redeploy_plan_legs`

Per leg: `ticker`, `account`, `allocation_pct`, `target_dollars`, `target_shares` (whole), `current_price`, `price_as_of`, fair value band, preferred entry, entry range, do-not-chase, stage 1/2/3 (pct, price, shares, dollars), `expected_yield`, `expected_beta`, `sector_contribution`, `overlap_delta`, `tax_location_rationale`, `thesis`, `invalidation`, `monitoring_rules`, `is_reserve`.

### 5.6 `redeploy_scenarios`

Per plan: `base` \| `bull` \| `bear` — `expected_income_annual`, `portfolio_vol_delta_pct`, `max_drawdown_est_pct`, `sector_restoration_pct`, `factor_restoration_pct`, `concentration_delta`, `cash_remaining`.

**Verifier:** reject plan if `portfolio_vol_delta_pct > 1.5` **percentage points** or `estimated_max_drawdown_pct <= -15`.

---

## 6. Plan engine specification

### 6.1 Plan archetypes (P0-1 — seven distinct concepts)

| Archetype | `plan_type` | Purpose |
|-----------|-------------|---------|
| **A** | `strategic_replacement` | Closest benchmark/risk restoration |
| **B** | `diversified_basket` | Multi-sector/sub-sector basket |
| **C** | `income_oriented` | Income + partial growth (dual-label option-income ETFs) |
| **D** | `defensive` | Risk reduction, bonds, low-beta |
| **E** | `tactical_opportunity` | Portfolio underweights — **all sectors** |
| **F** | `staged_deployment` | **Staging overlay** — reserve + tranches (orthogonal to A–E) |
| **G** | `hold_no_redeploy` | Hold cash / no immediate redeploy |

Generate A–G when applicable (**Q6 A**). Plan **F** may combine with A/C (e.g. strategic basket + staged entry).

**Staging rule (P0-9):** stage percentages apply to **each leg's target dollars**, not total proceeds unless the leg is 100% of deployable cash.

### 6.2 Pipeline steps

1. Reconcile proceeds → `reconciliation_status`
2. Decompose exposure → `fund_lookthrough.json` + themes
3. Build portfolio context → gaps (all sectors), overlap matrix, regime
4. Generate archetypes A–F
5. Score & verify → overlap penalty, concentration caps, vol/DD hard reject
6. Entry legs → `entry_planner_adapter`
7. Scenarios → before/after metrics
8. Rejected alternatives → reason codes (major sales)
9. Draft vs operator-ready → oversight + confidence threshold
10. Hermes narrative → PM memo (no structure change)
11. Persist version → new version if `plan_locked_at` set

### 6.3 Rejection reason codes

| Code | Meaning |
|------|---------|
| `RPL-001` | Duplicate proxy of sold fund |
| `RPL-002` | Issuer overlap >5% pro forma |
| `RPL-003` | Vol budget exceeded |
| `RPL-004` | Not sale replacement — portfolio gap only |
| `RPL-005` | Concentrated fund → concentrated fund |
| `RPL-006` | CIO AVOID (non-gap override) |
| `RPL-007` | Drawdown scenario breach |
| `RPL-008` | Proceeds unsettled — full deploy ill-advised |

### 6.4 Entry planner integration

**Reuse:** `watchlist_entry_planner.py` inputs (RSI, ATR, SMA20/50/200).

**Staging (Q25):** 25% / 25% / 50% with ATR-spaced levels:
- Stage 1: preferred entry
- Stage 2: preferred − 1.0× ATR (widen for high-ATR)
- Stage 3: preferred − 2.0× ATR

**Regime adjustments (Q24 D):**
- `risk_on` / low vol: stage 1 at preferred; tighter ranges
- `risk_off` / elevated vol: larger reserve; reduced stage 1 %

**Quotes (Q27 + P0-7):** Always show `price_as_of` with **STALE** watermark when aged; never block display. **Export / operator-ready limits** require quote age ≤ 15 minutes or explicit operator refresh.

---

## 7. API contract (new / extended)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v2/deploy/events` | Queue (+ `reconciliation_status`, `plan_count`) |
| GET | `/api/v2/deploy/events/{id}` | Event + plans summary |
| GET | `/api/v2/deploy/events/{id}/analysis` | Exposure loss + context + before/after |
| GET | `/api/v2/deploy/events/{id}/plans` | Versioned plans |
| GET | `/api/v2/deploy/plans/{plan_id}` | Full plan + legs + scenarios |
| POST | `/api/v2/deploy/events/{id}/lock` | Operator review started |
| POST | `/api/v2/deploy/oversight` | Grok/ChatGPT (PR-4) |
| POST | `/api/v2/deploy/events/{id}/record-fill` | Monitoring stage fill |
| GET | `/api/v2/deploy/events/{id}/export` | Trade plan JSON/CSV |
| POST | `/api/v2/deploy/recompute` | New plan **version** |

Existing: `detect`, `dismiss`, `restore`.

---

## 8. UI — Redeploy Desk v2

### 8.1 Executive queue row

Each sale row shows: sold security, account, dates, verified proceeds, exposure lost (summary), strategic significance, urgency, plan status, deploy %, cash reserve, leg count, data freshness, review status (draft vs ready count).

### 8.2 Expanded drawer tabs

`TIMELINE` · `WHAT CHANGED` · `PLANS` · `BEFORE/AFTER` · `ENTRIES` · `REJECTED` · `MEMO` · `MONITORING`

**WHAT CHANGED:** sector/factor/income/concentration/benchmark/tax impact; overlap with remaining holdings.

**PLANS:** competing Plan A–F cards with tags, confidence, vol Δ, advantages/compromises/risks, unmet exposure (major).

**ENTRIES:** per-leg quote@timestamp, fair value, preferred entry, range, do-not-chase, stages, reserve leg, invalidation.

**EXPORT:** operator-ready trade plan (account, symbol, side, whole shares, limits, stages) — no order placement.

### 8.3 Wireframe (text)

```
┌─ REDEPLOY DESK ─────────────────────────────────────────────────────────────┐
│ FCNTX │ Schwab Rollover IRA │ 14-Jul-26 │ $107,023 │ ⚠ UNSETTLED │ MAJOR   │
│ Exposure: −$27.6k Tech │ −$23.8k Comm Svcs │ Income: $0 │ 6 plans │ OPEN   │
│ Draft: 4 │ Ready: 0 (oversight pending) │ [OPEN] [EXPORT] [DISMISS]        │
├─ PLANS ────────────────────────────────────────────────────────────────────┤
│ [A Strategic] [B Diversified] [C Income] [D Staged★] [E Tactical] [F Hold]│
│ Selected: D — 25% deploy / 75% reserve │ Tags: staged, strategic          │
├─ MEMO ─────────────────────────────────────────────────────────────────────┤
│ FCNTX sale removed $27.6k technology… Proceeds unsettled ($17.5k visible). │
│ Recommend Plan D until settlement; Plan C if income priority.               │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. FCNTX worked example (event #144) — corrected acceptance fixture

**Runtime anchor:** 2026-07-14 detection; regime `risk_on_trend` / `low_vol` (2026-07-13).

| Field | Value | Source |
|-------|-------|--------|
| Proceeds (net) | $107,023.01 | `deploy_events` #144 |
| Account | `schwab_rollover_ira` | sale txn |
| Shares | 4,034.942 | sale txn |
| Settled cash (source acct) | $17,540.67 | `holdings.json` |
| **Deployable cash** | **$17,540.67** | `min(net, settled)` — **P0-2** |
| Planned-not-actionable | $89,482.34 | until settlement verified |
| Reconciliation | **unsettled** | 16.4% of proceeds visible |
| Portfolio equity MV | **$984,179** | `holdings.json` (matches Command Center Holdings) |
| Portfolio total w/ cash | $1,117,827 | cash reported separately in UI |
| SCHG same account | $58,429 | overlap context |
| JEPQ | $59,590 in `fidelity_rollover_ira` | cross-account — not default deploy acct |

### 9.1 Exposure removed (`fund_lookthrough.json`, 2026-07-05)

Sector weights sum **99.98%**; residual bucket **0.02%** (~$21).

| Sector | $ removed |
|--------|-----------|
| Technology | $27,612 (25.8%) |
| Communication Services | $23,770 (22.21%) |
| Financial Services | $16,032 (14.98%) |
| Consumer Cyclical | $10,767 (10.06%) |
| Healthcare | $9,375 (8.76%) |
| Industrials | $9,375 (8.76%) |
| *(remaining sectors)* | $16,692 (15.58%) |

**Top names:** META $12,083 · NVDA $9,557 · AMZN $5,801 · **BRK.A** $5,651 *(share-class note: yfinance reports BRK.A; fund may hold BRK.B economically)*  
**Income:** `income_status=unknown` — **not** $0/yr (P0-3)

### 9.2 Competing plans (summary — archetypes A–G)

| Plan | Archetype | Summary | Actionable today? |
|------|-----------|---------|-----------------|
| **A** | Strategic | QQQM + SCHD + BND basket | Only up to **$17,541** deployable |
| **B** | Diversified | Multi-sector across removed sleeves | Draft |
| **C** | Income | JEPQ + JEPI | Draft; income estimate uses `dividend_calendar` when deployed |
| **D** | Defensive | BND + low-beta | Draft |
| **E** | Tactical | ITA/XAR Defense gap — **not** FCNTX replacement | `RPL-004` if labeled replacement |
| **F** | Staged ★ | Example: 100% of **deployable** into JEPQ leg, stages 25/25/50 **of leg** | Stage 1 ≈ $4,385 (not $26,756) |
| **G** | Hold | 100% reserve / planned-not-actionable $89.5k | **Valid primary** per Q2/Q3 |

### 9.3 JEPQ entry example — Plan F leg only (technicals 2026-07-13 07:33)

Price **$60.12** · SMA20 $60.27 · ATR $0.97 · source `technical_snapshot.json`

**Leg budget (illustrative):** $17,541 deployable × 25% Plan F initial slice × 100% to JEPQ = **$4,385** leg  
Staging **of leg dollars** (25/25/50):

| Stage | % of leg | $ | Shares @ $59.50 pref |
|-------|----------|---|----------------------|
| 1 | 25% | $1,096 | 18 |
| 2 | 25% | $1,096 | 18 |
| 3 | 50% | $2,193 | 36 |

*Prior doc error: staging 25% of total proceeds ($26k+) exceeded deployable cash — corrected per P0-2/P0-9.*

### 9.4 v1 engine vs design intent

| Symbol | v1 score | Design classification |
|--------|----------|----------------------|
| JEPQ | 124.5 | Plan C leg (income + partial growth) |
| ITA | 104.5 | Plan E only — `RPL-004` as FCNTX replacement |
| XAR | 93.1 | Plan E only |
| QQQM | 77.0 | Plan A primary growth restore |
| SCHG | excluded | `RPL-001` duplicate proxy |

---

## 10. Governance

- **Advisory only** — no broker writes from redeploy desk
- **Fidelity** — manual-ticket only (Active Trader Pro)
- **Schwab** — execution only via existing proposal promote + 2FA path
- **No autonomous broker submit**
- **Export trade plan** without placing orders
- **Plan lock** → recompute creates new version; operator-reviewed plans do not silently change
- **Geopolitical** — disclosed in UI; flag only per Q21 (not hidden in composite score)
- **Multi-LLM oversight** required before major `operator_ready`
- **Hermes outcomes** feed learning bus with evidence gates

---

## 11. Phased implementation

| Phase | Deliverable | PR hint |
|-------|-------------|---------|
| **A — Data truth** | **Done** — `redeploy_data_truth.py`, migration, FCNTX tests | PR-Redeploy-A |
| **B — Plan engine** | **Done** — Archetypes A–G, versioning, verifier, rejections | PR-Redeploy-B |
| **C — Entry targets** | **Done** — Entry adapter, staging, whole shares, export | PR-Redeploy-C |
| **D — UI v2** | **Done** — Executive row, plan tabs, before/after, memo, export | PR-Redeploy-D |
| **E — Monitoring** | **Done** — Fill recording, restoration metrics, Hermes outcomes, re-eval cron | PR-Redeploy-E |
| **PR-4 Oversight** | **Done** — `POST /deploy/lock`, `POST /deploy/oversight`, `deploy_oversight_runs` | PR-Redeploy-4 |
| **PR-5 Cron** | **Done** — `install_deploy_redeploy_cron.sh` | PR-Redeploy-5 |

**Dependency order:** A → B (FCNTX E2E) → C → D → PR-4 oversight → E → PR-5 cron.

**Gate:** Phase B merge blocked until Phase A FCNTX acceptance passes in CI + operator sign-off.

---

## 12. Files changed (Phase A)

| Area | Files |
|------|-------|
| **New (Phase A)** | `scripts/lib/redeploy_data_truth.py`, `scripts/lib/redeploy_phase_a_db.py`, `migrations/2026_07_15_redeploy_phase_a_data_truth.sql`, `tests/test_redeploy_phase_a.py` |
| **Modified (Phase A)** | `scripts/lib/deploy_intelligence_engine.py` |
| **Phase B+ (not started)** | `redeploy_plan_engine.py`, `entry_planner_adapter.py`, `api_v2.py` UI |
| Migration (future) | `migrations/2026_07_XX_redeploy_plans_v2.sql` |
| UI | `RedeployPanel.tsx`, `RedeployEventModal.tsx`, new plan components |
| Tests | `test_redeploy_plan_engine.py`, extend `test_deploy_intelligence.py` |
| Docs | This file, `post-sale-redeploy-sync-2026-07-14.md`, `DOCUMENTATION_INDEX.md` |

**Do not touch** without explicit approval: unstaged local changes listed in audit (holdings UI, broker scripts, replay audits, stop tests).

---

## 13. Related documents

| Document | Relationship |
|----------|--------------|
| `docs/runbooks/post-sale-redeploy-sync-2026-07-14.md` | v1 ops runbook (as-built) |
| `docs/project/ETF_FUND_INSTRUMENTS.md` | ETF/sleeve universe |
| `config/rotation_sector_targets.json` | Theme floors/targets |
| `scripts/holding_proxies.py` | Fund proxy map (technicals only in v2) |
| `docs/PROPOSAL_EXECUTION_PATHS.md` | Execution boundaries |
| `scripts/strategy_planner.py` | Parallel Declare/Impact/Advise flow |

---

*Phase A implementation started 2026-07-14. Phases B–E design-only until operator approves merge.*