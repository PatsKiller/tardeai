# Phase 113 — Proposal Draft Sandbox Design Closeout

Status:      DRAFT
as_of:       2026-06-01T15:53:13-04:00
Measured at: efcc51365 / not measured

## Status: COMPLETE (design only)

## Deliverables

| Phase | Document | Status |
|-------|----------|--------|
| 113A | Proposal Authority Control Comparison | DONE |
| 113B | Hermes Proposal Draft Sandbox Design | DONE |
| 113C | Proposal Draft Quality Scorecard | DONE |
| 113D | Mock Proposal Packet Template | DONE |
| 113E | Sandbox Readiness Decision | DONE — READY_FOR_FILE_ONLY_SANDBOX |

## Key Decisions

1. **Sandbox type**: File-only first, DB table later after file quality proves out
2. **Readiness**: READY_FOR_FILE_ONLY_SANDBOX
3. **Quality threshold**: Composite score > 5.0 to consider DB sandbox, > 6.5 for promotion path
4. **Isolation**: Complete — no FK paths to proposal/trade/execution tables
5. **Authority boundaries**: Proposal creation is the FIRST boundary to sandbox. Journal append-only is SECOND. Holdings mutation is LAST.

## Safety Confirmation

| Check | Result |
|-------|--------|
| Real proposal writes | ZERO |
| Broker access | ZERO |
| Trade creation | ZERO |
| Journal mutation | ZERO |
| Holdings mutation | ZERO |
| Level 7 | PROHIBITED |

## Next Recommended Gate

- Produce 3-5 file-only draft packets using the Phase 113D template
- Score each against Phase 113C scorecard
- Review quality before considering hermes_proposal_drafts table creation
