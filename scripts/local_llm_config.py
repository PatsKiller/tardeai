#!/usr/bin/env python3
"""Pinned local embedding configuration; local generation is retired."""

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

DEFAULT_LOCAL_LLM_MODEL = "nomic-embed-text"

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
    STANDARD:        ("", ""),
    REALTIME:        ("", ""),
    BATCH_OVERNIGHT: ("", ""),
    MEDIA_CONTENT:   ("", ""),
    EMBEDDING:       ("LLM_EMBEDDING",         "nomic-embed-text"),
    CRITICAL_CLOUD:  ("LLM_CRITICAL_CLOUD",    ""),  # must be set explicitly
    CLOUD_FALLBACK:  ("LLM_CLOUD_FALLBACK",    ""),
}


def get_model_for_process_type(process_type: str) -> str:
    """Resolve the model for a given process type from .env, with defaults."""
    env_key, default = _PROCESS_TYPE_ENV_MAP.get(process_type, ("", ""))
    if env_key:
        val = os.getenv(env_key, "").strip()
        if val:
            return val
    return default


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
        model=DEFAULT_LOCAL_LLM_MODEL,
        base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434").strip(),
        backend=os.getenv("LOCAL_LLM_BACKEND", "vulkan").strip().lower(),
        require_gpu=os.getenv("LOCAL_LLM_REQUIRE_GPU", "true").strip().lower() in {"1", "true", "yes", "on"},
        ollama_vulkan=os.getenv("OLLAMA_VULKAN", "1"),
        ggml_vk_visible_devices=os.getenv("GGML_VK_VISIBLE_DEVICES", "0"),
        flash_attention=os.getenv("OLLAMA_FLASH_ATTENTION", "1"),
        kv_cache_type=os.getenv("OLLAMA_KV_CACHE_TYPE", "q8_0"),
        max_loaded_models=os.getenv("OLLAMA_MAX_LOADED_MODELS", "1"),
        keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
    )


def apply_ollama_runtime_env() -> None:
    """
    Apply Ollama server/runtime environment for Intel Arc / Vulkan.

    These variables affect Ollama only if present in the Ollama server
    process environment. Setting them in a client script is useful for
    subprocess starts and diagnostics, but systemd service overrides are
    required for a persistent Ollama service.
    """
    cfg = get_local_llm_config()

    if cfg.provider != "ollama":
        return

    if cfg.backend == "vulkan":
        os.environ.setdefault("OLLAMA_VULKAN", cfg.ollama_vulkan or "1")
        os.environ.setdefault("GGML_VK_VISIBLE_DEVICES", cfg.ggml_vk_visible_devices or "0")

    os.environ.setdefault("OLLAMA_FLASH_ATTENTION", cfg.flash_attention or "1")
    os.environ.setdefault("OLLAMA_KV_CACHE_TYPE", cfg.kv_cache_type or "q8_0")
    os.environ.setdefault("OLLAMA_MAX_LOADED_MODELS", cfg.max_loaded_models or "1")
    os.environ.setdefault("OLLAMA_KEEP_ALIVE", cfg.keep_alive or "30m")


def get_local_llm_model() -> str:
    return get_local_llm_config().model


def get_local_llm_base_url() -> str:
    return get_local_llm_config().base_url


def get_local_llm_status() -> dict[str, Any]:
    cfg = get_local_llm_config()

    return {
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "backend": cfg.backend,
        "require_gpu": cfg.require_gpu,
        "runtime_env": {
            "OLLAMA_VULKAN": os.getenv("OLLAMA_VULKAN"),
            "GGML_VK_VISIBLE_DEVICES": os.getenv("GGML_VK_VISIBLE_DEVICES"),
            "OLLAMA_FLASH_ATTENTION": os.getenv("OLLAMA_FLASH_ATTENTION"),
            "OLLAMA_KV_CACHE_TYPE": os.getenv("OLLAMA_KV_CACHE_TYPE"),
            "OLLAMA_MAX_LOADED_MODELS": os.getenv("OLLAMA_MAX_LOADED_MODELS"),
            "OLLAMA_KEEP_ALIVE": os.getenv("OLLAMA_KEEP_ALIVE"),
        },
        "gpu_checks": {
            "vulkaninfo": {"available": shutil.which("vulkaninfo") is not None},
            "clinfo": {"available": shutil.which("clinfo") is not None},
            "intel_gpu_top": {"available": shutil.which("intel_gpu_top") is not None},
            "ollama": {"available": shutil.which("ollama") is not None},
        },
    }
