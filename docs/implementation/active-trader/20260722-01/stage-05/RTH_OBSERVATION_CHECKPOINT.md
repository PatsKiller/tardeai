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

---

## CURRENT-STATE CORRECTION (2026-07-23, additive — history above preserved)
Condition (1) is now **CLEARED**: the operator completed the Moomoo OpenAPI agreement, the
device is trusted, and the authorized data-only smoke **PASSED** (see
`MOOMOO_DATA_SMOKE_SUCCESS.md` and `STAGE5_POST_AGREEMENT_DATA_SMOKE_ADDENDUM.md`). The
"BLOCKED_CREDENTIAL_GATE" text above reflects the state **when this checkpoint was first
written** and is retained as history.

Condition (2) remains: `completed_sessions: 0 of 5`, `verdict: PENDING`. Neither the
≥30-minute continuous capture nor any of the five RTH sessions has run (they require OPEN
US RTH sessions; the observation launcher itself is not yet checked in — see
`STAGE5_RESUME_REQUIREMENTS.md`). `DATA_FOUNDATION_VALIDATED` is still explicitly NOT claimed.
Stage 9 acceptance remains BLOCKED until five RTH sessions PASS.
