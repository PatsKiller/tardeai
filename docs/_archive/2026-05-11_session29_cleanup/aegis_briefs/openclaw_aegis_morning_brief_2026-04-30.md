# Aegis Morning Brief — 2026-04-30
*Generated: 2026-04-30 08:05 ET*

---

## Executive Summary
Portfolio $1,206,911. Heat 0.1%. 0 stops triggered, 11 unprotected. 1 items flagged for Steph review. Covered calls: 0 candidates, 12 need review, 1 avoid

## 1. IMMEDIATE RISK
- 7 stop(s) TRIGGERED: IRDM, TDG, LHX, RTX, LMT, NOC, DRS. Check /v2/risk immediately.
- 2 in danger zone: ARKG, BAH.
- 11 large positions without stops ($582,914 total).

## 2. STEPH REVIEW NEEDED
- ARKG: ARKG danger — $28.48 vs stop $27.71 2.7% from stop → /v2/approvals
- BAH: BAH danger — $76.37 vs stop $74.87 2.0% from stop → /v2/approvals
- LDOS: LDOS danger — $145.62 vs stop $142.76 2.0% from stop → /v2/approvals

## 3. RECOVERY WATCH
- NOC: wait_monitor (alloc: stay_cash) → /v2/recovery
- TDG: wait_monitor (alloc: stay_cash) → /v2/recovery
- LHX: wait_monitor (alloc: stay_cash) → /v2/recovery
- IRDM: wait_monitor (alloc: stay_cash) → /v2/recovery
- DRS: wait_monitor (alloc: stay_cash) → /v2/recovery
- RTX: wait_monitor (alloc: stay_cash) → /v2/recovery
- LMT: wait_monitor (alloc: stay_cash) → /v2/recovery

## 4. COVERED CALLS
- Review needed: CSWC, ARKQ, DIV, V
- Avoid: PFLT

## 5. ROTATION ALTERNATIVES
- DRS → BWXT: consider
- DRS → HII: not_yet
- LMT → BWXT: consider

## Steph Review Queue
- deferred: **1**
- failed: **12**
- in review: **76**
- needs john: **1**
- pending review: **5**
- resolved: **1**

## Ranked Next Actions
1. 1. Verify IRDM, TDG, LHX stop levels in broker → /v2/risk
2. 2. Review Steph escalations → /v2/approvals
3. 3. Check covered-call candidates → /v2/actions

## Evidence Quality
- adequate: 2 symbols
- strong: 13 symbols

---
*Aegis Portfolio Intelligence | 2026-04-30 | Provenance: model=aegis*
*Advisory only — no auto-trading — review chain: Aegis → Steph → John*