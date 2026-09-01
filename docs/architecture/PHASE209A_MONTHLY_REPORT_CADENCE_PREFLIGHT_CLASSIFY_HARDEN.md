# Phase 209A — Monthly Report Cadence: Preflight + Classify + Harden + Dry-Run — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T11:38:52-04:00
Measured at: efcc51365 / not measured

Follows the proven daily/weekly pattern (Phases 207–208).

## Preflight (verified)
- Legacy `portfolio-monthly.timer` **active/enabled** → `linux_launchers/run_portfolio_monthly.sh`
  (`OnCalendar` day-1 07:05; next Wed 2026-07-01 07:05). **Migration target.**
- Separate legacy monthly cron (OUT of scope): `run_alex_daily.py --monthly --telegram` @09:00 day-1.
- Controller `run_monthly()` runs `run_portfolio_monthly.sh` labeled `PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY`.
- No controller process running. Live blocked (paper, `LLM_DISABLE_LIVE_EXECUTION=true`); Level 7 prohibited.
- backup + daily + weekly cadences migrated; their legacy timers retired.

## Classification — `PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY`
`run_portfolio_monthly.sh` invokes:
- `portfolio_orchestrator.py --run-type monthly` → advisor_observations + advisor_recommendations
  (`status=draft`) + escalations (review-only).
- `portfolio_ai_analyst.py` → AI analysis output (review-only; no proposal/GO-WAIT/strategy/broker writes — verified).
- `portfolio_weekly_report.py` → narrative (qwen3:14b, fails-soft, unchanged).
- `portfolio_monthly_report.py` → monthly report (**Claude Sonnet** external API, fails-soft; review-only,
  no proposal/broker writes — verified).
- `generate_reports_hub.py` → report hub artifacts.
- `portfolio_yaml_advisor.py` → review JSON only (no strategy/accounts YAML mutation).

**No broker/order/submit/proposal-execution/protection/stop call-sites** in the monthly chain (verified).

### Required conclusion
- review-only advisory drafts: **YES**; broker/order execution: **NO**; proposal/trade/protection
  mutation: **NO**; strategy-YAML/GO-WAIT mutation: **NO**; acceptable for monthly cadence migration: **YES**

## Harden
Wired `assert_review_only_chain` into `run_monthly()` (scans `run_portfolio_monthly.sh` +
`portfolio_orchestrator.py` + `portfolio_ai_analyst.py` + `portfolio_monthly_report.py` +
`portfolio_yaml_advisor.py` for broker/order/stop exec call-sites; BLOCKS the step if any found).

## Dry-run — PASS
`--cadence monthly --dry-run` → `overall=ok`: only `portfolio_monthly_report` (review-only), no
backup/daily/weekly/lookthrough, price_cache + db_retention `EXCLUDED_NOT_RUN`, live OFF + Level 7
prohibited, monthly-specific lock/log/summary. Guard did not block.
