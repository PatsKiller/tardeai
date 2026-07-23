# Stage 13 — /v3 ↔ /v3-next Parity Matrix

**HEAD:** 4e4176ba · Categories: MATCH · INTENTIONALLY_NEW · NOT_APPLICABLE · FIXTURE_ONLY ·
LIVE_DATA_PENDING · PREMARKET_VALIDATION_PENDING

> Fixture parity is NOT live parity. v3-next renders from fixtures/read-only projections; live Moomoo
> data parity is explicitly **not** claimed.

| Field / surface | Category | Notes |
|---|---|---|
| Account inventory | FIXTURE_ONLY | v3-next renders read-only fixtures; live broker inventory not wired |
| Masked identifiers | MATCH | both mask (last-4 / `***`); no raw account ids |
| Positions / orders snapshots | FIXTURE_ONLY | read-only projections; no live order state in v3-next |
| P&L representations | FIXTURE_ONLY | shadow/sim P&L only; no live P&L |
| Capabilities | MATCH | capability matrix shared (discovery_* read-only) |
| Rejections | MATCH | normalized rejection taxonomy shared |
| Notifications | INTENTIONALLY_NEW | v3-next projects notifications read-only; no send path |
| Journal | INTENTIONALLY_NEW | append-only shadow/replay journal (Stage 9/11) |
| Feature states | MATCH | all live flags OFF in both; v3-next actions disabled |
| Classic navigation | MATCH | /v3 unchanged (0 files changed vs main) |
| Next navigation | INTENTIONALLY_NEW | /v3-next 18 read-only panels, all actions disabled |
| Session data | FIXTURE_ONLY | session builder = SHADOW/SIMULATION, test-identity |
| Market-data fields | LIVE_DATA_PENDING | live Moomoo data pending five-RTH observation |
| Level 2 / tape | PREMARKET_VALIDATION_PENDING | L2 suitability UNPROVEN; needs qualifying open sessions |
| Moomoo status | LIVE_DATA_PENDING | data smoke passed; continuous capture + 5 sessions pending |
| Live order actions | NOT_APPLICABLE | no live/paper/sim order path in v3-next (action contracts inactive) |
| Real 2FA (order) | NOT_APPLICABLE | no order 2FA wired (only one-time data-gateway device auth exists) |

## Summary
- Everything v3-next shows today is **FIXTURE_ONLY / read-only projection** or **INTENTIONALLY_NEW**.
- Classic-shared semantics (masking, capabilities, rejections, flags-off, navigation) **MATCH**.
- Live market-data / L2 / Moomoo parity is **PENDING** the observation gates — not claimed as parity.
