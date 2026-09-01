# Full Day Commit Log — 2026-05-22

Status:      HISTORICAL
as_of:       2026-05-22T17:42:22-04:00
Measured at: efcc51365 / not measured

**Total commits:** 39
**First:** `9794466` (09:09) | **Last:** `fd94bdc` (17:31)
**Duration:** 8h 22m
**Safety:** ALPACA_MODE=paper, LLM_DISABLE=true, ATM=dry_run, Live=BLOCKED

---

## Complete Commit Table

| # | Hash | Time | Subject | Phase |
|---|------|------|---------|-------|
| 1 | `9794466` | 09:09 | chore(audit): supply triage forensics and incubator drain | Supply Triage |
| 2 | `0ba0302` | 09:47 | fix(continuous): pass --allow-underfilled so pre-market runs generate proposals | Supply Triage |
| 3 | `fb6dba9` | 09:50 | fix(atm): bypass classifier_health gate during DRY_RUN cold-start | Supply Triage |
| 4 | `5a16e01` | 09:51 | chore(audit): supply triage findings — 3 cliffs identified and fixed | Supply Triage |
| 5 | `18046ee` | 10:05 | fix(atm): classifier_health helper returns detail + dashboard handles null baseline | Dashboard Audit |
| 6 | `39070c1` | 10:05 | fix(atm): populate config_hash on atm_state from config_manager each cycle | Dashboard Audit |
| 7 | `c50a1b1` | 10:05 | fix(atm): enrich API — predicted_decision, market hours, ATM/manual breakdown | Dashboard Audit |
| 8 | `fdbf0e0` | 10:05 | feat(atm): dashboard shows health baseline, predicted decisions, market-aware staleness | Dashboard Audit |
| 9 | `af5c017` | 10:07 | chore(atm): day-1 dashboard audit handoff doc | Dashboard Audit |
| 10 | `e41fcda` | 10:17 | fix(atm): reconcile quote-status banner with per-card classify_quote_trust | Dashboard Audit |
| 11 | `0130d98` | 10:18 | chore(atm): update handoff doc with Issue 7 fix details | Dashboard Audit |
| 12 | `041a8c5` | 10:26 | chore(audit): proposal supply throughput investigation — funnel mapped | Supply Throughput |
| 13 | `ba756cf` | 10:34 | fix(promoter): lower screener-path threshold from 42/48 to 38/45 | Supply Throughput |
| 14 | `370013b` | 10:44 | fix(promoter): run risk gate at proposal creation time | Supply Throughput |
| 15 | `5b902ca` | 10:47 | chore(audit): update supply audit with Fix 4 findings | Supply Throughput |
| 16 | `c2450bb` | 10:51 | docs: add ATM v1 + Supply Pipeline sections to Reference Architecture | Documentation |
| 17 | `d65293f` | 11:06 | chore: normalize strategy YAML formatting | Housekeeping |
| 18 | `c106159` | 11:20 | fix(atm): activity tiles count dry_run_approved/rejected when in dry_run mode | Pre-ACTIVE |
| 19 | `3a5d2b6` | 11:21 | chore(atm): pre-active fixes handoff doc | Pre-ACTIVE |
| 20 | `bb11a01` | 11:25 | fix(atm): import db connection for mode change and proposal-action endpoints | Pre-ACTIVE |
| 21 | `c1a2a41` | 11:29 | feat(enrich): schema + auto_enrichment_runner with concurrency and timeout | Auto-Enrichment |
| 22 | `0ffe673` | 11:31 | feat(atm): pre-check enrichment status before evaluating proposals | Auto-Enrichment |
| 23 | `5f05e27` | 11:39 | feat(atm): enrichment status panel on dashboard + API endpoint | Auto-Enrichment |
| 24 | `75e8a79` | 12:09 | chore(enrich): bootstrap drain + ai_review non-blocking + timeout bump | Auto-Enrichment |
| 25 | `7b3bb29` | 12:09 | chore(enrich): auto-enrichment handoff doc | Auto-Enrichment |
| 26 | `33957ed` | 12:19 | fix(monitor): update pnl column alongside unrealized_pnl for open trades | Monitor Fix |
| 27 | `67d6dc8` | 12:19 | fix(journal): COALESCE pnl with unrealized_pnl in journal API | Monitor Fix |
| 28 | `fa353b6` | 15:47 | fix(atm): partial-fill race, stale proposal expiry, quote endpoint, journal timestamps | Context Sync |
| 29 | `de74a20` | 15:51 | fix(nav): move ATM to Trading, Backtesting to Strategy, add missing pages | Context Sync |
| 30 | `8fe3086` | 16:02 | docs: sync 2026-05-22 ATM context from Drive | Context Sync |
| 31 | `b4d98ab` | 16:16 | fix(atm-safe-1): freeze active execution, fix audit schema, enforce quote fail-closed | **ATM-SAFE-1** |
| 32 | `9eecbae` | 16:27 | Regenerate maturity after ATM-SAFE-1 containment | Maturity Refresh |
| 33 | `3d0fc18` | 16:36 | docs: Stop Management v2 design | Stop v2 Design |
| 34 | `b2d8704` | 16:56 | STOP-V2.0 backfill stop tracking | **STOP-V2.0** |
| 35 | `1cb496b` | 17:04 | STOP-V2.1 add stop reconciliation engine | **STOP-V2.1** |
| 36 | `c1bdef3` | 17:12 | STOP-V2.2 merge stop monitors | **STOP-V2.2** |
| 37 | `33fd32c` | 17:20 | STOP-V2.3 add strategy trailing tiers | **STOP-V2.3** |
| 38 | `e3f594c` | 17:24 | docs: add session commit log for ATM safe and Stop v2 | Documentation |
| 39 | `fd94bdc` | 17:31 | Regenerate maturity after Stop Management v2 | Maturity Refresh |

