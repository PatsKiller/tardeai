"""Momentum-scalp hot tier: knobs, windows, freshness SLOs and budget math (data side only).

Operator decision (4), 2026-10-10 (``CONSOLIDATION_PLAN.md`` §C, verification workspace): market days only, off
weekends and after hours —

- Finviz scalp screeners every **2 min** 06:00–09:30 ET (L636's refresh stage; L1050 keeps its 5-min pulls
  09:30–16:00 and stays the writer of ``scalp_universe_latest.json``);
- scalp-only enrichment every **5 min** through one custom-column Finviz export (owner: ``scripts/finviz_enrichment.py``);
- Hermes/SearXNG research only for names **new to the list or older than 30 min**, through the search routing
  engine (Agent V, ``n8nmat/search-routing-engine``) — never a direct provider call from the hot tier;
- StockTwits for the scalp names every **10 min** 06:00–11:00 (owner: ``scripts/social_ingest.py``);
- L246, L708 and L636's proposal stage fire on the scalp list's ``as_of`` advancing (``lib.scalp_list_trigger``);
- freshness SLOs: list ≤5 min, enrichment ≤10, research ≤30 after arrival, social ≤15.

**Nothing here sizes, orders, stops or submits.** L1050 (scalp-live) and L323's paper-submit path are not touched.

The knob is OFF by default. ``enabled()`` is True only when the process env carries ``SCALP_HOT_TIER=1`` (set on the
operator's cron lines) **and** the kill file ``<state_root>/data/runtime/SCALP_HOT_TIER_DISABLED`` is absent. With the
knob off every hot-tier code path is inert and each changed script behaves exactly as on ``main``.

Pure: no network, no DB, no writes. Stdlib only (heavy deps are never imported here).
"""

from __future__ import annotations

import os
from datetime import datetime, time
from pathlib import Path
from typing import Any, Mapping

try:
    from zoneinfo import ZoneInfo

    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = None  # type: ignore[assignment]

SCHEMA = "ScalpHotTier@v1"
ENV_FLAG = "SCALP_HOT_TIER"
KILL_FILE_NAME = "SCALP_HOT_TIER_DISABLED"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

#: the four screeners of the ``scalp`` window in assets/screeners.yaml (the same ones L1050 pulls)
DEFAULT_SCREENER_IDS = ("prime_setups", "watchlist_setups", "pm_breakout_confirmation", "pm_volume_continuation")

#: cadence knobs (minutes). Applied only when ``enabled()``; the cron/dispatcher step sets how often a lane fires.
LIST_REFRESH_MIN = 2.0
#: a */2 grid fires ~2 min after the last START, but the DONE receipt is stamped at the END of a 30-60 s refresh;
#: the hot line refreshes whenever the receipt is older than LIST_REFRESH_MIN minus this (i.e. 0.5 min)
LIST_REFRESH_GRID_TOLERANCE_MIN = 1.5
ENRICH_EVERY_MIN = 5.0
SOCIAL_EVERY_MIN = 10.0
RESEARCH_STALE_MIN = 30.0  # research a name only when it is new to the list or its last research is older
RESEARCH_CACHE_TTL_MIN = 20.0  # (subject, intent) cache TTL the routing engine must honour for scalp research
SOCIAL_SYMBOL_CAP = 25
ENRICH_SYMBOL_CAP = 100
RESEARCH_SYMBOL_CAP = 15

#: windows (ET, market days only); end is exclusive
WINDOWS: dict[str, tuple[str, str]] = {
    "list_hot": ("06:00", "09:30"),  # hot-tier screener pulls; L1050 owns 09:30-16:00
    "enrichment": ("06:00", "16:00"),
    "research": ("06:00", "16:00"),
    "social": ("06:00", "11:00"),
    "slo": ("06:00", "16:00"),
}

#: freshness SLOs in minutes: healthy <= h, late <= d, degraded <= f, failed > f (CONSOLIDATION_PLAN §C.4)
SLOS: dict[str, dict[str, float]] = {
    "scalp_list": {"healthy": 5.0, "late": 7.5, "degraded": 15.0},
    "scalp_enrichment": {"healthy": 10.0, "late": 15.0, "degraded": 30.0},
    "scalp_research": {"healthy": 30.0, "late": 45.0, "degraded": 90.0},
    "scalp_social": {"healthy": 15.0, "late": 25.0, "degraded": 45.0},
}

#: Finviz global throttle: one request per 2.5 s across every process (finviz_throttle)
FINVIZ_THROTTLE_S = 2.5
FINVIZ_WEEKLY_CEILING = int(3600 / FINVIZ_THROTTLE_S) * 24 * 7  # 241,920
#: measured / counted baseline (CONSOLIDATION_PLAN §C.3): today's Finviz traffic and L1050's share of it
FINVIZ_TODAY_PER_WEEK = 93_000
FINVIZ_AFTER_OWNERS_PER_WEEK = 6_500
SEARXNG_DAILY_CAP = 10_000  # search_budget DEFAULT_LIMITS / registry providers.searxng.budget


