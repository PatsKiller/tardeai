"""broker_thesis_validity.py — drift gap / thesis validity range for broker proposals.

Pure functions: given entry/stop/target and live price, compute the price band where
the long thesis remains valid (entry zone + minimum R:R).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

try:
    from proposal_thresholds import min_rr_floor as _min_rr_floor, price_max_age_min as _price_max_age
    MIN_RR_DEFAULT = _min_rr_floor()
    BROKER_PRICE_MAX_AGE_MIN = _price_max_age()
except Exception:  # standalone import safety
    MIN_RR_DEFAULT = float(os.getenv("PROPOSAL_MIN_RR_FLOOR", "2.0"))
    BROKER_PRICE_MAX_AGE_MIN = int(os.getenv("BROKER_PRICE_MAX_AGE_MIN", "20"))


def _parse_ts(val) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    s = str(val).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s[:26])
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def assess_price_freshness(row: dict, *, live_quote: bool = False) -> dict:
    """True when stored DB current_price is fresh enough for live R:R / zone math.

    A `refreshed_at`/`quote_provider` marker is honored, but its ACTUAL age is checked against
    max_age — a stale refresh stamp no longer reads as age 0 (fixed 2026-06-24)."""
    max_age = BROKER_PRICE_MAX_AGE_MIN
    if live_quote:
        # caller asserts an in-hand live quote this request
        as_of = row.get("refreshed_at") or row.get("updated_at")
        return {
            "price_stale": False, "price_age_min": 0.0,
            "price_as_of": str(as_of or "")[:19] or None,
            "price_source": str(row.get("quote_provider") or "live_quote"),
            "max_age_min": max_age,
        }
    marker = row.get("refreshed_at") or row.get("quote_provider")
    if marker:
        ts = _parse_ts(row.get("refreshed_at") or row.get("updated_at"))
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60.0 if ts else None
        stale = age_min is None or age_min > max_age
        return {
            "price_stale": stale,
            "price_age_min": round(age_min, 1) if age_min is not None else None,
            "price_as_of": ts.isoformat()[:19] if ts else None,
            "price_source": str(row.get("quote_provider") or "marked"),
            "max_age_min": max_age,
        }
    px = row.get("current_price")
    if px is None:
        return {
            "price_stale": True,
            "price_age_min": None,
            "price_as_of": None,
            "price_source": "missing",
            "max_age_min": max_age,
        }
    ts = _parse_ts(row.get("updated_at"))
    if not ts:
        return {
            "price_stale": True,
            "price_age_min": None,
            "price_as_of": None,
            "price_source": "db",
            "max_age_min": max_age,
        }
    age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
    stale = age_min > max_age
    return {
        "price_stale": stale,
        "price_age_min": round(age_min, 1),
        "price_as_of": ts.isoformat()[:19],
        "price_source": "db",
        "max_age_min": max_age,
    }


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
    stop_proximity_warn_pct: float = 2.5,
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
    # Room to each band edge — computed up-front so the zone logic can use proximity-to-stop.
    room_up_pct = round((valid_high - (live or entry)) / (live or entry) * 100, 2) if (live or entry) > 0 else None
    room_down_pct = round(((live or entry) - valid_low) / (live or entry) * 100, 2) if (live or entry) > 0 else None
    # Actual distance to the STOP (not the band floor — they differ when entry_low > stop). This is the
    # real stop-out risk + the denominator that inflates a near-stop R:R.
    stop_proximity_pct = round((live - stop) / live * 100, 2) if (live and stop and live > stop) else None
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
            # Near-stop danger: valid_low is usually the stop itself, so a price hovering just above it
            # is HIGH stop-out risk even though it's technically "in band" — and its live R:R is INFLATED
            # by the tiny risk distance (WEN $7.45 vs stop $7.37 → a "14:1" that is really $0.08 of risk,
            # not a quality setup). Flag it so the card stops reading "comfortable / 14:1" on a precarious
            # position. Critical: a high R:R from a near-stop price is a red flag, not a green light.
            if stop_proximity_pct is not None and stop_proximity_pct < stop_proximity_warn_pct:
                zone_status = "approaching"
                zone_color = "yellow"
                if current_rr is not None and current_rr >= min_rr * 2:
                    reasons.append(f"Price only {stop_proximity_pct:.1f}% above stop — high stop-out risk; "
                                   f"live R:R {current_rr:.0f}:1 is inflated by the small risk distance")
                else:
                    reasons.append(f"Price only {stop_proximity_pct:.1f}% above stop — high stop-out risk")
    else:
        zone_status = "unknown"
        zone_color = "gray"
        reasons.append("No live price — refresh to assess thesis band")

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
        "stop_proximity_pct": stop_proximity_pct,
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
    # Live quote on row (list batch Schwab / refresh-prices) bypasses DB updated_at age check.
    live_quote = bool(row.get("refreshed_at") or row.get("quote_provider"))
    live = row.get("quote_last") or row.get("current_price")
    if quote:
        live = quote.get("last") or quote.get("last_price") or live
    fresh = assess_price_freshness(row, live_quote=live_quote)
    row["price_freshness"] = fresh
    row["price_stale"] = bool(fresh.get("price_stale"))

    use_live = float(live) if live is not None and not fresh.get("price_stale") else None
    tv = compute_thesis_validity(
        entry, stop, target,
        use_live,
        strategy_id=str(row.get("strategy_id") or ""),
    )
    if fresh.get("price_stale") and live is not None:
        try:
            stale_px = float(live)
        except Exception:
            stale_px = None
        if stale_px is not None:
            tv["current_price"] = stale_px
            tv["stale_display_price"] = stale_px
        tv["current_rr"] = None
        tv["drift_pct"] = None
        tv["zone_status"] = "stale_price"
        tv["zone_color"] = "gray"
        tv["actionable"] = False
        age = fresh.get("price_age_min")
        age_txt = f"{age:.0f}m" if age is not None else "unknown age"
        tv["reasons"] = [
            f"Stored price {age_txt} old (max {fresh.get('max_age_min')}m) — refresh for live R:R",
            *(tv.get("reasons") or []),
        ]
        tv["price_stale"] = True
        tv["price_age_min"] = fresh.get("price_age_min")
        tv["price_as_of"] = fresh.get("price_as_of")
        tv["price_source"] = fresh.get("price_source")
        row["live_rr"] = None
    else:
        tv["price_stale"] = False
        tv["price_age_min"] = fresh.get("price_age_min")
        tv["price_as_of"] = fresh.get("price_as_of")
        tv["price_source"] = fresh.get("price_source")
        # CRITICAL (trading correctness): always reflect the freshly computed live R:R, INCLUDING None.
        # _rr_at_price returns None once the live price blows past target (or to/below stop) — the thesis
        # is invalid and there is no meaningful live R:R. The old code only wrote on non-None, so a stale
        # FAVORABLE R:R (e.g. WEN 13.48, computed when price was near the $7.37 stop) persisted after the
        # price ran to $8.64 past the $8.53 target, making an at_risk/invalid setup look like a 13:1 entry.
        # Never display a stale R:R that contradicts the live zone.
        row["live_rr"] = tv.get("current_rr")

    row["thesis_validity"] = tv
    if tv.get("drift_pct") is not None:
        row["price_drift_pct"] = tv["drift_pct"]
    return row