# Source: scripts/local_llm_config.py (6246 bytes)
```python
#!/usr/bin/env python3
"""
Trade AI v12 local LLM configuration.

Centralizes local model selection and Ollama / Intel Arc runtime settings.
All scripts should import from here instead of hardcoding model names.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

log = logging.getLogger(__name__)

DEFAULT_LOCAL_LLM_MODEL = "qwen3:14b"

# ── LLM Fleet v4.1 — Process Type Constants ──────────────────────────────
# Scripts declare intent via process type; model resolution uses .env.
# See docs/LLM_FLEET_STRATEGY_v4_1_FINAL.md Section 2.
STANDARD = "STANDARD"
REALTIME = "REALTIME"
BATCH_OVERNIGHT = "BATCH_OVERNIGHT"
MEDIA_CONTENT = "MEDIA_CONTENT"
EMBEDDING = "EMBEDDING"
CRITICAL_CLOUD = "CRITICAL_CLOUD"
CLOUD_FALLBACK = "CLOUD_FALLBACK"

# Process-type → .env variable → default model
_PROCESS_TYPE_ENV_MAP = {
    STANDARD:        ("LLM_STANDARD",         DEFAULT_LOCAL_LLM_MODEL),
    REALTIME:        ("LLM_REALTIME",          DEFAULT_LOCAL_LLM_MODEL),
    BATCH_OVERNIGHT: ("LLM_BATCH_OVERNIGHT",   DEFAULT_LOCAL_LLM_MODEL),
    MEDIA_CONTENT:   ("LLM_MEDIA_CONTENT",     DEFAULT_LOCAL_LLM_MODEL),
    EMBEDDING:       ("LLM_EMBEDDING",         "nomic-embed-text"),
    CRITICAL_CLOUD:  ("LLM_CRITICAL_CLOUD",    ""),  # must be set explicitly
    CLOUD_FALLBACK:  ("LLM_CLOUD_FALLBACK",    ""),
}


def get_model_for_process_type(process_type: str) -> str:
    """Resolve the model for a given process type from .env, with defaults."""
    env_key, default = _PROCESS_TYPE_ENV_MAP.get(process_type, ("", DEFAULT_LOCAL_LLM_MODEL))
    if env_key:
        val = os.getenv(env_key, "").strip()
        if val:
            return val
    return default or DEFAULT_LOCAL_LLM_MODEL


def get_cloud_fallback_models() -> list[str]:
    """Return ordered list of cloud fallback models from .env."""
    models = []
    for key in ("LLM_CLOUD_FALLBACK", "LLM_CLOUD_FALLBACK_2"):
        val = os.getenv(key, "").strip()
        if val:
            models.append(val)
    # Hardcoded live defaults discovered from local_llm.py
    if not models:
        oai = os.getenv("LLM_FALLBACK_OPENAI", "gpt-4o-mini").strip()
        anth = os.getenv("LLM_FALLBACK_ANTHROPIC", "claude-sonnet-4-6").strip()
        if oai: models.append(oai)
        if anth: models.append(anth)
    return models


def get_deployment_phase() -> str:
    """Return current deployment phase tag."""
    return os.getenv("LLM_DEPLOYMENT_PHASE", "v4_1_phase_0")


@dataclass(frozen=True)
class LocalLLMConfig:
    provider: str
    model: str
    base_url: str
    backend: str
    require_gpu: bool
    ollama_vulkan: Optional[str]
    ggml_vk_visible_devices: Optional[str]
    flash_attention: Optional[str]
    kv_cache_type: Optional[str]
    max_loaded_models: Optional[str]
    keep_alive: Optional[str]


def get_local_llm_config() -> LocalLLMConfig:
    return LocalLLMConfig(
        provider=os.getenv("LOCAL_LLM_PROVIDER", "ollama").strip().lower(),
        model=os.getenv("LOCAL_LLM_MODEL", DEFAULT_LOCAL_LLM_MODEL).strip() or DEFAULT_LOCAL_LLM_MODEL,
```