def _state_root() -> Path:
    try:
        from scripts.lib.canonical_store_registry import production_state_root
    except Exception:
        try:
            from lib.canonical_store_registry import production_state_root  # type: ignore
        except Exception:
            return Path.home() / "trade-ai-releases" / "persistent-state"
    try:
        return Path(production_state_root())
    except Exception:
        return Path.home() / "trade-ai-releases" / "persistent-state"


def kill_file(state_root: Path | str | None = None) -> Path:
    return Path(state_root or _state_root()) / "data" / "runtime" / KILL_FILE_NAME


def enabled(env: Mapping[str, str] | None = None, *, state_root: Path | str | None = None) -> bool:
    """True only with ``SCALP_HOT_TIER=1`` and no kill file. Default (unset) is OFF."""
    e = os.environ if env is None else env
    if str(e.get(ENV_FLAG, "")).strip() != "1":
        return False
    try:
        return not kill_file(state_root).exists()
    except OSError:
        return False  # cannot tell -> off (the conservative side: legacy behaviour)


def flag_state(env: Mapping[str, str] | None = None, *, state_root: Path | str | None = None) -> dict[str, Any]:
    e = os.environ if env is None else env
    kf = kill_file(state_root)
    try:
        killed = kf.exists()
    except OSError:
        killed = None
    return {
        "env": ENV_FLAG,
        "env_value": e.get(ENV_FLAG),
        "kill_file": str(kf),
        "kill_file_present": killed,
        "enabled": enabled(e, state_root=state_root),
    }


