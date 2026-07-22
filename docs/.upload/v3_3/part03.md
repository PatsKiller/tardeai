If shadow expectancy is negative, lengthen the holding period or retire the module. Do not tighten thresholds to manufacture a backtest.

---

# 16A. ACTIVE TRADER WORKSTATION

## 16A.1 Product intent

The Active Trader workspace is the operator's real-time control surface for momentum names that enter the governed scalp universe.

It must answer, in one view:

- Why is this symbol in scope?
- Is the market data current and entitled?
- What is the tradable float and its source?
- How much volume and dollar volume has traded?
- Is participation expanding or decaying?
- What are the spread, book depth, order-flow imbalance, tape velocity, VWAP, high of day, support, resistance, and halt risk?
- Which accounts are eligible?
- How many shares are authorized per account?
- What is the total risk and gross exposure?
- Is the session saved, authorized, active, paused, or revoked?
- What is the engine doing now?
- Why is the engine holding, scaling, repricing, cancelling, or exiting?
- Where is the complete journal and replay?

The workspace is not merely a visual order-entry form. It is a projection of one server-side session, candidate, order, position, and journal state.

## 16A.2 Current-repository placement

The existing Command Center v3 already has:

- React Router under `/v3`;
- a Trading hub;
- a `Scalp` tab;
- scanner selection;
- broker orders and proposal surfaces;
- execution-quality data;
- API polling conventions.

The new workspace must not be inserted by rewriting the existing Trading hub in place.

Controlling deployment:

```text
/v3
  existing production Command Center
  remains unchanged except for an "Active Trader Next" link and status indicator

/v3-next
  separate Vite entry and bundle
  separate shell
  Active Trader-first layout
  additive APIs
  feature-flagged live controls
```

The two surfaces read the same server-side truth. They do not keep independent authorization or trading state in browser storage.

## 16A.3 Screen layout

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ SESSION STRIP                                                               │
│ mode · 2FA state · account set · loss budget · trades used · cutoff · kill │
├───────────────────────┬────────────────────────────────┬─────────────────────┤
│ PRIME QUEUE           │ SYMBOL WORKSPACE               │ SESSION / ORDER     │
│ ranked candidates     │ chart + VWAP + levels          │ shares / accounts   │
│ state + reason        │ Level 2 ladder                 │ allocation / risk   │
│ float / volume / RVOL │ time & sales                   │ save / 2FA / start  │
│ catalyst / halt       │ deterministic evidence        │ pause / revoke      │
├───────────────────────┴────────────────────────────────┴─────────────────────┤
│ OPEN POSITIONS AND TRADE MANAGEMENT                                         │
│ fills · P&L · MFE/MAE · resilience · resistance · mode · stop · next action│
├──────────────────────────────────────────────────────────────────────────────┤
│ EVENT JOURNAL / ENGINE EXPLANATION / REPLAY                                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 16A.4 Prime queue

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

