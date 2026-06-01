# Advisory Communication Actionability Dry-Run Summary

**Date:** 2026-06-01 01:15 UTC

---

## Input

Telegram weekly portfolio review fixture (payloads not stored in DB):

> "Shift at least 5-7% of the portfolio into higher-yielding income assets — specifically dividend-paying stocks and potentially a short-term bond ladder."

## Classification

- **Finding type:** vague_rebalance_recommendation
- **Severity:** high
- **Actionability score:** 0.15
- **Missing fields:** 9 of 9
- **Gate result:** FAIL
- **Reclassified to:** research_needed
- **Backlog required:** True

## Research Backlog Item

**Title:** Research income-rotation candidates for $40,519 income gap
**Priority:** medium
**Status:** candidate (not in DB)

### Research Questions

- Which current holdings are candidates for trimming?
- Which income sleeves are suitable (div ETFs, covered-call, Treasury, preferreds, REITs, BDCs, CEFs)?
- What is expected yield and risk for each candidate bucket?
- Which account type is suitable (Roth, IRA, taxable)?
- What tax impact exists from trimming?
- What sources support the recommendation?

### Candidate Buckets

- dividend-growth ETFs (SCHD, VYM, DGRO, HDV)
- covered-call ETFs (JEPI, JEPQ, XYLD)
- short-duration Treasury/bond ETFs (SHV, BIL, SGOV)
- preferred-stock ETFs (PFF, PFFD)
- REITs (VNQ, SCHH, O)
- BDCs (ARCC, MAIN, HTGC)
- CEFs (income-focused, review NAV discount)
- individual dividend stocks (from SCHD top holdings)
- current holdings trim review

**No trade is recommended from this Telegram post alone. Research is required before operator action.**

---

**DB writes: ZERO | Embeddings: ZERO | Promotions: ZERO | Alert sends: ZERO**