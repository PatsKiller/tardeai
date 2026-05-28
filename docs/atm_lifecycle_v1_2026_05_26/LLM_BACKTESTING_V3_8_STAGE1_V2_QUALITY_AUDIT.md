# v3.8 Stage 1 Close-Analysis v2 Quality Audit

**Date:** 2026-05-28

## Status: BLOCKED — GPU/Vulkan Corruption

### GPU Issue
All Ollama models (qwen3:14b, gemma3:4b, gemma3:27b) are producing garbage output.
- `qwen3:14b` "What is 2+2?" -> `'51234567890123456789012345678901234567890123456789'`
- `gemma3:4b` "What is 2+2?" -> `'ꯁ façon\uf04a\uf040I砝essaymxpnosság'`
- Root cause: Vulkan GPU driver instability (Arc B580, `OLLAMA_VULKAN=1`)
- Fix: Requires Ollama service restart (`sudo systemctl restart ollama`) or system reboot
- CPU fallback: Too slow for inference (300s timeout loading 4B model)

### What Was Completed
1. **Diagnosis**: Root cause of v1 failure identified (300 token cap, no JSON mode, no parser)
2. **Prompt v2**: `scripts/prompts/llm_backtesting_close_analysis_v2.md` — stricter, JSON-only, explicit field descriptions
3. **Parser**: JSON extraction from fences/prose, key validation, default filling, quality classification
4. **Quality classifier**: 5 categories (meaningful_structured_review, partial_review, missing_data, empty_shell, model_error)
5. **DB writer**: Full column mapping (thesis_assessment, execution_assessment, stop_assessment, etc.)
6. **Direct Ollama call**: Bypasses local_llm.py 300-token cap, uses num_predict=2048
7. **Parser validation**: 5/5 synthetic tests pass
8. **Write pipeline validation**: Test row #47 written and verified, then rolled back

### v2 Row Count: 0 (blocked on GPU)

### v1 vs v2 Comparison

| Field | v1 (4 rows) | v2 (0 rows, code ready) |
|-------|-------------|-------------------------|
| Prompt | close_analysis_v1 (broad, ambiguous) | close_analysis_v2 (strict, JSON-only) |
| Token cap | 300 (insufficient) | 2048 (via direct Ollama call) |
| JSON parser | None (raw string stored) | 3-tier: pure JSON, fences, brace extraction |
| Key validation | None | Required + optional with defaults |
| Column mapping | None (all NULL) | Full: thesis, execution, stop, TCA, lessons, confidence, etc. |
| Quality classification | None | meaningful_structured_review / partial / missing / shell / error |
| Model output | Empty (all 4 rows) | Pending GPU recovery |

### Stage 2 Readiness: NOT READY

No v2 rows exist yet. After GPU recovery and `sudo systemctl restart ollama`:

```bash
# Re-validate model
curl -s http://127.0.0.1:11434/api/chat -d '{"model":"qwen3:14b","stream":false,"messages":[{"role":"user","content":"What is 2+2?"}],"options":{"num_predict":10}}' | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('message',{}).get('content',''))"

# Then run v2 apply
python3 scripts/trade_close_llm_analyzer.py \
  --apply --confirm-llm-review-write --allow-local-llm \
  --limit 4 --prompt-version close_analysis_v2 \
  --json-out logs/llm_backtesting/v3_8_stage1_v2_apply_initial_reviews.json
```

### Safety
- No orders placed / No broker writes / No paper_trades changes
- No v1 rows deleted or modified
- Test row #47 was written and rolled back (clean)
- ALPACA_MODE=paper, LLM_DISABLE=true
