| 50–69 | >60 | resistance gaining | reduce or exit by policy |
| <50 | any high-risk state | resilience failure | exit |
| any | >=80 | resistance dominant | exit/major reduction |
| any | data invalid | unknown | protective fallback |

## 16C.5 Hard exits

Hard exits remain deterministic and do not wait for a model:

- broker-native protective stop;
- catastrophic spread or liquidity failure;
- session daily-loss breach;
- LULD/halt risk rule;
- negative catalyst rule;
- data/gateway failure without safe broker protection;
- account or broker rejection that leaves protection uncertain;
- operator kill switch;
- session flat-by rule.

## 16C.6 Soft exits and resilient holds

A soft exit requires persistence and combined evidence.

Examples:

```text
RES drops below threshold for configured duration
RRS rises above threshold for configured duration
VWAP loss + negative OFI + tape selling
failed HOD reclaim + ask replenishment + volume decay
```

A temporary one-tick book flip is not an exit.

A resilient hold may survive:

- a pullback within a volatility-normalized band;
- temporary OBI normalization;
- spread widening that immediately recovers;
- a support test with bid replenishment;
- a low-volume consolidation above VWAP.

## 16C.7 Profit management

Initial policy families:

### Protect

Immediately after fill:

- place broker-native stop or approved equivalent;
- confirm protection;
- block additional entries when protection is uncertain.

### First profit decision

At the first configured R milestone:

```text
if RES high and RRS low:
    take a smaller partial or no partial per configured profile
    trail by structure, not automatically to a fragile breakeven
elif RES moderate or RRS moderate:
    take standard partial
elif RRS high:
    take larger partial or exit
```

### Runner promotion

`RUNNER_CANDIDATE` requires:

- trade is profitable by configured R;
- no hard exit;
- RES above threshold;
- RRS below threshold;
- price above VWAP/anchor;
- continuation or constructive base;
- volume/tape not materially decaying;
- sufficient time before session cutoff;
- session envelope allows runner management.

`RUNNER_CONFIRMED` requires persistence over a configured window.

### Intraday trend hold

An intraday runner may use:

- 1-minute or 5-minute structure trail;
- anchored VWAP;
- chandelier/ATR trail;
- last confirmed higher low;
- microstructure deterioration overlay.

The stop may only loosen when the signed runner policy explicitly allows a structure conversion and total authorized risk does not increase beyond the session envelope.

## 16C.8 Overnight conversion

Overnight conversion is not an accidental consequence of holding too long.

It requires:

- `overnight_conversion_allowed=true` in the signed session;
- a separate verified swing/position-management ticket;
- event and earnings eligibility;
- account eligibility;
- overnight gap-risk calculation;
- new stop and size policy;
- enough time before cutoff;
- explicit deterministic conversion artifact.

Without all conditions, the scalp must be flat by the session rule.

## 16C.9 Explainability

Every management action records:

```yaml
position_state:
resilience_score:
resistance_score:
hard_exit_flags: []
soft_exit_flags: []
runner_state:
selected_action:
alternative_actions: []
feature_snapshot_id:
market_replay_ref:
policy_version:
reason_codes: []
```

The UI displays concise operator language:

```text
HOLD — resilient pullback
Bid replenished at $X; OFI remains positive; price above VWAP.
Resistance at $Y is present but not dominant.

SCALE 25% — supply test
Third HOD rejection; ask replenishment persistent; RES 72 / RRS 63.

EXIT — resilience failed
VWAP lost for 20s; negative OFI; tape sellers 68%; no reclaim.
```

---

# 16D. JOURNAL, REPLAY, AND LEARNING FEEDBACK

## 16D.1 Event-sourced journal

Every candidate and trade produces an append-only event stream.

Required events:

```text
candidate_discovered
candidate_in_scope
priming_started
primed
armed
fire_detected
fire_suppressed
session_draft_saved
session_authorized
session_activated
order_intent_created
order_submitted
order_modified
order_partial_fill
order_filled
protection_submitted
protection_confirmed
position_state_changed
resilience_changed
resistance_changed
scale_submitted
scale_filled
exit_decided
exit_submitted
position_flat
session_paused
session_revoked
session_closed
reconciliation_completed
outcome_scored
lesson_candidate_created
hypothesis_created
```

