# Phase 3 — Media/Prose Model Pilot

**Status:** PHASE 3C ROUTED — gemma3:4b approved for media/prose workflows
**Media/prose model:** gemma3:4b (3.3 GB, coexists with qwen3:14b)
**STANDARD/REALTIME:** qwen3:14b (unchanged)
**Embedding:** nomic-embed-text (unchanged)
**Deep reasoning:** gemma3-overnight (unchanged)
**Rejected:** gemma4:e4b (9.6 GB, removed)

## Phase 3C/3D Routing

- Config: `config/phase3_media_prose_routing.yaml`
- **18 approved** media/prose workflows (14 original + 4 Phase 3D additions)
- **12 blocked** trading/execution workflows
- Phase 3D pilot: **15/15 OK, 0 fallbacks, avg 4.8s**
- Router: `scripts/phase3_media_prose_router.py`
- Audit: `.venv/bin/python scripts/audit_phase3_media_prose_routing.py`
- Rollback: `./scripts/rollback_phase3_media_prose_routing.sh --disable`

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
