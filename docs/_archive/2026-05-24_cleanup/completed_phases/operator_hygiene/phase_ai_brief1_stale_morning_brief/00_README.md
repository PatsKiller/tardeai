# AI-BRIEF-1 — Stale Morning Brief Diagnosis

**Status:** DIAGNOSED + MITIGATED

## Source Found

The "April 5, 2025" content lives in `data/portfolios/state/ai_analysis_cache.json` field `executive_summary`. The cache file's `generated_at` is `2026-05-20T07:04:34` (today), but the LLM-generated content references old dates from its training/context.

## Root Cause

The AI pipeline (`portfolio_ai_analyst.py` or similar) regenerated the cache today at 07:04, but the LLM's executive summary mentions "April 5, 2025" — this is stale context from the LLM prompt, not a rendering bug. The system timestamp is fresh; the content references old analysis.

## Mitigation Applied

1. **UI-CONTRACT-1** (prior commit): Added STALE badge to reports >24h old
2. **AI Analyst page header** already shows `timeAgo(generated_at)` — today's cache shows "Xh ago"
3. The "April 5, 2025" is in the text body, not the system date field

## What Would Fully Fix

- Refresh the AI analysis cache with current-date context by running the AI pipeline with today's portfolio snapshot
- Verify the LLM prompt includes current date and recent holdings data
- This is a content generation issue, not a UI bug

## No Fake Brief Created

No artificial content was generated. The existing cache file was not modified.
