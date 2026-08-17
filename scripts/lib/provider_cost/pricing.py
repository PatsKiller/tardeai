"""Effective-dated pricing. Never apply a later table retroactively."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PRICE_UNKNOWN = "PRICE_UNKNOWN"

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SCHEDULES = _ROOT / "config" / "provider_pricing_schedules.json"
_SCRIPTS_FALLBACK = Path(__file__).resolve().parent / "fixtures" / "provider_pricing_schedules.json"


class PriceUnknownError(ValueError):
    pass


def parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_schedules(path: Path | None = None) -> list[dict[str, Any]]:
    candidates = []
    if path:
        candidates.append(Path(path))
    else:
        candidates.extend([_DEFAULT_SCHEDULES, _SCRIPTS_FALLBACK])
    for p in candidates:
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            return list(data.get("schedules") or [])
    raise FileNotFoundError(f"pricing schedules not found in {candidates}")


def _in_window(dt: datetime, start: str, end: Optional[str]) -> bool:
    t = parse_dt(dt)
    if t < parse_dt(start):
        return False
    if end and t >= parse_dt(end):
        return False
    return True


def resolve_schedule(
    *,
    provider: str,
    model: str,
    at: Any,
    schedules: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    rows = schedules if schedules is not None else load_schedules()
    model_l = str(model or "").split("[", 1)[0]
    hits = [
        s
        for s in rows
        if s.get("provider") == provider
        and str(s.get("model") or "").split("[", 1)[0] == model_l
        and _in_window(at, s["effective_from"], s.get("effective_to"))
    ]
    if not hits:
        raise PriceUnknownError(f"{PRICE_UNKNOWN}: {provider}/{model} at {at}")
    hits.sort(key=lambda s: s["effective_from"], reverse=True)
    return hits[0]


def is_peak(dt: Any, schedule: dict[str, Any]) -> bool:
    if not schedule.get("peak_enabled"):
        return False
    minutes = parse_dt(dt).hour * 60 + parse_dt(dt).minute
    for start, end in schedule.get("peak_windows_utc_half_open") or ():
        if start <= minutes < end:
            return True
    return False


def calculate_usd(
    *,
    provider: str,
    model: str,
    at: Any,
    cache_hit_input: int = 0,
    cache_miss_input: int = 0,
    output: int = 0,
    schedules: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    try:
        sched = resolve_schedule(provider=provider, model=model, at=at, schedules=schedules)
    except PriceUnknownError as exc:
        return {
            "calculated_cost_usd": None,
            "cost_source": PRICE_UNKNOWN,
            "price_schedule_id": None,
            "reason": str(exc),
        }
    if sched.get("peak_enabled"):
        band = "peak" if is_peak(at, sched) else "off_peak"
        prices = sched.get(band) or {}
    else:
        prices = {
            "input_cache_hit": sched.get("input_cache_hit"),
            "input_cache_miss": sched.get("input_cache_miss"),
            "output": sched.get("output"),
        }
    usd = (
        int(cache_hit_input or 0) / 1_000_000 * float(prices.get("input_cache_hit") or 0)
        + int(cache_miss_input or 0) / 1_000_000 * float(prices.get("input_cache_miss") or 0)
        + int(output or 0) / 1_000_000 * float(prices.get("output") or 0)
    )
    return {
        "calculated_cost_usd": round(usd, 8),
        "cost_source": "LOCAL_CALCULATED",
        "price_schedule_id": sched.get("schedule_id"),
        "band": "peak" if is_peak(at, sched) else "off_peak" if sched.get("peak_enabled") else "flat",
    }
