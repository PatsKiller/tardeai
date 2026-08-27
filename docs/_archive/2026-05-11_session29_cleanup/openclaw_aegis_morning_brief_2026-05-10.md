# Aegis Morning Brief — 2026-05-10
*Generated: 2026-05-10 20:18 ET*

---

## Executive Summary
Portfolio $1,189,371. Heat 0.1%. 0 stops triggered, 11 unprotected. 6 items flagged for Steph review. Covered calls: 1 candidates, 12 need review, 0 avoid

## 1. IMMEDIATE RISK
- 6 stop(s) TRIGGERED: RTX, LHX, LMT, LDOS, NOC, KBR. Check /v2/risk immediately.
- 2 in danger zone: AVAV, CACI.
- 11 large positions without stops ($581,774 total).

## 2. STEPH REVIEW NEEDED
- DRS: assessment → /v2/approvals
- BAH: assessment → /v2/approvals
- CACI: assessment → /v2/approvals

## 3. RECOVERY WATCH
- LHX: wait_monitor (alloc: stay_cash) → /v2/recovery
- TDG: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- IRDM: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- LMT: wait_monitor (alloc: stay_cash) → /v2/recovery
- DRS: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- KBR: wait_monitor (alloc: stay_cash) → /v2/recovery
- LDOS: wait_monitor (alloc: stay_cash) → /v2/recovery
- NOC: wait_monitor (alloc: stay_cash) → /v2/recovery
- RTX: wait_monitor (alloc: stay_cash) → /v2/recovery

## 4. COVERED CALLS
- Review needed: PFLT, ARKQ, DIV, CSWC

## 5. ROTATION ALTERNATIVES
- RTX → BWXT: consider
- RTX → HII: not_yet
- NOC → BWXT: consider

## Steph Review Queue
- deferred: **1**
- in review: **319**
- needs john: **1**
- resolved: **1**

## Event Intelligence (Last 24h)
**62 events fired**

- **CONTENT_GAP**: SCHD (1 events, all done)
- **PORTFOLIO_FRESH_NEEDED**: ARKQ, XLB, JEPI, ARKG, IRDM, BAH, CACI, LPIH (34 events, 32 done, 2 pending)
- **RSI_EXTREME**: SCHG (4 events, all done)
- **STOP_TRIGGERED**: LDOS, RTX, KBR, LHX, NOC, LMT (19 events, all done)
- **TOPIC_INTELLIGENCE**: TOPIC:disability_retirement, TOPIC:covered_call_income, TOPIC:dividend_income (4 events, all done)

## Iris — Taxonomy Intelligence
Iris: 100% transcripts tagged | 48 channels active | 131 proposals need review | Top gap: 'Form 4: CIMPRESS plc Form 4'

## Ranked Next Actions
1. 1. Verify RTX, LHX, LMT stop levels in broker → /v2/risk
2. 2. Review Steph escalations → /v2/approvals
3. 3. Check covered-call candidates → /v2/actions

## Evidence Quality
- strong: 13 symbols
- adequate: 2 symbols

---
*Aegis Portfolio Intelligence | 2026-05-10 | Provenance: model=aegis*
*Advisory only — no auto-trading — review chain: Aegis → Steph → John*