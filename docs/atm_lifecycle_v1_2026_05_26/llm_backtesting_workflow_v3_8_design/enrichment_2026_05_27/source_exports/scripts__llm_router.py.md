# Source: scripts/llm_router.py (23709 bytes)
```python
#!/usr/bin/env python3
"""llm_router.py — Smart LLM routing with fallback hierarchy.

Routes requests through provider chain. Task-aware routing.
Logs everything for cost/quality tracking.

═══ PROVIDER CHAIN (May 2026 — GPU testing phase) ═══════════════════════════

  LOCAL qwen3:1.7b  →  GROK (xAI)  →  CLAUDE (Anthropic)  →  OPENAI

Provider   Speed      Cost/1K   Quality    Best For
─────────  ─────────  ────────  ─────────  ────────────────────────────────
Local      Fast       Free      Medium     Routine batch, overnight, tagging
Grok       Very fast  ~$0.01    Good       Agent analyses, debates, sector alerts
                                           *** PRIMARY TESTING PROVIDER ***
Claude     Medium     ~$1.00    Best       Retirement, disability, Roth, CIO synthesis
OpenAI     Fast       ~$0.50    Good       Last resort only

═══ GPU UPGRADE FAILBACK PLAN ════════════════════════════════════════════════

When qwen3:14b is installed on GPU:
  1. Set LOCAL_MODEL = "qwen3:14b" in this file OR set in .env:
       echo "LOCAL_MODEL=qwen3:14b" >> .env
  2. Grok auto-demotes from primary testing → fallback (code below handles this)
  3. Local handles: agent_narrative, agent_debate, sector_correlation, sentiment
  4. Claude remains for: cio_synthesis, retirement, disability (always best)
  5. Verify: python3 scripts/llm_router.py --test

  REVERT if GPU fails: set LOCAL_MODEL=qwen3:1.7b — Grok auto-promotes back.
  No other changes needed. Single-line failback.

═══ TASK ROUTING ════════════════════════════════════════════════════════════

  Pre-GPU (qwen3:1.7b):          local → grok → claude
  Post-GPU (qwen3:14b):          local → claude → grok
  Retirement/disability:         claude → grok → local (always Claude-first)
  Sector correlation/debate:     grok → local → claude (Grok fast + good reasoning)

Usage:
    from llm_router import get_llm_response
    result = get_llm_response("agent_narrative", prompt, high_impact=False)
    result = get_llm_response("agent_debate", prompt, high_impact=True)
"""
import json, os, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Configuration ──────────────────────────────────────────────────────────

LOCAL_TIMEOUT = 90      # seconds — qwen3:14b agent prompts with RAG context need 60-90s on Intel Arc B580
CONFIDENCE_THRESHOLD = 0.65

from local_llm_config import get_local_llm_model, get_local_llm_base_url, apply_ollama_runtime_env

apply_ollama_runtime_env()

LOCAL_MODEL = get_local_llm_model()

LOCAL_URL = get_local_llm_base_url().rstrip("/") + "/api/chat"
DAILY_BUDGET_LIMIT = 1.50  # USD/day — allows cloud fallback when Ollama offline (typical spend ~$0.02/day)

# ── Task routing — auto-adjusts based on LOCAL_MODEL ─────────────────────

# Pre-GPU routing: Grok is primary cloud (local quality limited)
_TASK_ROUTING_PRE_GPU = {
    "agent_narrative":          ["local", "grok", "claude"],
    "agent_debate":             ["local", "grok", "claude"],
    "sector_correlation":       ["grok", "local", "claude"],
    "cio_synthesis":            ["local", "claude", "grok", "openai"],
    "catalyst_classification":  ["local", "grok"],
    "sentiment":                ["local", "grok"],
    "code_generation":          ["claude", "openai"],
    "fast_summary":             ["local"],
    "default":                  ["local", "grok", "claude", "openai"],
}

# Post-GPU routing: local is high quality, Grok demoted to fallback
_TASK_ROUTING_POST_GPU = {
    "agent_narrative":          ["local", "claude", "grok"],
    "agent_debate":             ["local", "claude", "grok"],
    "sector_correlation":       ["local", "grok", "claude"],
    "cio_synthesis":            ["local", "claude", "grok", "openai"],
    "catalyst_classification":  ["local", "grok"],
    "sentiment":                ["local"],
    "code_generation":          ["claude", "openai"],
    "fast_summary":             ["local"],
    "default":                  ["local", "claude", "grok", "openai"],
}

# High-impact always prefers Claude, regardless of GPU state
_HIGH_IMPACT_ROUTING = {
    "cio_synthesis":        ["claude", "grok", "openai"],
    "agent_narrative":      ["grok", "claude", "local"],
    "agent_debate":         ["grok", "claude", "local"],
    "sector_correlation":   ["grok", "claude", "local"],
    "default":              ["claude", "grok", "local", "openai"],
}

```
