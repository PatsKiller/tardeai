# Session Commit Log — 2026-05-22

**Commit range:** `c925a92..33fd32c`
**Total commits:** 40
**Files changed:** 120 files, +10,489 / -2,264 lines

---

## Session Phases

| Phase | Commits | Purpose |
|-------|---------|---------|
| Overnight Pipeline Repair | 1 | Fix DB/quote readiness for morning pipeline |
| ATM v1 Build | 6 | Build automated trade mode (schema → API → dashboard → deploy) |
| Supply Triage (P0) | 4 | Emergency funnel fix — 0 proposals flowing |
| Dashboard Audit | 7 | 7 dashboard issues for operator trust |
| Supply Throughput | 4 | Full funnel investigation + 4 fixes deployed |
| Reference Architecture | 2 | Doc update + YAML normalization |
| Pre-ACTIVE Fixes | 3 | Mode change fix, dry-run tiles, predicted decisions |
| Auto-Enrichment | 5 | Remove human-click prerequisites from ATM |
| Monitor PnL Fix | 2 | Fix journal showing $0 for open trades |
| Context Sync | 2 | Drive context sync + nav restructure |
| ATM-SAFE-1 | 1 | Freeze execution, fix audit schema, quote fail-closed |
| Maturity Refresh | 1 | Regenerate maturity board post-containment |
| Stop Mgmt v2 Design | 1 | Architecture doc for 4-phase stop overhaul |
| STOP-V2.0 | 1 | Backfill planned_stop + stop_order_id |
| STOP-V2.1 | 1 | Broker stop reconciliation engine |
| STOP-V2.2 | 1 | Merge racing monitors → unified supervisor |
| STOP-V2.3 | 1 | Strategy-aware trailing tiers |

---

## Full Commit Table

