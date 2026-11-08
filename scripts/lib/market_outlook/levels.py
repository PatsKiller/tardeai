"""Key levels (§4.2, §4.6 key_levels): three supports and three resistances per index, with their basis stated.

The engine has no cash-index daily history (that is WU-1). Until it does, the levels are computed on the ETF proxy's
own bars and mapped to the index's scale by the policy's ``etf_to_index`` factor, and every level set is labelled
``basis: etf_derived``. A cash basis is claimed only when the bundle actually carries cash daily bars.
"""

from __future__ import annotations

from typing import Any, Sequence


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _sma(values: Sequence[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _pick(
    candidates: list[tuple[str, float]], anchor: float, *, above: bool, scale: float, count: int = 3
) -> list[dict[str, Any]]:
    seen: set[float] = set()
    out: list[dict[str, Any]] = []
    ordered = sorted(candidates, key=lambda c: c[1], reverse=not above)
    for source, value in ordered:
        if above and value <= anchor:
            continue
        if not above and value >= anchor:
            continue
        if abs(value - anchor) / anchor < 1e-4:
            continue
        scaled = value * scale  # candidates live on the proxy's scale; the level is stated on the index's
        rounded = round(scaled, 2)
        if rounded in seen:
            continue
        seen.add(rounded)
        out.append({"level": rounded, "source": source, "distance_pct": round((value / anchor - 1.0) * 100.0, 2)})
        if len(out) >= count:
            break
    return out


def key_levels(
    bundle: Any, policy: dict[str, Any], *, sessions: int = 5
) -> dict[str, dict[str, Any]]:
    cfg = policy["levels"]
    out: dict[str, dict[str, Any]] = {}
    for index in cfg["indices"]:
        proxy = str(cfg["proxy"][index])
        factor = float(cfg["etf_to_index"][index])
        cash_bars = list((bundle.bars or {}).get(f"${index}") or [])
        use_cash = bool(cash_bars)
        bars = cash_bars or list((bundle.bars or {}).get(proxy) or [])
        if len(bars) < 2:
            out[index] = {"support": [], "resistance": [], "basis": None,
                          "reason": f"no daily bars for {'$' + index if use_cash else proxy}"}
            continue
        scale = 1.0 if use_cash else factor
        closes = [float(b["close"]) for b in bars]
        highs = [_f(b.get("high")) for b in bars]
        lows = [_f(b.get("low")) for b in bars]
        anchor = closes[-1]
        candidates: list[tuple[str, float]] = []
        if any(highs[-sessions:]) and any(lows[-sessions:]):
            hi = max(v for v in highs[-sessions:] if v is not None)
            lo = min(v for v in lows[-sessions:] if v is not None)
            candidates += [("prior_week_high", hi), ("prior_week_low", lo)]
        for n, label in ((50, "dma50"), (200, "dma200")):
            v = _sma(closes, n)
            if v is not None:
                candidates.append((label, v))
        step = float(cfg["round_number_step"][index]) / scale  # round numbers live in index space
        tol = float(cfg["round_number_tolerance_pct"]) / 100.0
        for mult in (int(anchor / step) * step, (int(anchor / step) + 1) * step):
            if mult > 0 and abs(mult - anchor) / anchor <= tol:
                candidates.append(("round_number", mult))
        support = _pick(candidates, anchor, above=False, scale=scale)
        resistance = _pick(candidates, anchor, above=True, scale=scale)
        basis = "cash" if use_cash else "etf_derived"
        out[index] = {
            "support": support,
            "resistance": resistance,
            "basis": basis,
            "anchor": round(anchor * scale, 2),
            "proxy": None if use_cash else proxy,
            "as_of": str(bars[-1].get("as_of") or bars[-1].get("date")),
            "note": (
                f"{index} levels computed on {proxy} bars and mapped x{factor:g} to the index scale"
                if not use_cash
                else f"{index} levels computed on cash daily bars"
            ),
        }
    return out


def what_would_change_view(band: str | None, levels: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The §4.2 triggers: the levels and readings that would move the stance, each with its current status."""
    spx = levels.get("SPX") or {}
    sup = (spx.get("support") or [{}])[0].get("level")
    res = (spx.get("resistance") or [{}])[0].get("level")
    triggers = [
        {"trigger": "SPX closes below the nearest stated support", "threshold": sup, "status": "armed" if sup else "no level"},
        {"trigger": "SPX closes above the nearest stated resistance", "threshold": res, "status": "armed" if res else "no level"},
        {"trigger": "VIX closes below 20 with breadth above 50%", "threshold": 20.0, "status": "armed"},
        {"trigger": "HY OAS widens more than 50 bp over 20 sessions", "threshold": 50.0, "status": "armed"},
        {"trigger": "MRE tier changes", "threshold": None, "status": "armed"},
    ]
    if band in ("RISK_OFF", "DEFENSIVE"):
        triggers.append({"trigger": "two consecutive evaluations in NEUTRAL-or-better", "threshold": 2,
                         "status": "not yet"})
    return triggers


__all__ = ["key_levels", "what_would_change_view"]
