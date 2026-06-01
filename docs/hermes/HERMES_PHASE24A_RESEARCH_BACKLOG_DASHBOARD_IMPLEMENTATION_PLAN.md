# Hermes Phase 24A — Research Backlog Dashboard Implementation Plan

**Date:** 2026-06-01
**Status:** COMPLETE

---

## Route/Section

- Page: Hermes Intelligence (`/v2/hermes-intelligence`)
- Section: New "Research Backlog" card between Promotion Review and detail modal
- No new page needed

## API

- Endpoint: `GET /api/v2/hermes/research-backlog`
- Read-only, no POST/PUT/PATCH/DELETE
- Source: `hermes_research_intelligence WHERE research_type='research_backlog'`

## Response Shape

```json
{
  "ok": true,
  "items": [
    {
      "id": 19,
      "symbol": null,
      "topic": "Research income-rotation candidates...",
      "summary": "...",
      "confidence_score": 0.30,
      "status": "staged",
      "priority": "medium",
      "owner_agent": "source_discovery_agent",
      "backlog_type": "vague_rebalance_recommendation",
      "created_at": "2026-06-01T..."
    }
  ],
  "total": 5
}
```

## Fields Displayed

| Field | Source | Display |
|-------|--------|---------|
| Priority | evidence_json→priority | Color badge |
| Symbol/Topic | symbol or topic | Text |
| Backlog type | evidence_json→backlog_type | Formatted label |
| Owner agent | evidence_json→owner_agent | Text |
| Summary | summary | Truncated |
| Status | status | Badge |
| Created | created_at | Date |

## Labels

- "Advisory Only — Research Needed — Not Execution"
- "No Autonomous Research"
- "Operator Review Required"

## Forbidden Controls

- No "Start Research" button
- No "Resolve" button
- No "Delete" button
- No "Assign" button
- No write endpoints

## Rollback

- Remove API endpoint function and route entry
- Remove UI section from HermesIntelligence.tsx
