# RTH Observation Checkpoint — Stage 5

Resumable five-RTH-session observation (hard gate before Stage 9 acceptance / Stage 10
promotion / any live canary). Backed by lab table `md_observation_session`
(PK = observation_id + session_date → no duplicate dates).

```yaml
observation_id: (not started)
required_sessions: 5
completed_sessions: 0
session_date: []
symbols: [US.AAPL]            # ≤2, P0 only
entitlements: UNAVAILABLE     # pending working data login
events: 0
gaps: 0
reconnects: 0
queue_overflows: 0
WAL_segments: 0
Parquet_segments: 0
feature_equivalence: null
disk_growth: 0
verdict: PENDING
evidence_refs: []
```

## Status: NOT STARTED
Blocked on two conditions: (1) a working Moomoo data login (currently
BLOCKED_CREDENTIAL_GATE), and (2) open US RTH sessions (the implementation was completed
after hours, market CLOSED). Neither the 30-minute continuous capture nor any of the five
RTH sessions has run. DATA_FOUNDATION_VALIDATED is explicitly NOT claimed.
Stage 9 acceptance remains BLOCKED until five RTH sessions PASS.
