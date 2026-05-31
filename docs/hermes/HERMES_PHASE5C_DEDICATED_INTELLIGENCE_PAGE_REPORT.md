# Hermes Phase 5C — Dedicated Intelligence Page

**Date:** 2026-05-31
**Status:** COMPLETE

## New Page
- Route: `/v2/hermes-intelligence`
- Nav: System & Pipeline → Hermes Intelligence
- API: `GET /api/v2/hermes/intelligence` (read-only)

## Features
- Summary cards: Total, Promoted, Staged, Embedded, Audit Records
- Advisory banner: "Not Execution — Not Broker-Connected"
- Table with ID, Symbol, Type, Confidence, Status, Summary, Date
- Search by symbol/topic
- Filter by status (promoted/staged/embedded)
- Detail modal with full summary, thesis, provenance
- Status badges: promoted (blue), staged (gray), embedded (green)

## No Mutation Controls
- No promote/approve/reject/trade/embed buttons
- No write endpoints
- Dashboard is read-only

## Safety
| Item | Status |
|------|--------|
| Write endpoints | ZERO |
| Mutation controls | ZERO |
| DB writes | ZERO |
