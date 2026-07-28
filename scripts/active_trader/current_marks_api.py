"""Timestamped current marks for scanner candidates and visible ActiveTrader symbols.

Fresh dedicated-gateway marks have explicit priority. Missing/stale symbols fall back to one
batch read from the approved ticker_prices provider. Sources are never averaged.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Iterable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "active-trader-current-marks-v1"
_DEFAULT_FUTURE_SKEW_MS = 1_000.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _symbols(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        symbol = str(value or "").strip().upper().replace("US.", "")
        if symbol and symbol not in result and len(symbol) <= 20:
            result.append(symbol)
    return result[:100]


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _mark_age_ms(
    value: Any,
    now: datetime,
    *,
    max_future_skew_ms: Optional[float] = None,
) -> Optional[float]:
    """Return a non-negative age, failing closed on invalid/materially future timestamps."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        delta_ms = (now - parsed.astimezone(timezone.utc)).total_seconds() * 1000.0
    except (TypeError, ValueError):
        return None
    allowed = (
        _env_float("ACTIVE_TRADER_MAX_FUTURE_SKEW_MS", _DEFAULT_FUTURE_SKEW_MS)
        if max_future_skew_ms is None
        else max(0.0, float(max_future_skew_ms))
    )
    if delta_ms < -allowed:
        return None
    return max(0.0, delta_ms)


def _approved_batch(symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    try:
        import sys

        scripts_path = str(_REPO_ROOT / "scripts")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        from db_adapter import get_connection
    except Exception:
        return {}
    output: dict[str, dict[str, Any]] = {}
    try:
        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT DISTINCT ON (symbol) symbol, bid, ask, price, updated_at
                   FROM ticker_prices
                   WHERE symbol = ANY(%s)
                   ORDER BY symbol, updated_at DESC""",
                (symbols,),
            )
            stale_after_ms = _env_float("ACTIVE_TRADER_CURRENT_MARK_STALE_MS", 6000.0)
            now = datetime.now(timezone.utc)
            for symbol, bid, ask, price, updated_at in cursor.fetchall():
                at = updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at
                age_ms = _mark_age_ms(at, now)
                stale = age_ms is None or age_ms > stale_after_ms
                has_value = price is not None or bid is not None or ask is not None
                output[str(symbol).upper()] = {
                    "symbol": str(symbol).upper(),
                    "bid": float(bid) if bid is not None else None,
                    "ask": float(ask) if ask is not None else None,
                    "last": float(price) if price is not None else None,
                    "source": "approved_ticker_prices",
                    "provider_at": at,
                    "received_at": at,
                    "age_ms": age_ms,
                    "available": bool(has_value and not stale),
                    "stale": stale,
                    "fallback": True,
                }
    except Exception:
        return {}
    return output


def current_marks_payload(symbols: Iterable[str], *, client=None, approved_batch=None) -> dict[str, Any]:
    wanted = _symbols(symbols)
    if client is None:
        try:
            from moomoo.gateway_ipc import SnapshotClient
        except ImportError:  # pragma: no cover
            from scripts.moomoo.gateway_ipc import SnapshotClient  # type: ignore
        client = SnapshotClient()
    read = client.read()
    snapshot_marks = ((read.payload or {}).get("current_marks") or {}) if read.fresh else {}
    marks: dict[str, dict[str, Any]] = {}
    fallback_needed: list[str] = []
    for symbol in wanted:
        raw = snapshot_marks.get(symbol)
        if isinstance(raw, dict) and raw.get("available") and not raw.get("stale"):
            marks[symbol] = {**raw, "symbol": symbol, "fallback": False}
        else:
            fallback_needed.append(symbol)
    fallback = (approved_batch or _approved_batch)(fallback_needed)
    for symbol in fallback_needed:
        raw = fallback.get(symbol)
        marks[symbol] = raw or {
            "symbol": symbol,
            "bid": None,
            "ask": None,
            "last": None,
            "source": None,
            "provider_at": None,
            "received_at": None,
            "available": False,
            "stale": True,
            "fallback": True,
        }
    ordered = [marks[symbol] for symbol in wanted]
    return {
        "contract": CONTRACT,
        "read_only": True,
        "write": False,
        "order_path": False,
        "generated_at": _now_iso(),
        "requested_symbols": wanted,
        "marks": ordered,
        "mark_count": sum(1 for mark in ordered if mark.get("available")),
        "snapshot_fresh": read.fresh,
        "snapshot_reason": read.reason,
        "snapshot_age_seconds": read.age_seconds,
        "source_priority": ["fresh_moomoo_gateway", "approved_ticker_prices"],
        "note": "Current marks are separate from immutable scanner scan-time snapshots; sources are never averaged.",
        "authority": {
            "mutation": False,
            "order": False,
            "session_authorize": False,
            "canary": False,
            "financial_action": False,
        },
    }