Side states:
BLOCKED
STALE
ENTITLEMENT_MISSING
QUOTA_DEFERRED
HALTED
SESSION_NOT_AUTHORIZED
RISK_BUDGET_EXHAUSTED
```

A symbol is `PRIMED` only after deterministic gates pass.

Displayed fields:

### Identity and capital structure

- symbol and company;
- exchange;
- current session;
- price;
- gap percent;
- market capitalization;
- issued shares;
- outstanding shares;
- tradable/float shares;
- float-source name;
- float-source timestamp;
- float-source confidence;
- days since listing;
- reverse-split or corporate-action flags.

Moomoo market snapshot may provide issued and outstanding shares, volume, turnover, turnover rate, and market value. The canonical float may also use Moomoo screening or existing Trade AI sources. Conflicts are displayed and resolved through source policy; they are never silently averaged.

### Participation

- current volume;
- pre-market volume;
- regular-session volume;
- dollar volume;
- 1-minute, 5-minute and session RVOL;
- turnover rate;
- tape prints per second;
- tape shares per second;
- block-trade indicators where supported;
- acceleration/deceleration;
- percentage of float traded.

### Price structure

- open;
- previous close;
- pre-market high/low;
- session high/low;
- VWAP;
- anchored VWAPs where configured;
- recent 1-minute and 5-minute swing levels;
- support zones;
- resistance zones;
- LULD distance/status;
- halt and resumption state;
- ATR and realized intraday volatility.

### Microstructure

- bid/ask;
- spread in cents and basis points;
- top-of-book size;
- depth by level;
- level-weighted book imbalance;
- multi-level order-flow imbalance;
- microprice;
- weighted mid;
- bid/ask replenishment;
- cancellation pressure;
- queue persistence;
- aggressor buy/sell ratio;
- sweep and absorption state;
- sequence-gap and staleness state.

### Catalyst and eligibility

- catalyst summary and source;
- catalyst timestamp;
- earnings/event block;
- Watch/Trade AI decision;
- Sentinel state;
- deterministic ticket state;
- borrow/short state where applicable;
- account eligibility;
- margin/day-trading rule state returned by each broker;
- reason in scope;
- reason not yet armed.

## 16A.5 Symbol workspace

The symbol workspace contains:

1. synchronized 1-second, 1-minute, and 5-minute views;
2. VWAP and configured anchored VWAP;
3. support, resistance, HOD, LOD, pre-market levels, and LULD markers;
4. normal aggregated Level 2 ladder;
5. time-and-sales feed;
6. feature history;
7. deterministic trade thesis;
8. current engine state;
9. last action and exact reason;
10. next possible action and conditions.

US Level 2 must not be presented as individual order identity when the entitlement provides only aggregated levels.

## 16A.6 Session and order configuration

The right-side form supports:

### Session fields

- session name;
- broker;
- allowed account checkboxes;
- candidate universe rule or explicit symbol list;
- session start;
- entry cutoff;
- session expiry;
- regular-hours, pre-market, after-hours permissions;
- maximum trades;
- maximum concurrent positions;
- maximum gross notional;
- maximum daily loss;
- maximum risk per trade;
- maximum chase basis points;
- maximum order lifetime;
- runner policy;
- overnight-conversion policy;
- kill-switch behavior.

### Quantity fields

Input modes:

```text
SHARES
DOLLAR_NOTIONAL
RISK_BASED
```

The operator may enter:

- total desired shares;
- per-account shares;
- per-account dollar limit;
- per-account risk limit;
- allocation weights.

Allocation modes:

```text
MANUAL_PER_ACCOUNT
EQUAL_SHARES
EQUAL_NOTIONAL
PROPORTIONAL_TO_BUYING_POWER
PROPORTIONAL_TO_OPERATOR_WEIGHT
```

The server computes and displays:

- total shares;
- estimated gross notional;
- risk per share;
- total risk;
- account buying power remaining;
- account concentration;
- expected number of child orders;
- estimated fees;
- day-trading/intraday-margin eligibility;
- any account-specific block.

The browser never decides account eligibility or final quantity.

## 16A.7 Account checkboxes

Each account row displays:

```text
[ ] account label
    broker
    environment
    account type
    buying power
    settled cash
    margin/intraday state
    open scalp exposure
    day trades or broker intraday-limit state
    maximum shares allowed
    requested shares
    eligibility reason
```

Selecting multiple accounts creates one parent trading decision with separate child order intents.

Each child has its own:

- account;
- quantity;
- idempotency key;
- broker order ID;
- fill state;
- protection state;
- journal stream;
- reconciliation state.

A failure in one account does not cause an unbounded retry or silently duplicate another account's order.

## 16A.8 Save, authorize, and activate workflow

```text
EDITING
  → SAVE SESSION DRAFT
  → VALIDATE SERVER-SIDE
  → SAVED
  → REVIEW AUTHORIZATION ENVELOPE
  → ONE-TIME SESSION 2FA
  → AUTHORIZED
  → ACTIVATE AUTO-TRADE
  → ACTIVE
```

### Save

`SAVE SESSION` persists an immutable draft version but does not unlock OpenD and does not trade.

Any later edit creates a new draft version.

### 2FA

The operator reviews the complete session envelope and completes one 2FA ceremony.

The authorization hash binds:

- accounts;
- quantities and allocation policy;
- symbol/universe policy;
- risk budgets;
- strategy and feature versions;
- allowed sessions;
- time bounds;
- order types;
- chase policy;
- protection policy;
- runner policy;
- model-review policy;
- live-arm token.

### Activate

`ACTIVATE AUTO-TRADE` activates the exact authorized version.

No activation is permitted when the saved draft hash differs from the authorized hash.

### Reconfigure

A material edit while active requires:

```text
PAUSE
  → REVOKE OR DRAIN
  → SAVE NEW VERSION
  → NEW 2FA
  → ACTIVATE
