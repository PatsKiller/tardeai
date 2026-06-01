# Hermes Phase 23D — Income-Rotation Actionability Audit

**Date:** 2026-06-01
**Status:** COMPLETE

---

## Comparison: Original Telegram vs Phase 23 Research

### Original Telegram (Phase 20E — FAIL, 0.15 actionability)

> "Shift at least 5–7% of the portfolio into higher-yielding income assets — specifically dividend-paying stocks and potentially a short-term bond ladder."

### Phase 23 Research Output

| Actionability Field | Original | Phase 23 |
|--------------------|----------|----------|
| Names candidate sleeves? | NO | **YES — 7 sleeves scored** |
| Names specific tickers? | NO | **YES — SCHD, VYM, JEPI, JEPQ, DIVO, SHV, BIL, PFF, VNQ, O, ARCC, MAIN** |
| Identifies risk tradeoffs? | NO | **YES — per-sleeve risk scoring** |
| Identifies tax tradeoffs? | NO | **YES — QDI vs ordinary income, state-exempt** |
| Identifies account location? | NO | **YES — Roth/IRA/Taxable per sleeve** |
| Gives income impact context? | NO | **PARTIAL — yield ranges but no portfolio-specific projection** |
| Provides evidence sources? | NO | **YES — 55 sources from 8 SearXNG queries** |
| Creates research backlog? | NO | **YES — Phase 22 backlog item #19** |

### Actionability Score Improvement

| Metric | Original | Phase 23 |
|--------|----------|----------|
| Fields present | 0/9 | **7/9** |
| Actionability score | 0.15 | **0.78** |
| Gate result | FAIL | **PASS_WITH_LIMITS** |

---

## What Is Now Available for Operator Review

1. **7 ranked income sleeves** with yield, risk, tax, and account-location data
2. **12+ specific tickers/funds** across all sleeves
3. **55 credible external sources** from Seeking Alpha, Motley Fool, Fidelity, Vanguard, etc.
4. **Per-sleeve risk/tax scoring** (10 dimensions each)
5. **Tax placement strategy** identified as prerequisite
6. **Research backlog** linking this to the original Telegram finding

---

## What Is Still Missing

| Missing Item | Severity | How to Resolve |
|-------------|----------|----------------|
| Portfolio-specific yield projection | MEDIUM | Calculate based on current holdings + shift amount |
| Current holdings trim candidates | MEDIUM | Review portfolio for underperforming/low-conviction positions |
| Roth contribution room check | LOW | Check IRS limits and current Roth balance |
| Tax lot review for trim positions | MEDIUM | Review cost basis for capital gains impact |
| Specific allocation percentages | LOW | Operator decision after research |

---

## What Would Be Needed Before a Proposal/Trade

1. Operator reviews scored sleeves and selects 2–3 for further analysis
2. Portfolio-specific yield projection (requires DB read of current holdings)
3. Current holdings trim candidate review
4. Tax lot analysis for candidate trims
5. Roth/IRA contribution room verification
6. Operator explicitly approves research-to-proposal pipeline (NOT approved yet)
7. Separate Phase approval for any proposal creation

**No proposal/trade is recommended from this research alone. Operator review is required.**

---

## Verdict

The Phase 23 research transforms a vague Telegram FAIL (0.15) into a structured, evidence-backed PASS_WITH_LIMITS (0.78) research package. The operator now has named sleeves, tickers, risk/tax analysis, and sources — enough to make informed decisions. The remaining gaps (portfolio-specific projections, trim candidates) require DB reads and operator judgment, not more SearXNG discovery.
