# Hermes Phase 35E — Backlog Health Dashboard Visibility Design

**Date:** 2026-06-01
**Status:** DESIGN ONLY — no UI implementation

---

## Proposed Future Card: "Backlog Health"

Add to Hermes Intelligence page alongside Research Backlog card:

| Field | Source | Display |
|-------|--------|---------|
| Total backlog | checks.total_backlog | Number |
| High priority | checks.high_priority_count | Red badge |
| Stale (>7d) | checks.stale_count | Amber badge if >0 |
| Duplicate risks | checks.duplicate_risk_count | Warning if >0 |
| Missing evidence | checks.missing_evidence | Warning if >0 |
| Ready for discovery | checks.ready_for_discovery | Number |
| Oldest item age | checks.oldest_item.age_days | Days |
| Last health check | summary.timestamp | Date/time |

## No Action Buttons

Read-only display only. No "resolve", "delete", or "start research" buttons.

## Data Source

- File: `docs/hermes/backlog_health/latest_backlog_health_summary.json`
- Future API: `GET /api/v2/hermes/backlog-health` (not implemented)

## No Implementation in Phase 35E
