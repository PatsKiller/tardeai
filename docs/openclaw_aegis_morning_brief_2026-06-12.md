# Aegis Morning Brief — 2026-06-12
*Generated: 2026-06-12 08:05 ET*

---

## Executive Summary
Portfolio $1,245,865. Heat 0.3%. 5 stops triggered, 11 unprotected. 11 items flagged for Steph review. Covered calls: 0 candidates, 12 need review, 1 avoid

## 1. IMMEDIATE RISK
- 5 stop(s) TRIGGERED: PFLT, LHX, LMT, NOC, LDOS. Check /v2/risk immediately.
- 1 in danger zone: NEE.
- 11 large positions without stops ($612,116 total).

## 2. STEPH REVIEW NEEDED
- NEE: The stop-loss price has been tightened by $0.21, moving from $84.62 to $84.83. → /v2/approvals
- LDOS: assessment → /v2/approvals
- NOC: The position was triggered due to a price movement exceeding the stop-loss order → /v2/approvals

## 3. RECOVERY WATCH
- CACI: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- AVAV: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- IRDM: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- LDOS: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- BAH: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- PFLT: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- NOC: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- LHX: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- DRS: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- LMT: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- NEE: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- TDG: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- RTX: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- KBR: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery

## 4. COVERED CALLS
- Review needed: CSWC, ARKQ, DIV, V
- Avoid: PFLT

## 5. ROTATION ALTERNATIVES
- PFLT → no alternative: not_yet
- NOC → no alternative: not_yet
- AVAV → no alternative: not_yet

## 6. RESEARCH ADVISORIES
- Income ETF alternatives to JEPI/SCHD (iter #17): Okay, here’s your updated advisory reflecting Iteration #17, building on our previous research into income ETF alternati… → /v2/research-topics
- Tax-loss harvesting opportunities Q2 2026 (iter #17): Okay, here’s your updated advisory based on our Q2 2026 tax-loss harvesting research, iteration #17:  **1. What’s New/Ch… → /v2/research-topics
- Defense sector rotation signals (iter #17): Okay, here’s your updated advisory based on iteration #17 of our defense sector rotation research, designed to aggressiv… → /v2/research-topics

## Steph Review Queue
- deferred: **1**
- failed: **4**
- in review: **1074**
- needs john: **1**
- resolved: **1**

## Event Intelligence (Last 24h)
**18 events fired**

- **PORTFOLIO_FRESH_NEEDED**: SP500-D, FID-CONTRA-F, SS-SMMD (3 events, 2 done, 1 pending)
- **STOP_TRIGGERED**: LMT, NOC, PFLT, LHX, LDOS (15 events, 10 done, 5 pending)

## Iris — Taxonomy Intelligence
Iris: 100% transcripts tagged | 48 channels active | 1262 proposals need review | Top gap: 'Form 4: CIMPRESS plc Form 4'

## Ranked Next Actions
1. 1. Verify PFLT, LHX, LMT stop levels in broker → /v2/risk
2. 2. Review Steph escalations → /v2/approvals
3. 3. Check covered-call candidates → /v2/actions

## Evidence Quality
- strong: 15 symbols

---
*Aegis Portfolio Intelligence | 2026-06-12 | Provenance: model=aegis*
*Advisory only — no auto-trading — review chain: Aegis → Steph → John*