# Current Project Context — Trade AI v12

**Last updated:** 2026-05-22  
**Author:** Context sync from Drive documentation  
**Purpose:** Canonical handoff document for future Claude Code sessions

---

## 1. Current Safety State

- **ALPACA_MODE=paper** — only paper trading endpoint accessible
- **LLM_DISABLE_LIVE_EXECUTION=true** — live execution blocked at code level
- **Live trading: BLOCKED** — no path to live orders exists
- **Holdings:** $1,201,120 / 47 positions (Schwab/Fidelity/Vanguard — untouchable)

## 2. ATM Status

ATM (Automated Trade Mode) v1 exists and has been used in both dry-run and active modes.

- **ATM was deployed** 2026-05-22 in DISABLED mode
- **Dry-run mode** ran successfully for ~2 hours (09:45–11:15 ET)
- **Active mode** was enabled by operator at 11:25 ET on 2026-05-22
- **Active execution submitted paper orders** for NWG, NVDA, AGNC, CMCSA
- **ATM active execution must be frozen** until ATM-SAFE-1 containment completes

**ATM mode is currently: dry_run** (frozen by ATM-SAFE-1 at 16:13:49 ET 2026-05-22).  
Do NOT change ATM mode without explicit operator command.

## 3. ATM-SAFE-1 Containment — COMPLETE

ATM-SAFE-1 containment completed 2026-05-22. All items resolved:

- Partial-fill race condition → **FIXED** (adapter polls through partially_filled)
- Stale proposal retry loop → **FIXED** (expiry logic, enrichment-failed tracking)
- Quote fetch 404 → **FIXED** (switched to data.alpaca.markets)
- NWG/NVDA missing stops → **FIXED** (stops placed, DB synced)
- audit_log schema mismatch → **FIXED** (event→event_type, details→input_snapshot)
- Quote fail-closed → **FIXED** (blocks order if no price source)
- Paper execution containment → **FIXED** (enrichment pre-check, risk gate on promoter)

**Maturity score post-containment: 6.2/10.0**

## 3a. Stop Management V2 — COMPLETE

All 4 phases completed 2026-05-22:

- **V2.0:** planned_stop + stop_order_id backfilled on all 5 open trades
- **V2.1:** Broker stop reconciliation engine — 5/5 GTC stops verified
- **V2.2:** Racing monitors merged into unified_stop_supervisor (*/3)
- **V2.3:** Strategy-aware trailing tiers (momentum/swing/income/position)

**Maturity score post-STOP-V2: 7.0/10.0** (up from 6.2)

Next: ATM re-enable decision package, STOP-V2 burn-in, A-5 strategy proof

## 3b. A-5 Final Observation Review — FAIL / EXTEND

Reviewed 2026-05-22. Decision: **Phase 8D BLOCKED**.

- 11 closed trades across 7 strategies (8 clean after filtering orphans)
- 0 strategies have 3+ closed trades (minimum for baseline)
- Strategy proof score remains 3.5/10
- Agent learning remains BLOCKED
- Continue observation via ATM active (limited caps)
- Re-review when total closed trades ≥ 20 or any strategy reaches 5+ closed

## 4. Recent Paper Executions

All on Alpaca paper account (2026-05-22):

| Trade | Symbol | Shares | Entry | Stop | Status |
|---|---|---|---|---|---|
| #28 | NWG | 189 | $15.84 | $15.05 | open, stop confirmed |
| #29 | NVDA | 13 | $218.00 | $210.58 | open, stop confirmed |
| #31 | AGNC | 293 | $10.22 | $9.71 | open, stop confirmed |
| #33 | CMCSA | 120 | $24.97 | $23.61 | open, stop confirmed |
| #27 | ASPN | 553 | $5.52 | $5.15 | open, stop confirmed (pre-existing) |

## 5. Known Bugs

| Bug | Severity | Status |
|---|---|---|
| audit_log.event column missing | P2 | OPEN |
| Quote failure fallback did not fail-closed | P2 | MITIGATED (data API now primary) |
| Broker error/partial fill reconciliation | P1 | FIXED (code + DB synced) |
| Stale proposal infinite retry | P1 | FIXED (expiry logic) |
| Orphan pending paper_trades | P2 | FIXED (#30, #32 closed) |

## 6. Recent Drive Docs Read

All from 2026-05-22/23:
- `docs/prompts/ATM_V1_BUILD_PROMPT.md`
- `docs/operator/ATM_RUNBOOK.md`
- `docs/sessions/ATM_V1_BUILD_2026-05-22.md`
- `docs/audits/SUPPLY_TRIAGE_2026-05-22.md`
- `docs/audits/PROPOSAL_SUPPLY_AUDIT_2026-05-22.md`
- `docs/sessions/ATM_V1_DAY1_DASHBOARD_2026-05-22.md`
- `docs/sessions/ATM_PRE_ACTIVE_FIXES_2026-05-22.md`
- `docs/sessions/AUTO_ENRICHMENT_2026-05-22.md`
- `docs/audits/ATM_APPROVE_FAILED_2026-05-22.md`
- `docs/audits/STOP_MGMT_DISCOVERY_2026-05-23.md`

## 7. Do-Not-Do List

- No active ATM without operator command
- No new orders or trades
- No proposal approvals
- No live trading
- No strategy activation changes
- No YAML threshold changes
- No Finviz criteria changes
- No .env modifications

## 8. Recommended Next

1. **ATM-SAFE-1** — freeze active execution, fix audit_log schema, enforce quote-failure
   fail-closed, verify no new orders/trades after freeze, run tests, commit
2. **Regenerate maturity board** — only after ATM-SAFE-1 completes
3. **Stop management v2** — after John answers the 7 pending decisions
4. **Strategy proof (A-5)** — required before any live trading consideration
