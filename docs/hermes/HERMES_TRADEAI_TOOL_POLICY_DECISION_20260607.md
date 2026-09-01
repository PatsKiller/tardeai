# Hermes tradeai Tool Policy — Operator Decision (2026-06-07)

Status:      ACTIVE
as_of:       2026-06-07T11:42:35-04:00
Measured at: efcc51365 / not measured

## Decision
**Leave `tradeai` and `tradeai12b` fully tool-less (0 enabled toolsets) as designed.** No read/write/search/
file/terminal/browser tools will be added to the Trade AI advisory profiles.

## Rationale (confirmed)
- The advisory chat profile does its whole job — summarize evidence, challenge assumptions, flag risks,
  review docs/logs, recommend safe next checks — by reasoning over context the operator provides. It needs
  no tools to do that.
- 0 tools is the safety boundary: an advisory model with no ability to touch broker/orders/DB/files/web.
- The writes Trade AI actually needs (research staging, embeddings) are performed by the **research fleet**
  scripts (scoped DB access to hermes_* staging tables + Trade AI safe views), NOT by the chat profile's
  toolset — so enabling tools on tradeai would add risk without adding capability.

## Consequence (accepted)
`tradeai`/`tradeai12b` cannot self-fetch live data; live-data needs are routed through the operator or the
dev profile / research fleet. This is intentional.

## Status
No change applied (already 0 tools). Verified: tradeai 0 / tradeai12b 0 enabled. Decision recorded; supersedes
any future suggestion to add a "safe-view query tool" to tradeai unless separately operator-approved.
