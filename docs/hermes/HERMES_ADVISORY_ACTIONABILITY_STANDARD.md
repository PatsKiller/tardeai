# Hermes Advisory Actionability Standard

**Date:** 2026-05-31
**Status:** AUTHORITATIVE — governance document

---

## Problem Statement

A Telegram weekly portfolio review produced:

> "Shift at least 5–7% of the portfolio into higher-yielding income assets — specifically dividend-paying stocks and potentially a short-term bond ladder."

This recommendation identifies a real income gap ($40,519) but provides zero actionable detail. It lacks:
- What to trim
- What to buy or research
- Specific tickers, ETFs, funds, sectors, or sleeves
- Taxable vs IRA vs Roth suitability
- Yield/risk/tax tradeoffs
- Evidence sources
- Expected income impact
- Research backlog item
- Operator-ready next action

**This must never pass as a complete advisory recommendation.**

---

## Required Fields for Any Advisory Recommendation

Every Hermes advisory recommendation must include:

| # | Field | Required | Description |
|---|-------|----------|-------------|
| 1 | Recommendation type | YES | rebalance / research_needed / monitor / no_action |
| 2 | Specific action or "research needed" | YES | Concrete action OR explicit "research required" |
| 3 | Funding source / source of shift | IF APPLICABLE | What to trim, reduce, or reallocate from |
| 4 | Destination candidates | IF APPLICABLE | What to research, add, or increase |
| 5 | Specific ticker/fund/sector/sleeve examples | IF AVAILABLE | Named candidates or "none identified — research needed" |
| 6 | Account location suitability | YES | taxable / IRA / Roth / unknown |
| 7 | Expected impact — income | IF APPLICABLE | Estimated yield/income change |
| 8 | Expected impact — risk | IF APPLICABLE | Risk change assessment |
| 9 | Expected impact — taxes | IF APPLICABLE | Tax implications |
| 10 | Expected impact — diversification | IF APPLICABLE | Concentration/diversification effect |
| 11 | Evidence summary | YES | Sources supporting the recommendation |
| 12 | Missing evidence | YES | What data is needed before action |
| 13 | Confidence | YES | 0–1 scale with explanation |
| 14 | Time sensitivity | YES | urgent / this_week / this_month / no_rush |
| 15 | Operator decision required | YES | YES (always for recommendations) |
| 16 | Research backlog item required | YES | yes / no — if missing evidence, must be yes |

---

## Forbidden-Action Check

Every recommendation must pass:

- [ ] No trade instruction (advisory only)
- [ ] No broker action
- [ ] No proposal mutation
- [ ] No journal mutation
- [ ] No auto-execution
- [ ] No "immediately shift" without named candidates and evidence

---

## Failure Classes

| Failure Type | Description | Severity |
|-------------|-------------|----------|
| vague_rebalance_recommendation | Recommends shift without specific candidates | HIGH |
| missing_ticker_candidates | No named tickers/funds/sectors | MEDIUM |
| missing_funding_source | No indication what to trim/reduce | MEDIUM |
| missing_account_location | No taxable/IRA/Roth guidance | MEDIUM |
| missing_evidence | No source citations | HIGH |
| stale_thesis | Evidence older than 90 days | MEDIUM |
| unsupported_income_claim | Income projection without data | HIGH |
| unsupported_tax_claim | Tax impact claim without analysis | HIGH |
| unsupported_sector_rotation_claim | Sector rotation without breadth data | MEDIUM |
| action_without_risk_tradeoff | Action recommendation without risk assessment | HIGH |
| action_without_operator_review | Recommendation bypasses operator | CRITICAL |

---

## Core Rule

**If the system cannot name candidate tickers/funds/sectors or a concrete research task, it must not say "immediately shift." It must instead say "research required before action."**

---

## Compliant vs Non-Compliant Examples

### Non-Compliant (FAIL)

> "Shift 5–7% into higher-yielding income assets."

Missing: candidates, funding source, account location, evidence, income impact, research backlog.

### Compliant (PASS)

> **Recommendation type:** research_needed
> **Action:** Research income-rotation candidates before any portfolio shift.
> **Funding source review:** Review TELO, SPRC, FLYW positions for trim candidates (underperforming, low conviction).
> **Destination research:** Dividend-growth ETFs (SCHD, VYM, DGRO), covered-call ETFs (JEPI, JEPQ), short-duration Treasury ETFs (SHV, BIL).
> **Account location:** Roth IRA preferred for dividend income (tax-free growth). Avoid taxable for high-yield.
> **Expected income impact:** Unknown — research required. Target: reduce $40,519 gap by $2,000–$4,000/yr.
> **Evidence:** Income gap from portfolio_weekly_report. No external analyst sources yet.
> **Missing evidence:** Current yield analysis, tax lot review, Roth contribution room, risk impact.
> **Confidence:** 0.3 — low until research complete.
> **Time sensitivity:** this_month — not urgent.
> **Operator decision:** YES — required before any rebalance.
> **Research backlog:** YES — create "income-rotation research" task.
