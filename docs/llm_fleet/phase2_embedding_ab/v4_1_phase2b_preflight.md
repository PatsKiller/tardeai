# Phase 2B Preflight Gates — 2026-05-14

## Safety Gates

| Gate | Result |
|------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Holdings | $1,191,288 (>$1M) |
| Deep LLM lock | NOT present |
| Active deep job | NONE |

## Model Inventory

| Model | Installed | Resident | VRAM |
|-------|-----------|----------|------|
| qwen3:14b | YES | YES | 9.4 GB |
| nomic-embed-text | YES | YES | 0.54 GB |
| qwen3-embedding:8b | YES | NO (on disk) | ~5.67 GB when loaded |
| gemma3-overnight | YES | NO | ~17 GB when loaded |

## Deep Overnight Health
All 11 checks: PASS

## Production Embedding State
- Table: content_embeddings
- Rows: 14,787
- Model: nomic-embed-text
- Dimensions: 768
- pgvector: NOT available (jsonb storage, Python cosine)

## Preflight Verdict
**PASS** — all gates clear. Phase 2B can proceed.
