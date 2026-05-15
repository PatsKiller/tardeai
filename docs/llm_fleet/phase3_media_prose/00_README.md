# Phase 3 — Media/Prose Model Pilot

**Status:** AWAITING MODEL PULL
**Candidate model:** gemma4:e4b (~3-4 GB)
**Current production model:** qwen3:14b (STANDARD/REALTIME)

## Purpose

Evaluate a smaller local model for media/prose/content workflows so qwen3:14b and gemma3-overnight are not overloaded with lower-risk writing, summarization, and content tasks.

## Candidate

`gemma4:e4b` — documented in LLM Fleet Strategy v4.1 Final as the Phase 3 MEDIA_CONTENT candidate. Expected ~3-4 GB Q4, can coexist with qwen3:14b on Intel Arc B50.

**Not yet installed.** Pull command:
```bash
ollama pull gemma4:e4b
```

## Approved Workflows

YouTube transcript summarization, transcript cleanup, content digest drafting, report narrative polish, article summarization, media metadata enrichment, post-market narrative drafting (read-only), weekly summary prose drafting (read-only)

## Blocked Workflows

broker_execution, risk_gate, order_placement, stop/target execution, market-hours trading decisions, Telegram/OpenClaw interactive trading

## Safety

- No trade recommendations from Phase 3 model
- No broker/execution calls
- Read-only content workflows only
- Fallback to qwen3:14b if candidate fails
