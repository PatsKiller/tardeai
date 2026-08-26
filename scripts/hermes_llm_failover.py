"""Governed cloud JSON chat for Hermes advisory research.

The historical module name is retained for import compatibility. Local generative
fallback was retired: bridge failure is now a hard, labeled failure.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any

DEEPSEEK_PEAK_UTC = ((1, 4), (6, 10))
AUTHORITY = "READ_ONLY_ADVISORY"
DEFAULT_BRIDGE = (
    os.getenv("HERMES_BRIDGE_URL")
    or os.getenv("CIO_GOVERNED_BRIDGE_URL")
    or "http://127.0.0.1:8766"
).rstrip("/")
DEFAULT_FLASH = os.getenv("HERMES_BRIDGE_MODEL", "deepseek-v4-flash")
DEFAULT_FLASH_TIMEOUT = float(os.getenv("HERMES_CLOUD_TIMEOUT_S", "90"))


class HermesLlmError(Exception):
    pass


def failover_enabled() -> bool:
    """Compatibility signal: local generative failover is permanently disabled."""
    return False


def allow_deepseek_peak() -> bool:
    return os.getenv("HERMES_ALLOW_DEEPSEEK_PEAK", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def is_deepseek_offpeak(when: datetime | None = None) -> bool:
    try:
        from lib.deepseek_offpeak import is_bulk_deepseek_window
        return is_bulk_deepseek_window(when)
    except Exception:
        dt = when or datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        hour = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
        return not any(start <= hour < end for start, end in DEEPSEEK_PEAK_UTC)


def deepseek_window_label(when: datetime | None = None) -> str:
    return "bulk-et-10-21" if is_deepseek_offpeak(when) else "as-needed-only"


def primary_provider() -> str:
    """The only permitted generative provider for this module."""
    return "bridge_flash"


def _extract_json_text(content: str) -> str:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if not text.startswith(("{", "[")):
        match = re.search(r"[\{\[].*[\}\]]", text, re.S)
        if match:
            text = match.group(0)
    return text


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
        "max_tokens": int(os.getenv("HERMES_CLOUD_MAX_TOKENS", "4096")),
        "temperature": 0.2,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{DEFAULT_BRIDGE}/v1/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-TradeAI-Agent": os.getenv("HERMES_BRIDGE_AGENT", "advisory_desk"),
            "X-TradeAI-Task-Type": os.getenv("HERMES_BRIDGE_TASK", "advisory_opinion"),
            "X-TradeAI-Process-Id": os.getenv(
                "HERMES_BRIDGE_PROCESS", "hermes_cloud_json",
            ),
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_s or DEFAULT_FLASH_TIMEOUT) as response:
        raw = json.loads(response.read().decode("utf-8", errors="replace"))
    message = ((raw.get("choices") or [{}])[0].get("message") or {})
    return str(message.get("content") or message.get("reasoning_content") or "")


def chat_json(
    prompt: str,
    *,
    cloud_timeout_s: float | None = None,
    **legacy_local_options: Any,
) -> dict[str, Any]:
    """Call the governed cloud bridge; never invoke a local generative runtime.

    Legacy local arguments are rejected so stale service configuration cannot
    silently preserve the retired capability.
    """
    if legacy_local_options:
        names = ",".join(sorted(legacy_local_options))
        raise HermesLlmError(f"local_generative_options_forbidden:{names}")
    try:
        content = _bridge_flash_chat(prompt, timeout_s=cloud_timeout_s)
    except Exception as exc:
        raise HermesLlmError(
            f"bridge_flash_error:{type(exc).__name__}:{exc}"[:300]
        ) from exc
    text = _extract_json_text(content)
    if not text:
        raise HermesLlmError("bridge_flash_empty_content")
    return {
        "content": text,
        "provider": "bridge_flash",
        "model": DEFAULT_FLASH,
        "failover": False,
        "reason": None,
        "authority": AUTHORITY,
        "primary": primary_provider(),
    }
