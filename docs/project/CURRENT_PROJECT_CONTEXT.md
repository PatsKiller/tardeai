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

**ATM mode is currently: active** (set by operator via dashboard 2026-05-22 11:25 ET).  
Do NOT change ATM mode without explicit operator command.

## 3. Critical Open Issue — ATM-SAFE-1

ATM-SAFE-1 containment is **required before any further enhancements**.

The ATM active-mode event on 2026-05-22 revealed:
- Partial-fill race condition → **FIXED** (adapter now polls through partially_filled)
- Stale proposal retry loop → **FIXED** (expiry logic added, 4h/5-attempt/enrichment-failed)
- Quote fetch 404 → **FIXED** (switched to data.alpaca.markets)
- NWG/NVDA missing stops → **FIXED** (manual stops placed, DB synced)

Remaining ATM-SAFE-1 items:
- audit_log.event column missing (schema mismatch, audit trail lost)
- Validated-price fallback did not fail-closed (mitigated but not eliminated)
- Paper execution containment gate hardening

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
