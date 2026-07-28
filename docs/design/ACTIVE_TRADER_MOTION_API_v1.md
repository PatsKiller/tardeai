# Active Trader Aggregate Motion API v1

## Status

This tranche adds the backend read contract and local observation persistence needed by the live-motion UI. It is stacked on the T2 JIT and momentum-exit policy branch. It does not deploy a polling service, bind an account, activate execution authority, subscribe to a provider, or send an order.

## Account-agnostic boundary

The motion plane is deliberately independent of account type, broker, venue, and environment.

It produces:

- candidate motion-resource decisions;
- T2 leases;
- open-position market-state evidence;
- `EXIT_SIGNAL` evidence.

It does **not** produce:

- an account selection;
- an environment classification;
- a route;
- an order request;
- an execution authorization.

A future exit-intent execution orchestrator may consume a signal only after it receives a separate runtime account capability and authority envelope. That orchestrator is not part of this tranche.

## Components

- `motion_journal.py` — append-only, hash-chained JSONL evidence journal.
- `motion_engine.py` — restores T2 lease state, replays open-position observations through the deterministic exit policy, and writes one aggregate snapshot.
- `motion_snapshot_api.py` — read-only validation and stale-state projection for the latest snapshot.
- `active_trader_motion_tick.py` — one-shot `tick` and local `record` commands.
- `GET /api/v3/active-trader/motion` — browser-facing aggregate read endpoint.

## Data flow

```text
existing scanner / IGN read models
          +
local candidate observations
          +
local position observations
          +
active workflow + explicit symbol authorization
          ↓
Active Trader motion tick
          ↓
T2 lease reconciliation + exit-policy replay
          ↓
hash-chained observation journal
          +
atomic motion_snapshot.json
          ↓
GET /api/v3/active-trader/motion
          ↓
one aggregate UI request per refresh cycle
```

The browser never creates one request per ticker. It reads one snapshot and uses the server-provided refresh hint, clamped by the UI to 5–30 seconds.

## Workflow and symbol admission

The engine fails closed unless all of these are present:

- workflow session state `ACTIVE`;
- an explicit authorized symbol list;
- fresh candidate or position evidence;
- deterministic setup/gate eligibility required by the T2 policy.

A broad rule such as a wildcard, price filter, or RVOL expression is not converted into authorization. The first implementation accepts only explicit symbol lists or `symbols:` CSV notation.

The engine does not inspect account ID, account category, venue, broker, environment, buying power, or route. The upstream workflow/session layer supplies only the symbol authorization needed for motion-resource admission.

## T2 persistence

The motion state file stores current leases and cooldown deadlines. A new process restores those values before reconciling the next tick, preserving lease identity, minimum dwell, expiry, and cooldown behavior across process restarts.

The provider hard ceiling and normal operating cap remain distinct. The snapshot exposes both, and the provider ceiling is never represented as a utilization target.

## Position replay and exit evidence

Position observations are appended to the journal. At each tick, open-position history is replayed in order through `MomentumExitPolicy`. This reconstructs hysteresis state without trusting browser memory.

The snapshot may expose:

- `HOLD`
- `WATCH`
- `EXIT_ARMED`
- `EXIT_SIGNAL`
- `PROTECT_ONLY`

`EXIT_SIGNAL` is account-unbound evidence. The API explicitly returns:

- `signal_only: true`;
- `automatic_order_sent: false`;
- `account_bound: false`;
- zero order authority.

Before any future orchestrator acts, it must independently validate signal identity, strategy/ticket identity, runtime account ownership, position quantity, venue capability, environment, session authority, freshness, risk, protection, reconciliation, and idempotency.

## Journal integrity

Every journal record contains:

- monotonic sequence;
- previous record hash;
- canonical record hash;
- kind;
- timestamp;
- payload.

A broken sequence, previous hash, record hash, contract, or JSON line blocks further appends and blocks snapshot production. The system does not silently truncate or repair the journal.

## Snapshot states

- `LIVE_MOTION` — fresh snapshot with candidate or position rows.
- `EMPTY_LIVE_MOTION` — fresh snapshot, no active rows.
- `MOTION_DATA_STALE` — last good snapshot retained but older than the freshness budget.
- `MOTION_API_UNAVAILABLE` — no readable contract-valid snapshot exists.

The read endpoint always overrides authority fields to false, even if a malformed or tampered snapshot attempts to claim authority.

## Operating commands

Record a local observation:

```bash
python scripts/active_trader_motion_tick.py record \
  --kind position_observation \
  --payload-json /path/to/observation.json
```

Produce one snapshot:

```bash
python scripts/active_trader_motion_tick.py tick
```

The utility intentionally does not contain a loop. A supervised user service or timer will be a separate deployment tranche after host data proof and cadence measurements are complete.

## Remaining gaps

- No supervised 5/10/30-second tick service is installed in this tranche.
- No direct Moomoo gateway IPC adapter is stacked into this branch yet.
- Scanner/IGN projections do not all expose per-symbol source timestamps; missing timestamps fail stale rather than being treated as fresh.
- No exit-intent execution orchestrator exists.
- Threshold calibration still requires the replay corpus described in the T2/exit design.
