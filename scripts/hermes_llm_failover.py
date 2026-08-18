"""Governed DeepSeek Flash / Ollama JSON chat for overnight Hermes units.

Overnight default: Flash primary, Ollama backup.
READ_ONLY_ADVISORY. No broker, Telegram, or order language.

Provider is always labeled. It is not a silent model swap.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

# Official DeepSeek peak windows (half-open, UTC).
# https://api-docs.deepseek.com/quick_start/pricing/
# Peak: 01:00-04:00 and 06:00-10:00 UTC. All other hours are off-peak (half price).
# These are Beijing 09:00-12:00 and 14:00-18:00 — NOT US 21:00-09:00.
DEEPSEEK_PEAK_UTC = ((1, 4), (6, 10))

AUTHORITY = "READ_ONLY_ADVISORY"
DEFAULT_OLLAMA = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
DEFAULT_BRIDGE = (
    os.getenv("HERMES_BRIDGE_URL")
    or os.getenv("CIO_GOVERNED_BRIDGE_URL")
    or "http://127.0.0.1:8766"
).rstrip("/")
DEFAULT_FLASH = os.getenv("HERMES_BRIDGE_MODEL", "deepseek-v4-flash")
DEFAULT_FLASH_TIMEOUT = float(os.getenv("HERMES_FAILOVER_TIMEOUT_S", "90"))


class HermesLlmError(Exception):
    pass


def failover_enabled() -> bool:
    return os.getenv("HERMES_OLLAMA_FAILOVER", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def allow_deepseek_peak() -> bool:
    """Manual override for now-tests. Default is refuse Flash apply during official peak."""
    return os.getenv("HERMES_ALLOW_DEEPSEEK_PEAK", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def is_deepseek_offpeak(when: datetime | None = None) -> bool:
    """True outside official DeepSeek peak hours."""
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
    for start, end in DEEPSEEK_PEAK_UTC:
        if start <= hour < end:
            return False
    return True


def deepseek_window_label(when: datetime | None = None) -> str:
    return "off-peak" if is_deepseek_offpeak(when) else "peak"


def primary_provider() -> str:
    """bridge_flash (overnight default) or ollama."""
    raw = os.getenv("HERMES_LLM_PRIMARY", "bridge_flash").strip().lower()
    if raw in {"flash", "deepseek", "deepseek-flash", "bridge", "bridge_flash"}:
        return "bridge_flash"
    return "ollama"


def ollama_probe(timeout_s: float = 2.0) -> str | None:
    """Return None if /api/tags answers; else a short reason."""
    try:
        urllib.request.urlopen(f"{DEFAULT_OLLAMA}/api/tags", timeout=timeout_s)
        return None
    except Exception as exc:
        return f"ollama_unhealthy:{type(exc).__name__}"


def _extract_json_text(content: str) -> str:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if not text.startswith("{") and not text.startswith("["):
        m = re.search(r"[\{\[].*[\}\]]", text, re.S)
        if m:
            text = m.group(0)
    return text


def _ollama_chat(
    prompt: str,
    *,
    model: str,
    timeout_s: float,
    num_ctx: int,
    num_predict: int,
    temperature: float,
) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "temperature": temperature,
        },
        "format": "json",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{DEFAULT_OLLAMA}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = json.loads(resp.read().decode("utf-8", errors="replace"))
    return str((raw.get("message") or {}).get("content") or "")


def _bridge_flash_chat(prompt: str, *, timeout_s: float | None = None) -> str:
    payload = json.dumps({
        "model": DEFAULT_FLASH,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Hermes READ_ONLY research. No orders/stops language. "
                    "Reply with JSON only (no markdown)."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "max_tokens": int(os.getenv("HERMES_FAILOVER_MAX_TOKENS", "4096")),
        "temperature": 0.2,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{DEFAULT_BRIDGE}/v1/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-TradeAI-Agent": os.getenv("HERMES_BRIDGE_AGENT", "advisory_desk"),
            "X-TradeAI-Task-Type": os.getenv("HERMES_BRIDGE_TASK", "advisory_opinion"),
            "X-TradeAI-Process-Id": os.getenv(
                "HERMES_BRIDGE_PROCESS", "hermes_ollama_failover",
            ),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s or DEFAULT_FLASH_TIMEOUT) as resp:
        raw = json.loads(resp.read().decode("utf-8", errors="replace"))
    msg = ((raw.get("choices") or [{}])[0].get("message") or {})
    content = msg.get("content") or msg.get("reasoning_content") or ""
    return str(content)


def _pack(*, content: str, provider: str, model: str, failover: bool, reason: str | None) -> dict[str, Any]:
    text = _extract_json_text(content)
    if not text.strip():
        raise HermesLlmError(f"{provider}_empty_content")
    return {
        "content": text,
        "provider": provider,
        "model": model,
        "failover": failover,
        "reason": reason,
        "authority": AUTHORITY,
        "primary": primary_provider(),
    }


def chat_json(
    prompt: str,
    *,
    ollama_model: str,
    ollama_timeout_s: float,
    num_ctx: int = 8192,
    num_predict: int = 2000,
    temperature: float = 0.3,
    probe_first: bool = True,
) -> dict[str, Any]:
    """Primary provider first; labeled backup on error.

    Overnight default primary is governed DeepSeek Flash (:8766).
    Ollama is backup. Set HERMES_LLM_PRIMARY=ollama to invert.
    """
    primary = primary_provider()
    allow_backup = failover_enabled()

    def _try_flash() -> str:
        return _bridge_flash_chat(prompt)

    def _try_ollama() -> str:
        if probe_first:
            bad = ollama_probe()
            if bad:
                raise HermesLlmError(bad)
        return _ollama_chat(
            prompt,
            model=ollama_model,
            timeout_s=ollama_timeout_s,
            num_ctx=num_ctx,
            num_predict=num_predict,
            temperature=temperature,
        )

    first, second = (
        ("bridge_flash", _try_flash, DEFAULT_FLASH),
        ("ollama", _try_ollama, ollama_model),
    ) if primary == "bridge_flash" else (
        ("ollama", _try_ollama, ollama_model),
        ("bridge_flash", _try_flash, DEFAULT_FLASH),
    )

    first_name, first_fn, first_model = first
    second_name, second_fn, second_model = second
    try:
        return _pack(
            content=first_fn(),
            provider=first_name,
            model=first_model,
            failover=False,
            reason=None,
        )
    except Exception as exc:
        reason = f"{first_name}_error:{type(exc).__name__}:{exc}"[:220]
        if not allow_backup:
            raise HermesLlmError(reason) from exc
    try:
        return _pack(
            content=second_fn(),
            provider=second_name,
            model=second_model,
            failover=True,
            reason=reason,
        )
    except Exception as exc:
        raise HermesLlmError(
            f"backup_failed:{reason}|{second_name}:{type(exc).__name__}:{exc}"[:300]
        ) from exc
