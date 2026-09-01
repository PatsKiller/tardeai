# Phase 210A — Lookthrough Cadence: Preflight + Classify + Harden + Dry-Run — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T14:36:32-04:00
Measured at: efcc51365 / not measured

The **last** report-family cadence. Follows the proven pattern (Phases 207–209).

## Preflight (verified)
- Legacy `portfolio-lookthrough.timer` **active/enabled** → `linux_launchers/run_lookthrough.sh`
  (1st-Sunday monthly 06:00; next Sun 2026-07-05 06:00). **Migration target.** No separate cron.
- Controller `run_lookthrough()` runs `run_lookthrough.sh` labeled **`READ_ONLY_SNAPSHOT`**.
- No controller process running. Live blocked (paper, `LLM_DISABLE_LIVE_EXECUTION=true`); Level 7 prohibited.
- backup + daily + weekly + monthly cadences migrated; their legacy timers retired.

## Classification — `READ_ONLY_SNAPSHOT` (lowest-risk cadence)
`run_lookthrough.sh` is a read-only fund/ETF look-through analysis:
- `phase3_lookthrough_fetcher.py` → fetch fund/ETF underlying-holdings data.
- `phase3_lookthrough_resolver.py` → resolve holdings to underlying sector exposures.
- `phase2_coverage_audit.py` → coverage audit.

**No advisory drafts** (does not write advisor_recommendations), **no broker/order/submit/
proposal-execution/protection/stop** call-sites (verified). Writes look-through sector/coverage snapshot
data only.

### Required conclusion
- read-only snapshot: **YES**; advisory drafts: **N/A** (none created); broker/order/proposal/protection/
  strategy mutation: **NO**; acceptable for lookthrough cadence migration: **YES**

## Harden
Wired `assert_review_only_chain` into `run_lookthrough()` (scans `run_lookthrough.sh` + the 3 phase
scripts for broker/order/stop exec call-sites; BLOCKS the step if any found). Comparator
`compare_portfolio_daily_outputs.py` generalized to accept the `READ_ONLY_SNAPSHOT` label + the
`portfolio_lookthrough` step name.

## Dry-run — PASS
`--cadence lookthrough --dry-run` → `overall=ok`: only `portfolio_lookthrough` (READ_ONLY_SNAPSHOT), no
backup/daily/weekly/monthly, price_cache + db_retention `EXCLUDED_NOT_RUN`, live OFF + Level 7 prohibited,
lookthrough-specific lock/log/summary. Guard did not block.
