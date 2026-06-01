# Hermes Phase 22D — Research Backlog Dashboard Visibility Design

**Date:** 2026-06-01
**Status:** DESIGN ONLY — no code changes

---

## Current Visibility

Research backlog items (research_type='research_backlog') already appear on the Hermes Intelligence page alongside other staged rows. They show with:
- research_type: "research backlog"
- Status: "staged"
- Symbol: TELO, APAM, FJSCX, or SYSTEM
- Summary truncated in table
- Full detail in modal

---

## Future Enhancement: Dedicated Backlog Section

### Proposed Design

Add a "Research Backlog" card to the Hermes Intelligence page below the existing table, showing:

| Field | Display |
|-------|---------|
| Count | Total backlog items badge |
| Priority | Color-coded: high=red, medium=amber, low=text3 |
| Owner agent | source_discovery_agent / hermes_librarian_agent |
| Related symbol/topic | TELO, APAM, FJSCX, SYSTEM |
| Reason | Backlog type (vague_rebalance, low_confidence, borderline_confidence, etc.) |
| Missing evidence | Summary of what's needed |
| Requested research | Research questions list |
| Status | staged / reviewed / rejected / archived |
| Created from | Finding ID or source reference |

### What NOT To Add

- No "Start Research" action button (requires autonomous approval)
- No "Resolve" button (requires operator workflow approval)
- No "Delete" button (requires explicit rollback approval)
- No auto-refresh polling
- No SearXNG query integration

### Future Action Buttons (Requires Separate Approval)

- "Mark Reviewed" — change status to reviewed
- "Reject" — change status to rejected
- "Archive" — change status to archived
- "Assign to Source Discovery" — queue for next SearXNG batch

---

## Filter Enhancement

Add to existing Intelligence page status filter:
- "Research Backlog" option (filters research_type='research_backlog')

---

## No Implementation in This Phase

Docs-only. No UI code, no API endpoints, no DB writes.
