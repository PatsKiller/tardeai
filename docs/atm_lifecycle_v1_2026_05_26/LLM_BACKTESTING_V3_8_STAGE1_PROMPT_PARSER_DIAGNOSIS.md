# v3.8 Stage 1 Prompt/Parser Diagnosis

**Date:** 2026-05-28

## Root Cause Classification: **Token Cap + No JSON Mode + No Parser**

### Issue 1: Token cap too low (PRIMARY)
- `local_llm.py` `_try_ollama()` uses `"num_predict": 300`
- The v1 prompt injects full trade JSON, proposal JSON, stop audit JSON, TCA JSON
- After filling those placeholders, the prompt is ~2000+ tokens of input
- 300 output tokens is insufficient for a structured JSON response with 12+ fields
- Result: model returns empty string or truncated response
- Evidence: `"model_output_preview": "empty"` in dry-run log

### Issue 2: No Ollama JSON format mode
- Ollama supports `"format": "json"` to force valid JSON output
- v1 did not use this — relied only on prompt instruction "Provide ONLY valid JSON"
- qwen3:14b without format constraint may return markdown, prose, or mixed output

### Issue 3: `think: False` suppresses qwen3 reasoning
- qwen3 uses chain-of-thought by default; `think: False` disables it
- For structured analysis, thinking mode helps produce better assessments
- However, thinking tokens count against num_predict, making the cap worse
- Decision: keep `think: False` for v2 but increase num_predict significantly

### Issue 4: No response parser in analyzer
- `trade_close_llm_analyzer.py` v3.8 stores raw model output as-is
- No JSON extraction from markdown fences
- No validation of required keys
- No fallback for partial responses
- `output_payload` stored as raw string, not parsed JSON
- Assessment columns (`thesis_assessment`, `execution_assessment`, etc.) never populated
  because the analyzer never maps parsed JSON fields to DB columns

### Issue 5: v1 prompt too broad
- Single-line JSON template with `"..."` placeholders is ambiguous
- No explicit field descriptions or constraints
- No example of expected output length per field
- No null-safety instructions for missing data

## Affected Fields (All NULL in v1 rows)
- `thesis_assessment`
- `execution_assessment`
- `stop_assessment`
- `tca_assessment`
- `lessons`
- `confidence`
- `data_quality_gaps`
- `output_payload` (empty — 0 length)

## What Worked in v1
- Input snapshot construction (`_build_input`)
- Input hash generation (deterministic, reproducible)
- Safety gates (ALPACA_MODE, no broker writes)
- Human-written `summary` field

## Proposed Fixes for v2

1. **Increase num_predict**: Pass `num_predict=2048` via analyzer (not changing global default)
2. **Use Ollama JSON format mode**: Add `"format": "json"` to Ollama request
3. **Stricter prompt**: Explicit field descriptions, max lengths, null defaults
4. **Parser**: Extract JSON from fences, validate keys, fill defaults, classify quality
5. **Column mapping**: Map parsed JSON fields to `thesis_assessment`, `execution_assessment`, etc.
6. **Quality classification**: `meaningful_structured_review`, `partial_review`, `empty_shell`, `model_error`
