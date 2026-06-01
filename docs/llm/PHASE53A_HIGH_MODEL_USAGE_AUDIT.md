# Phase 53A — High-Model Usage Audit

**Date:** 2026-06-01
**Status:** COMPLETE

## Scripts Using High/Deep Models

| Script | Model | Schedule | Purpose |
|--------|-------|----------|---------|
| overnight_batch.py | gemma3:12b (deep) | Nightly | Deep overnight LLM queue |
| create_deep_overnight_llm_queue.py | gemma3:12b | Nightly | Queue population |
| gemma3_calibration_scorer.py | gemma3:12b | Nightly | Prediction scoring |
| multi_tier_trade_reviewer.py | gemma3:12b / gemma4 31B | On-demand | Tier 2/3 trade review |
| data_gap_resolver.py | gemma3:12b | Hourly (market) | Pipeline gap resolution |
| hermes_autonomous_loop.py | gemma3:12b | Daily 01:00 UTC | Ticker challenger |
| hermes_browse_proxy.py | gemma3:12b | On-demand | Web research |

## Monopolization Risks

| Risk | Severity | Notes |
|------|----------|-------|
| Overnight batch owns entire window | HIGH | Single process, no quota |
| Hermes loop can collide with overnight | MEDIUM | 01:00 UTC, may overlap |
| Calibration scorer during overnight | LOW | Short job |
| Data gap resolver hourly | LOW | Fast, market hours only |

## GPU Lock Behavior

- Ollama MAX_LOADED_MODELS=1
- KEEP_ALIVE=5m
- Only 1 model in VRAM at a time
- Model swaps take ~10–30s (gemma3:12b cold load)
- No explicit GPU lock file — Ollama manages internally

## Current State

The overnight batch is the only process that systematically uses the nightly window. Hermes runs at 01:00 UTC but finishes in <5 minutes. There is no global priority queue — each process independently calls Ollama.
