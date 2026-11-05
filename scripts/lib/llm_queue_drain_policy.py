"""When the deep overnight LLM queue may drain, which lanes it may use, and which jobs are worth running.

Pure policy over config/llm_queue_drain.json. It schedules nothing and calls no model.

Operator 2026-10-31: weekends and market holidays drain all day; trading days drain 21:00-04:00 ET; budget
ceilings stay; DeepSeek only outside its billing peak (scripts/lib/deepseek_offpeak.py).
AUTHORITY: READ_ONLY_ADVISORY · MBI_BEHAVIOR=0.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "llm_queue_drain.json"
ET = ZoneInfo("America/New_York")


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _is_trading_day(now: datetime) -> bool:
    try:
        from scripts.market_session import is_trading_day
    except ImportError:  # pragma: no cover - scripts/ on sys.path
        from market_session import is_trading_day  # type: ignore
    return bool(is_trading_day(now))


def _is_deepseek_peak(now: datetime) -> bool:
    try:
        from scripts.lib.deepseek_offpeak import is_deepseek_peak_utc
    except ImportError:  # pragma: no cover
        from lib.deepseek_offpeak import is_deepseek_peak_utc  # type: ignore
    return bool(is_deepseek_peak_utc(now))


def window_state(
    now: Optional[datetime] = None,
    policy: Optional[dict] = None,
    *,
    is_trading_day: Optional[Callable[[datetime], bool]] = None,
) -> dict[str, Any]:
    """{"unrestricted": bool, "reason": str}. Unrestricted = continuous drain allowed now."""
    pol = policy or load_policy()
    now = now or datetime.now(timezone.utc)
    et = now.astimezone(ET)
    win = pol["unrestricted_windows"]
    trading = (is_trading_day or _is_trading_day)(now)
    if not trading and win.get("non_trading_days_all_day"):
        return {"unrestricted": True, "reason": "non_trading_day"}
    night = win.get("trading_day_night_et") or {}
    start, end = int(night.get("start_hour", 24)), int(night.get("end_hour", 0))
    if et.hour >= start or et.hour < end:
        return {"unrestricted": True, "reason": f"night_{start:02d}-{end:02d}_et"}
    return {"unrestricted": False, "reason": "trading_day_hours"}


def provider_chain(
    now: Optional[datetime] = None,
    policy: Optional[dict] = None,
    *,
    is_deepseek_peak: Optional[Callable[[datetime], bool]] = None,
) -> list[str]:
    """Lanes in order; DeepSeek lanes dropped inside DeepSeek's billing peak."""
    pol = policy or load_policy()
    now = now or datetime.now(timezone.utc)
    peak = (is_deepseek_peak or _is_deepseek_peak)(now)
    ds = set(pol.get("deepseek_lanes") or [])
    return [lane for lane in pol["provider_order"] if not (peak and lane in ds)]


def triage_filter_sql(policy: Optional[dict] = None) -> tuple[str, list[Any]]:
    """SQL predicate (on alias-free deep_overnight_llm_queue columns) selecting jobs worth paying for."""
    pol = policy or load_policy()
    parts, params = [], []
    for job_type, rule in sorted((pol.get("triage") or {}).get("runnable_job_types", {}).items()):
        days = int(rule.get("symbol_snapshot_within_days") or 0)
        if days > 0:
            parts.append(
                "(job_type = %s AND EXISTS (SELECT 1 FROM ticker_snapshot_daily s "
                "WHERE s.symbol = deep_overnight_llm_queue.symbol AND s.snapshot_date >= current_date - %s))"
            )
            params += [job_type, days]
        else:
            parts.append("(job_type = %s)")
            params.append(job_type)
    if not parts:
        return "FALSE", []
    return "(" + " OR ".join(parts) + ")", params
