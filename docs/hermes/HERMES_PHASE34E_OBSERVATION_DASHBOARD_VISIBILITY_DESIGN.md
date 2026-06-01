# Hermes Phase 34E — Observation Dashboard Visibility Design

**Date:** 2026-06-01
**Status:** DESIGN ONLY — no UI implementation

---

## Proposed Future Card: "System Observation"

Add to Hermes Intelligence page or System Applications page:

| Field | Source | Display |
|-------|--------|---------|
| Last observation | latest_observation_summary.json timestamp | Date/time |
| Checks passed | passed / total_checks | Badge (green if all, amber if warnings) |
| Hermes gateway | checks.hermes_gateway.status | active/inactive |
| SearXNG | checks.searxng_container.status | Up/down |
| Backlog count | checks.research_backlog_count.count | Number |
| Embedded count | checks.hermes_embeddings.count | Number |
| Promoted count | checks.hermes_rows.promoted | Number |
| Kill switch | checks.kill_switch.active | ON/OFF |
| Warnings | warnings array | List if any |

## No Action Buttons

- No "Run Observation" button
- No "Fix Warning" button
- No "Restart Service" button
- Read-only display only

## Data Source

- File: `docs/hermes/observations/latest_observation_summary.json`
- API: Future `GET /api/v2/hermes/observation-latest` (not implemented)

## No Implementation in Phase 34E

Docs-only design. Requires separate approval.
