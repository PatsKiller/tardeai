# Active Trader Aggregate Motion API v1

## Status

This tranche adds the backend read contract and local shadow persistence needed by the live-motion UI. It is stacked on the T2 JIT and momentum-exit policy branch. It does not deploy a polling service, activate a trading session, subscribe to a provider, or send an order.

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
active SHADOW/SIMULATION session snapshot
          ↓
Active Trader motion tick
          ↓
T2 lease reconciliation + exit-policy replay
          ↓
hash-chained shadow journal
          +
atomic motion_snapshot.json
          ↓
GET /api/v3/active-trader/motion
          ↓
one aggregate UI request per refresh cycle
```

The browser never creates one request per ticker. It reads one snapshot and uses the server-provided refresh hint, clamped by the UI to 5–30 seconds.

## Session and symbol admission

The engine fails closed unless all of these are present:

- session state `ACTIVE`;
- mode `SIMULATION`, `SHADOW`, or `PAPER`;
- an explicit authorized symbol list;
- fresh candidate or position evidence;
- deterministic setup/gate eligibility required by the T2 policy.

A broad rule such as a wildcard, price filter, or RVOL expression is not converted into authorization. The first implementation accepts only explicit symbol lists or `symbols:` CSV notation.

## T2 persistence

The motion state file stores current leases and cooldown deadlines. A new process restores those values before reconciling the next tick, preserving lease identity, minimum dwell, expiry, and cooldown behavior across process restarts.

The provider hard ceiling and normal operating cap remain distinct. The snapshot exposes both, and the provider ceiling is never represented as a utilization target.

## Position replay and exits

Position observations are appended to the journal. At each tick, open-position history is replayed in order through `MomentumExitPolicy`. This reconstructs the hysteresis state without trusting browser memory.

The snapshot may expose:

- `HOLD`
- `WATCH`
- `EXIT_ARMED`
- `EXIT_SIGNAL`
- `PROTECT_ONLY`

`EXIT_SIGNAL` is display-only evidence. The API explicitly returns `automatic_order_sent: false` and zero execution authority. A later paper execution consumer must independently validate session authorization, ticket identity, capability, freshness, risk, protection, idempotency, and reconciliation.

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

Record a local shadow observation:

```bash
python scripts/active_trader_motion_tick.py record \
  --kind position_observation \
  --payload-json /path/to/observation.json
```

Produce one snapshot:

```bash
python scripts/active_trader_motion_tick.py tick
```

The utility intentionally does not contain a loop. A supervised user service or timer will be a separate deployment tranche after the host data proof and cadence measurements are complete.

## Remaining gaps

- No supervised 5/10/30-second tick service is installed in this tranche.
- No direct Moomoo gateway IPC adapter is stacked into this branch yet.
- Scanner/IGN projections do not all expose per-symbol source timestamps; missing timestamps fail stale rather than being treated as fresh.
- No paper exit-signal consumer exists yet.
- Threshold calibration still requires the shadow replay corpus described in the T2/exit design.
