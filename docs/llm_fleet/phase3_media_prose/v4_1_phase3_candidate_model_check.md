# Phase 3 — Candidate Model Check

**Date:** 2026-05-14

## Candidate

`gemma4:e4b` — documented in LLM Fleet Strategy v4.1 Final, Section "Phase 3 — Media/Content"

## Installation Status

**NOT INSTALLED**

```
$ ollama list | grep gemma4
(no output)
```

## Expected Specs

| Metric | Value |
|--------|-------|
| Model | gemma4:e4b |
| Disk | ~3-4 GB |
| VRAM | ~3-4 GB Q4 |
| Can coexist with qwen3:14b | Yes (~13-14 GB total, fits 16 GB) |
| Context | TBD after pull |
| Architecture | Dense (not MoE) |

## Pull Command

```bash
ollama pull gemma4:e4b
```

## Recommendation

**Approve pull `gemma4:e4b` for Phase 3 media/prose pilot.**

Do not pull without operator approval.

## What Happens After Pull

1. Verify disk/VRAM impact
2. Run smoke tests (summarize, rewrite, classify, extract facts)
3. Compare against qwen3:14b baseline for content workflows
4. Evaluate coexistence with production models
5. Create pilot wrapper if quality is acceptable