def now_et(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(ET) if ET else datetime.now()
    if now.tzinfo is None:
        return now.replace(tzinfo=ET) if ET else now
    return now.astimezone(ET) if ET else now


def is_market_day(now: datetime | None = None) -> bool:
    """Weekday and not a US market holiday (scripts/market_session.py, stdlib)."""
    t = now_et(now)
    if t.weekday() >= 5:
        return False
    try:
        try:
            from market_session import is_trading_day
        except ImportError:
            from scripts.market_session import is_trading_day  # type: ignore
        return bool(is_trading_day(t))
    except Exception:
        return True  # same fail-open as market_day_gate.sh: weekday is the floor


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_window(name: str, now: datetime | None = None) -> bool:
    """Market day and ``start <= t < end`` for the named window."""
    t = now_et(now)
    if not is_market_day(t):
        return False
    start, end = WINDOWS[name]
    return _hm(start) <= t.timetz().replace(tzinfo=None) < _hm(end)


def phase(now: datetime | None = None) -> dict[str, Any]:
    t = now_et(now)
    md = is_market_day(t)
    return {
        "now_et": t.isoformat(),
        "market_day": md,
        **{name: (md and in_window(name, t)) for name in WINDOWS},
    }


def scalp_screener_ids(root: Path | str | None = None) -> list[str]:
    """The ``scalp`` window's screeners from assets/screeners.yaml; the four defaults when unreadable."""
    path = Path(root or PROJECT_ROOT) / "assets" / "screeners.yaml"
    try:
        import yaml  # light dependency, already used by every screener lane

        doc = yaml.safe_load(path.read_text()) or {}
        for key in ("schedules", "windows", "slots"):
            node = doc.get(key)
            if isinstance(node, dict) and isinstance(node.get("scalp"), dict):
                ids = node["scalp"].get("active_screeners") or []
                if ids:
                    return [str(x) for x in ids]
        for node in doc.values():
            if isinstance(node, dict) and isinstance(node.get("scalp"), dict):
                ids = node["scalp"].get("active_screeners") or []
                if ids:
                    return [str(x) for x in ids]
    except Exception:
        pass
    return list(DEFAULT_SCREENER_IDS)


def slo_status(domain: str, age_min: float | None) -> str:
    """healthy / late / degraded / failed for an age in minutes (None -> failed: no data is not fresh)."""
    s = SLOS[domain]
    if age_min is None:
        return "failed"
    if age_min <= s["healthy"]:
        return "healthy"
    if age_min <= s["late"]:
        return "late"
    if age_min <= s["degraded"]:
        return "degraded"
    return "failed"


# ── budget math ───────────────────────────────────────────────────────────────


def _window_hours(name: str) -> float:
    a, b = (_hm(x) for x in WINDOWS[name])
    return (b.hour * 60 + b.minute - a.hour * 60 - a.minute) / 60.0


def budget_projection(
    *,
    screeners: int = len(DEFAULT_SCREENER_IDS),
    enrich_symbols: int = 80,
    social_symbols: int = SOCIAL_SYMBOL_CAP,
    research_names_per_hour: float = 50.0,
    queries_per_name: int = 3,
    research_cache_hit_rate: float = 0.5,
    market_days: int = 5,
) -> dict[str, Any]:
    """Projected weekly provider usage of the hot tier against each provider's ceiling.

    Finviz: the list pull is ``screeners`` exports per refresh, every LIST_REFRESH_MIN in list_hot; the enrichment
    is ceil(enrich_symbols / 20) custom-column exports every ENRICH_EVERY_MIN in the enrichment window.
    SearXNG: names new/stale per hour x queries (worst case: 25 names re-researched every 30 min = 50/h), minus the
    routing engine's 20-min (subject, intent) cache shared by L708 and L379.
    StockTwits: one stream request per scalp name every SOCIAL_EVERY_MIN in the social window.
    """
    lh = _window_hours("list_hot")
    eh = _window_hours("enrichment")
    sh = _window_hours("social")
    rh = _window_hours("research")
    list_refreshes = (60.0 / LIST_REFRESH_MIN) * lh * market_days
    enrich_batches = -(-int(enrich_symbols) // 20)
    enrich_refreshes = (60.0 / ENRICH_EVERY_MIN) * eh * market_days
    finviz_list = int(round(screeners * list_refreshes))
    finviz_enrich = int(round(enrich_batches * enrich_refreshes))
    finviz_hot = finviz_list + finviz_enrich
    # L1050 (unchanged, counted in today's figure too): 4 scalp screeners every 5 min 09:30-16:00
    finviz_l1050 = int(round(screeners * 12 * 6.5 * market_days))
    finviz_after = FINVIZ_AFTER_OWNERS_PER_WEEK + finviz_hot + finviz_l1050
    weekday_window = int(3600 / FINVIZ_THROTTLE_S) * 11 * market_days  # 06:00-17:00 weekdays
    peak_per_min = screeners / LIST_REFRESH_MIN + enrich_batches / ENRICH_EVERY_MIN
    searx_day_worst = int(round(research_names_per_hour * queries_per_name * rh))
    searx_day = int(round(searx_day_worst * (1.0 - research_cache_hit_rate)))
    st_hour = int(round(social_symbols * 60.0 / SOCIAL_EVERY_MIN))
    st_week = int(round(st_hour * sh * market_days))
    return {
        "schema": "ScalpHotTierBudget@v1",
        "assumptions": {
            "screeners": screeners,
            "enrich_symbols": enrich_symbols,
            "social_symbols": social_symbols,
            "research_names_per_hour": research_names_per_hour,
            "queries_per_name": queries_per_name,
            "research_cache_hit_rate": research_cache_hit_rate,
            "market_days": market_days,
            "windows_et": dict(WINDOWS),
        },
        "finviz": {
            "throttle_s": FINVIZ_THROTTLE_S,
            "ceiling_per_week_24x7": FINVIZ_WEEKLY_CEILING,
            "weekday_0600_1700_per_week": weekday_window,
            "hot_list_per_week": finviz_list,
            "hot_enrichment_per_week": finviz_enrich,
            "hot_tier_per_week": finviz_hot,
            "l1050_unchanged_per_week": finviz_l1050,
            "today_per_week": FINVIZ_TODAY_PER_WEEK,
            "today_pct_of_ceiling": round(100.0 * FINVIZ_TODAY_PER_WEEK / FINVIZ_WEEKLY_CEILING, 1),
            "after_owners_plus_l1050_plus_hot_per_week": finviz_after,
            "after_pct_of_ceiling": round(100.0 * finviz_after / FINVIZ_WEEKLY_CEILING, 1),
            "after_pct_of_weekday_window": round(100.0 * finviz_after / weekday_window, 1),
            "hot_tier_alone_pct_of_ceiling": round(100.0 * finviz_hot / FINVIZ_WEEKLY_CEILING, 2),
            "peak_requests_per_min": round(peak_per_min, 2),
            "throttle_requests_per_min": round(60.0 / FINVIZ_THROTTLE_S, 1),
            "headroom_x": round((60.0 / FINVIZ_THROTTLE_S) / peak_per_min, 1) if peak_per_min else None,
            "within_ceiling": finviz_after < FINVIZ_WEEKLY_CEILING,
        },
        "searxng": {
            "via": "search routing engine (Agent V) — hot tier never calls SearXNG/Brave directly",
            "daily_cap": SEARXNG_DAILY_CAP,
            "worst_case_per_day_no_cache": searx_day_worst,
            "expected_per_day_with_cache": searx_day,
            "per_week_expected": searx_day * market_days,
            "pct_of_daily_cap_worst": round(100.0 * searx_day_worst / SEARXNG_DAILY_CAP, 1),
            "within_cap": searx_day_worst < SEARXNG_DAILY_CAP,
        },
        "stocktwits": {
            "per_hour_in_window": st_hour,
            "per_week": st_week,
            "provider_limit": "UNDECLARED in config/data_source_authority.json (decision D.14)",
        },
    }
