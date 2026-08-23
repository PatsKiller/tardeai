# Hermes Ticker Intelligence Wiring Closeout

**Date:** 2026-08-23  
**Status:** LIVE  
**Authority:** `READ_ONLY_ADVISORY`

## Result

PR #485 (`b970aba5bcd7ef32ee65c9b2cbe3ce3cb7a7935e`) is merged to protected
`main` and promoted to the exact-main live release:

`/home/johnclaw/trade-ai-releases/portfolio-server/b970aba5-main-exact-phase2-20260823-180900`

The live `CURRENT` link, `BUILD_SHA`, `SOURCE_COMMIT`, and loaded application
source resolve to `b970aba5bcd7ef32ee65c9b2cbe3ce3cb7a7935e`. The deployment
health gate passed and `/v3/cio` returned HTTP 200.

## What Changed

The existing Hermes completion callback now acts as a thin consumer projection.
It does not create a second research lane and does not start a new paid request
when Hermes context already exists.

For each completed Hermes result, the adapter:

- preserves the originating ticker and stable ticker ID;
- preserves `research_id`, request/plan identity, and trace identity;
- writes an idempotent `TickerResearchArtifact@v1` record;
- projects existing `hermes_research_intelligence` rows and external-lane
  context for the symbol;
- retains source URL, source type, status, freshness, and producer provenance;
- supports linear, lateral, vertical, macro, and calendar relationship buckets.

## Media Sources

Existing Hermes YouTube transcript staging is consumed through the same path and
is classified as `hermes_youtube_transcript`. Social, Reddit, and X/Twitter
records are classified as `hermes_social` when their source type or URL is
present. Media is evidence/context only; it does not become financial truth or
execution authority.

## Cost Boundary

This change is consumption-only. It does not raise the LLM cap and does not
retry `COST_CAP_EXCEEDED`. SearXNG remains the free acquisition source; the
Hermes worker's governed DeepSeek Flash bridge remains a separately gated
curation path. Scheduling Flash off-hours changes timing, not provider price.

## Verification

- Focused tests: 6 passed (`test_ticker_knowledge_graph.py`,
  `test_hybrid_evidence.py`).
- Python compilation passed for the adapter, worker callback, and Hermes data
  access module.
- Exact-main pin-integrity check: pass, zero source drift.
- Live deployment health: pass.
- No broker/order/stop/risk/2FA code or authority was changed.

## Remaining Gate

The free-first SearXNG acquisition router and off-hours Flash scheduling are
separate provider-routing work. This closeout records the completed Hermes
consumer/provenance path and does not claim that the global cost cap has been
changed or that new paid research is currently executable.
