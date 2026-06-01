# Phase 105 — Promotion Action Controls Design Closeout

**Date:** 2026-06-01
**Status:** DESIGN ONLY — no live action buttons

## Designed Controls

| Control | Status | Requires |
|---------|--------|----------|
| Approve Promotion | DESIGNED | Confirmation + audit |
| Reject | DESIGNED | Reason required |
| Defer / Observe | DESIGNED | Auto-expires |
| Needs Research | DESIGNED | Creates backlog item |
| Veto Auto-Promotion | DESIGNED | Immediate block |
| Request High-LLM Review | DESIGNED | Enqueues job |

## Backend Endpoint (Design Only)

POST /api/v2/hermes/promotion-action — NOT IMPLEMENTED

## Governance

- Operator-only controls
- Confirmation dialog required
- Audit row written
- Rollback available
- Rate-limited
- Level 7 boundary respected

## Safety

| Check | Result |
|-------|--------|
| Action buttons live | NO (design only) |
| Write endpoint live | NO (design only) |
| Dry-run simulation | Created conceptually |
| Level 7 | PROHIBITED |