| Hash | Message | Phase | Safety Impact |
|------|---------|-------|---------------|
| `c925a92` | fix: repair overnight pipeline DB and quote readiness | Pipeline Repair | Restored pipeline operation |
| `7b9d4e9` | Fix 6 audit bugs: correlation route, forecast, command refresh, regime, governance, attribution | Pipeline Repair | Fixed audit trail |
| `fc8dd1b` | feat: open trade intelligence card + EOD Telegram alert | ATM Build | New monitoring capability |
| `6d0e57c` | Wire OpenTradesCard into Automated Trade Journal | ATM Build | Journal visibility |
| `98f93af` | fix: journal closed trades table formatting | ATM Build | Display fix |
| `51bfcbd` | feat(atm): phases 0-4 — accounts registry, schema, config, auto-approver | ATM Build | ATM foundation |
| `80dd666` | feat(atm): phases 5-8 — API endpoints, Telegram, dashboard, deploy | ATM Build | ATM operational |
| `41aa0dc` | docs(atm): build handoff + operator runbook for ATM v1 | ATM Build | Documentation |
| `9794466` | chore(audit): supply triage forensics and incubator drain | Supply Triage | Diagnosed supply cliff |
| `0ba0302` | fix(continuous): pass --allow-underfilled so pre-market runs generate proposals | Supply Triage | Unblocked pre-market proposals |
| `fb6dba9` | fix(atm): bypass classifier_health gate during DRY_RUN cold-start | Supply Triage | Cold-start deadlock fix |
| `5a16e01` | chore(audit): supply triage findings — 3 cliffs identified and fixed | Supply Triage | Audit doc |
| `18046ee` | fix(atm): classifier_health helper returns detail + dashboard handles null baseline | Dashboard Audit | Health display fixed |
| `39070c1` | fix(atm): populate config_hash on atm_state from config_manager each cycle | Dashboard Audit | Hash tracking |
| `c50a1b1` | fix(atm): enrich API — predicted_decision, market hours, ATM/manual breakdown | Dashboard Audit | Operator visibility |
| `fdbf0e0` | feat(atm): dashboard shows health baseline, predicted decisions, market-aware staleness | Dashboard Audit | Full dashboard overhaul |
| `af5c017` | chore(atm): day-1 dashboard audit handoff doc | Dashboard Audit | Documentation |
| `e41fcda` | fix(atm): reconcile quote-status banner with per-card classify_quote_trust | Dashboard Audit | Quote display consistency |
| `0130d98` | chore(atm): update handoff doc with Issue 7 fix details | Dashboard Audit | Documentation |
| `041a8c5` | chore(audit): proposal supply throughput investigation — funnel mapped | Supply Throughput | Full funnel analysis |
| `ba756cf` | fix(promoter): lower screener-path threshold from 42/48 to 38/45 | Supply Throughput | +66 promotable candidates |
| `370013b` | fix(promoter): run risk gate at proposal creation time | Supply Throughput | 0%→37.5% exec ready |
| `5b902ca` | chore(audit): update supply audit with Fix 4 findings | Supply Throughput | Documentation |
| `c2450bb` | docs: add ATM v1 + Supply Pipeline sections to Reference Architecture | Ref Architecture | Canonical doc updated |
| `d65293f` | chore: normalize strategy YAML formatting | Ref Architecture | YAML cleanup |
| `c106159` | fix(atm): activity tiles count dry_run_approved/rejected when in dry_run mode | Pre-ACTIVE | Operator can see dry-run activity |
| `3a5d2b6` | chore(atm): pre-active fixes handoff doc | Pre-ACTIVE | Documentation |
| `bb11a01` | fix(atm): import db connection for mode change and proposal-action endpoints | Pre-ACTIVE | Mode change was silently failing |
| `c1a2a41` | feat(enrich): schema + auto_enrichment_runner with concurrency and timeout | Auto-Enrichment | End-to-end automation |
| `0ffe673` | feat(atm): pre-check enrichment status before evaluating proposals | Auto-Enrichment | ATM defers un-enriched |
| `5f05e27` | feat(atm): enrichment status panel on dashboard + API endpoint | Auto-Enrichment | Enrichment visibility |
| `75e8a79` | chore(enrich): bootstrap drain + ai_review non-blocking + timeout bump | Auto-Enrichment | First proposals enriched |
| `7b3bb29` | chore(enrich): auto-enrichment handoff doc | Auto-Enrichment | Documentation |
| `33957ed` | fix(monitor): update pnl column alongside unrealized_pnl for open trades | Monitor Fix | Journal shows live PnL |
| `67d6dc8` | fix(journal): COALESCE pnl with unrealized_pnl in journal API | Monitor Fix | Belt-and-suspenders fallback |
| `fa353b6` | fix(atm): partial-fill race, stale proposal expiry, quote endpoint, journal timestamps | Context Sync | Safety fixes from Drive sync |
| `de74a20` | fix(nav): move ATM to Trading, Backtesting to Strategy, add missing pages | Context Sync | Nav restructure |
| `8fe3086` | docs: sync 2026-05-22 ATM context from Drive | Context Sync | Context alignment |
| `b4d98ab` | fix(atm-safe-1): freeze active execution, fix audit schema, enforce quote fail-closed | ATM-SAFE-1 | **Containment — execution frozen** |
| `9eecbae` | Regenerate maturity after ATM-SAFE-1 containment | Maturity Refresh | Score: 6.2/10 |
| `3d0fc18` | docs: Stop Management v2 design | Stop v2 Design | Architecture for 4-phase overhaul |
| `b2d8704` | STOP-V2.0 backfill stop tracking | STOP-V2.0 | planned_stop 3→0 missing, stop_order_id 5→0 |
| `1cb496b` | STOP-V2.1 add stop reconciliation engine | STOP-V2.1 | 5/5 broker stops verified |
| `c1bdef3` | STOP-V2.2 merge stop monitors | STOP-V2.2 | Racing monitors eliminated |
| `33fd32c` | STOP-V2.3 add strategy trailing tiers | STOP-V2.3 | 4 trailing policies deployed |

---

## Final Safety State

- **ALPACA_MODE:** paper
- **LLM_DISABLE_LIVE_EXECUTION:** true
- **ATM mode:** dry_run (frozen by ATM-SAFE-1)
- **Broker GTC stops:** 5/5 reconciled, all match DB
- **New trades/orders from STOP-V2 phases:** NONE
- **Holdings:** $1,201,120 / 47 positions
- **Maturity:** 6.2/10.0

## Recommended Next

1. Maturity refresh after STOP-V2.0–V2.3
2. ATM re-enable decision package (John's 7 decisions)
3. Continue A-5 strategy proof (need 3+ closed trades per strategy)
