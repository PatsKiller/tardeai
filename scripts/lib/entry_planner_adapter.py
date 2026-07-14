"""entry_planner_adapter — Phase C: entry targets, staging, quote freshness, export (advisory only)."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.redeploy_data_truth import EXPORT_QUOTE_MAX_AGE_MINUTES, _as_float, _load_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE = PROJECT_ROOT / "data" / "portfolios" / "state"

ADAPTER_VERSION = "phase_c_1.0.0"

MONITORING_RULES = (
    "+1R -> stop to breakeven; stage fill -> trail 1R or prior-day low; "
    "close below invalidation = exit; never average down"
)

# Stage pct + ATR multiplier from preferred entry (watchlist_entry_planner pullback discipline)
_REGIME_STAGES: dict[str, list[tuple[int, float]]] = {
    "risk_on": [(30, 0.0), (25, 0.75), (45, 1.5)],
    "neutral": [(25, 0.0), (25, 1.0), (50, 2.0)],
    "risk_off": [(15, 0.0), (20, 1.25), (65, 2.5)],
}

_HIGH_ATR_PCT = 3.0


def _parse_snapshot_ts(as_of: str | None) -> datetime | None:
    if not as_of:
        return None
    text = str(as_of).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(text[: len(fmt.replace("%z", ""))], fmt.replace("%z", ""))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def quote_age_minutes(as_of: str | None, *, now: datetime | None = None) -> float | None:
    ts = _parse_snapshot_ts(as_of)
    if not ts:
        return None
    ref = now or datetime.now(timezone.utc)
    return max(0.0, (ref - ts).total_seconds() / 60.0)


def is_quote_stale(
    as_of: str | None,
    *,
    max_age_minutes: int = EXPORT_QUOTE_MAX_AGE_MINUTES,
    now: datetime | None = None,
) -> bool:
    age = quote_age_minutes(as_of, now=now)
    if age is None:
        return True
    return age > max_age_minutes


def load_technicals(sym: str) -> dict[str, Any]:
    tech = _load_json(STATE / "technical_snapshot.json", {})
    row = tech.get(sym.upper()) or {}
    meta = tech.get("_meta") or {}
    price = _as_float(row.get("price"))
    atr = _as_float(row.get("atr"))
    sma20 = _as_float(row.get("sma20"))
    sma50 = _as_float(row.get("sma50"))
    sma200 = _as_float(row.get("sma200"))
    if not sma50 and price and row.get("sma50_pct") is not None:
        sma50 = price / (1 + _as_float(row.get("sma50_pct")) / 100.0)
    if not sma20 and price and row.get("sma20_pct") is not None:
        sma20 = price / (1 + _as_float(row.get("sma20_pct")) / 100.0)
    atr_pct = (atr / price * 100.0) if price and atr else 0.0
    return {
        "price": price,
        "atr": atr,
        "atr_pct": round(atr_pct, 2),
        "rsi": _as_float(row.get("rsi")),
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "as_of": meta.get("last_updated") or row.get("as_of"),
    }


def whole_shares(dollars: float, price: float) -> tuple[int, float]:
    if price <= 0 or dollars <= 0:
        return 0, 0.0
    sh = int(dollars // price)
    return sh, round(sh * price, 2)


def _stage_profile(regime_posture: str, atr_pct: float) -> list[tuple[int, float]]:
    profile = list(_REGIME_STAGES.get(regime_posture) or _REGIME_STAGES["neutral"])
    if atr_pct >= _HIGH_ATR_PCT:
        profile = [(pct, round(mult + 0.25, 2)) for pct, mult in profile]
    return profile


def _preferred_entry(tech: dict[str, Any]) -> float | None:
    price = tech.get("price") or 0
    atr = tech.get("atr") or (price * 0.015 if price else 0)
    if not price:
        return None
    pref = round(price - atr * 0.5, 2)
    sma50 = tech.get("sma50")
    if sma50 and pref:
        pref = round(min(pref, max(sma50, price * 0.98)), 2)
    return pref


def build_entry_package(
    sym: str,
    *,
    leg_dollars: float,
    regime_posture: str = "neutral",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Per-leg entry math — mirrors watchlist_entry_planner pullback discipline."""
    tech = load_technicals(sym)
    price = tech["price"]
    atr = tech["atr"] or (price * 0.015 if price else 0)
    pref = _preferred_entry(tech)
    as_of = tech.get("as_of")
    stale = is_quote_stale(as_of, now=now)

    stages: dict[str, Any] = {}
    profile = _stage_profile(regime_posture, tech.get("atr_pct") or 0)
    if pref and leg_dollars > 0:
        for i, (pct, mult) in enumerate(profile, 1):
            stage_price = round(pref - atr * mult, 2)
            stage_d = round(leg_dollars * pct / 100.0, 2)
            sh, filled = whole_shares(stage_d, stage_price)
            stages[f"stage_{i}_pct"] = pct
            stages[f"stage_{i}_price"] = stage_price
            stages[f"stage_{i}_shares"] = sh
            stages[f"stage_{i}_dollars"] = filled

    urgency = "watch"
    if price and pref:
        if price <= pref + atr * 0.1:
            urgency = "ready"
        elif price <= pref + atr:
            urgency = "near_entry"

    return {
        "current_price": price or None,
        "price_as_of": as_of,
        "price_stale": stale,
        "quote_age_minutes": quote_age_minutes(as_of, now=now),
        "preferred_entry": pref,
        "entry_range_low": round(pref - atr, 2) if pref else None,
        "entry_range_high": round(pref + atr * 0.3, 2) if pref else None,
        "do_not_chase": round(price + atr * 0.5, 2) if price else None,
        "setup_type": "pullback",
        "urgency": urgency,
        "rsi": tech.get("rsi"),
        "atr": atr,
        "sma50": tech.get("sma50"),
        "invalidation": (
            f"Daily close below {round(pref - atr, 2)}"
            if pref
            else None
        ),
        "monitoring_rules": MONITORING_RULES,
        "staging_profile": regime_posture,
        **stages,
    }


