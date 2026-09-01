Status:      HISTORICAL
as_of:       2026-06-05T12:02:41-04:00
Measured at: efcc51365 / not measured

---
## STOP-on-mismatch update (apply completed; Option B chosen)
The full `--apply` completed (no timeout): **overall=degraded**, run_ts 2026-06-05T15:43:27Z. Steps:
| step | status | ms |
|------|--------|----|
| portfolio_backup | ok | 330,138 (5.5m) |
| portfolio_daily_report | ok | 281,994 (4.7m) |
| portfolio_weekly_report | ok | 249,375 (4.2m) |
| portfolio_monthly_report | ok | **934,865 (15.6m)** ← slowest, LLM analyst |
| portfolio_lookthrough | ok | 25,009 |
| secrets_state_backup | **FAILED(rc=2)** | 12 |
| price_cache / db_retention | EXCLUDED_NOT_RUN | 0 |

Total ~26 min. **Slowest = monthly (15.6 min, LLM-heavy).**

### Findings
- **`secrets_state_backup` failure is a controller-call bug, not a backup failure:** the script
  requires an arg — `backup_secrets_state.sh {env|data}` — and the legacy cron invokes it **twice**
  (`env` and `data`). The bundled controller called it with no arg → usage error rc=2. Fixed in the
  cadence redesign (calls `env` + `data`). Non-cascading design correctly recorded it without aborting.
- **Classification correction:** `portfolio_daily/weekly/monthly_report` (via `run_portfolio*.sh` →
  `portfolio_orchestrator.py` + `portfolio_ai_analyst.py`) generate **advisor recommendation drafts +
  action-queue review drafts via LLM**. Verified non-broker / non-order / non-proposal / non-executing
  (review-only), but **NOT "pure static report"** → reclassified as `PORTFOLIO_ADVISORY_DRAFT_REVIEW_ONLY`.
- **Cadence blocker confirmed:** monthly is 15.6 min LLM-heavy; bundling would run it on the wrong
  days. A single bundled timer cannot preserve the distinct backup/daily/weekly/monthly/lookthrough
  cadences. **202G–202I (bundled) HELD. No legacy retirement authorized.**
- **Safety proven:** no broker/order/proposal/protection/trading mutation; legacy timers 6/6 active;
  crontab 437 unchanged; safety-net monitor+watchdog cron untouched (2 active).

**Decision: Option B — cadence-aware controller redesign (below).**
