# Cross-Asset Decision Intelligence — Master Implementation Plan

Status: ACTIVE  
as_of: 2026-09-29T17:45:00-04:00  
Measured at: repo `wt/cross-asset-decision-intel` @ base `86e228273` + this program’s commits  
Canonical repo path: `docs/CROSS_ASSET_DECISION_INTELLIGENCE_IMPLEMENTATION_PLAN.md`  
Authority: Operator directive 2026-09-29 — Plan → Build → Test → Validate → Shadow → Readiness  
Supersedes: none (new program)  
See also: `docs/CROSS_ASSET_DECISION_INTELLIGENCE_TEST_PLAN.md`, `docs/CROSS_ASSET_DECISION_INTELLIGENCE_BACKLOG.md`, `docs/CROSS_ASSET_DECISION_INTELLIGENCE_READINESS_REPORT.md`, `scripts/lib/options_decision_packet_v2.py`, `scripts/lib/agent_decision_payload.py`, `scripts/lib/options_strategy_matrix.py`, `scripts/missed_opportunity_policy.py`

---

## 0. Program north-star

> For every investment decision in the platform, what is the highest expected-value **expression** of that thesis (shares / long call / CSP / spread / covered call / protective put / collar), and can we **prove** it with lineage?

**Hard rule:** advisory-only until Readiness says READY. Shadow mode records decisions; it does not place orders.

---

## 1. Current State (measured)

### 1.1 What exists today

| Surface | What is real |
|---|---|
| **Portfolio** | Holdings JSON + broker sync; CIO product surfaces book; positions drive coverage gates for covered calls. |
| **Watchlists** | `watch_directives` + ranked `/api/v2/watchlist`; directive promote bounded; Hermes research queue; provenance per symbol. |
| **CIO** | Desk loop, situations, operator product, reentry book (Surface A), gap resolver + pending fulfill. |
| **Hermes** | Research requests/results JSONL + projection; specialist artifacts; lineage envelopes. |
| **Options Desk** | `OptionsDecisionPacket@v1/v2`, strategy matrix (CC/CSP/PP/long call/debit/credit), enterprise desk, research universe, identity GUIDs. |
| **Re-Entry** | Reentry decision desk statuses (READY/NEAR); CIO situations read desk read-only. |
| **Research** | Hermes + llm_curation interim; operator watch research priority; thesis fields often `INSUFFICIENT_DATA`. |
| **Signal Generation** | Screeners, watch alerts, proposal lifecycle, active trader policies — **per-lane**, not unified. |
| **Scheduler** | systemd + cron on CURRENT; Hermes workers; CIO telegram loop. |
| **Persistence** | Postgres (directives, watchlist) + `data/cio/*.jsonl` ledgers + persistent-state symlink. |
| **Decision lineage** | `DecisionPayload@v1` (flagged `AGENT_DECISION_PAYLOAD`), agent run traces. |
| **Missed opportunity** | `missed_opportunity_policy.py` — proposal timing classification only (not expression EV). |

### 1.2 What partially exists

- Options vs stock **comparison** inside OptionsDecisionPacket (stock_play / options_play) — not generalized to every Buy/Hold/Sell/Reentry signal.
- Identity linking (`subject_guid`, `issuer_guid`, options identity) — used in options/CIO lineage, **not** as a single SymbolDecisionObject.
- Shadow / measurement flags (`AGENT_DECISION_PAYLOAD`, memory shadow) — not a cross-asset expression shadow.
- Collar family listed in `ABSENT` matrix set — known gap.

### 1.3 What is missing

- Canonical **SymbolDecisionObject** spanning equity thesis → expression ranking.
- Unified update path triggered by research complete / signal / position change / CIO situation.
- Cross-asset **ranking engine** with comparable EV / R:R / risk units across expressions.
- Missed-opportunity **ledger** for “shares chosen when CSP/call was superior” (and reverse).
- Historical replay harness for 30/60/90d expression counterfactuals.
- UI surface for SymbolDecisionObject.
- Production go-live gate for expression routing (today: NOT READY).

### 1.4 What is duplicated

- Decision-shaped payloads: DecisionPayload@v1, OptionsDecisionPacket@v2, proposal packets, alert routing decisions, risk decisions.
- Symbol identity resolution in multiple libs (identity_registry, options_identity, desk evidence gatherers).

### 1.5 What is disconnected

- Hermes completed research does not always open/fulfill operator pending (fixed partially 2026-09-29 for interim+queue; broader expression reevaluation still unwired).
- Options desk packets do not systematically refresh when watchlist research lands.
- Reentry READY does not auto-evaluate CSP vs shares vs spread.
- Aegis / defense surfaces are separate from options expression ranking.
- Scheduler fires lane jobs; no single “reevaluate SymbolDecisionObject” consumer.

