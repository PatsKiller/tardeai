# Active Trader T2 JIT and Momentum Exit — Design v1

**Status:** first backend tranche; deterministic SHADOW/SIMULATION policy only
**Contract modules:** `active-trader-t2-jit-policy-v1`, `active-trader-momentum-exit-policy-v1`
**Live authority:** none

## 1. Design decision

T2 is an execution resource, not a discovery resource. The broad scanner remains T0. A candidate can become T1 when it is worth monitoring, but it can consume T2 only when the system is materially capable of acting: the session is ACTIVE, the account is execution-eligible for the paper/shadow path, the deterministic gate passes, baseline data is fresh, and the candidate is within the configured trigger distance or expected-fire window. An already-open position receives the highest T2 priority.

The UI must not create one request per ticker. The backend should publish one aggregate Active Trader motion snapshot. Push callbacks are primary. The snapshot includes a refresh hint: 5 seconds for a T2 symbol or open position, 10 seconds for near-fire T1 candidates, and 30 seconds for idle T0 state. Pull fallbacks are bounded to initial hydration, reconnect recovery, and explicit stale-data repair.

## 2. T2 lease lifecycle

```text
T0 discovery
  -> T1 setup valid / monitored
  -> T2 lease requested only near fire
  -> T2 admitted under operating cap
  -> lease renewed while valid
  -> released on invalidation, staleness, kill switch, completion, or expiry
  -> cooldown to prevent subscription thrash
```

Default policy values are provisional SHADOW defaults, not trading conclusions:

- provider hard cap: 8
- normal operating cap: 2
- near-fire distance: 12 bps
- expected-fire window: 30 seconds
- lease TTL: 20 seconds
- minimum dwell: 10 seconds
- release cooldown: 15 seconds
- pull fallback budget: 2 per minute

The provider hard cap is never treated as a utilization target. Open-position leases cannot be evicted by pre-fire candidates. A higher-priority pre-fire candidate may evict a lower-priority pre-fire lease only after minimum dwell.

## 3. Aggregate motion contract

A future read endpoint should expose one snapshot shaped from the policy result:

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

The front end should update rows in place and visibly show `last_update_age_s`, tier, lease reason, exit-policy state, persistence progress, high-water mark, stop, trailing threshold, and stale/fault state. It must not label a scanner process as streaming market data.

## 4. Momentum exit hysteresis

The initial policy separates temporary deterioration from persistent failure:

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

Provisional SHADOW thresholds:

- arm threshold: 0.58 for 10 seconds
- fire threshold: 0.72 for 10 additional seconds
- reset threshold: 0.38 for 15 seconds
- minimum hold before a soft exit: 20 seconds
- at least two confirming dimensions
- price confirmation: at least 0.35R retracement from the high-water mark, price at/below entry, or a severe structure failure

A known hard-stop breach emits an immediate typed exit signal. Stale book/tape/quote evidence does **not** invent a momentum exit; it emits `PROTECT_ONLY`, leaving the separately-installed protective stop as the operative defense.

## 5. Authority boundary

These modules do not subscribe to data, open a socket, call a broker, read credentials, or send an order. `EXIT_SIGNAL` is an evidence artifact for a later, separately-authorized paper execution component. Before any paper automation consumes it, the downstream component must independently re-check session authorization, ticket hash, account capability, current freshness, risk, protection, idempotency, and reconciliation.

## 6. Calibration plan

Do not tune thresholds from intuition alone. Record the policy inputs and hypothetical decisions in SHADOW against completed scalp trades, then evaluate:

- profit retained versus peak
- false exits followed by continuation
- loss avoided after genuine momentum failure
- time from deterioration to signal
- results by setup, price band, liquidity, session, and volatility regime
- T2 subscription seconds and fallback round trips per trade

Only after the shadow sample is sufficient should defaults move into a versioned setup-specific registry. No single threshold should silently govern all setups.
