# Phase 208A — Weekly Report Cadence: Preflight + Classification + Harden + Dry-Run — 2026-06-07

Status:      HISTORICAL
as_of:       2026-06-07T11:18:44-04:00
Measured at: efcc51365 / not measured

Follows the proven daily-cadence pattern (Phase 207).

## Preflight (verified)
- Legacy `portfolio-weekly.timer` **active/enabled** → `linux_launchers/run_portfolio_weekly.sh`
  (`OnCalendar` Sun 20:00; next Sun 2026-06-07 20:00). **Migration target.**
- Separate legacy weekly cron (OUT of scope): `run_alex_daily.py --weekly --telegram` @08:00 Sun.
- Controller `run_weekly()` already runs `run_portfolio_weekly.sh` labeled
  `PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY`; secrets-data is owned by the backup cadence (not run here).
- No controller process running. Live blocked (paper, `LLM_DISABLE_LIVE_EXECUTION=true`); Level 7 prohibited.
- Backup cadence migrated; daily cadence migrated + legacy retired (Phase 207).

## Classification — `PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY`
`run_portfolio_weekly.sh` invokes:
- `portfolio_orchestrator.py --run-label weekly --run-type daily` → advisor_observations +
  advisor_recommendations (`status=draft`) + escalations (review-only).
- `portfolio_weekly_report.py` → weekly narrative report (Ollama **qwen3:14b** — currently uninstalled
  per model policy, so this step **fails soft** via `|| echo skipped`; **not changed** — model policy is
  out of scope).
- `generate_reports_hub.py` → report hub artifacts.
- `portfolio_yaml_advisor.py` → reads `assets/portfolio_accounts.yaml`, writes a **review JSON**
  (`yaml_advisor_output.json`) of *proposed* changes — **does NOT mutate strategy YAML or
  portfolio_accounts.yaml**. (The `config/strategies/*.yaml` working-tree churn is unrelated/pre-existing,
  not produced by this report.)
- `backfill_acct_periods_v3.py` (non-fatal helper).

**No broker/order/submit/proposal-execution/protection/stop call-sites** in the weekly chain (verified).

### Required conclusion
- review-only advisory drafts: **YES**
- broker/order execution: **NO**; proposal/trade/protection mutation: **NO**; strategy-YAML mutation: **NO**
- acceptable for weekly cadence migration: **YES**

## Harden
Wired the fail-closed `assert_review_only_chain` guard into `run_weekly()` (scans `run_portfolio_weekly.sh`
+ `portfolio_orchestrator.py` + `portfolio_weekly_report.py` + `portfolio_yaml_advisor.py` for
broker/order/stop exec call-sites; BLOCKS the step if any found).

## Dry-run — PASS
`--cadence weekly --dry-run` → `overall=ok`: only `portfolio_weekly_report` (review-only), no
backup/daily/monthly/lookthrough, price_cache + db_retention `EXCLUDED_NOT_RUN`, live OFF + Level 7
prohibited, weekly-specific lock/log/summary. Guard did not block.
