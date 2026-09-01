# Context Sync Timeline — 2026-05-22

Status:      HISTORICAL
as_of:       2026-05-22T16:02:12-04:00
Measured at: efcc51365 / not measured

## 1. ATM v1 Design / Build

**Docs:** `ATM_V1_BUILD_PROMPT.md`, `ATM_RUNBOOK.md`, `ATM_V1_BUILD_2026-05-22.md`

ATM v1 (Automated Trade Mode) was designed and deployed as a cron-based auto-approval
system for paper trade proposals. Key design decisions:

- Controlled via `config/atm_config.yaml` with per-account caps, enabled accounts,
  operating hours, kill-switch thresholds, and strategy filters
- Three modes: **disabled** (default), **dry_run** (log only), **active** (submit orders)
- Operator controls via Telegram commands and dashboard toggle
- Originally deployed in **DISABLED** mode — operator must explicitly flip to active
- Cron schedule: `*/15 9-15 * * 1-5` (every 15 min during market hours)
- Gate chain: enrichment → overrides → account → B-1/same-day → classifier health →
  position limits → approve_proposal() → broker submit

## 2. Supply Triage / Proposal Supply Repair

**Docs:** `SUPPLY_TRIAGE_2026-05-22.md`, `PROPOSAL_SUPPLY_AUDIT_2026-05-22.md`

Before ATM could operate, the proposal pipeline needed supply. Audit found:

- Funnel throughput was too low — screener → signal → proposal path had gaps
- Promoter thresholds were too restrictive (42/48 → lowered to 38/45)
- Risk gate was not running at proposal creation time (added)
- Result: proposals went from 0% execution-ready to 37.5% execution-ready

## 3. Dashboard Visibility / Operator Confidence

**Docs:** `ATM_V1_DAY1_DASHBOARD_2026-05-22.md`, `ATM_PRE_ACTIVE_FIXES_2026-05-22.md`

Dashboard panels were added so the operator could monitor ATM before going active:

- ATM mode toggle on dashboard
- Activity tiles showing dry_run_approved/rejected counts
- Enrichment status panel
- Pre-active fixes: quote-status banner reconciliation, activity tile counting

## 4. Auto-Enrichment

**Docs:** `AUTO_ENRICHMENT_2026-05-22.md`

Auto-enrichment was built to remove manual prerequisites before ATM approval:

- `auto_enrichment_runner.py` runs on `*/5 9-16 * * 1-5` (every 5 min)
- Removes manual "Refresh Price / Check Execution / AI Review" steps
- Runs BEFORE the ATM 15-minute approval cron
- Enrichment must complete (`enrichment_status = 'COMPLETE'`) before ATM evaluates
- Bootstrap drain handled initial backlog

## 5. ATM Active-Mode Event

**Doc:** `ATM_APPROVE_FAILED_2026-05-22.md`

Timeline of ATM going active on 2026-05-22:

| Time (ET) | Event |
|---|---|
| 09:00-09:05 | 8 proposals created by auto-enrichment pipeline |
| 09:45 | First ATM cycle (dry_run mode) — 6 rejected (classifier_health), 2 deferred (bucket2) |
| 10:00-11:15 | 7 dry_run cycles — all 6 eligible proposals dry_run_approved each cycle |
| 11:25 | **Operator set ATM to ACTIVE via dashboard** |
| 11:30 | First ACTIVE cycle — 4 approved + submitted, 2 rejected (stale prices), 2 deferred |
| 11:30 | NWG approved → partial fill race → broker=error, no stop placed |
| 11:30 | NVDA approved → partial fill race → broker=error, no stop placed |
| 11:30 | AGNC approved → filled → stop placed @ $9.71 ✓ |
| 11:30 | CMCSA approved → filled → stop placed @ $23.61 ✓ |
| 11:30 | ARM rejected (7.2% drift > 3% threshold) |
| 11:30 | BCS rejected (5.0% drift > 3% threshold) |
| 11:45-12:45 | 5 more cycles — ARM/BCS rejected each cycle with same stale prices |
| 12:45 | Last ATM cycle of the day |

## 6. Known Defects Discovered

| Defect | Severity | Status |
|---|---|---|
| Partial-fill race condition in alpaca_paper_adapter.py | P1 | **FIXED** 2026-05-23 |
| NWG/NVDA no stop-loss orders after broker=error | P0 | **FIXED** 2026-05-23 (manual stops placed) |
| Stale proposal infinite retry loop | P1 | **FIXED** 2026-05-23 (expiry logic added) |
| Quote fetch 404 (wrong API URL) | P1 | **FIXED** 2026-05-23 (switched to data.alpaca.markets) |
| audit_log.event column does not exist | P2 | **OPEN** — non-blocking but losing audit trail |
| Orphan pending paper_trades stubs | P2 | **FIXED** 2026-05-23 (#30, #32 closed as orphans) |
| validated_price fallback allowed execution without live quote | P2 | **MITIGATED** — data API now primary, fallback still exists |

## 7. Stop Management Discovery

**Doc:** `STOP_MGMT_DISCOVERY_2026-05-23.md`

Discovery-only session (no code changes) found:

- Two monitors (`paper_trade_monitor.py` every 5 min, `open_trade_monitor.py` every 2 min)
  apply identical R-multiple trailing stop thresholds to all strategies
- Strategy YAML configs define per-strategy stop methods but runtime ignores them
- No explicit stop_state column — state is implicit, recomputed each cycle
- 3 of 9 closed trades were discovered closed after the fact via phantom check
- LLM involvement: post-trade only (qwen3:14b lessons), not in live stop decisions
- 7 decisions pending from John before building stop management v2

## 8. Current Maturity Impact

- Prior practical maturity estimate: 7.6 / 10
- Revised provisional maturity: 6.4 / 10
- Reason: paper execution governance crossed expected boundaries
- ATM active execution is now the top containment priority
- Strategy proof (A-5) still insufficient
- Live trading remains blocked
- Maturity board must re-run after ATM-SAFE-1 containment completes
