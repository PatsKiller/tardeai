# Profit-Capture Refresh Artifacts (generated)

Per-run evidence artifacts written by `scripts/run_profit_capture_refresh.sh` (weekly cron,
Sun 03:30). One date-stamped set per run:

- `pc_refresh_<YYYYMMDD>.{json,md}` — canonical all-trades measurable analysis
- `pc_bt_<YYYYMMDD>.{json,md}` — quality-gated, path-measured rule backtest snapshot
- `pc_shadow_<YYYYMMDD>.{json,md}` — shadow threshold recommendations (advisory only)
- `pc_val_<YYYYMMDD>.{json,md}` — validation report (PASS/FAIL)

These are **evidence-only** snapshots kept as a **permanent audit trail** — committed to git and
mirrored to the Trade_AI_Docs_v2 Drive folder by the weekly doc sync. Each run overwrites its
same-date files; the archive accumulates one set per week so `reliable_n` progress toward the floor
(20) is reviewable. The curated narrative lives in `docs/project/PROFIT_CAPTURE_*` and
`V3_PROTECTION_*`; these are the raw per-run records behind it.
