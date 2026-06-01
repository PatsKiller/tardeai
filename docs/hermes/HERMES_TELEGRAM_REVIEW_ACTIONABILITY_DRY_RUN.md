# Hermes Telegram Review Actionability Dry-Run Classification

**Date:** 2026-05-31
**Status:** COMPLETE — dry-run classification, no DB writes

---

## Input Message (Telegram Weekly Review Excerpt)

> "Shift at least 5–7% of the portfolio into higher-yielding income assets — specifically dividend-paying stocks and potentially a short-term bond ladder."

---

## Classification

| Field | Value |
|-------|-------|
| finding_type | `vague_rebalance_recommendation` |
| severity | **HIGH** |
| source | Telegram weekly portfolio review |
| actionability_score | 0.15 (very low) |

## Reason

The message recommends a 5–7% portfolio shift (~$60,000–$84,000 at current $1.2M portfolio) but lacks:

| Missing Field | Status |
|---------------|--------|
| Concrete candidates (tickers/funds) | MISSING — says "dividend-paying stocks" generically |
| Funding source (what to trim) | MISSING — no trim candidates named |
| Account location (taxable/IRA/Roth) | MISSING — no guidance |
| Income impact estimate | MISSING — no yield projection |
| Risk tradeoff | MISSING — no rate sensitivity or drawdown analysis |
| Tax impact | MISSING — no tax lot review |
| Evidence sources | MISSING — no citations |
| Research backlog item | MISSING — no structured follow-up |

**9 of 9 actionability fields are missing or vague.**

## Gate Result

**FAIL** — must be reclassified as `research_needed` and routed to Research Backlog Manager.

---

## Backlog Recommendation

Route to Research Backlog Manager with the following structured task:

### Research Backlog Item

**Title:** Research income-rotation candidates for $40,519 income gap

**Priority:** MEDIUM (income gap is real but not urgent — SSDI covers baseline)

**Research Questions:**

1. Which current holdings are candidates for trimming?
   - Review TELO (staged, low conviction 0.2), SPRC (small position), FLYW (volatile)
   - Review any holdings with negative trailing returns and no catalyst

2. Which income sleeves are suitable?
   - Dividend-growth ETFs (SCHD, VYM, DGRO, HDV)
   - Covered-call ETFs (JEPI, JEPQ, XYLD)
   - Short-duration Treasury/bond ETFs (SHV, BIL, SGOV, VGSH)
   - Preferred-stock ETFs (PFF, PFFD)
   - REITs (VNQ, SCHH, O)
   - BDCs (ARCC, MAIN, HTGC)
   - CEFs (income-focused, review NAV discount)
   - Individual dividend stocks (from SCHD top holdings)

3. What is expected yield and risk for each candidate bucket?
   - Target: reduce $40,519 gap by $2,000–$4,000/yr
   - Assess yield vs price volatility tradeoff
   - Assess rate sensitivity (duration risk)

4. Which account type is suitable?
   - Roth IRA preferred for dividend/income (tax-free growth)
   - Taxable: consider qualified dividends vs ordinary income
   - IRA: standard for bond ladder

5. What tax impact exists?
   - Capital gains on trimmed positions
   - Tax lot optimization opportunity
   - Wash sale risk if trimming losers

6. What sources support the recommendation?
   - SearXNG source discovery (Phase 18–19 candidates available)
   - Existing Hermes research (SCHD id=3, id=12)
   - FinViz screening data
   - Morningstar/Zacks fund analysis

**Task Owner:** Source Discovery Agent → Hermes Librarian Agent

**Status:** `candidate` (not yet started)

---

## Required Statement

**No trade is recommended from this Telegram post alone. Research is required before operator action.**

---

## Summary

| Item | Value |
|------|-------|
| Message classified | YES |
| Finding type | vague_rebalance_recommendation |
| Severity | HIGH |
| Actionability score | 0.15 |
| Missing fields | 9 of 9 |
| Gate result | FAIL |
| Reclassified to | research_needed |
| Research backlog item created | YES (in this document, not in DB) |
| DB writes | ZERO |
| Embeddings | ZERO |
| Promotions | ZERO |
