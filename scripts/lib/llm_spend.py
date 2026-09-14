"""llm_spend.py — what paid AI and search actually cost, by provider, model and process.

WHY
---
Operator, 2026-09-14: "I need to see at any point the actual spend with paid APIs, which LLM it is,
a breakdown by process, cost in dollars, tokens ... daily, weekly, monthly ... which are scheduled and
which are ad hoc ... something's not adding up." Plus: "the breakdown of what ran off peak and what ran
peak. Off peak is China nighttime and weekends. Anything on a schedule should be off peak."

Three different numbers had been called "spend":
- Real: provider token usage × the effective price schedule, recorded in `llm_consumption_log`.
- Counted: what the cap system held in `llm_cost_reservations`, where failed or ambiguous calls settle
  conservatively. Test suites also wrote rows there.
- Projected: the worst case added before each call.

This module reports the REAL number and shows the counted number beside it, so a cap decision is made on
money, not on bookkeeping.

DEFINITIONS
-----------
- **Peak** is `deepseek_offpeak.DEEPSEEK_PEAK_UTC`: DeepSeek's official peak pricing hours, 01:00–04:00
  and 06:00–10:00 UTC (09:00–12:00 and 14:00–18:00 Beijing), Monday to Friday. Everything else, including
  China night and the whole weekend, is off-peak.
- **Scheduled** is `trigger_mode = 'automated'` (cron, timers, workers). **Ad hoc** is `manual` (operator
  or desk requests).
- **Paid** is a row with `estimated_cost_usd > 0`. The OAuth lanes (Grok, ChatGPT) and local models cost $0
  and are listed separately.
- **Periods** follow calendar days in America/New_York.

READ_ONLY_ADVISORY. Reads only.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SCHEMA = "LlmSpendReport@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# `%%` because these patterns are interpolated into SQL executed with bound parameters (psycopg2).
SYNTHETIC_PREFIXES = ("test\\_%%", "test-%%", "pytest\\_%%", "fixture\\_%%", "caprace\\_%%")
PERIODS = ("today", "yesterday", "week", "last_week", "month", "last_month")
CAP_FILE = Path(os.path.expanduser("~/.config/tradeai/llm_global_daily_usd_cap.env"))
SEARCH_BUDGET = PROJECT_ROOT / "data" / "runtime" / "search_budget.json"


def period_bounds(period: str, *, now: Optional[datetime] = None) -> tuple[datetime, datetime, str]:
    """[start, end) in UTC for a named period, plus a human label. Calendar days in ET. Pure."""
    now = (now or datetime.now(timezone.utc)).astimezone(ET)
    today = now.date()

    def at(d: date) -> datetime:
        return datetime.combine(d, time.min, tzinfo=ET).astimezone(timezone.utc)

    if period == "today":
        return at(today), now.astimezone(timezone.utc), f"today ({today.isoformat()}, so far)"
    if period == "yesterday":
        d = today - timedelta(days=1)
        return at(d), at(today), f"yesterday ({d.isoformat()})"
    if period == "week":
        start = today - timedelta(days=6)
        return at(start), now.astimezone(timezone.utc), f"last 7 days ({start.isoformat()} → today)"
    if period == "last_week":
        monday = today - timedelta(days=today.weekday())
        start = monday - timedelta(days=7)
        return at(start), at(monday), f"week of {start.isoformat()} (Mon–Sun)"
    if period == "month":
        start = today.replace(day=1)
        return at(start), now.astimezone(timezone.utc), f"{start:%B %Y} to date"
    if period == "last_month":
        first = today.replace(day=1)
        start = (first - timedelta(days=1)).replace(day=1)
        return at(start), at(first), f"{start:%B %Y}"
    raise ValueError(f"unknown period {period!r}; one of {PERIODS}")


def peak_sql(column: str = "created_at") -> str:
    """SQL boolean: the row falls in DeepSeek official peak hours (weekday UTC windows)."""
    try:
        from scripts.lib.deepseek_offpeak import DEEPSEEK_PEAK_UTC
    except ImportError:                                              # pragma: no cover
        from lib.deepseek_offpeak import DEEPSEEK_PEAK_UTC  # type: ignore
    hour = f"EXTRACT(HOUR FROM ({column} AT TIME ZONE 'UTC'))"
    dow = f"EXTRACT(ISODOW FROM ({column} AT TIME ZONE 'UTC'))"
    windows = " OR ".join(f"({hour} >= {int(a)} AND {hour} < {int(b)})" for a, b in DEEPSEEK_PEAK_UTC)
    return f"({dow} BETWEEN 1 AND 5 AND ({windows}))"


def provider_of(model_lane: Optional[str], model_name: Optional[str], cost: float) -> str:
    """Human provider label. Pure."""
    lane = (model_lane or "").lower()
    name = (model_name or "").lower()
    if "grok" in lane or "grok" in name:
        return "Grok (free OAuth)"
    if "chatgpt" in lane or "gpt" in name or "codex" in lane:
        return "ChatGPT (free OAuth)"
    if "local" in lane or "ollama" in lane or "gemma" in name or "qwen" in name:
        return "Local model (free)"
    if "deepseek" in name or "deepseek" in lane or lane in ("fast", "pro", "fast_think", "pro_think", "pro_max"):
        return "DeepSeek (metered)"
    return "Other (metered)" if cost > 0 else "Other (free)"


def _synthetic_filter(column: str = "process_id") -> str:
    return " AND ".join(f"{column} NOT LIKE '{p}' ESCAPE '\\'" for p in SYNTHETIC_PREFIXES)


def default_db_query(sql: str, params: Any = None) -> list[dict[str, Any]]:
    """Read-only, statement-timeout-bounded dict rows."""
    import psycopg2  # noqa: PLC0415
    import psycopg2.extras  # noqa: PLC0415

    def setting(k: str, d: str = "") -> str:
        v = os.getenv(k, "")
        if v:
            return v
        try:
            for line in (PROJECT_ROOT / ".env").read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{k}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            pass
        return d
    conn = psycopg2.connect(host=setting("DB_HOST", "localhost"), dbname=setting("DB_NAME", "trade_ai"),
                            user=setting("DB_USER", "trade_ai"), password=setting("DB_PASSWORD"),
                            options="-c default_transaction_read_only=on -c statement_timeout=15000",
                            connect_timeout=5)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def configured_global_cap() -> Optional[float]:
    """The durable host cap (one file every unit loads last). None when absent."""
    try:
        for line in CAP_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("LLM_GLOBAL_DAILY_USD_CAP="):
                return float(line.split("=", 1)[1].strip())
    except (OSError, ValueError):
        return None
    return None


def brave_requests(start: datetime, end: datetime, *, path: Optional[Path] = None) -> dict[str, Any]:
    """Brave Search requests by caller in [start, end) from the governed search budget ledger."""
    path = Path(path or SEARCH_BUDGET)  # resolved per call, so a relocated ledger is honoured
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"requests": None, "by_caller": {}, "note": "search budget ledger unreadable"}
    daily = ((doc.get("providers") or {}).get("brave") or {}).get("caller_daily") or {}
    s_day, e_day = start.astimezone(ET).date(), end.astimezone(ET).date()
    by_caller: dict[str, int] = {}
    for day, callers in daily.items():
        try:
            d = date.fromisoformat(day)
        except ValueError:
            continue
        if s_day <= d <= e_day and isinstance(callers, dict):
            for caller, n in callers.items():
                by_caller[caller] = by_caller.get(caller, 0) + int(n or 0)
    return {"requests": sum(by_caller.values()), "by_caller": by_caller,
            "note": "Brave is a paid plan billed per request; no per-request price is configured, so requests are shown, not dollars"}


def build_report(period: str, *, now: Optional[datetime] = None,
                 db_query: Callable[..., list[dict[str, Any]]] = default_db_query) -> dict[str, Any]:
    start, end, label = period_bounds(period, now=now)
    peak = peak_sql()
    synth = _synthetic_filter()
    base = f"FROM llm_consumption_log WHERE created_at >= %s AND created_at < %s AND {synth}"
    params = (start, end)
    totals = (db_query(
        f"""SELECT COUNT(*) AS calls,
                   COUNT(*) FILTER (WHERE estimated_cost_usd > 0) AS paid_calls,
                   COUNT(*) FILTER (WHERE NOT success) AS failures,
                   COALESCE(SUM(estimated_cost_usd), 0) AS usd,
                   COALESCE(SUM(tokens_in), 0) AS tokens_in, COALESCE(SUM(tokens_out), 0) AS tokens_out,
                   COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
                   COALESCE(SUM(cache_hit_tokens), 0) AS cache_hit_tokens,
                   COALESCE(SUM(estimated_cost_usd) FILTER (WHERE {peak}), 0) AS usd_peak,
                   COUNT(*) FILTER (WHERE {peak}) AS calls_peak
            {base}""", params) or [{}])[0]
    models = db_query(
        f"""SELECT model_lane, model_name, COUNT(*) AS calls, COALESCE(SUM(estimated_cost_usd), 0) AS usd,
                   COALESCE(SUM(tokens_in), 0) AS tokens_in, COALESCE(SUM(tokens_out), 0) AS tokens_out,
                   COALESCE(SUM(estimated_cost_usd) FILTER (WHERE {peak}), 0) AS usd_peak
            {base} GROUP BY model_lane, model_name ORDER BY usd DESC, calls DESC""", params)
    procs = db_query(
        f"""SELECT process_id, MAX(process_name) AS process_name, trigger_mode,
                   COUNT(*) AS calls, COUNT(*) FILTER (WHERE NOT success) AS failures,
                   COALESCE(SUM(estimated_cost_usd), 0) AS usd,
                   COALESCE(SUM(tokens_in), 0) AS tokens_in, COALESCE(SUM(tokens_out), 0) AS tokens_out,
                   COUNT(*) FILTER (WHERE {peak}) AS calls_peak,
                   COALESCE(SUM(estimated_cost_usd) FILTER (WHERE {peak}), 0) AS usd_peak,
                   STRING_AGG(DISTINCT COALESCE(model_name, model_lane), ', ') AS models,
                   MAX(created_at) AS last_call
            {base} GROUP BY process_id, trigger_mode ORDER BY usd DESC, calls DESC""", params)
    caps = {r["process_id"]: r for r in db_query(
        "SELECT process_id, category, mode, daily_soft_cap, daily_cost_cap_usd FROM llm_process_config")}
    counted = (db_query(
        f"""SELECT COALESCE(SUM(CASE WHEN status='reserved' THEN projected_usd
                                     WHEN status='settled' THEN COALESCE(actual_usd, projected_usd) ELSE 0 END), 0) AS usd
            FROM llm_cost_reservations WHERE created_at >= %s AND created_at < %s AND {synth}""", params) or [{}])[0]

    def num(v: Any) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    by_provider: dict[str, dict[str, float]] = {}
    model_rows = []
    for r in models:
        usd = num(r.get("usd"))
        prov = provider_of(r.get("model_lane"), r.get("model_name"), usd)
        agg = by_provider.setdefault(prov, {"calls": 0, "usd": 0.0, "tokens_in": 0, "tokens_out": 0, "usd_peak": 0.0})
        for k in ("calls", "tokens_in", "tokens_out"):
            agg[k] += int(num(r.get(k)))
        agg["usd"] += usd
        agg["usd_peak"] += num(r.get("usd_peak"))
        model_rows.append({"provider": prov, "model": r.get("model_name") or r.get("model_lane"), "lane": r.get("model_lane"),
                           "calls": int(num(r.get("calls"))), "usd": usd, "tokens_in": int(num(r.get("tokens_in"))),
                           "tokens_out": int(num(r.get("tokens_out"))), "usd_peak": num(r.get("usd_peak"))})
    process_rows = []
    for r in procs:
        cfg = caps.get(r["process_id"]) or {}
        scheduled = str(r.get("trigger_mode") or "").lower() == "automated"
        process_rows.append({
            "process_id": r["process_id"], "process_name": r.get("process_name") or r["process_id"],
            "kind": "scheduled" if scheduled else "ad hoc", "category": cfg.get("category"),
            "calls": int(num(r.get("calls"))), "failures": int(num(r.get("failures"))), "usd": num(r.get("usd")),
            "tokens_in": int(num(r.get("tokens_in"))), "tokens_out": int(num(r.get("tokens_out"))),
            "calls_peak": int(num(r.get("calls_peak"))), "usd_peak": num(r.get("usd_peak")),
            "models": r.get("models"), "last_call": str(r.get("last_call") or "")[:19],
            "daily_cost_cap_usd": (num(cfg["daily_cost_cap_usd"]) if cfg.get("daily_cost_cap_usd") is not None else None),
            "daily_request_cap": cfg.get("daily_soft_cap"),
        })
    scheduled_on_peak = sorted((p for p in process_rows if p["kind"] == "scheduled" and p["calls_peak"] > 0),
                               key=lambda p: (-p["usd_peak"], -p["calls_peak"]))
    usd = num(totals.get("usd"))
    usd_peak = num(totals.get("usd_peak"))
    days = max(1.0, (end - start).total_seconds() / 86400.0)
    return {
        "schema": SCHEMA, "authority": AUTHORITY, "period": period, "label": label,
        "start_utc": start.isoformat(), "end_utc": end.isoformat(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "totals": {
            "usd": usd, "usd_per_day": usd / days, "calls": int(num(totals.get("calls"))),
            "paid_calls": int(num(totals.get("paid_calls"))), "failures": int(num(totals.get("failures"))),
            "tokens_in": int(num(totals.get("tokens_in"))), "tokens_out": int(num(totals.get("tokens_out"))),
            "reasoning_tokens": int(num(totals.get("reasoning_tokens"))),
            "cache_hit_tokens": int(num(totals.get("cache_hit_tokens"))),
            "usd_peak": usd_peak, "usd_offpeak": max(0.0, usd - usd_peak),
            "calls_peak": int(num(totals.get("calls_peak"))),
            "calls_offpeak": int(num(totals.get("calls"))) - int(num(totals.get("calls_peak"))),
        },
        "counted_by_caps_usd": num(counted.get("usd")),
        "global_cap_usd_per_day": configured_global_cap(),
        "by_provider": [{"provider": k, **v} for k, v in sorted(by_provider.items(), key=lambda kv: -kv[1]["usd"])],
        "by_model": model_rows,
        "by_process": process_rows,
        "scheduled_on_peak": [{"process_id": p["process_id"], "process_name": p["process_name"],
                               "calls_peak": p["calls_peak"], "usd_peak": p["usd_peak"]} for p in scheduled_on_peak],
        "brave": brave_requests(start, end),
        "definitions": {
            "peak": "DeepSeek official peak hours 01:00–04:00 and 06:00–10:00 UTC (09:00–12:00, 14:00–18:00 Beijing), Mon–Fri; everything else incl. China night and weekends is off-peak",
            "scheduled": "trigger_mode automated (cron, timers, workers); ad hoc = manual/desk requests",
            "real_vs_counted": "real = provider tokens × price schedule; counted = what the cap ledger held (conservative on failed calls)",
        },
    }


__all__ = ["PERIODS", "brave_requests", "build_report", "configured_global_cap", "peak_sql", "period_bounds", "provider_of"]
