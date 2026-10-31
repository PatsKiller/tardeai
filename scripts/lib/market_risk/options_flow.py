"""Index options-flow detector: put/call open interest and volume versus their own trailing median.

Why this exists: at 10:00 ET on 2026-10-29 the system's own snapshot (option_chain_snapshots, written by
scripts/options_chain_snapshot.py) recorded QQQ put/call OI 1.375 → 2.856 and put/call volume 0.96 → 3.31 —
hedging demand tripling the morning before the 10-30 selloff — and nothing read it (RCA finding 4).

Pure functions; no I/O. `evaluate()` returns one finding per index symbol whose ratios exceed the configured
multiples of their trailing median (WARN / STRESS), with the numbers a card needs. Thresholds come from
config/market_risk_policy.yaml `options_flow`; nothing is hardcoded here. Advisory only.
"""

from __future__ import annotations

from statistics import median
from typing import Any

WARN, STRESS = "WARN", "STRESS"


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _state(
    ratio: float | None, med: float | None, cfg: dict, *, absolute_stress: float | None = None
) -> tuple[str | None, float | None]:
    """(state, factor) for one ratio against its median; absolute_stress short-circuits to STRESS."""
    if ratio is None:
        return None, None
    factor = round(ratio / med, 2) if med and med > 0 else None
    if absolute_stress is not None and ratio >= float(absolute_stress):
        return STRESS, factor
    if factor is None:
        return None, None
    if factor >= float(cfg["stress_factor"]):
        return STRESS, factor
    if factor >= float(cfg["warn_factor"]):
        return WARN, factor
    return None, factor


def evaluate(today: dict[str, dict], history: dict[str, list[dict]], cfg: dict) -> list[dict]:
    """today: {symbol: {pc_oi_ratio, pc_vol_ratio, underlying_price, as_of}}; history: {symbol: [{as_of, pc_oi_ratio,
    pc_vol_ratio, underlying_price}, ...] newest first, excluding today}. Returns findings sorted STRESS first."""
    out: list[dict] = []
    look = int(cfg["lookback_sessions"])
    need = int(cfg["min_history_sessions"])
    for sym in cfg["index_symbols"]:
        row = today.get(sym)
        if not row:
            continue
        hist = (history.get(sym) or [])[:look]
        oi_hist = [x for x in (_f(h.get("pc_oi_ratio")) for h in hist) if x is not None]
        vol_hist = [x for x in (_f(h.get("pc_vol_ratio")) for h in hist) if x is not None]
        if len(oi_hist) < need and len(vol_hist) < need:
            out.append({"symbol": sym, "state": "UNKNOWN", "reason": f"history {len(hist)} < {need} sessions"})
            continue
        oi_med = median(oi_hist) if len(oi_hist) >= need else None
        vol_med = median(vol_hist) if len(vol_hist) >= need else None
        oi_state, oi_factor = _state(_f(row.get("pc_oi_ratio")), oi_med, cfg)
        vol_state, vol_factor = _state(
            _f(row.get("pc_vol_ratio")), vol_med, cfg, absolute_stress=cfg.get("absolute_pc_vol_stress")
        )
        states = [s for s in (oi_state, vol_state) if s]
        if not states:
            continue
        state = STRESS if STRESS in states else WARN
        prev_px = _f(hist[0].get("underlying_price")) if hist else None
        px = _f(row.get("underlying_price"))
        px_chg = round((px / prev_px - 1) * 100, 2) if px and prev_px else None
        out.append(
            {
                "symbol": sym,
                "state": state,
                "pc_oi_ratio": _f(row.get("pc_oi_ratio")),
                "pc_oi_median": round(oi_med, 3) if oi_med else None,
                "pc_oi_factor": oi_factor,
                "pc_oi_state": oi_state,
                "pc_vol_ratio": _f(row.get("pc_vol_ratio")),
                "pc_vol_median": round(vol_med, 3) if vol_med else None,
                "pc_vol_factor": vol_factor,
                "pc_vol_state": vol_state,
                "history_sessions": len(hist),
                "underlying_price": px,
                "underlying_change_pct_vs_prior": px_chg,
                "as_of": row.get("as_of"),
            }
        )
    out.sort(key=lambda f: (0 if f.get("state") == STRESS else 1 if f.get("state") == WARN else 2, f["symbol"]))
    return out


def priority_for(findings: list[dict], session: str, cfg: dict) -> str | None:
    """P1 when any STRESS during premarket/regular hours; P2 for STRESS after hours or any WARN; None otherwise."""
    pr = cfg["priority"]
    actionable = [f for f in findings if f.get("state") in (WARN, STRESS)]
    if not actionable:
        return None
    if any(f["state"] == STRESS for f in actionable):
        return pr["stress_market_hours"] if session in ("premarket", "regular") else pr["stress_after_hours"]
    return pr["warn"]


def render(findings: list[dict], session: str, when_et: str) -> str:
    """Phone-length card: what moved, versus what, and the only action class we recommend (a review)."""
    actionable = [f for f in findings if f.get("state") in (WARN, STRESS)]
    worst = STRESS if any(f["state"] == STRESS for f in actionable) else WARN
    head = ("🟠" if worst == STRESS else "🟡") + f" *INDEX OPTIONS FLOW {worst}* · {when_et} ({session})"
    lines = [head]
    for f in actionable:
        bits = []
        if f.get("pc_vol_state"):
            bits.append(
                f"put/call volume {f['pc_vol_ratio']:.2f} = {f['pc_vol_factor']}× its {f['history_sessions']}-session median ({f['pc_vol_median']})"
            )
        if f.get("pc_oi_state"):
            bits.append(f"put/call OI {f['pc_oi_ratio']:.2f} = {f['pc_oi_factor']}× median ({f['pc_oi_median']})")
        px = f.get("underlying_change_pct_vs_prior")
        px_s = f" · price {px:+.1f}% vs prior snapshot" if px is not None else ""
        lines.append(f"• *{f['symbol']}* {f['state']}: " + "; ".join(bits) + px_s)
    lines.append(
        "Hedging demand is rising faster than price is moving. Review stops and exposure on index and growth-ETF "
        "holdings; no order, size or stop level is implied (advisory, MBI_BEHAVIOR = 0)."
    )
    unknown = [f["symbol"] for f in findings if f.get("state") == "UNKNOWN"]
    if unknown:
        lines.append(f"Not evaluable yet (history too short): {', '.join(unknown)}")
    return "\n".join(lines)
