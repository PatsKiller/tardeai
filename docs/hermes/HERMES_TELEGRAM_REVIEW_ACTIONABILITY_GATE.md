# Hermes Telegram Review Actionability Gate

**Date:** 2026-05-31
**Status:** AUTHORITATIVE — governance document

---

## Purpose

Define the required output structure for all future Telegram weekly portfolio reviews and AI analyst messages. Any advisory message that fails this gate must be flagged and routed to the Research Backlog Manager.

---

## Required Output Sections

### 1. Key Observations
- Portfolio value change ($ and %)
- Top/bottom performers
- Sector concentration changes
- Risk metric changes (beta, VaR, drawdown)

### 2. Income Gap Assessment
- Current projected annual income
- Target income (from retirement/SSDI plan)
- Gap amount ($)
- Gap as % of target
- Trend (improving / worsening / stable)

### 3. Rebalancing Recommendation
- Recommendation type: `rebalance` / `research_needed` / `monitor` / `no_action`
- If `rebalance`: must include actionability block (section 4)
- If `research_needed`: must include research backlog item (section 4.i)

### 4. Required Actionability Block

| Field | Required? | Example |
|-------|-----------|---------|
| a. What to trim/review | YES if rebalance | "Review TELO, SPRC positions" |
| b. What to research/add | YES if rebalance | "Research SCHD, JEPI, SHV" |
| c. Candidate tickers/funds/sectors | YES (or "none — research needed") | "SCHD, VYM, DGRO, JEPI, SHV" |
| d. Account location | YES | "Roth preferred for dividend income" |
| e. Yield/income impact estimate | YES (or "unknown — research needed") | "+$2,000–$4,000/yr estimated" |
| f. Risk/tax tradeoff | YES (or "research needed") | "Higher yield = more rate sensitivity" |
| g. Evidence quality | YES | "Internal data only / External SA confirmed" |
| h. Missing research | YES | "No external analyst sources, no tax lot review" |
| i. Research backlog task created | YES if missing evidence | Title + research questions |

### 5. Operator Decision Checklist
- [ ] Reviewed by operator
- [ ] Research tasks assigned (if needed)
- [ ] Account location confirmed
- [ ] Tax impact reviewed
- [ ] Risk tolerance confirmed
- [ ] Execution approved (separate step)

### 6. "Research Needed Before Action" Fallback

If the message cannot complete sections 4a–4f with concrete data:

> **No trade is recommended from this advisory alone. Research is required before operator action.**

This fallback MUST appear. No vague "shift immediately" language is permitted.

---

## Gate Logic

```
IF recommendation_type == 'rebalance':
    IF missing(candidates) OR missing(funding_source) OR missing(account_location):
        FAIL → route to Research Backlog Manager
        CHANGE recommendation_type to 'research_needed'
    IF missing(evidence):
        FAIL → route to Research Backlog Manager
    IF missing(income_impact) AND income_gap > 0:
        WARN → add research task for income analysis
```