```

## 16A.9 Session strip

The session strip is always visible.

It displays:

- `DRAFT`, `SAVED`, `2FA_REQUIRED`, `AUTHORIZED`, `ACTIVE`, `PAUSED`, `ENTRY_CUTOFF`, `DRAINING`, `REVOKED`, or `CLOSED`;
- authorization ID and short hash;
- selected accounts;
- entry cutoff and expiry in ET;
- trades used/maximum;
- positions open/maximum;
- gross notional used/maximum;
- realized plus open P&L;
- daily loss used/maximum;
- Moomoo trade-lock state;
- gateway health;
- data freshness;
- kill switch.

A red `REVOKE / EXIT-ONLY` control remains accessible without scrolling.

## 16A.10 Browser and server authority

Browser state may contain only presentation preferences.

The authoritative session is server-side.

Refresh, browser closure, duplicate tabs, and switching between `/v3` and `/v3-next` must not create, renew, or lose authorization.

Concurrent browser actions use optimistic version checks.

---

# 16B. LEVEL 2 ENTRY AND ORDER MANAGEMENT

## 16B.1 Research basis and limitation

Queue imbalance and order-flow imbalance can contain short-horizon information, but they are not reliable as isolated static signals.

The engine therefore combines:

- multi-level order-flow imbalance;
- queue imbalance;
- depth;
- spread;
- microprice;
- replenishment/cancellation;
- tape aggression;
- price structure;
- volatility;
- persistence;
- data integrity.

The book may contain fleeting or deceptive liquidity. A displayed wall is evidence only after persistence and execution behavior support it.

## 16B.2 Core deterministic features

### Level-weighted book imbalance

```text
LWI = Σ(w_l × (bid_size_l - ask_size_l) / (bid_size_l + ask_size_l))
```

Weights decay by level.

### Microprice

```text
microprice =
  (ask_price × bid_size + bid_price × ask_size)
  / (bid_size + ask_size)
```

### Order-flow imbalance

Use changes in prices and sizes across book events, not only the current snapshot.

Store:

- top-level OFI;
- integrated multi-level OFI;
- 1-second, 5-second, 15-second, and 60-second OFI;
- normalized OFI by local depth.

### Resilient liquidity features

- bid replenishment after market sells;
- ask depletion after market buys;
- time required to restore depth;
- cancellation burst asymmetry;
- spread recovery;
- reclaim speed after adverse prints.

## 16B.3 Prime and fire logic

A symbol may arm only when:

- candidate and session policy permit;
- quote/book/tape are current;
- sequence continuity is healthy;
- spread is executable;
- minimum dollar volume and depth pass;
- current price structure is valid;
- catalyst/event gates pass;
- account and session risk remain available.

A fire must require a price event plus flow confirmation.

Example governed fire:

```text
price breaks or reclaims trigger
AND integrated OFI positive
AND tape aggression positive
AND microprice at/above mid by threshold
AND spread within limit
AND book/tape persistence exceeds minimum duration
AND no LULD, halt, stale-data, event, risk, or session block
```

## 16B.4 Entry-price modes

```text
PASSIVE_JOIN
IMPROVE_ONE_TICK
MIDPOINT_LIMIT
MARKETABLE_LIMIT
NO_ENTRY
```

No market entry is used in the initial live canary.

The selected mode depends on:

- urgency;
- spread;
- microprice;
- queue persistence;
- tape velocity;
- trigger distance;
- available depth;
- maximum authorized slippage.

## 16B.5 Central account rate governor

Moomoo's documented account limits include:

```text
place_order:  15 requests per 30 seconds per account
modify_order: 20 requests per 30 seconds per account
```

The older 750 ms fixed chase loop is prohibited because one order could exceed the modify limit.

One account-level token bucket governs:

- placements;
- modifications;
- cancellations;
- protection changes;
- emergency reserve.

Required policy:

- reserve capacity for cancel and protection actions;
- dynamically divide modification budget across working orders;
- throttle lower-priority entries before protection;
- never consume emergency reserve for ordinary price improvement;
- expose budget in the UI;
- fail closed before exceeding provider limits.

Initial safe policy:

```text
ordinary modify budget: <= 16 per 30 seconds/account
reserved emergency/protection budget: >= 4 per 30 seconds/account
single-order ordinary reprice floor: >= 1.9 seconds
multiple-order interval: dynamically slower
```

The final values are capability-probed and tested.

## 16B.6 Bounded smart-limit algorithm

Each order stores:

- arrival bid/ask/mid;
- arrival microprice;
- trigger price;
- reference price;
- maximum authorized price;
- maximum chase bps;
- TTL;
- rate-governor budget;
- current state.

Loop:

```text
if filled:
    stop entry management
