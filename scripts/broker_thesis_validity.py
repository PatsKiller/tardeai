"""broker_thesis_validity.py — drift gap / thesis validity range for broker proposals.

Pure functions: given entry/stop/target and live price, compute the price band where
the long thesis remains valid (entry zone + minimum R:R).
"""
from __future__ import annotations

MIN_RR_DEFAULT = 2.0


def _rr_at_price(price: float, stop: float, target: float) -> float | None:
    if price <= stop or target <= price:
        return None
    risk = price - stop
    reward = target - price
    if risk <= 0:
        return None
    return reward / risk


def _price_at_min_rr(stop: float, target: float, min_rr: float) -> float | None:
    """Upper bound (long) where R:R falls to min_rr."""
    if min_rr <= 0 or target <= stop:
        return None
    return (target + min_rr * stop) / (1 + min_rr)


def compute_thesis_validity(
    entry: float,
    stop: float,
    target: float,
    current_price: float | None = None,
    *,
    strategy_id: str = "",
    min_rr: float = MIN_RR_DEFAULT,
    drift_threshold_pct: float | None = None,
) -> dict:
    """Return visual + numeric thesis validity band for a long proposal."""
    entry = float(entry or 0)
    stop = float(stop or 0)
    target = float(target or 0)
    if entry <= 0 or stop <= 0 or target <= 0 or entry <= stop or target <= entry:
        return {
            "ok": False,
            "error": "invalid entry/stop/target",
            "zone_status": "invalid",
            "zone_color": "red",
        }

    if drift_threshold_pct is None:
        try:
            from proposal_lifecycle import get_price_drift_threshold
            drift_threshold_pct = float(get_price_drift_threshold(strategy_id or "momentum_scalp"))
        except Exception:
            drift_threshold_pct = 5.0

    drift_frac = drift_threshold_pct / 100.0
    entry_low = round(entry * (1 - drift_frac), 4)
    entry_high = round(entry * (1 + drift_frac), 4)
    rr_cap = _price_at_min_rr(stop, target, min_rr)
    rr_cap_r = round(rr_cap, 4) if rr_cap is not None else None

    valid_low = round(max(stop, entry_low), 4)
    valid_high = round(min(entry_high, rr_cap) if rr_cap is not None else entry_high, 4)
    if valid_high < valid_low:
        valid_high = valid_low

    live = float(current_price) if current_price is not None and float(current_price) > 0 else None
    drift_pct = None
    current_rr = None
    if live is not None:
        drift_pct = round((live - entry) / entry * 100, 2)
        current_rr = _rr_at_price(live, stop, target)
        if current_rr is not None:
            current_rr = round(current_rr, 2)

    span = valid_high - valid_low
    zone_status = "comfortable"
    zone_color = "green"
    reasons: list[str] = []

    if live is not None:
        if live <= stop:
            zone_status = "invalid"
            zone_color = "red"
            reasons.append("Price at/below stop — thesis invalidated")
        elif live > valid_high:
            zone_status = "at_risk"
            zone_color = "red"
            if current_rr is not None and current_rr < min_rr:
                reasons.append(f"R:R {current_rr:.1f}:1 below minimum {min_rr:.1f}:1")
            else:
                reasons.append(f"Price {drift_pct:+.1f}% outside entry zone (±{drift_threshold_pct:.0f}%)")
        elif live < valid_low:
            zone_status = "at_risk"
            zone_color = "red"
            reasons.append(f"Price {drift_pct:+.1f}% below valid entry band")
        elif span > 0:
            pos = (live - valid_low) / span
            if pos < 0.15 or pos > 0.85:
                zone_status = "approaching"
                zone_color = "yellow"
                reasons.append("Price near edge of thesis validity band")
            if current_rr is not None and current_rr < min_rr * 1.15:
                zone_status = "approaching"
                zone_color = "yellow"
                reasons.append(f"R:R tightening ({current_rr:.1f}:1)")
    else:
        zone_status = "unknown"
        zone_color = "gray"
        reasons.append("No live price — refresh to assess thesis band")

    room_up_pct = round((valid_high - (live or entry)) / (live or entry) * 100, 2) if (live or entry) > 0 else None
    room_down_pct = round(((live or entry) - valid_low) / (live or entry) * 100, 2) if (live or entry) > 0 else None

    label = (
        f"Thesis valid ${valid_low:.2f} – ${valid_high:.2f} "
        f"(±{drift_threshold_pct:.0f}% entry · min {min_rr:.1f}:1 R:R)"
    )

    return {
        "ok": True,
        "label": label,
        "valid_low": valid_low,
        "valid_high": valid_high,
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "target": round(target, 4),
        "drift_threshold_pct": drift_threshold_pct,
        "min_rr": min_rr,
        "current_price": live,
        "drift_pct": drift_pct,
        "current_rr": current_rr,
        "planned_rr": round((target - entry) / (entry - stop), 2) if entry > stop else None,
        "room_up_pct": room_up_pct,
        "room_down_pct": room_down_pct,
        "rr_cap_price": rr_cap_r,
        "entry_band_low": entry_low,
        "entry_band_high": entry_high,
        "zone_status": zone_status,
        "zone_color": zone_color,
        "reasons": reasons,
        "actionable": zone_status in ("comfortable", "approaching"),
    }


def attach_thesis_validity(row: dict, quote: dict | None = None) -> dict:
    """Mutate/enrich a broker proposal row dict with thesis_validity."""
    entry = float(row.get("proposed_entry") or 0)
    stop = float(row.get("proposed_stop") or 0)
    target = float(row.get("proposed_target1") or 0)
    live = row.get("quote_last") or row.get("current_price")
    if quote:
        live = quote.get("last") or quote.get("last_price") or live
    tv = compute_thesis_validity(
        entry, stop, target,
        float(live) if live is not None else None,
        strategy_id=str(row.get("strategy_id") or ""),
    )
    row["thesis_validity"] = tv
    if tv.get("drift_pct") is not None:
        row["price_drift_pct"] = tv["drift_pct"]
    if tv.get("current_rr") is not None:
        row["live_rr"] = tv["current_rr"]
    return row