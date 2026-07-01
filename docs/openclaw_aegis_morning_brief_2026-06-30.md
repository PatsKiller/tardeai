# Aegis Morning Brief — 2026-06-30
*Generated: 2026-06-30 08:05 ET*

---

## Executive Summary
Portfolio $1,248,720. Heat 0.3%. 5 stops triggered, 8 unprotected. 7 items flagged for Steph review. Covered calls: 0 candidates, 18 need review, 1 avoid

## 1. IMMEDIATE RISK
- 5 stop(s) TRIGGERED: PFLT, NOC, BAH, LDOS, CACI. Check /v2/risk immediately.
- 8 large positions without stops ($290,343 total).

## 2. STEPH REVIEW NEEDED
- CACI: The stop-loss order was triggered, resulting in a sale at $457.04. → /v2/approvals
- LDOS: assessment → /v2/approvals
- BAH: The stop-loss was triggered, resulting in a loss on the position. → /v2/approvals

## 3. RECOVERY WATCH
- NOC: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- DRS: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- RTX: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- AVAV: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- LHX: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- PFLT: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- CACI: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- BAH: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- NEE: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- KBR: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- TDG: reentry_candidate (alloc: hold_for_reentry) → /v2/recovery
- LMT: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- LDOS: market_relist_monitor (alloc: stay_cash) → /v2/recovery
- IRDM: market_relist_monitor (alloc: stay_cash) → /v2/recovery

## 4. COVERED CALLS
- Review needed: SCHG, SCHD, ARKQ, CSWC
- Avoid: PFLT

## 5. ROTATION ALTERNATIVES
- LMT → no alternative: not_yet
- RTX → no alternative: not_yet
- NOC → no alternative: not_yet

## 6. RESEARCH ADVISORIES
- Income ETF alternatives to JEPI/SCHD (iter #25): Okay, here’s your updated advisory based on Iteration #25, focusing on income ETF alternatives to JEPI/SCHD, considering… → /v2/research-topics
- Defense sector rotation signals (iter #25): Okay, here’s an updated advisory reflecting the latest defense sector rotation signals, considering your portfolio conte… → /v2/research-topics
- Tax-loss harvesting opportunities Q2 2026 (iter #25): Okay, here’s an updated advisory regarding tax-loss harvesting opportunities for Q2 2026, building on our previous resea… → /v2/research-topics

## Steph Review Queue
- deferred: **1**
- failed: **1**
- in review: **1674**
- needs john: **1**
- resolved: **1**

## Event Intelligence (Last 24h)
**32 events fired**

- **PORTFOLIO_FRESH_NEEDED**: HPE, 543354104, 628518102, ARKX (7 events, 3 done, 4 pending)
- **RSI_EXTREME**: LDOS (3 events, 2 done, 1 pending)
- **STOP_TRIGGERED**: PFLT, BAH, LDOS, NOC, CACI (15 events, 8 done, 7 pending)
- **TOPIC_INTELLIGENCE**: TOPIC:su_industry_staffing_employment_services, TOPIC:su_industry_reit_retail, TOPIC:d23_defense_aerospace, TOPIC:su_industry_specialty_industrial_machinery, TOPIC:su_industry_specialty_retail, TOPIC:d101_sector_rotation_mechanics_and_timing_sig (7 events, all done)

## Iris — Taxonomy Intelligence
Iris: 100% transcripts tagged | 48 channels active | 1706 proposals need review | Top gap: 'Form 4: CIMPRESS plc Form 4'

## Ranked Next Actions
1. 1. Verify PFLT, NOC, BAH stop levels in broker → /v2/risk
2. 2. Review Steph escalations → /v2/approvals
3. 3. Check covered-call candidates → /v2/actions

## Evidence Quality
- strong: 15 symbols

---
*Aegis Portfolio Intelligence | 2026-06-30 | Provenance: model=aegis*
*Advisory only — no auto-trading — review chain: Aegis → Steph → John*