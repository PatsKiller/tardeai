"""Enrich outcome-bus alerts with drilldown contributors and actionable links."""
from __future__ import annotations

from typing import Any

ALERT_LABELS = {
    "hit_rate_declining": "Hit rate declining",
    "efficiency_declining": "Efficiency below threshold",
    "scope_creep": "Scope creep detected",
    "stop_quality_divergence": "Stop quality tier advantage fading",
}

_SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}


def _symbol_hit_rate(meta: dict[str, Any]) -> float | None:
    hits = int(meta.get("outcome_hits") or 0)
    misses = int(meta.get("misses") or 0)
    d = hits + misses
    return round(hits / d, 3) if d else None


def _worst_symbols(by_symbol: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sym, meta in by_symbol.items():
        hits = int(meta.get("outcome_hits") or 0)
        misses = int(meta.get("misses") or 0)
        n = int(meta.get("n") or 0)
        if n < 1:
            continue
        hr = _symbol_hit_rate(meta)
        rows.append({
            "symbol": str(sym).upper(),
            "hits": hits,
            "misses": misses,
            "n": n,
            "hit_rate": hr,
            "avg_r": meta.get("avg_r"),
            "gate": meta.get("gate"),
            "lift": meta.get("lift"),
            "dominant_tag": meta.get("dominant_tag"),
            "tag_flagged": meta.get("tag_flagged"),
        })
    rows.sort(key=lambda r: (r.get("hit_rate") if r.get("hit_rate") is not None else 1.0, -r["misses"]))
    return rows[:limit]


def _pressure_symbols(by_symbol: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    pressure = {"pause_eligible", "demote_pressure", "pause", "promote_blocked_bad_tag"}
    rows = [
        {
            "symbol": str(sym).upper(),
            "gate": meta.get("gate"),
            "hits": int(meta.get("outcome_hits") or 0),
            "misses": int(meta.get("misses") or 0),
            "n": int(meta.get("n") or 0),
            "hit_rate": _symbol_hit_rate(meta),
            "avg_r": meta.get("avg_r"),
            "lift": meta.get("lift"),
            "dominant_tag": meta.get("dominant_tag"),
        }
        for sym, meta in by_symbol.items()
        if str(meta.get("gate") or "") in pressure
    ]
    rows.sort(key=lambda r: (-r["misses"], r.get("hit_rate") or 1.0))
    return rows[:limit]


def _negative_lift_tags(by_tag: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    rows = []
    for tag, meta in by_tag.items():
        lift = meta.get("lift")
        if lift is None or float(lift) >= 0:
            continue
        rows.append({
            "tag": str(tag),
            "lift": lift,
            "precision": meta.get("precision"),
            "n": meta.get("n"),
            "quality_multiplier": meta.get("quality_multiplier"),
            "flagged": meta.get("flagged"),
        })
    rows.sort(key=lambda r: (float(r.get("lift") or 0), -int(r.get("n") or 0)))
    return rows[:limit]


def _promote_symbols(by_symbol: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    rows = [
        {
            "symbol": str(sym).upper(),
            "gate": meta.get("gate"),
            "hits": int(meta.get("outcome_hits") or 0),
            "misses": int(meta.get("misses") or 0),
            "n": int(meta.get("n") or 0),
            "hit_rate": _symbol_hit_rate(meta),
            "lift": meta.get("lift"),
        }
        for sym, meta in by_symbol.items()
        if meta.get("gate") == "promote_eligible"
    ]
    rows.sort(key=lambda r: (-(r.get("hit_rate") or 0), -r["n"]))
    return rows[:limit]


def _symbol_links(symbol: str) -> list[dict[str, str]]:
    sym = symbol.upper()
    return [
        {"label": "Outcome bus", "endpoint": f"/api/v2/hermes/outcome-bus?symbol={sym}"},
        {"label": "Scope governor", "endpoint": f"/api/v2/hermes/scope-governor?symbol={sym}"},
        {"label": "Hermes intel", "endpoint": f"/api/v2/hermes/intel/{sym}"},
    ]


def _duration_days(alert: dict[str, Any]) -> int | None:
    m = alert.get("metrics") or {}
    for key in ("streak_days", "window_days"):
        if m.get(key) is not None:
            return int(m[key])
    since = alert.get("since")
    if since and len(str(since)) >= 10:
        try:
            from datetime import datetime, timezone
            start = datetime.fromisoformat(f"{str(since)[:10]}T00:00:00+00:00")
            return max(1, (datetime.now(timezone.utc) - start).days)
        except Exception:
            pass
    return None


def _enrich_hit_rate_declining(alert: dict[str, Any], bus: dict[str, Any]) -> dict[str, Any]:
    symbols = _worst_symbols(bus.get("by_symbol") or {}, limit=5)
    tags = _negative_lift_tags(bus.get("by_tag") or {}, limit=3)
    return {
        "summary": (
            f"{len(symbols)} worst-performing symbols; "
            f"{len(tags)} tags with negative lift may be dragging promotion hit rate"
        ),
        "symbols": symbols,
        "tags": tags,
        "root_causes": [
            "Price-graded promotion/external_rec outcomes declining vs 7d baseline",
            "Check symbols with high miss counts and negative-lift dominant tags",
        ],
    }


def _enrich_efficiency_declining(alert: dict[str, Any], bus: dict[str, Any]) -> dict[str, Any]:
    symbols = _pressure_symbols(bus.get("by_symbol") or {}, limit=5)
    resource = bus.get("resource_efficiency") or {}
    streak = (alert.get("metrics") or {}).get("streak_days")
    return {
        "summary": (
            f"Efficiency score below threshold for {streak or '?'} days; "
            f"{len(symbols)} symbols under governor pressure"
        ),
        "symbols": symbols,
        "tags": _negative_lift_tags(bus.get("by_tag") or {}, limit=3),
        "metrics_snapshot": {
            "resource_efficiency_score": resource.get("score"),
            "positive_outcomes_7d": resource.get("positive_outcomes_7d"),
            "research_rows_7d": resource.get("research_rows_7d"),
            "hermes_api_calls_7d": resource.get("hermes_api_calls_7d"),
        },
        "root_causes": [
            "Outcome yield not keeping pace with research/API throughput",
            "Governor may tighten promotion gates on next run",
        ],
    }


def _enrich_scope_creep(alert: dict[str, Any], bus: dict[str, Any]) -> dict[str, Any]:
    m = alert.get("metrics") or {}
    symbols = _promote_symbols(bus.get("by_symbol") or {}, limit=5)
    return {
        "summary": (
            f"Bus grew {int(m.get('symbols_baseline', 0))} → {int(m.get('symbols_current', 0))} symbols "
            f"while hit rate flat/declined"
        ),
        "symbols": symbols,
        "tags": [],
        "metrics_snapshot": {
            "symbol_growth_pct": m.get("symbol_growth_pct"),
            "hit_rate_delta_pp": m.get("hit_rate_delta_pp"),
            "symbols_in_bus": len(bus.get("by_symbol") or {}),
        },
        "root_causes": [
            "Scope expanding without matching outcome yield improvement",
            "Scope Governor may reduce promotion cap if scope_creep reaction is active",
        ],
    }


def _enrich_stop_quality_divergence(alert: dict[str, Any], bus: dict[str, Any]) -> dict[str, Any]:
    stop_q = bus.get("stop_quality") or {}
    by_tier = stop_q.get("by_tier") or {}
    m = alert.get("metrics") or {}
    tier_rows = []
    for tier in ("hot", "warm", "cold"):
        t = by_tier.get(tier) or {}
        if (t.get("sample_n") or 0) == 0:
            continue
        tier_rows.append({
            "tier": tier,
            "trail_activation_rate": t.get("trail_activation_rate"),
            "aligned_pct": t.get("aligned_pct"),
            "sample_n": t.get("sample_n"),
        })
    return {
        "summary": (
            f"Hot vs Cold trail delta {m.get('current_delta_pp', 'n/a')} below "
            f"{m.get('min_delta_pp', 0.15):.0%} for {m.get('streak_days', '?')} days"
        ),
        "symbols": [],
        "tags": [],
        "stop_quality_by_tier": tier_rows,
        "correlations": stop_q.get("correlations") or [],
        "root_causes": [
            "Hot-tier stop-quality advantage vs Cold is fading",
            "Governor may tighten warm/cold promotion or boost Hot research priority",
        ],
    }


_ENRICHERS = {
    "hit_rate_declining": _enrich_hit_rate_declining,
    "efficiency_declining": _enrich_efficiency_declining,
    "scope_creep": _enrich_scope_creep,
    "stop_quality_divergence": _enrich_stop_quality_divergence,
}


def _apply_severity_rules(alert: dict[str, Any], cfg: dict[str, Any]) -> str:
    """Optionally upgrade severity based on sustained metrics."""
    sev = str(alert.get("severity") or "warning")
    rules = ((cfg.get("notifications") or {}).get("severity_rules") or {})
    aid = alert.get("id")
    rule = rules.get(aid) or {}
    streak = int((alert.get("metrics") or {}).get("streak_days") or 0)
    crit = int(rule.get("critical_streak_days") or 999)
    if streak >= crit:
        return "critical"
    return sev


def enrich_alert(alert: dict[str, Any], bus: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add label, duration, contributors, drilldown, and links to one alert."""
    cfg = cfg or {}
    aid = str(alert.get("id") or "")
    out = dict(alert)
    out["label"] = ALERT_LABELS.get(aid, aid)
    out["duration_days"] = _duration_days(alert)
    out["severity"] = _apply_severity_rules(out, cfg)

    enricher = _ENRICHERS.get(aid)
    drilldown = enricher(out, bus) if enricher else {"summary": out.get("detail"), "symbols": [], "tags": []}

    symbols = drilldown.get("symbols") or []
    out["contributors"] = {
        "symbols": symbols[:5],
        "tags": drilldown.get("tags") or [],
    }
    out["drilldown"] = {
        **drilldown,
        "panel_path": (cfg.get("notifications") or {}).get("panel_path", "/v3/hermes"),
        "governor_audit_endpoint": "/api/v2/hermes/scope-governor",
        "outcome_bus_endpoint": "/api/v2/hermes/outcome-bus",
    }
    if symbols:
        out["drilldown"]["symbol_links"] = {
            s["symbol"]: _symbol_links(s["symbol"]) for s in symbols[:5]
        }
    return out


def enrich_alerts(
    alerts: dict[str, Any],
    bus: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich all active alerts in-place."""
    cfg = cfg or {}
    enriched = [enrich_alert(a, bus, cfg) for a in (alerts.get("active") or [])]
    return {**alerts, "active": enriched, "active_count": len(enriched)}