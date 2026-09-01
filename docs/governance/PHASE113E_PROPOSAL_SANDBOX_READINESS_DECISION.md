# Phase 113E — Proposal Sandbox Readiness Decision

Status:      HISTORICAL
as_of:       2026-06-01T15:53:13-04:00
Measured at: efcc51365 / not measured

## Decision: READY_FOR_FILE_ONLY_SANDBOX

### Rationale

1. **Architecture is sound**: The sandbox design (Phase 113B) is fully isolated from execution. No FK paths to proposal tables, no broker access, no enrichment pipeline integration.

2. **Quality scorecard exists**: Phase 113C defines 10 scoring dimensions with fail thresholds and a composite score. This gives objective criteria for evaluating Hermes drafts.

3. **Template is concrete**: Phase 113D provides a complete JSON template with mandatory safety fields (execution_statement, why_not_trade, required_human_review).

4. **Evidence infrastructure exists**: Hermes has 8 safe DB views (76K+ rows), headless browser, SearXNG search, 11+ staged research rows, and 7 embeddings. Enough to produce meaningful drafts.

5. **Blast radius is zero**: Sandbox writes only to hermes_* tables or files. TradeAI execution path is completely unaware of Hermes drafts.

### Conditions for Proceeding

- Start with **file-only sandbox** (Option A from 113B): JSON files in `hermes_sidecar/drafts/proposals/`
- Produce **3-5 draft packets** manually using the template
- Score each against the quality scorecard
- Only consider DB table (Option B) after file-only proves quality > 5.0 composite
- Only consider promotion path after 20+ drafts with consistent quality > 6.5

### What This Does NOT Authorize

- No `hermes_proposal_drafts` table creation (needs separate approval)
- No real proposal writes
- No broker access
- No automatic promotion
- No Level 7 boundary changes
