"""Lightweight JSONL request logger for /api/v2/hermes/* endpoints.

Delegates to hermes_request_log (single log file: state/hermes/hermes_api_requests.jsonl).
"""
from __future__ import annotations

from typing import Any, Optional

from lib.hermes_request_log.logger import (
    HERMES_REQUEST_LOG as LOG_PATH,
    aggregate_request_stats,
    log_hermes_request as _log_impl,
)


def log_hermes_request(
    endpoint: str,
    method: str = "GET",
    status_code: int = 200,
    tokens: int = 0,
    duration_ms: int = 0,
    user: Optional[str] = None,
    **extra: Any,
) -> None:
    """Append one Hermes API request (best-effort, non-blocking)."""
    payload = dict(extra) if extra else {}
    if user:
        payload["user"] = user
    _log_impl(
        endpoint=endpoint,
        method=method,
        latency_ms=duration_ms or None,
        status=status_code,
        tokens_estimate=tokens or None,
        extra=payload or None,
    )


__all__ = ["LOG_PATH", "aggregate_request_stats", "log_hermes_request"]