---

## 2. Gap Analysis (capability matrix)

| Capability | Status | Complexity | Risk | Dependencies |
|---|---|---|---|---|
| SymbolDecisionObject schema | Missing → **building Phase 1** | Medium | Low | identity_registry, JSONL append hygiene |
| Assemble from portfolio/watch/CIO/Hermes/options | Missing → Phase 1–2 | Large | Medium | holdings, provenance API, hermes results, options packets |
| Cross-system identity linking | Partial | Medium | Medium | subject_guid / issuer_guid consistency |
| Options expression router (Buy/Hold/Reentry/Sell) | Partial (matrix only) | Large | High | options chains, quotes, cash, share coverage |
| Event-driven reevaluation | Missing | Large | Medium | research complete events, watch alerts, position deltas |
| Missed opportunity ledger (expression) | Partial (timing only) | Medium | Low | SymbolDecisionObject history |
| Cross-asset ranking engine | Missing | Large | High | comparable EV model, risk unit, liquidity |
| UI integration | Missing | Medium | Low | CC v3 API + SymbolDecisionObject store |
| Shadow mode continuous | Missing → Phase 3/6 | Medium | Low | scheduler, no broker writes |
| Historical 30/60/90 replay | Missing | Large | Medium | historical prices, past signals, options chains archive |
| Production go-live | Missing | Large | High | readiness report READY + operator approval |

---

## 3. Target Architecture

### 3.1 SymbolDecisionObject (canonical)

```
SymbolDecisionObject@v1
  identity              # symbol, subject_guid, issuer_guid, as_of
  equity_thesis         # stance, summary, conviction, invalidation, source refs
  research_state        # hermes_request_id, result_id, status, age_hours
  event_state           # catalysts, regime, material flags
  signal_state          # buy|hold|sell|reentry|none, lane, signal_id, fired_at
  position_state        # held qty, accounts, cost basis band, coverage
  options_state         # packets[], chain_as_of, liquidity notes
  cio_state             # situation ids, product refs, advisory stance
  historical_state      # prior decisions[], outcomes refs
  expression_comparison # ranked ExpressionCandidate[]
  audit_history         # who/what/when updates
```

**ExpressionCandidate:** `{ family, structure, expected_value, reward_to_risk, max_loss, pop, blocks[], rank, shadow_only }`

Families evaluated by signal class (shadow):

| Signal | Expressions |
|---|---|
| Buy | shares, long_call, CSP, call_spread (debit) |
| Hold | shares, covered_call, protective_put, collar* |
| Re-entry | shares, CSP, spread |
| Sell | sell_shares, collar*, protective_put |

\*collar remains `ABSENT` in matrix → candidate may be `status=unavailable` until implemented.

### 3.2 Ownership

| Field group | Owner writer | Readers |
|---|---|---|
| identity | `cross_asset.assemble` via identity_registry | all |
| equity_thesis / research_state | Hermes projection + assemble | CIO, options router |
| signal_state | lane emitters (watch/reentry/alerts) | router |
| position_state | holdings snapshot | options gates |
| options_state | options desk builders | ranking |
| expression_comparison | `cross_asset.expression_router` | UI, ledger, shadow |
| persistence | `cross_asset.persistence` → `data/cio/symbol_decisions.jsonl` | API, replay |

### 3.3 Update paths / event triggers

1. Hermes research COMPLETED for symbol → assemble + route (shadow).  
2. Watch alert / CIO BUY-ish signal → assemble + route.  
3. Reentry status → READY/NEAR → assemble + route.  
4. Position delta (shares cross 100 / cash change) → refresh Hold expressions.  
5. Nightly batch → historical + missed-opportunity ledger.  

### 3.4 Persistence

- Append-only JSONL: `data/cio/symbol_decisions.jsonl` (schema `SymbolDecisionObject@v1`).  
- Optional projection index later; Phase 1 is file-ledger only (matches CIO pattern).  
- Authority: `READ_ONLY_ADVISORY` on every row.

---

## 4. Implementation Milestones

### Phase 1 — Canonical SymbolDecisionObject
Schema, validate, persist, assemble stub, unit tests.

### Phase 2 — Cross-system identity linking
Wire subject_guid/issuer_guid; join Hermes result + watch provenance + holdings.

### Phase 3 — Options routing layer (shadow)
Expression router for Buy/Hold/Reentry/Sell using strategy matrix + honesty (blocks / unavailable).

