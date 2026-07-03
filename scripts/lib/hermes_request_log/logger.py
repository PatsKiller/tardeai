"""Append-only JSONL logger for /api/v2/hermes/* requests.

Used by the Outcome & Feedback Agent to compute resource_efficiency_score inputs
(hermes_api_calls_7d) without a heavy metrics stack.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
HERMES_REQUEST_LOG = PROJECT_ROOT / "state" / "hermes" / "hermes_api_requests.jsonl"
_MAX_LINES = 50_000
_RETENTION_DAYS = 30
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_hermes_request(
    endpoint: str,
    method: str = "GET",
    latency_ms: int | float | None = None,
    status: int | None = None,
    tokens_estimate: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one Hermes API request record (non-blocking, best-effort)."""
    ts = _now_iso()
    row = {
        "ts": ts,
        "timestamp": ts,  # alias for external tooling / v1.1 schema
        "endpoint": str(endpoint).split("?")[0],
        "method": method.upper(),
        "latency_ms": int(latency_ms) if latency_ms is not None else None,
        "duration_ms": int(latency_ms) if latency_ms is not None else None,
        "status": status,
        "status_code": status,
        "tokens_estimate": tokens_estimate,
        "tokens": tokens_estimate,
    }
    if extra:
        row.update(extra)
    try:
        with _lock:
            HERMES_REQUEST_LOG.parent.mkdir(parents=True, exist_ok=True)
            with HERMES_REQUEST_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
            _maybe_trim()
    except Exception:
        pass


def _maybe_trim() -> None:
    """Keep log bounded: retention window + max line count."""
    if not HERMES_REQUEST_LOG.exists():
        return
    try:
        lines = HERMES_REQUEST_LOG.read_text(encoding="utf-8").splitlines()
        if len(lines) <= _MAX_LINES:
            cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
            kept = []
            for line in lines:
                try:
                    row = json.loads(line)
                    ts = datetime.fromisoformat(str(row.get("ts", "")).replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= cutoff:
                        kept.append(line)
                except Exception:
                    kept.append(line)
            if len(kept) < len(lines):
                HERMES_REQUEST_LOG.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            return
        HERMES_REQUEST_LOG.write_text("\n".join(lines[-_MAX_LINES:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def aggregate_request_stats(days: int = 7) -> dict[str, Any]:
    """Roll up JSONL log for the feedback agent (7d window by default)."""
    days = max(1, min(int(days), 90))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    if not HERMES_REQUEST_LOG.exists():
        return {
            "measurement_window_days": days,
            "hermes_api_calls": 0,
            "hermes_api_estimated_tokens": 0,
            "endpoints_top": [],
            "notes": "no_log_yet",
        }

    by_endpoint: dict[str, int] = {}
    total = 0
    tokens = 0
    try:
        for line in HERMES_REQUEST_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                raw_ts = row.get("ts") or row.get("timestamp") or ""
                ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
                ep = str(row.get("endpoint") or "unknown")
                by_endpoint[ep] = by_endpoint.get(ep, 0) + 1
                total += 1
                tok = row.get("tokens_estimate") if row.get("tokens_estimate") is not None else row.get("tokens")
                if tok is not None:
                    tokens += int(tok)
            except Exception:
                continue
    except Exception:
        return {"measurement_window_days": days, "hermes_api_calls": 0, "notes": "read_error"}

    top = sorted(by_endpoint.items(), key=lambda x: -x[1])[:8]
    return {
        "measurement_window_days": days,
        "hermes_api_calls": total,
        "hermes_api_estimated_tokens": tokens or None,
        "endpoints_top": [{"endpoint": ep, "count": n} for ep, n in top],
        "notes": "hermes_api_requests.jsonl",
    }