# v3.8 Stage 1 Close-Analysis v2 Implementation Report

**Date:** 2026-05-28

## Summary
Prompt, parser, and analyzer hardened for v2 close analysis. GPU/Vulkan corruption prevents
actual model inference — code is complete and validated, v2 review generation blocked on
Ollama restart.

## Files Changed
- `scripts/trade_close_llm_analyzer.py` (v4.0 -> v4.1)
- `scripts/prompts/llm_backtesting_close_analysis_v2.md` (new)
- `docs/atm_lifecycle_v1_2026_05_26/LLM_BACKTESTING_V3_8_STAGE1_PROMPT_PARSER_DIAGNOSIS.md` (new)
- `docs/atm_lifecycle_v1_2026_05_26/LLM_BACKTESTING_V3_8_STAGE1_V2_QUALITY_AUDIT.md` (new)

## Prompt v2 Created: YES
- Path: `scripts/prompts/llm_backtesting_close_analysis_v2.md`
- Stricter: JSON-only, no markdown, no prose
- Explicit field descriptions with max 200 char constraint
- Null-safe: all fields required with null/empty-array defaults
- Facts vs inferences separation enforced
- Safety language: analysis only, no orders/stops/strategy changes

## Parser Hardened: YES
Changes to `trade_close_llm_analyzer.py`:
1. **`_extract_json()`**: 3-tier extraction (pure JSON, markdown fences, brace matching)
2. **`_validate_and_fill()`**: Required key check + optional default filling
3. **`_classify_quality()`**: 5 classifications:
   - `meaningful_structured_review` — summary + 2+ assessments + lessons
   - `partial_review` — some fields but incomplete
   - `missing_data` — 3+ required fields missing
   - `empty_shell` — JSON parse failed
   - `model_error` — empty response or exception
4. **`_call_ollama_direct()`**: Direct Ollama HTTP call bypassing local_llm.py 300-token cap
   - `num_predict=2048` (vs 300)
   - `format: json` (Ollama JSON mode)
   - `think: false` (disable qwen3 chain-of-thought to save tokens)
5. **`_write_review_row()`**: Full column mapping:
   - `thesis_assessment`, `execution_assessment`, `stop_assessment`, `tca_assessment`
   - `strengths` (jsonb), `weaknesses` (jsonb), `lessons` (jsonb)
   - `confidence` (numeric), `data_quality_gaps` (jsonb)
   - `output_payload` (full parsed JSON)
   - Status mapped from classification

## Parser Validation: 5/5 PASS
| Test | Input | Classification |
|------|-------|---------------|
| Pure JSON (all fields) | Valid JSON object | meaningful_structured_review |
| Markdown fences (4 keys) | ```json {...} ``` | partial_review |
| Empty response | "" | model_error |
| Partial (summary only) | {"summary":"..."} | missing_data |
| Garbage text | "not json at all" | empty_shell |

## DB Write Pipeline Validation: PASS
- Test row #47 written for APPS #34 with synthetic model output
- All columns populated: thesis=TRUE, exec=TRUE, stop=TRUE, lessons=TRUE, confidence=0.75
- Row verified via SELECT, then rolled back (DELETE)

## Dry-Run No-Model: PASS
- `--dry-run --prompt-version close_analysis_v2 --paper-trade-id 34`
- No model call, no DB writes, prompt v2 selected, safety gates passed
- Same input hash as v1: `504b60ef03bf0683`

## Local LLM Dry-Run: BLOCKED
- GPU/Vulkan corruption: all models producing garbage
- qwen3:14b returns sequential digits, gemma3:4b returns Unicode garbage
- Root cause: Intel Arc B580 Vulkan driver instability
- Fix: `sudo systemctl restart ollama` (requires elevated privileges)

## v2 Stage 1 Rows Created: 0 (blocked on GPU)
- Paper trade IDs to review: 34 (APPS), 29 (NVDA), 21 (INFU), 15 (BLBD)
- v1 rows preserved (not deleted)

## v2 Quality Classification: N/A (no rows generated yet)

## Stage 2 Readiness: NOT READY
Blocked on GPU recovery. After Ollama restart:
```bash
# Validate model is working
curl -s http://127.0.0.1:11434/api/chat -d '{"model":"qwen3:14b","stream":false,"messages":[{"role":"user","content":"What is 2+2?"}],"options":{"num_predict":10}}'

# Generate v2 reviews
python3 scripts/trade_close_llm_analyzer.py \
  --apply --confirm-llm-review-write --allow-local-llm \
  --limit 4 --prompt-version close_analysis_v2 \
  --json-out logs/llm_backtesting/v3_8_stage1_v2_apply_initial_reviews.json
```

## Model/Provider
- Model: qwen3:14b (local Ollama)
- Provider: local (direct Ollama HTTP, not via local_llm.py)
- Grok called: NO
- External LLM called: NO
- Cron added: NO

## API Validation
- `/api/v2/lifecycle/llm-review-status`: OK, coverage stats include v4.0 backtest data
- `/api/v2/lifecycle/trade-llm-review?paper_trade_id=34`: Returns v1 row
- `/api/v2/lifecycle/trade-inspector?symbol=APPS`: Returns identity
- model_calls_executed_by_endpoint: false
- All endpoints read-only

## Build: PASS
- `npx vite build` successful (424ms)
- LLMBacktestingReviewPanel included in ATMControlRoom bundle

## Safety
- No orders placed
- No broker writes
- No paper_trades trade-state changes
- No proposal changes
- No journal mutations
- No backtest mutations
- No strategy changes
- No cron changes
- No v1 rows deleted or modified
- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true

## Rollback
```sql
DELETE FROM trade_llm_reviews WHERE review_stage='close_analysis' AND prompt_version='close_analysis_v2';
```
```bash
git revert <commit_hash>
```
