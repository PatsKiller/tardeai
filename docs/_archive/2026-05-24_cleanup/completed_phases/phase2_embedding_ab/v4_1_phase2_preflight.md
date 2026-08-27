# Phase 2A Preflight Gates — 2026-05-14

## Git State
```
4f13d9a docs: schedule data gap resolver + canonical doc updates
6f448cb docs: update for self-healing gap orchestration
979323f feat: self-healing data gap orchestration
465ae39 Phase 1 finalization: deep overnight governance and closeout
b702721 docs: update system counts for overnight dashboard v2
f599f4b feat: overnight dashboard v2 — parsed gemma3 outputs and actionable signals
1def1a4 Phase 1J: enforce mixed deep queue and preserve Friday extended cron
798a6a0 feat: overnight intelligence dashboard at /v2/overnight
72837b1 docs: Session 34 hotfix — overnight queue crash fixes
b173ed7 Session 34 hotfix: overnight queue crash fixes for 23:00 window
```

## Safety Gates

| Gate | Result |
|------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Holdings | $1,190,653 (>$1M) |
| Deep LLM lock | NOT present |
| Active deep job | NONE |

## Model Inventory

| Model | Size | Installed | Resident |
|-------|------|-----------|----------|
| qwen3:14b | 9.3 GB | YES | YES (9.4 GB VRAM) |
| nomic-embed-text:latest | 274 MB | YES | YES (0.54 GB VRAM) |
| gemma3-overnight:latest | 17 GB | YES | NO |
| gemma3:27b | 17 GB | YES | NO |
| **qwen3-embedding:8b** | **~5 GB** | **NOT INSTALLED** | N/A |

## Deep Overnight Health

All 11 checks: **PASS**

## Provider Status

| Provider | Status |
|----------|--------|
| Local (qwen3:14b) | Resident, timeout on generate probe |
| OpenAI (gpt-4o-mini) | USABLE |
| Anthropic | DEGRADED (credit balance low) |
| xAI/Grok | CONFIGURED |

## Preflight Verdict

**PASS** — all gates clear. Phase 2A discovery and tooling can proceed.

**BLOCKING NOTE:** qwen3-embedding:8b is NOT installed. A/B candidate testing cannot run until operator approves pull. Discovery, baseline tooling, and design documents can proceed without it.
