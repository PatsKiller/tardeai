"""Opening shock detector, 09:16-09:46 ET (DSN-20261031-market-risk-engine P2-T11, plan §5.14).

Large moves reveal themselves between 09:15 and 09:45. Given, per symbol, the prior close, an ATR, the indicative
(extended-hours) price, the first regular print and the opening-range prices, plus first-15-minute internals when
they exist, ``classify`` returns one of:

* ``panic_open``  — gap <= panic ATRs, advancers below the floor, TRIN above the ceiling, VIX up. Scoring treats it
  as a single-evaluation RED (evidence carries ``shock=True``). With internals UNKNOWN a deeper gap is required and
  the result says the internals were not measured.
* ``gap_and_go``  — |gap| >= the go threshold in ATRs and the opening range extends in the gap's direction.
* ``gap_fade``    — at least the configured share of the gap retraced by 09:45.
* ``normal`` / ``unknown`` (inputs missing — never guessed).

Pure function over numbers the caller read through the engine's reader; no data access, no sends.
"""

from __future__ import annotations

from typing import Any


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def classify(sym: dict[str, Any], internals: dict[str, Any] | None, cfg: dict[str, Any]) -> dict[str, Any]:
    """sym: {symbol, prior_close, atr, indicative?, open_print?, range: [prices after the open]?, vix_change_pct?}."""
    pc, atr = _f(sym.get("prior_close")), _f(sym.get("atr"))
    first = _f(sym.get("open_print"))
    if first is None:
        first = _f(sym.get("indicative"))
    out: dict[str, Any] = {"symbol": sym.get("symbol"), "class": "unknown", "shock": False, "evidence": {}}
    if not pc or not atr or first is None:
        out["reason"] = "prior close, ATR or first print missing"
        return out
    gap = first - pc
    gap_atr = gap / atr
    rng = [p for p in (_f(x) for x in sym.get("range") or []) if p is not None]
    last = rng[-1] if rng else first
    retrace = (first - last) / gap if gap else 0.0
    vix = _f(sym.get("vix_change_pct"))
    ev = {
        "gap_pct": round(100 * gap / pc, 2),
        "gap_atr": round(gap_atr, 2),
        "retrace_share": round(retrace, 2),
        "vix_change_pct": vix,
    }
    adv = _f((internals or {}).get("advancers_pct"))
    trin = _f((internals or {}).get("trin"))
    internals_known = adv is not None and trin is not None
    ev["internals"] = "measured" if internals_known else "UNKNOWN"
    if internals_known:
        ev.update(advancers_pct=adv, trin=trin)
    vix_ok = vix is not None and vix >= float(cfg.get("panic_vix_change_pct", 10))
    if internals_known:
        panic = (
            gap_atr <= float(cfg.get("panic_gap_atr", -1.5))
            and adv < float(cfg.get("panic_advancers_pct", 20))
            and trin > float(cfg.get("panic_trin", 2.0))
            and vix_ok
        )
    else:
        panic = gap_atr <= float(cfg.get("panic_gap_atr_without_internals", -2.0)) and vix_ok
    go = float(cfg.get("gap_and_go_atr", 0.75))
    if panic:
        cls = "panic_open"
    elif abs(gap_atr) >= go and retrace >= float(cfg.get("gap_fade_retrace", 0.5)):
        cls = "gap_fade"
    elif abs(gap_atr) >= go and (last - first) * gap >= 0:
        cls = "gap_and_go"
    else:
        cls = "normal"
    out.update({"class": cls, "shock": cls == "panic_open", "evidence": ev})
    return out


def classify_all(symbols: list[dict[str, Any]], internals: dict[str, Any] | None, cfg: dict[str, Any]) -> dict:
    """Index-level verdict: panic if any configured index proxy panics; otherwise the most severe class seen."""
    rows = [classify(s, internals, cfg) for s in symbols]
    order = ["unknown", "normal", "gap_fade", "gap_and_go", "panic_open"]
    worst = max(rows, key=lambda r: order.index(r["class"])) if rows else {"class": "unknown", "shock": False}
    return {"class": worst["class"], "shock": bool(worst.get("shock")), "symbols": rows}