---

## Commits by Phase

### Supply Triage (09:09–09:51) — 4 commits
Emergency P0: 0700 scan showed 7 symbols, 0 GO, 0 proposals. Fixed 3 cliffs:
underfilled gate, missing 0900/1000 crons, classifier_health cold-start.

### Dashboard Audit (10:05–10:18) — 7 commits
7 issues fixed: classifier health display, predicted decisions, config_hash,
STALE warning, ATM/manual breakdown, ghost cards, quote banner reconciliation.

### Supply Throughput (10:26–10:47) — 4 commits
Full funnel investigation. Promoter threshold 42→38, risk gate at creation,
execution readiness 0%→37.5%.

### Pre-ACTIVE Fixes (11:20–11:25) — 3 commits
Dry-run tiles, mode change fix (`_get_conn` not imported), handoff doc.

### Auto-Enrichment (11:29–12:09) — 5 commits
End-to-end automation: 5-min enrichment cron, enrichment pre-check on ATM,
dashboard panel, bootstrap drain. First live ATM approvals at 11:30.

### Monitor Fix (12:19) — 2 commits
Journal showed $0 PnL. Monitor now updates `pnl` alongside `unrealized_pnl`.
Journal API adds COALESCE fallback.

### Context Sync (15:47–16:02) — 3 commits
Drive sync, partial-fill race fix, nav restructure, quote endpoint fix.

### ATM-SAFE-1 (16:16) — 1 commit
Freeze execution, fix audit_log schema (event→event_type), enforce quote
fail-closed. 5/5 positions reconciled.

### Maturity Refreshes (16:27, 17:31) — 2 commits
Post-ATM-SAFE-1: 6.2/10. Post-STOP-V2: 7.0/10.

### Stop Management v2 (16:36–17:20) — 5 commits
Design + 4 implementation phases:
- V2.0: planned_stop + stop_order_id backfill
- V2.1: Broker stop reconciliation engine
- V2.2: Unified supervisor (racing monitors merged)
- V2.3: Strategy-aware trailing tiers (4 families)

### Documentation (10:51, 11:06, 17:24) — 3 commits
Reference Architecture update, YAML normalization, session commit log.

---

## End-of-Day State

- **Maturity:** 7.0/10.0 (meets A-6 threshold)
- **Strategy proof:** 3.5 (binding constraint for live readiness)
- **ATM:** dry_run (frozen by ATM-SAFE-1)
- **Broker stops:** 5/5 reconciled, GTC, all match DB
- **Unified supervisor:** installed, */3 market hours
- **Stop Management v2:** complete (V2.0–V2.3)
- **Live trading:** BLOCKED
- **Holdings:** $1,201,120 / 47 positions

## Recommended Next
1. ATM re-enable decision package (John's 7 decisions)
2. STOP-V2 burn-in observation (3-5 days)
3. Continue A-5 strategy proof (need 3+ closed per strategy)
