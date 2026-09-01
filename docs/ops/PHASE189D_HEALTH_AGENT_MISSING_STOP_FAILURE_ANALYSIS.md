# PHASE 189D — Health-Agent Missing-Stop Failure Analysis

Status:      HISTORICAL
as_of:       2026-06-02T09:13:00-04:00
Measured at: efcc51365 / not measured

**Run:** 2026-06-02 ~09:08 ET · Alpaca **paper** only · Evidence-backed (file:line)

---

## The question
Why did no health/monitoring agent "scream" that ANY (id 48) holds 619 shares with no recorded
stop, and that SNOW (43) / TMHC (47) have unverified broker stops?

## The answer (one line)
**Detection existed and ran every 3 minutes and correctly flagged all three as CRITICAL — but the
result was written to a log with no alert wiring; meanwhile the only alert-capable health checks
inspect the *wrong dataset* (brokerage JSON, not `paper_trades`).** This is an **alert-routing bug
+ coverage gap**, NOT a query-filter bug and NOT a timing bug.

## Monitor inventory

| Script | Open-pos? | Checks stop coverage? | Queries broker? | In crontab? |
|---|---|---|---|---|
| `reconcile_stop_v21_broker_stops.py` | YES (`WHERE status='open'`, `:89-92`) | **YES** (MISSING_BROKER_STOP) | YES (Alpaca orders) | **NO** (only via supervisor) |
| `unified_stop_supervisor.py` | via reconciler | YES | YES | **YES** `*/3 9-16 * * 1-5` |
| `report_stop_v20_open_trade_stop_tracking.py` | YES | YES | YES | **NO** |
| `open_trade_monitor.py` | YES (`status='open'`) | NO (price-vs-stop only) | replace-only | YES (via supervisor) |
| `paper_trade_monitor.py` | iterates Alpaca positions | NO alert (`stop>0` gate `:372-377`) | YES | YES (via supervisor) |
| `system_health_agent.py` | sync-age only (`:910`) | **NO** for paper | NO | **YES** `*/5 9-20` |
| `health_agent_llm_review.py` | counts `no_stop` (`:80`) | counts, **never alerts** | NO | YES `30 20 * * 1-5` |
| `aegis_surveillance.py` | reads `risk_management.json` | wrong dataset | NO | YES 08:00 |

## Evidence-backed findings

1. **Not a query-filter bug.** The reconciler's query has **no** `proposal_id IS NOT NULL`, no
   strategy requirement, no `opened_via` exclusion (`reconcile_stop_v21_broker_stops.py:89-92`).
   It *sees* 43/47/48 and classifies them CRITICAL (`MISSING_BROKER_STOP`, severity map `:16-29`).
2. **Alert-routing bug (the core failure).** When the reconciler returns CRITICAL, the supervisor
   does only `log.warning("CRITICAL: ... may be unprotected")` (`unified_stop_supervisor.py:126-128`)
   and has **zero** `send_telegram`/`dispatch_alert`/SIEM calls anywhere in the file. The result
   dies in `logs/unified_stop_supervisor.log`. The standalone reconciler `main()` only
   prints/writes JSON+audit_log (`:229-282`) and isn't scheduled.
3. **Coverage gap (compounding).** The frequent, alert-capable `system_health_agent.py` (`*/5`)
   reads `risk_management.json` and counts `status=="NO STOP"` (`:995-1017`) — that file is built
   from **brokerage holdings** (`portfolio_stops.py:78`), so **paper trades never appear**. Same
   for `aegis_surveillance.py:110,164`. Paper positions 43/47/48 are structurally invisible to
   every alerting monitor. The no-stop Telegram is also gated at `> 5` positions (`:1018`).
4. **Broker vs local.** Only the reconciler/`report_stop_v20` actually query Alpaca orders.
   `system_health_agent.py` checks paper trades for **sync-age only** (`:910`);
   `health_agent_llm_review.py` checks the **local** `stop_order_id IS NULL` column (`:80`) but
   never alerts and runs once daily after close.
5. **No "large gain + no stop" rule.** ABSENT — grep of `unrealized.*stop`, `gain.*stop`,
   `profit.*stop` across `scripts/` returns nothing. Nothing correlates ANY's +$507 / SNOW's
   +$348 with missing stop tracking.
6. **`system_health_agent` treats the supervisor as a liveness component only** (`:64-67`) — it
   checks the cron is alive, never reads the supervisor's `all_protected=False` / critical
   findings.

## Why ANY (619 sh, no recorded stop) produced silence
The one monitor that detected it (`unified_stop_supervisor` → reconciler, every 3 min) **logged
and swallowed** the CRITICAL finding (no alert wiring). The monitors that *can* alert
(`system_health_agent`, `aegis`) look at brokerage JSON, where paper trades don't exist. And the
per-trade paper monitors only act when a stop already exists (`stop>0`), so a NULL stop yields
no path at all. Net: a correct detection, an unwired alert, and a blind alerting layer.

## What must change (designed in 189G; implemented in Phase 190 — not here)
- Wire `unified_stop_supervisor` CRITICAL findings → SIEM event + actionable Telegram.
- Point an alert-capable health check at `paper_trades` (broker-verified), not brokerage JSON.
- Add a "large unrealized gain + unverified stop" rule.
- Schedule `reconcile_stop_v21` / `report_stop_v20` directly (don't rely on supervisor only).
