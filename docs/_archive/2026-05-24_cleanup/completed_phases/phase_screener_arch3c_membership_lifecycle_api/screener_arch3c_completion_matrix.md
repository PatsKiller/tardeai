# SCREENER-ARCH-3C — Completion Matrix

| Deliverable | Status | Evidence | Deferred Phase |
|---|---|---|---|
| Prior-vs-current comparison | done | backfill_screener_membership_transitions.py | |
| Dropped detection | done | 727 dropped memberships, 1,257 dropped events | |
| Stale detection | done | STALE_THRESHOLD=3, logic tested | |
| Reentered detection | done | 55 reentered events | |
| Expired detection | done | EXPIRE_THRESHOLD=7, logic tested | |
| Mass-drop protection | done | 8 runs protected during backfill | |
| Transition backfill dry-run | done | 5,035 events previewed | |
| Transition backfill apply | done | 5,035 events created | |
| Falloff lifecycle dry-run | done | 1,129 candidates analyzed | |
| Falloff lifecycle apply | deferred | Requires operator approval for expiry | ARCH-3D |
| Membership status after report | done | 2,038 memberships, lifecycle working | |
| Ticker catalog after report | done | 1,139 incubator, 1,129 active | |
| API endpoints | done | 3 read-only endpoints | |
| Dashboard integration | done | Scanner Catalog Lifecycle on Paper Governance | |
| Tests | done | 23/23 + regression 34/34 | |
| Safety | done | Full audit passed | |
