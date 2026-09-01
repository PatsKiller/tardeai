# Profit-Capture Refresh Artifacts (generated)

Status:      ACTIVE
as_of:       2026-06-06T22:43:08-04:00
Measured at: efcc51365 / not measured

A **rolling** set of evidence artifacts written by `scripts/run_profit_capture_refresh.sh`
(weekly cron, Sun 03:30) — overwritten each run:

- `pc_refresh.{json,md}` — canonical all-trades measurable analysis
- `pc_bt.{json,md}` — quality-gated, path-measured rule backtest snapshot
- `pc_shadow.{json,md}` — shadow threshold recommendations (advisory only)
- `pc_val.{json,md}` — validation report (PASS/FAIL)

These are **evidence-only** and kept as a **permanent audit trail** — committed to git and mirrored
to the Trade_AI_Docs_v2 Drive folder. The refresh commits + pushes **only when the substantive
signal changes** (the per-rule `reliable_n` + graft-verdict signature) — not on cosmetic
timestamp-only regen. So the **git history is the dated trail**: one commit per real change in
`reliable_n`/verdicts, each timestamped with its diff. Weeks with no substantive change leave no
commit and no Drive churn (the cosmetic regen is reverted).

The curated narrative lives in `docs/project/PROFIT_CAPTURE_*` and `V3_PROTECTION_*`; these are the
raw current records behind it.
