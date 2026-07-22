# TRADE AI MASTER AGENTIC FINANCIAL SYSTEM ARCHITECTURE v3.2
## Canonical Active Trader, Moomoo Level 2, Live Momentum Scalp, Journal, and Dual-Dashboard Amendment

**Status:** ARCHITECTURE-OWNER APPROVED IMPLEMENTATION BLUEPRINT  
**Date:** 2026-07-22  
**Supersedes:** `TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_1.md` where this amendment conflicts.  
**Full canonical artifact SHA-256:** `8085c644efcf6039eb236566bdaaae5496546d09949812577d68d92058f635bc`  
**Full canonical artifact length:** 4,228 lines  
**Codex implementation prompt:** `docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_0.md`  
**Codex prompt SHA-256:** `27ea012c863c486c48be850b7af5fd3abf1311dc5654082d489704fddb8e03cf`

The full v3.2 artifact contains the complete v3.1 architecture plus this amendment. This Git entry records the controlling product, execution, UX, market-data, journal, rollout, and implementation requirements.

## 1. Architecture-owner approval

The architecture owner authorizes:

1. a new Active Trader workspace;
2. a quasi-parallel `/v3-next` dashboard while `/v3` remains operational;
3. operator-selected account checkboxes and share quantities;
4. saved session drafts;
5. one 2FA ceremony for a bounded momentum-scalp session;
6. automatic live entries, bounded repricing, protection, scale-outs, runner management, exits, and reconciliation inside the signed session;
7. Moomoo Level 2 and time-and-sales-informed execution;
8. deterministic resilience/resistance trade management;
9. complete journal, replay, Darwin scoring, and governed learning;
10. staged Codex implementation with stop points and evidence.

No implementation agent may change these financial guardrails without another explicit architecture-owner amendment.

## 2. Dual-dashboard delivery

```text
/v3
  current Command Center
  remains available and rollback-ready

/v3-next
  separate Vite application and bundle
  Active Trader-first operator workspace
  additive APIs and schemas
```

The old application may receive only an additive link/status indicator during initial stages.

The new application must not replace `TradingHub`, change the `/v3` basename, delete routes, move legacy APIs, or force current consumers to migrate.

Both dashboards read one server-side session and trading state. Browser storage is not an authorization source.

Required feature flags:

```text
active_trader_next_visible
active_trader_next_read_only
active_trader_session_builder_enabled
active_trader_simulation_enabled
active_trader_live_canary_enabled
active_trader_multi_account_enabled
active_trader_runner_enabled
active_trader_overnight_conversion_enabled
```

Rollout:

```text
READ_ONLY_MIRROR
→ SHADOW_ENGINE
→ SIMULATION
→ LIVE_CANARY
→ DUAL_OPERATION
→ PRIMARY only after a separate decision
```

## 3. Active Trader workspace

The screen contains:

```text
SESSION STRIP
PRIME QUEUE
SYMBOL WORKSPACE
LEVEL 2 LADDER
TIME AND SALES
SESSION / ORDER BUILDER
OPEN POSITIONS
TRADE MANAGEMENT
EVENT JOURNAL / REPLAY
```

### Prime queue fields

- symbol, company, exchange, session and current price;
- gap, market cap, issued shares, outstanding shares and tradable float;
- source, timestamp and confidence for float;
- current, pre-market and regular-session volume;
- dollar volume, turnover, RVOL and percent of float traded;
- catalyst, event block and data freshness;
- VWAP, HOD/LOD, pre-market levels, support, resistance and LULD state;
- spread, depth, microprice, level-weighted imbalance and integrated OFI;
- replenishment, cancellation pressure, tape velocity and aggressor balance;
- Watch/Trade AI decision, Sentinel state and ticket verification;
- account eligibility and in-scope/blocked reason.

Candidate lifecycle:

```text
DISCOVERED
→ IN_SCOPE
→ PRIMING
→ PRIMED
→ ARMED
→ FIRED
→ WORKING
→ FILLED
→ MANAGING
→ FLAT
```

Side states include `BLOCKED`, `STALE`, `ENTITLEMENT_MISSING`, `QUOTA_DEFERRED`, `HALTED`, `SESSION_NOT_AUTHORIZED`, and `RISK_BUDGET_EXHAUSTED`.

## 4. Account and quantity configuration

The operator may select accounts using checkboxes and enter:

```text
SHARES
DOLLAR_NOTIONAL
RISK_BASED
```

Allocation modes:

```text
MANUAL_PER_ACCOUNT
EQUAL_SHARES
EQUAL_NOTIONAL
PROPORTIONAL_TO_BUYING_POWER
PROPORTIONAL_TO_OPERATOR_WEIGHT
```

Each account row displays broker, environment, account type, buying power, settled cash, current intraday-margin state, open exposure, maximum allowed shares, requested shares, and eligibility reason.

The server, not the browser, calculates:

- maximum shares;
- total shares;
- gross notional;
- risk per share;
- aggregate risk;
- concentration;
- account buying power;
- expected child orders;
- account-specific blocks.

