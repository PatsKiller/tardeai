# State of the Repo — 2026-06-02 Consolidated

Status:      HISTORICAL
as_of:       2026-06-02T14:03:58-04:00
Measured at: efcc51365 / not measured

**Generated:** 2026-06-02 ~13:00 ET
**Purpose:** Single source of truth for resuming as one workstream after parallel session consolidation.

---

## 1. Today's Commits (53 total)

| Subsystem | Commits | Summary |
|-----------|---------|---------|
| Protection 188-192 | ~15 | Root-cause (broker stops DO exist), verify/record/alert fix, SIEM routing, Hermes view, protection adjustment proposals, operator-approved ANY stop 3.07→3.56, dry-run, v2/v3 parity inventory |
| v3 Dashboard | 10 | Foundation, routing fix, Strategy+Risk slice, all 11 hubs, deferred tabs filled, Intelligence crash fix, ProtectionPanel, promotion to canonical |
| Gate Fix | 1 | `close_date` → `closed_at` — gate was reading 0% due to wrong column name |
| Protection 193-198 | ~15 | Close-loop reconciler, MFE/MAE unit fix, intraday MFE, exit_time persistence, learning pipeline orchestrator+cron, v3 Journal outcomes panel, threshold tuning framework |
| Extended Hours/ATM | ~5 | Proposal expiry fix, cron 4-19, extended_hours config, auto-approver timing |
| Docs | ~7 | Phase indexes, MASTER updates, parity inventory, handoff doc |

## 2. Working Tree

- **49 modified files** — all cron-generated noise (26 strategy YAML timestamps, governance/Hermes JSON snapshots, tsbuildinfo). No real uncommitted work.
- **1 stash** from a prior session (`stash@{0}` — queue cap + .env fixes, pre-dates today)
- **Untracked**: `container/` directory, Hermes phase3b dry-run payloads, morning briefs — all artifacts, not code

## 3. Phases Completed Today

| Phase | Status | What Shipped |
|-------|--------|-------------|
| 188 | COMPLETE | Root-cause: broker stops exist, "naked" assessment was wrong |
| 189 | COMPLETE | Market-open protection watch, root-cause trace, remediation plan |
| 190 | COMPLETE | `verify_paper_trade_broker_stops.py`, `protection_alerts.py`, Hermes view, SIEM routing, +11 paper_trades columns, migration applied |
| 191 | COMPLETE | Profit-protection intelligence: inline advisory endpoint, alert policy, Hermes/learning integration, ANY/SNOW advisory reports |
| 192 | COMPLETE | Protection adjustment proposals API, operator-approved ANY stop 3.07→3.56, dry-run, v2/v3 parity, handoff doc |
| 193 | COMPLETE | Close-loop reconciler + outcomes schema + learning endpoint |
| 194 | COMPLETE | MFE/MAE unit fix (R written into percent column) + authoritative reconciler |
| 195 | COMPLETE | `exit_time` persistence on close + analyzer date derivation fix |
| 196 | COMPLETE | Intraday MFE for same-day scalps + analyzer .env load fix |
| 197 | COMPLETE | v3 Journal protection outcomes panel (`ProtectionOutcomesPanel`) |
| 198 | COMPLETE | Advisory threshold tuning framework (backtest, recommend, no auto-apply) |
| v3 build | COMPLETE | Foundation → 11 hubs → deferred fill → ProtectionPanel → promotion |
| Gate fix | COMPLETE | `close_date` → `closed_at` — all 3 win-rate sources now agree at 45.8% |
| v3 promotion | COMPLETE | Root redirects to /v3/, v2 frozen with banner, doc index updated |

## 4. Open Paper Positions (7)

| # | Symbol | Strategy | Entry | Stop | PnL | Note |
|---|--------|----------|-------|------|-----|------|
| 31 | AGNC | reit_income | $10.22 | $9.71 | +$23 | |
| 48 | **ANY** | unknown_sync | $3.23 | **$3.56** | +$384 | **Stop moved from $3.07 → $3.56 (operator-approved profit lock)** |
| 33 | CMCSA | dividend_growth_compounder | $24.97 | $23.61 | -$5 | |
| 50 | MRVL | fib_retracement_bounce | $284.49 | $269.67 | -$5 | New today |
| 28 | NWG | dividend_growth_compounder | $15.84 | $15.05 | +$59 | |
| 43 | SNOW | unknown_sync | $236.50 | None | +$214 | No stop in DB |
| 47 | TMHC | swing_breakout | $71.61 | $68.02 | -$3 | |

**Account equity: $101,230**

## 5. Remaining v3 Placeholder Tabs (2)

| Hub | Tab | Status | Why |
|-----|-----|--------|-----|
| Strategy | Incubator | Placeholder | Deeper integration deferred — `/api/v2/incubator` exists but needs custom view |
| System | LLM | Renders but sparse | `local-llm-status` returns a flat object — renders as key-value, detected as "placeholder" by text check |

All other 37 tabs are **LIVE** with verified endpoint data.

## 6. PROPOSED / Half-Done State

| Item | State | Detail |
|------|-------|--------|
| `paper_protection_adjustment_proposals` | **5 PROPOSED** | ANY (3: keep/add-TP/trailing), MRVL (2: keep/add-TP). Not applied. Require operator approval. |
| `atm_profit_protection_advisories` | 34 rows | Advisory data, read-only |
| `protection_advisory_outcomes` | 31 rows | Reconciliation outcomes tracked |
| LLM queue | 12 queued_for_review, 4 dry_run, 4 failed | No approved — worker only picks approved |
| Pending paper proposals | 0 | None pending |
| Phase 198 threshold tuning | DESIGNED | Framework exists, backtest+recommend, no auto-apply — requires operator to approve any threshold change |

**No half-built code.** All committed phases are complete. The 5 PROPOSED protection adjustments are intentionally awaiting operator decision — that's the designed workflow.

## 7. Live-Trading Gate Status

| Gate | Required | Current | Status |
|------|----------|---------|--------|
| Win Rate >= 55% | 0.55 | 0.458 (45.8%) | FAIL |
| Profit Factor >= 1.3 | 1.3 | 3.69 | **PASS** |
| Minimum 30 Closed Trades | 30 | 24 | FAIL (6 more) |
| Minimum 6 Months Paper | 6 | 0.9 | FAIL (5.1 more) |

**Status: PAPER_ONLY.** Gate reads real data (fixed today). PF passes. Need 6 more closed trades, ~9 points WR improvement, and 5 more months.

## 8. v3 Dashboard

- **Canonical URL:** http://192.168.50.16:7777/v3/
- **v2 frozen** at /v2/ with banner
- **11 hubs, 37/39 tabs live** — all from verified endpoints
- **ProtectionPanel** live on Trading hub (21 candidates, 6 positions)
- **ProtectionOutcomesPanel** live on Journal hub (Phase 197)
