# Aegis Morning Brief — 2026-05-01
*Generated: 2026-05-01 08:05 ET*

---

## Executive Summary
Portfolio $1,195,658. Heat 0.1%. 0 stops triggered, 11 unprotected. 1 items flagged for Steph review. Covered calls: 0 candidates, 12 need review, 1 avoid

## 1. IMMEDIATE RISK
- 4 stop(s) TRIGGERED: TDG, RTX, LMT, NOC. Check /v2/risk immediately.
- 2 in danger zone: LHX, DRS.
- 11 large positions without stops ($583,174 total).

## 2. STEPH REVIEW NEEDED
- BAH: BAH danger — $77.64 vs stop $74.87 3.6% from stop → /v2/approvals
- ARKG: ARKG danger — $29.92 vs stop $27.71 7.4% from stop → /v2/approvals
- DRS: DRS triggered — $40.60 vs stop $40.20 1.0% from stop → /v2/approvals

## 3. RECOVERY WATCH
- LHX: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- TDG: wait_monitor (alloc: stay_cash) → /v2/recovery
- NOC: wait_monitor (alloc: stay_cash) → /v2/recovery
- IRDM: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- DRS: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- RTX: wait_monitor (alloc: stay_cash) → /v2/recovery
- LMT: wait_monitor (alloc: stay_cash) → /v2/recovery

## 4. COVERED CALLS
- Review needed: CSWC, ARKQ, DIV, V
- Avoid: PFLT

## 5. ROTATION ALTERNATIVES
- LMT → GD: consider
- LMT → HII: not_yet
- RTX → GD: consider

## Steph Review Queue
- deferred: **1**
- failed: **9**
- in review: **80**
- needs john: **1**
- pending review: **22**
- resolved: **1**

## Event Intelligence (Last 24h)
**53 events fired**

- **PORTFOLIO_FRESH_NEEDED**: VANG-FTSE-SOC, V, JPM-LGCG, LPIH, XLB, DIV, NEE, XLI (38 events, all done)
- **STOP_TRIGGERED**: LMT, LHX, TDG, NOC, RTX (15 events, all done)

## Ranked Next Actions
1. 1. Verify TDG, RTX, LMT stop levels in broker → /v2/risk
2. 2. Review Steph escalations → /v2/approvals
3. 3. Check covered-call candidates → /v2/actions

## Evidence Quality
- adequate: 2 symbols
- strong: 13 symbols

---
*Aegis Portfolio Intelligence | 2026-05-01 | Provenance: model=aegis*
*Advisory only — no auto-trading — review chain: Aegis → Steph → John*