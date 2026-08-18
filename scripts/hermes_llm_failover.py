"""Ollama-first JSON chat with governed DeepSeek Flash failover.

Used by overnight Hermes units that currently die on gemma3 timeout/SSL.
READ_ONLY_ADVISORY. No broker, Telegram, or order language.

Failover is labeled. It is not a silent model swap.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

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
    """Ollama first; on unhealthy/timeout/error, governed Flash.

    Returns content plus explicit provider labels. Never invents JSON.
    """
    reason: str | None = None
    if failover_enabled() and probe_first:
        reason = ollama_probe()
    if reason is None:
        try:
            content = _ollama_chat(
                prompt,
                model=ollama_model,
                timeout_s=ollama_timeout_s,
                num_ctx=num_ctx,
                num_predict=num_predict,
                temperature=temperature,
            )
            text = _extract_json_text(content)
            if not text.strip():
                raise HermesLlmError("ollama_empty_content")
            return {
                "content": text,
                "provider": "ollama",
                "model": ollama_model,
                "failover": False,
                "reason": None,
                "authority": AUTHORITY,
            }
        except Exception as exc:
            reason = f"ollama_error:{type(exc).__name__}:{exc}"[:220]
            if not failover_enabled():
                raise HermesLlmError(reason) from exc
    try:
        content = _bridge_flash_chat(prompt)
        text = _extract_json_text(content)
        if not text.strip():
            raise HermesLlmError("flash_empty_content")
        return {
            "content": text,
            "provider": "bridge_flash",
            "model": DEFAULT_FLASH,
            "failover": True,
            "reason": reason,
            "authority": AUTHORITY,
        }
    except Exception as exc:
        raise HermesLlmError(
            f"failover_failed:{reason}|{type(exc).__name__}:{exc}"[:300]
        ) from exc
