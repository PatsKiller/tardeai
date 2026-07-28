# Active Trader T2 JIT and Momentum Exit — Design v1

**Status:** deterministic market-state and motion-resource policy
**Contract modules:** `active-trader-t2-jit-policy-v1`, `active-trader-momentum-exit-policy-v1`
**Account/venue/environment binding:** none
**Order authority:** none

## 1. Separation of concerns

The market-state layer must be account agnostic.

It may determine that a symbol is near firing, that scarce T2 evidence is justified, or that an open position has reached `EXIT_SIGNAL`. It must not know whether a separately supplied account is simulated, sandbox, or production; which broker or venue owns the account; or whether any order action is permitted.

The boundaries are:

```text
market-state policy
  -> motion-resource decision
  -> entry/exit evidence or intent
  -> execution orchestrator
  -> runtime account + venue capability
  -> separately granted authority
  -> adapter
```

Only the execution orchestrator may combine an intent with a runtime account capability. No account category is encoded in the T2 or momentum policy.

## 2. T2 design decision

T2 is a scarce motion-data resource, not a discovery resource and not an account resource. The broad scanner remains T0. A candidate can become T1 when it is worth monitoring, but it consumes T2 only when:

- the workflow session is `ACTIVE`;
- motion resources are explicitly authorized for that symbol;
- the deterministic setup and gate are valid;
- baseline evidence is fresh;
- the candidate is within the trigger-distance or expected-fire window, or a monitored position is already open.

The upstream session/capability layer calculates the boolean `motion_eligible`. The T2 policy does not inspect account, venue, environment, route, buying power, or execution mode.

The UI must not create one request per ticker. The backend publishes one aggregate Active Trader motion snapshot. Push callbacks are primary. The snapshot includes a refresh hint: 5 seconds for a T2 symbol or open position, 10 seconds for near-fire T1 candidates, and 30 seconds for idle T0 state. Pull fallbacks are bounded to initial hydration, reconnect recovery, and explicit stale-data repair.

## 3. T2 lease lifecycle

```text
T0 discovery
  -> T1 setup valid / monitored
  -> T2 lease requested only near fire
  -> T2 admitted under operating cap
  -> lease renewed while valid
  -> released on invalidation, staleness, kill switch, completion, or expiry
  -> cooldown to prevent subscription thrash
```

Default values are provisional observation defaults, not trading conclusions:

- provider hard cap: 8
- normal operating cap: 2
- near-fire distance: 12 bps
- expected-fire window: 30 seconds
- lease TTL: 20 seconds
- minimum dwell: 10 seconds
- release cooldown: 15 seconds
- pull fallback budget: 2 per minute

The provider hard cap is never treated as a utilization target. Open-position leases cannot be evicted by pre-fire candidates. A higher-priority pre-fire candidate may evict a lower-priority pre-fire lease only after minimum dwell.

## 4. Aggregate motion contract

```json
{
  "contract": "active-trader-motion-snapshot-v1",
  "generated_at": 0,
  "ui_refresh_after_s": 5,
  "push_primary": true,
  "t2": {
    "operating_cap": 2,
    "provider_hard_cap": 8,
    "leases": [],
    "decisions": []
  },
  "positions": [],
  "exit_signals": []
}
```

The front end updates rows in place and visibly shows `last_update_age_s`, tier, lease reason, exit-policy state, persistence progress, high-water mark, stop, threshold, and stale/fault state. It must not label a scanner process as streaming market data.

## 5. Momentum exit hysteresis

```text
HOLD
  -> WATCH after score crosses arm threshold
  -> EXIT_ARMED only after arm persistence
  -> EXIT_SIGNAL only after stronger score, price confirmation, and fire persistence
  -> HOLD again only after recovery stays below the reset threshold
```

The normalized deterioration score combines four deterministic inputs:

- momentum failure: 35%
- tape reversal: 25%
- book weakness: 20%
- price-structure failure: 20%

Provisional observation thresholds:

- arm threshold: 0.58 for 10 seconds
- fire threshold: 0.72 for 10 additional seconds
- reset threshold: 0.38 for 15 seconds
- minimum hold before a soft exit signal: 20 seconds
- at least two confirming dimensions
- price confirmation: at least 0.35R retracement from the high-water mark, price at/below entry, or a severe structure failure

A known hard-stop breach emits an immediate typed exit signal. Stale book/tape/quote evidence does **not** invent an exit; it emits `PROTECT_ONLY`, indicating that the evidence layer cannot make a fresh momentum determination.

## 6. Exit signal and future consumer

`EXIT_SIGNAL` means: **the deterministic market-state policy recommends leaving or reducing the monitored position under the current strategy rules.** It does not mean that an order was sent or that any account is authorized.

A future consumer is an account-agnostic **exit-intent execution orchestrator**. Before acting, it must receive and independently validate:

- immutable signal/intent identity;
- strategy and ticket identity;
- active session and authority envelope;
- runtime account identifier;
- venue and adapter capability;
- environment supplied by the account registry;
- current position ownership and quantity;
- current freshness, risk, protection, and reconciliation state;
- idempotency and duplicate-action protection.

The orchestrator must reject an intent when any required capability is absent. The intent producer never selects or assumes an account environment.

## 7. Calibration plan

Record policy inputs and hypothetical decisions against completed monitored trades, then evaluate:

- profit retained versus peak;
- false exits followed by continuation;
- loss avoided after genuine momentum failure;
- time from deterioration to signal;
- results by setup, price band, liquidity, session, and volatility regime;
- T2 subscription seconds and fallback round trips per trade.

Only after the observation sample is sufficient should defaults move into a versioned setup-specific registry. No single threshold should silently govern all setups.