## 16D.2 Snapshot policy

Store compact feature snapshots in PostgreSQL.

Store high-frequency raw market data in replay files.

Journal events reference:

- feature snapshot;
- replay segment;
- source timestamps;
- sequence range;
- policy versions;
- code SHA;
- authorization hash;
- account child order.

## 16D.3 Post-trade scoring

Capture:

- arrival price;
- fill price;
- slippage;
- spread capture;
- time to fill;
- number of modifications;
- rate-governor waits;
- partial-fill ratio;
- MFE and MAE;
- realized R;
- capture ratio;
- exit efficiency;
- runner promotion result;
- whether the chosen exit was early, timely, or late;
- counterfactual outcomes at +30s, +2m, +5m, +15m, close, and next session;
- account-by-account differences;
- gateway/data incidents.

## 16D.4 Learning

Darwin scores:

- prime quality;
- fire quality;
- entry execution;
- resilience classification;
- resistance classification;
- scale decision;
- runner promotion;
- exit decision;
- account allocation;
- operator overrides.

Nightly reflection produces candidates only.

Hermes may propose:

- threshold changes;
- feature weighting changes;
- separate profiles by float, tick size, time of day, or volatility;
- new exit or runner hypotheses.

No threshold self-updates in production.

## 16D.5 Operator journal

The journal page supports:

- replay the entire trade;
- scrub chart, book, tape, scores, orders, and actions on one timeline;
- compare engine action with counterfactual actions;
- add operator notes;
- mark data or thesis errors;
- promote an incident to Aegis;
- propose a lesson to Iris;
- inspect eventual Darwin score.

---

# 16E. QUASI-PARALLEL DASHBOARD DELIVERY

## 16E.1 Deployment topology

```text
apps/command-center-v3
  existing production app
  served at /v3
  frozen except additive switch/link/status changes

apps/command-center-v3-next
  new app
  served at /v3-next
  Active Trader workspace
  separate bundle and build marker
```

Shared backend truth:

```text
/api/v3/active-trader/*
/ws/v3/active-trader
```

Legacy APIs remain unchanged.

## 16E.2 Switch behavior

Both shells display:

```text
CLASSIC
ACTIVE TRADER NEXT
```

The switch is navigation, not a client-side replacement.

It must preserve:

- server-side session state;
- selected symbol;
- active account set;
- open positions;
- authorization;
- kill-switch state.

## 16E.3 Feature flags

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

Flags are server-side and audited.

The live flag cannot create authorization by itself.

## 16E.4 Rollout

```text
READ_ONLY_MIRROR
  new UI reads existing data

SHADOW_ENGINE
  new engine computes, old system remains authoritative

SIMULATION
  new UI and engine trade simulation

LIVE_CANARY
  one session, bounded accounts/symbols/risk

DUAL_OPERATION
  operator can switch old/new

PRIMARY
  new dashboard default after parity

LEGACY_RETIREMENT
  separate decision after observation
```

## 16E.5 Parity

Required cross-surface parity:

- quote and timestamp;
- candidate state;
- session state;
- account quantities;
- order state;
- position state;
- P&L;
- risk budget;
- authorization hash;
- kill-switch state;
- journal event count.

A parity mismatch is visible and blocks live activation from the new surface.

## 16E.6 No-break build rule

Initial Codex stages may not:

- delete or rename current routes;
- replace `TradingHub`;
- alter the current `/v3` basename;
- move current APIs;
- change existing broker behavior;
- enable live flags;
- change session guardrails;
- introduce a shared abstraction that forces the old app to migrate.

Reuse is allowed only through additive libraries or copied/adapted components until the new path proves parity.


# 16F. MULTI-BROKER ACCOUNT AND CAPABILITY FABRIC

## 16F.1 Scope

Active Trader discovers and governs every API-enabled Trade AI account for:

```text
ALPACA
MOOMOO
SCHWAB
```

“Available” means:

- present in the account registry;
- connector installed;
- authentication current;
- account readable;
- environment known;
- trading capability explicitly probed;
- account eligible for the requested symbol, session, order type, quantity, and strategy;
- included in the saved and authorized Active Trader session.

An account appearing in a broker portal does not make it automatically tradeable through Trade AI.