A multi-account parent decision creates separate child order intents, idempotency keys, broker IDs, protection states, journals and reconciliation states.

## 5. Save, 2FA, and activate

```text
EDITING
→ SAVE SESSION DRAFT
→ SERVER VALIDATION
→ SAVED
→ REVIEW ENVELOPE
→ ONE-TIME SESSION 2FA
→ AUTHORIZED
→ ACTIVATE AUTO-TRADE
→ ACTIVE
```

`SAVE SESSION` cannot trade.

The authorization hash binds:

- accounts and quantities;
- universe rule or explicit symbols;
- strategy, ticket, feature, risk and runner-policy versions;
- start, entry cutoff and expiry;
- maximum trades and concurrent positions;
- maximum gross and per-trade notional;
- maximum risk per trade and daily loss;
- order types, sessions, chase limits and TTL;
- protection policy;
- model-review policy;
- live-arm token and operator identity.

A material edit requires pause/revocation, a new saved version, new 2FA and reactivation.

Browser refresh, duplicate tabs and switching dashboards cannot create or renew authorization.

## 6. Moomoo execution constraints

Moomoo is accessed through one isolated execution gateway.

OpenD unlock is shared across connections, so:

- OpenD is localhost/network-isolated;
- only the deterministic execution gateway may use the live trade interface;
- no agent, UI or ad hoc script may connect to live trading;
- internal Trade AI session policy is checked for every order even while OpenD is unlocked;
- revocation closes new entries and locks OpenD after safe drain/reconciliation.

Documented account limits:

```text
place_order:  15 requests / 30 seconds / account
modify_order: 20 requests / 30 seconds / account
```

The legacy 750 ms chase loop is prohibited.

A centralized account token bucket must:

- reserve at least 20% of modify capacity for cancel/protection;
- divide ordinary capacity across working orders;
- throttle entries before protection;
- expose remaining budget;
- reject before exceeding provider limits.

Initial safe ordinary modify budget:

```text
<=16 modifications / 30 seconds / account
single-order ordinary reprice floor >=1.9 seconds
multiple-order repricing dynamically slower
```

Final values require capability probes and replay tests.

## 7. Level 2 entry management

Level 2 is not sufficient by itself.

A live action requires:

- current quote, book and tape;
- sequence integrity;
- persistence;
- tape confirmation;
- price-structure agreement;
- spread/depth eligibility;
- risk and session eligibility.

Deterministic features:

```text
level-weighted book imbalance
top-level and multi-level OFI
microprice
weighted mid
bid/ask replenishment
cancellation asymmetry
tape aggressor ratio
tape velocity
sweep/absorption state
spread recovery
```

Entry modes:

```text
PASSIVE_JOIN
IMPROVE_ONE_TICK
MIDPOINT_LIMIT
MARKETABLE_LIMIT
NO_ENTRY
```

Initial live canary uses no market entry.

The bounded loop cancels on stale data, sequence gap, revocation, cutoff, spread blowout, persistent flow reversal, cap breach or expired TTL.

Partial fills are protected immediately. Only the unfilled remainder may be repriced.

## 8. Resilience and resistance methodology

The position manager maintains two independent deterministic scores.

### Resilience Score `RES`

Measures demand defense using:

- price above VWAP/anchor;
- higher-low/base structure;
- volatility-normalized pullback depth;
- reclaim speed;
- bid replenishment;
- integrated OFI;
- tape aggression;
- spread stability;
- volume continuation;
- distance from invalidation;
- catalyst/market context.

### Resistance Score `RRS`

Measures supply dominance using:

- proximity to verified resistance/HOD;
- repeated rejection;
- ask replenishment;
- negative OFI;
- aggressor selling;
- microprice below mid;
- spread widening;
- volume/tape deceleration;
- failed breakout/reclaim;
- halt/event risk.

Initial decision matrix:

| RES | RRS | Interpretation | Default action |
|---:|---:|---|---|
| >=75 | <=35 | resilient continuation | hold and evaluate runner |
| >=70 | 36–60 | demand intact, supply present | partial or tighter structure stop |
| 50–69 | <=45 | ordinary pullback | hold while hard thesis remains |
| 50–69 | >60 | resistance gaining | reduce or exit |
| <50 | any high-risk state | resilience failure | exit |
| any | >=80 | resistance dominant | exit/major reduction |
| any | data invalid | unknown | protective fallback |

A one-tick book flip is never enough. Book evidence requires persistence, event count, tape confirmation and no sequence gap.

Hard exits do not wait for a model.

## 9. Runner and longer-hold logic

A profitable scalp does not become a hope trade.

States:

```text
NORMAL_PULLBACK
RESILIENT_CONTINUATION
SUPPLY_TEST
RESISTANCE_DOMINANT
THESIS_FAILURE
RUNNER_CANDIDATE
RUNNER_CONFIRMED
INTRADAY_TREND_HOLD
OVERNIGHT_CONVERSION_CANDIDATE
```

`RUNNER_CANDIDATE` requires profit by configured R, high RES, low RRS, intact price structure, continuing participation, sufficient session time and an authorized runner policy.