def enrich_plan_legs(plan: dict[str, Any], *, regime_posture: str = "neutral") -> dict[str, Any]:
    for leg in plan.get("legs") or []:
        if leg.get("is_reserve"):
            continue
        dollars = _as_float(leg.get("target_dollars"))
        entry = build_entry_package(leg["ticker"], leg_dollars=dollars, regime_posture=regime_posture)
        leg.update(entry)
        if dollars > 0 and entry.get("current_price"):
            sh, filled = whole_shares(dollars, entry["current_price"])
            leg["target_shares"] = sh
            leg["target_dollars"] = filled or round(dollars, 2)
    return plan


def assess_export_readiness(plans: list[dict[str, Any]]) -> dict[str, Any]:
    stale: set[str] = set()
    fresh: set[str] = set()
    for plan in plans:
        for leg in plan.get("legs") or []:
            if leg.get("is_reserve"):
                continue
            sym = leg.get("ticker") or ""
            if leg.get("price_stale"):
                stale.add(sym)
            else:
                fresh.add(sym)
    quotes_fresh = len(stale) == 0 and bool(fresh or not plans)
    return {
        "quotes_fresh": quotes_fresh,
        "stale_symbols": sorted(stale),
        "fresh_symbols": sorted(fresh - stale),
        "export_quote_max_age_minutes": EXPORT_QUOTE_MAX_AGE_MINUTES,
        "export_allowed": quotes_fresh,
    }


def enrich_bundle_phase_c(bundle: dict[str, Any], *, market_context: dict[str, Any] | None) -> dict[str, Any]:
    posture = (market_context or {}).get("regime_posture") or "neutral"
    for plan in bundle.get("plans") or []:
        enrich_plan_legs(plan, regime_posture=posture)
    readiness = assess_export_readiness(bundle.get("plans") or [])
    bundle["entry_adapter_version"] = ADAPTER_VERSION
    bundle["regime_posture"] = posture
    bundle["export_readiness"] = readiness
    return bundle


