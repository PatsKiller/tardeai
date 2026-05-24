# Phase 2C Preflight Gates — 2026-05-14

## Safety Gates

| Gate | Result |
|------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Holdings | $1,191,263 (>$1M) |
| Deep LLM lock | NOT present |
| Active deep job | NONE |

## Model Inventory

| Model | Installed | Resident | VRAM |
|-------|-----------|----------|------|
| qwen3:14b | YES | YES | 9.4 GB |
| nomic-embed-text | YES | YES | 0.54 GB |
| qwen3-embedding:8b | YES | NO (disk) | ~5.67 GB when loaded |

## Table Counts

| Table | Rows |
|-------|------|
| content_embeddings (production) | 14,792 |
| content_embeddings_qwen3_test | 1,000 |

## Deep Overnight Health
All 11 checks: PASS

## Preflight Verdict
**PASS** — all gates clear. Phase 2C hybrid pilot can proceed.
