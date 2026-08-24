# CIO persistent cognition consumption

**Date:** 2026-08-24  
**Status:** SOURCE + TESTED. Not MERGED as live. Not NATURALLY_PROVEN.  
**Authority:** `READ_ONLY_ADVISORY`  
**MEMORY_BEHAVIOR_INFLUENCE:** 0  

M1 is LIVE on CURRENT `5c0a993a`. This PR makes CIO/Hermes/Telegram **read** that brain.

## What

`scripts/lib/cio_persistent_cognition.py` loads canonical:

- `TickerResearchState`
- `HermesCurationSummary` (`MATERIAL` or `BASELINE_PROJECTION` v0)

Baseline v0 is legitimate prior cognition, not “no cognition.”

`get_context_for_agent()` attaches a bounded pack at `research_memory.persistent_ticker_cognition`. No `cio_ticker_memory.jsonl`. No provider dispatch. Unchanged watermarks → `NO_PORTFOLIO_CHANGE` without an LLM.

Telegram and CIO use the same `cognition_for_symbol` loader.

## Not in this PR

SQL `r10_memory_shadow.sql` apply. Neo4j. Producer retirement. UI overhaul. Paid Flash activation. CURRENT promote.