def enrich_event_phase_c(event: dict[str, Any]) -> dict[str, Any]:
    meta = dict(event.get("metadata") or {})
    bundle = meta.get("phase_b")
    if not bundle or not bundle.get("plans"):
        return event
    bundle = enrich_bundle_phase_c(bundle, market_context=meta.get("market_context"))
    meta["phase_b"] = bundle
    meta["phase_c"] = {
        "adapter_version": ADAPTER_VERSION,
        "regime_posture": bundle.get("regime_posture"),
        "export_readiness": bundle.get("export_readiness"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    meta["institutional_plans"] = bundle.get("plans") or []
    event["metadata"] = meta
    return event


def build_export_payload(event: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    meta = event.get("metadata") or {}
    pa = meta.get("phase_a") or {}
    recon = pa.get("reconciliation") or {}
    readiness = (meta.get("phase_c") or {}).get("export_readiness") or {}
    legs_out = []
    for leg in plan.get("legs") or []:
        if leg.get("is_reserve"):
            legs_out.append({
                "ticker": leg.get("ticker"),
                "is_reserve": True,
                "target_dollars": leg.get("target_dollars"),
                "account": leg.get("account"),
                "thesis": leg.get("thesis"),
            })
            continue
        legs_out.append({
            "ticker": leg.get("ticker"),
            "account": leg.get("account"),
            "target_dollars": leg.get("target_dollars"),
            "target_shares": leg.get("target_shares"),
            "current_price": leg.get("current_price"),
            "price_as_of": leg.get("price_as_of"),
            "price_stale": leg.get("price_stale"),
            "preferred_entry": leg.get("preferred_entry"),
            "entry_range_low": leg.get("entry_range_low"),
            "entry_range_high": leg.get("entry_range_high"),
            "do_not_chase": leg.get("do_not_chase"),
            "stages": [
                {
                    "pct": leg.get(f"stage_{i}_pct"),
                    "price": leg.get(f"stage_{i}_price"),
                    "shares": leg.get(f"stage_{i}_shares"),
                    "dollars": leg.get(f"stage_{i}_dollars"),
                }
                for i in range(1, 4)
                if leg.get(f"stage_{i}_price") is not None
            ],
            "thesis": leg.get("thesis"),
            "invalidation": leg.get("invalidation"),
            "monitoring_rules": leg.get("monitoring_rules"),
        })
    return {
        "advisory_only": True,
        "no_broker_execution": True,
        "event_id": event.get("id"),
        "event_key": event.get("event_key"),
        "sold_symbol": event.get("symbol"),
        "account": event.get("account"),
        "net_proceeds_usd": recon.get("net_proceeds_usd") or event.get("proceeds_usd"),
        "deployable_cash_usd": recon.get("deployable_cash_usd"),
        "reconciliation_status": recon.get("reconciliation_status"),
        "plan_archetype": plan.get("plan_archetype"),
        "plan_type": plan.get("plan_type"),
        "objective": plan.get("objective"),
        "operator_status": plan.get("operator_status"),
        "oversight_status": plan.get("oversight_status"),
        "export_readiness": readiness,
        "regime_posture": meta.get("phase_c", {}).get("regime_posture"),
        "legs": legs_out,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def export_trade_plan_csv(payload: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "ticker", "account", "reserve", "target_dollars", "target_shares",
        "current_price", "preferred_entry", "stage_1_price", "stage_1_shares",
        "stage_2_price", "stage_2_shares", "stage_3_price", "stage_3_shares",
        "price_stale", "thesis",
    ])
    for leg in payload.get("legs") or []:
        stages = leg.get("stages") or []
        s = {i + 1: st for i, st in enumerate(stages)}
        w.writerow([
            leg.get("ticker"),
            leg.get("account"),
            leg.get("is_reserve", False),
            leg.get("target_dollars"),
            leg.get("target_shares"),
            leg.get("current_price"),
            leg.get("preferred_entry"),
            (s.get(1) or {}).get("price"),
            (s.get(1) or {}).get("shares"),
            (s.get(2) or {}).get("price"),
            (s.get(2) or {}).get("shares"),
            (s.get(3) or {}).get("price"),
            (s.get(3) or {}).get("shares"),
            leg.get("price_stale"),
            (leg.get("thesis") or "")[:120],
        ])
    return buf.getvalue()


def export_trade_plan(
    event: dict[str, Any],
    plan: dict[str, Any],
    *,
    fmt: str = "json",
    force_stale: bool = False,
) -> dict[str, Any] | str:
    readiness = (event.get("metadata") or {}).get("phase_c", {}).get("export_readiness") or {}
    if not force_stale and not readiness.get("export_allowed"):
        return {
            "ok": False,
            "error": "stale_quotes",
            "stale_symbols": readiness.get("stale_symbols") or [],
            "export_quote_max_age_minutes": EXPORT_QUOTE_MAX_AGE_MINUTES,
            "hint": "Refresh technical_snapshot or pass force_stale=1 for advisory preview only.",
        }
    payload = build_export_payload(event, plan)
    if fmt == "csv":
        return export_trade_plan_csv(payload)
    return {"ok": True, "format": "json", "trade_plan": payload}