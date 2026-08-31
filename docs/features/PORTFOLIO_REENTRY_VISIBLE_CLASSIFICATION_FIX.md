# Re-Entry Visible Classification and Data-Source Correction

Status:      ACTIVE
as_of:       2026-07-23T17:13:17-04:00
Measured at: efcc51365 / not measured

## Screenshot defect

The production screenshot exposed three regressions after PR #156:

1. The per-symbol classification action was placed in the far-right table column and could be outside the visible viewport.
2. The summary used `/api/v2/redeploy/history?days=365`, which intentionally provides a thin planning summary and often omits quantity and execution price.
3. The prior current-status table—status/action, last versus exit, RSI, pullback distance, candidate entry and alerts—was no longer on the first screen.

## Correction

- `ReEntryExitWorkbench` reads `portfolio.reentry.exit-universe.v1` first. This scheduled cache contains the original broker quantity and execution price. Redeploy history is used only as an explicitly labeled fallback.
- `CLASSIFY` and `ROTATION DESK` now live directly under each symbol, so classification never depends on horizontal scrolling.
- The classification modal persists the primary mandate, independent strategy flags, target account/weight, priority, thesis, exit type, reason, notes and queue disposition.
- `ReEntryCurrentIntelligence` restores the actionable table above the classification workbench with current status/action, last versus average exit, RSI, pullback, entry zone, resistance, portfolio flags, analyst consensus and alerts.
- The current-intelligence CLASSIFY button opens the same classification workbench modal through a page event.
- Re-Entry and the Redeploy bridge use the same corrected surfaces.

## Cache truthfulness

When `portfolio.reentry.exit-universe.v1` is unavailable or empty, the workbench states that it is using the thin Redeploy summary fallback. It does not display derived shares or average exit as if the full broker data were present.