`RUNNER_CONFIRMED` requires persistence.

An intraday runner may trail by 1-minute/5-minute structure, anchored VWAP, ATR/chandelier or confirmed higher low.

Overnight conversion requires all of:

- `overnight_conversion_allowed=true` in the session;
- separate verified swing/position-management ticket;
- event eligibility;
- account eligibility;
- overnight gap-risk calculation;
- new stop and size policy;
- deterministic conversion artifact.

Otherwise the scalp is flat by session policy.

## 10. Protection and kill switch

Every fill must receive broker-native or equivalent independently survivable protection before another entry is allowed.

Exit-only mode:

```text
SESSION_REVOKED_FOR_NEW_ENTRIES
ENTRY_DISABLED
PROTECTION_PRESERVED
OPEN_SESSION_POSITIONS_MANAGED_TO_FLAT
SESSION_AUTHORIZED_EXITS_AUTOMATIC
BROKER_RESIDENT_STOPS_REMAIN_ACTIVE
OPERATOR_ALERTED
```

Revocation never removes protection.

## 11. Journal and learning

Every candidate/trade is event-sourced.

Required events include candidate, prime, arm, fire, draft, authorization, activation, order, modifications, fills, protection, score changes, scales, exits, revocation, closeout, reconciliation and outcome scoring.

Compact feature snapshots live in PostgreSQL. High-frequency market data lives in append-only replay files. Journal events reference replay segment, sequence range, source timestamps, policy versions, code SHA, authorization hash and account child order.

Score:

- arrival/fill/slippage;
- time to fill and modification count;
- partial-fill ratio;
- MFE, MAE and realized R;
- capture ratio and exit efficiency;
- runner outcome;
- counterfactual +30s, +2m, +5m, +15m, close and next-session outcomes;
- account differences;
- rate-governor waits;
- gateway/data incidents.

Darwin scores prime, fire, execution, resilience, resistance, scale, runner and exit quality.

Nightly reflection, Iris and Hermes may create lesson/hypothesis candidates. They may not change live thresholds directly.

## 12. Staged implementation spine

```text
Stage 0  baseline and mapping
Stage 1  additive schema, contracts and flags
Stage 2  /api/v3/active-trader read plane
Stage 3  Moomoo data gateway and rate governor
Stage 4  /v3-next read-only UI
Stage 5  session builder, account checkboxes and save
Stage 6  session 2FA and authorization service
Stage 7  shadow prime/fire/RES/RRS
Stage 8  simulation execution
Stage 9  journal, Darwin and learning
Stage 10 controlled live canary
Stage 11 dual-operation primary-surface decision
```

The exact Codex prompts and stage gates are in the companion prompt file.

## 13. Acceptance invariants

```text
/V3 AVAILABLE: YES
/V3-NEXT AVAILABLE: YES
OLD/NEW SWITCH VERIFIED: YES
SERVER-SIDE SESSION STATE: VERIFIED
ACCOUNT CHECKBOX VALIDATION: VERIFIED
PER-ACCOUNT QUANTITY VALIDATION: VERIFIED
DRAFT/AUTHORIZATION HASH MATCH: VERIFIED
ONE-TIME SESSION 2FA: VERIFIED
ORDERS OUTSIDE SESSION AUTHORIZATION: 0
ORDERS AFTER ENTRY CUTOFF: 0
SESSION LIMIT BREACHES REACHING ADAPTER: 0
MOOMOO PLACE RATE-LIMIT VIOLATIONS: 0
MOOMOO MODIFY RATE-LIMIT VIOLATIONS: 0
UNPROTECTED LIVE FILLS: 0
BOOK-ONLY UNCONFIRMED ACTIONS: 0
DUPLICATE MULTI-ACCOUNT ORDERS: 0
BROKER/DB POSITION MISMATCH: 0
JOURNAL REQUIRED-EVENT COMPLETENESS: 100%
REPLAY REFERENCES: 100%
LIVE ACTIVATION DURING PARITY MISMATCH: 0
REFLECTIVE-AGENT BROKER WRITES: 0
```

## 14. Research and repository basis

Repository inspection confirms:

- Command Center v3 is React/Vite/TypeScript with React Router under `/v3`;
- `TradingHub` already contains a `Scalp` tab, scanner data, broker orders and execution-quality surfaces;
- terminal chrome is currently always on rather than toggleable.

Primary external evidence used:

- Moomoo OpenAPI v10.9 quote, snapshot, order-book, ticker, subscription, unlock, place and modify documentation;
- Cont, Kukanov and Stoikov on order-flow imbalance;
- Gould and Bonart on queue imbalance;
- Cont, Cucuringu and Zhang on multi-level integrated OFI;
- SEC Release 34-105226 on the 2026 intraday-margin transition;
- OpenAI Codex guidance on repository instructions, planning, testing, sandboxing, approvals and auditability.

The research supports feature inclusion and operational constraints. It does not establish profitable edge. Edge must be demonstrated through Trade AI replay, shadow, simulation and live-canary evidence.