### Phase 4 — Event-driven reevaluation
Hooks from Hermes complete + reentry desk + watch alert emitters (flag-gated).

### Phase 5 — Missed opportunity ledger
Expression counterfactual ledger distinct from proposal timing policy.

### Phase 6 — Cross-asset ranking engine
Comparable EV scoring + rank stability tests.

### Phase 7 — UI integration
CC read API + thin Symbol Intelligence panel (no trade buttons).

### Phase 8 — Shadow mode
Continuous cycle CLI + systemd timer candidate; record only.

### Phase 9 — Production validation
Historical 30/60/90 harness + metrics; failure budget.

### Phase 10 — Go-live
Operator approval; feature flag; rollback pin.

---

## 5. Acceptance Criteria (per phase)

| Phase | Pass | Fail | Rollback | Owner | Dependencies |
|---|---|---|---|---|---|
| 1 | Schema validate + persist roundtrip tests green; sample assemble for NFLX | Invalid schema written to ledger | Delete feature module; no flag on | Staff Eng | identity helpers |
| 2 | Linked IDs present when stores have them; hermetic fixtures | Fabricated GUIDs | Disable linker | Staff Eng | Phase 1 |
| 3 | Each signal class emits ranked candidates; collar unavailable honest | Silent skip of required family | Flag off | Options + Staff | matrix |
| 4 | Event hook fires assemble in dry_run | Hook writes broker | Flag off | Staff Eng | Phase 2–3 |
| 5 | Ledger rows for sample counterfactuals | Overwrites timing policy | Separate file only | Staff Eng | Phase 3 |
| 6 | Rank metrics on fixture set | Unbounded EV invention | Flag off | Quant + Staff | Phase 3 |
| 7 | Read-only UI | Trade CTA | Revert UI | FE + Staff | API |
| 8 | Shadow cycle ≥1 successful run | Any order submit | Stop timer | Ops + Staff | Phase 3 |
| 9 | 30d harness produces metrics file | Harness invents fills | N/A | QA + Staff | archives |
| 10 | Readiness READY + grant | Cond./Not Ready | Pin prior release | CIO Ops | all |

---

## 6. Execution log (system of record)

### Phase 1 — Canonical SymbolDecisionObject
Status: COMPLETE  
Date: 2026-09-29  
Commit: bc9b38c1d  
Files changed: `scripts/lib/cross_asset/symbol_decision_object.py`, `persistence.py`, `assemble.py`, tests, docs  
Tests passed: 8/8 hermetic (`test_cross_asset_symbol_decision_object_20260929.py`)

### Phase 2 — Cross-system identity linking
Status: COMPLETE (scaffold)  
Date: 2026-09-29  
Commit: _(same cut)_  
Files changed: `assemble.py` (subject_guid / issuer_guid / hermes result_id join)  
Tests passed: assemble fixture links `ecb5ba89-test` + `rr_4a877da8499b`  
Note: Live store auto-join still Phase 4 event wiring.

### Phase 3 — Options routing layer (shadow)
Status: COMPLETE (scaffold)  
Date: 2026-09-29  
Commit: _(same cut)_  
Files changed: `expression_router.py`, shadow CLI  
Tests passed: Buy/Hold/Reentry/Sell routing + collar unavailable honesty  
Note: No chain pricing / EV yet.

### Phase 4 — Event-driven reevaluation
Status: PARTIAL  
Date: 2026-09-29  
Files changed: `events.py` (`CROSS_ASSET_SHADOW` flag)  
Tests passed: flag off no-write; flag on writes ledger  
Gap: not hooked into Hermes complete producer yet.

### Phase 5 — Missed opportunity ledger
Status: COMPLETE (scaffold)  
Date: 2026-09-29  
Files changed: `missed_opportunity_ledger.py`  
Tests passed: counterfactual row when chosen≠top

### Phase 6 — Cross-asset ranking engine
Status: PENDING (structural rank only; EV null)

### Phase 7 — UI integration
Status: PENDING

### Phase 8 — Shadow mode
Status: PARTIAL (CLI dry-run + apply-ledger proven; no systemd timer)

### Phase 9 — Production validation
Status: PARTIAL (replay harness returns INSUFFICIENT_DATA without archives — correct honesty)

### Phase 10 — Go-live
Status: NOT READY — see Readiness Report

---

## 7. Explicit non-goals (until READY)

- Auto-trading options or equity from this object.  
- Replacing OptionsDecisionPacket@v2 (we **embed/reference** it).  
- Inventing collar pricing before matrix support.  
- Treating hermetic PASS as OBSERVED_LIVE.