elif quote/book/tape stale or sequence broken:
    cancel
elif session revoked or entry cutoff passed:
    cancel
elif spread exceeds cap:
    cancel or hold without repricing
elif flow reverses beyond configured persistence:
    cancel
elif next price breaches authorized cap:
    hold at cap or cancel
elif rate token unavailable:
    wait
else:
    calculate deterministic next limit
    submit one governed modification
```

The next limit may improve by one tick, move toward microprice, or become a marketable limit within the signed cap.

## 16B.7 Partial fills and account fan-out

Partial fills are first-class.

For every account:

- protect filled quantity immediately;
- reprice only the remaining quantity;
- never change total authorized quantity;
- cancel remainder when thesis fails;
- journal filled and unfilled opportunity separately.

When multiple accounts are selected:

- child orders are independently rate-governed;
- allocation drift is visible;
- no child order is duplicated to compensate for another account unless the envelope explicitly allows reallocation;
- aggregate risk is recomputed after every fill.

## 16B.8 OpenD unlock and Trade AI authorization

Moomoo documents that unlocking is an OpenD-wide state: if one connection unlocks trading, other connections can use trading interfaces.

Therefore:

- OpenD binds to localhost or an isolated network namespace;
- one Trade AI execution gateway owns the live trading connection;
- no research, agent, UI, or ad hoc script may connect to the live trade interface;
- session 2FA creates Trade AI authorization first;
- only then may the gateway unlock OpenD;
- every order still passes the internal session-policy check;
- session close or revocation locks OpenD after working orders and positions are safely handled;
- OpenD unlock is never treated as sufficient authorization.

---

# 16C. IN-TRADE RESILIENCE, RESISTANCE, AND RUNNER MANAGEMENT

## 16C.1 Objective

A profitable trade should not exit merely because it pauses.

It also should not convert a scalp into an unbounded hope trade.

The position manager must distinguish:

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

## 16C.2 Two independent scores

### Resilience Score — `RES`

Measures whether demand continues to defend the trade.

Initial components:

| Component | Weight |
|---|---:|
| Price above VWAP / relevant anchor | 12 |
| Higher-low or base structure | 12 |
| Pullback depth normalized by ATR/impulse | 10 |
| Reclaim speed after adverse excursion | 10 |
| Bid replenishment persistence | 10 |
| Integrated OFI | 12 |
| Tape aggression | 10 |
| Spread stability/recovery | 6 |
| Volume continuation | 8 |
| Distance from hard invalidation | 5 |
| Catalyst and market context intact | 5 |

### Resistance Score — `RRS`

Measures whether supply is likely to stop continuation.

Initial components:

| Component | Weight |
|---|---:|
| Proximity to verified HOD/resistance | 10 |
| Repeated rejection count | 12 |
| Ask replenishment/stacking persistence | 12 |
| Negative integrated OFI | 12 |
| Aggressor selling | 10 |
| Microprice below mid | 7 |
| Spread widening | 7 |
| Tape/volume deceleration | 8 |
| Failed breakout/reclaim | 12 |
| LULD/halt or event risk | 10 |

Weights are experiment seeds and live only after shadow/simulation evaluation.

## 16C.3 Score integrity

A book-only feature cannot dominate.

Requirements:

- minimum persistence;
- minimum event count;
- tape confirmation;
- no sequence gaps;
- session-specific thresholds;
- volatility normalization;
- large-tick/small-tick profile;
- float and liquidity profile;
- no stale feature reuse.

## 16C.4 Decision matrix

| RES | RRS | Deterministic interpretation | Default action |
|---:|---:|---|---|
| >=75 | <=35 | resilient continuation | hold; runner evaluation |
| >=70 | 36–60 | demand intact, supply present | partial scale or tighter structure stop |
| 50–69 | <=45 | ordinary pullback | hold if hard thesis intact |
