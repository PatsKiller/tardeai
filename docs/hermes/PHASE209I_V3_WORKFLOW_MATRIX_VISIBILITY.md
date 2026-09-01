# Phase 209I — v3 Hermes Workflow Matrix Visibility (2026-06-07)

Status:      HISTORICAL
as_of:       2026-06-07T12:30:30-04:00
Measured at: efcc51365 / not measured

- New read-only endpoint `GET /api/v2/hermes/workflow-matrix` — aggregates Phase 209 audit JSON
  (graph nodes, workflow owners, DB lineage) + chat-usage guidance + quick answers (who owns librarian,
  tradeai vs tradeai12b, tradeai12b-automated). No action/execution controls.
- System → Hermes panel: new **"Workflow Matrix — who owns what"** card showing workflow/node/table/safe-view
  counts, CLI-profile-in-automation flag, the three quick answers, and DB writes/24h per table.
- Read-only; no v2 UI; no tool/model/trading changes. Regenerate underlying JSON via the audit scripts.
