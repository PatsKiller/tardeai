"""momentum_scalp_regime.py — Per-symbol momentum regime detection for stop management.

Scores price structure, RVOL, ADX (or MA-proxy), and ATR expansion into one of:
  strong_trending_bull | strong_trending_bear | trending | ranging | high_volatility

Hysteresis + shift detection feed Layer 4 (0.5× ATR tighten on Trending→Ranging).
See docs/MOMENTUM_SCALP_REGIME_DETECTION_ALGORITHM.md.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_CFG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "momentum_scalp_regime.yaml"

REGIME_KEYS = (
    "strong_trending_bull",
    "strong_trending_bear",
    "trending",
    "ranging",
    "high_volatility",
)


def _load_yaml(path: Path | None = None) -> dict:
    p = path or DEFAULT_CFG_PATH
    try:
        import yaml

        return yaml.safe_load(p.read_text()) or {}
    except Exception:
        return {}


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _estimate_adx_from_ma(sma20_pct: float | None, sma50_pct: float | None, sma200_pct: float | None) -> float:
    """Proxy ADX 15–35 from MA stack alignment when true ADX unavailable."""
    pcts = [p for p in (sma20_pct, sma50_pct, sma200_pct) if p is not None]
    if not pcts:
        return 18.0
    aligned_up = sum(1 for p in pcts if p >= 0)
    aligned_dn = sum(1 for p in pcts if p < 0)
    spread = max(pcts) - min(pcts)
    if aligned_up == len(pcts) or aligned_dn == len(pcts):
        return min(35.0, 22.0 + spread * 0.4)
    if spread < 3:
        return 16.0
    return 22.0


def _structure_bias(sma20_pct: float | None, sma50_pct: float | None, direction: str = "long") -> str:
    up = sum(1 for p in (sma20_pct, sma50_pct) if p is not None and p >= 0)
    dn = sum(1 for p in (sma20_pct, sma50_pct) if p is not None and p < 0)
    if up >= 2:
        return "bullish"
    if dn >= 2:
        return "bearish"
    return "neutral"


def score_regime(ctx: dict, cfg: dict | None = None) -> dict[str, Any]:
    """Score regimes from a symbol context dict. Does not apply hysteresis."""
    cfg = cfg or _load_yaml()
    det = (cfg.get("detection") or {}).get("inputs") or {}
    scores = {k: 0.0 for k in REGIME_KEYS}

    rvol = _f(ctx.get("rvol"))
    adx = _f(ctx.get("adx"))
    atr_pct = _f(ctx.get("atr_pct"))
    sma20 = _f(ctx.get("sma20_pct"))
    sma50 = _f(ctx.get("sma50_pct"))
    sma200 = _f(ctx.get("sma200_pct"))
    gap_pct = abs(_f(ctx.get("gap_pct"), 0) or 0)
    direction = str(ctx.get("direction") or "long").lower()

    if adx is None:
        adx = _estimate_adx_from_ma(sma20, sma50, sma200)

    bias = _structure_bias(sma20, sma50, direction)
    if ctx.get("structure_bias"):
        bias = str(ctx["structure_bias"])

    # High volatility / event
    if (atr_pct or 0) >= det.get("atr_expansion_pct", 25) or gap_pct >= 4 or (rvol or 0) >= 3.5:
        scores["high_volatility"] += 4
    if (rvol or 0) >= 2.5 and (atr_pct or 0) >= 18:
        scores["high_volatility"] += 2

    # Strong trending
    if (rvol or 0) >= det.get("rvol_strong_min", 1.8) and adx >= det.get("adx_strong_min", 25):
        if bias == "bullish" or (direction == "long" and (sma20 or 0) >= 0):
            scores["strong_trending_bull"] += 5
        elif bias == "bearish" or direction == "short":
            scores["strong_trending_bear"] += 5
        else:
            scores["trending"] += 3

    # Normal trending
    if adx >= det.get("adx_ranging_max", 20):
        scores["trending"] += 2
        if bias == "bullish":
            scores["strong_trending_bull"] += 1
        elif bias == "bearish":
            scores["strong_trending_bear"] += 1

    # Ranging / low vol
    if adx < det.get("adx_ranging_max", 20) and (rvol or 1) <= det.get("rvol_low_max", 1.2):
        scores["ranging"] += 4
    if adx < 18 and abs(sma20 or 0) < 2 and abs(sma50 or 0) < 3:
        scores["ranging"] += 2

    # Tie-break toward trending when moderate ADX + RVOL
    if (rvol or 0) >= 1.3 and 20 <= adx < 25:
        scores["trending"] += 2

    winner = max(scores, key=scores.get)
    total = sum(scores.values()) or 1
    confidence = round(100.0 * scores[winner] / total, 1)

    regimes_cfg = cfg.get("regimes") or {}
    meta = regimes_cfg.get(winner) or {}
    trail_band = meta.get("trail_multiplier_band")

    parts = [
        f"RVOL={rvol if rvol is not None else '?'}",
        f"ADX≈{round(adx, 1)}",
        f"structure={bias}",
    ]
    if atr_pct is not None:
        parts.append(f"ATR%={round(atr_pct, 1)}")

    return {
        "regime": winner,
        "regime_label": meta.get("label") or winner.replace("_", " ").title(),
        "regime_short": meta.get("short") or winner[:6].upper(),
        "confidence": confidence,
        "direction": direction,
        "scores": scores,
        "adx_used": round(adx, 2),
        "rvol": rvol,
        "structure_bias": bias,
        "trail_multiplier_band": trail_band,
        "explanation": "; ".join(parts),
    }


def _state_path(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parent.parent.parent
    return root / "data" / "runtime" / "symbol_regime_state.json"


def _load_state(project_root: Path | None = None) -> dict:
    p = _state_path(project_root)
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_state(state: dict, project_root: Path | None = None) -> None:
    p = _state_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, default=str))


def detect_regime(
    symbol: str,
    ctx: dict,
    *,
    entry_regime: str | None = None,
    project_root: Path | None = None,
    cfg: dict | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Detect regime with hysteresis; optionally persist per-symbol state."""
    cfg = cfg or _load_yaml()
    sym = str(symbol).upper()
    raw = score_regime(ctx, cfg)
    hysteresis = (cfg.get("detection") or {}).get("hysteresis") or {}
    confirm_bars = int(hysteresis.get("confirm_bars", 3))
    min_conf_shift = float(hysteresis.get("shift_min_confidence", 60))

    state = _load_state(project_root)
    prev = state.get(sym) or {}
    prev_regime = prev.get("regime") or entry_regime
    candidate = raw["regime"]
    streak = prev.get("candidate_streak", 0)
    streak_regime = prev.get("candidate_regime")

    if candidate == streak_regime:
        streak += 1
    else:
        streak_regime = candidate
        streak = 1

    current = prev.get("regime") or candidate
    if candidate != current:
        if streak >= confirm_bars and raw["confidence"] >= min_conf_shift:
            current = candidate
        else:
            current = prev.get("regime") or candidate

    shift_detected = False
    shift_from = shift_to = shift_direction = None
    if prev_regime and current != prev_regime:
        shift_detected = True
        shift_from, shift_to = prev_regime, current
        shift_direction = f"{shift_from} → {shift_to}"

    regimes_cfg = cfg.get("regimes") or {}
    cur_meta = regimes_cfg.get(current) or {}
    trail_tighten = None
    if shift_detected and prev_regime in ("strong_trending_bull", "strong_trending_bear", "trending") and current == "ranging":
        trail_tighten = (regimes_cfg.get("regime_shift") or {}).get("trail_tighten_atr_mult", 0.5)

    out = {
        **raw,
        "regime": current,
        "regime_at_entry": entry_regime or prev.get("entry_regime") or current,
        "regime_shift_detected": shift_detected,
        "regime_shift_from": shift_from,
        "regime_shift_to": shift_to,
        "regime_shift_direction": shift_direction,
        "trail_tighten_atr_mult": trail_tighten,
        "stop_adjust_factor": trail_tighten,
        "candidate_regime": candidate,
        "candidate_streak": streak,
    }

    if persist:
        state[sym] = {
            "regime": current,
            "entry_regime": out["regime_at_entry"],
            "candidate_regime": streak_regime,
            "candidate_streak": streak,
            "confidence": raw["confidence"],
            "updated_at": ctx.get("as_of"),
        }
        if not prev.get("entry_regime"):
            state[sym]["entry_regime"] = current
        _save_state(state, project_root)

    return out


def build_context_from_enrich(
    enrich: dict | None,
    *,
    price: float | None = None,
    direction: str = "long",
    gap_pct: float | None = None,
) -> dict:
    """Map finviz enrichment cache row → regime detection context."""
    e = enrich or {}
    px = price or _f(e.get("price"))
    atr = _f(e.get("atr"))
    atr_pct = round(atr / px * 100, 2) if (atr and px) else _f(e.get("atr_pct"))
    return {
        "rvol": _f(e.get("rvol")),
        "atr": atr,
        "atr_pct": atr_pct,
        "adx": _f(e.get("adx")),
        "sma20_pct": _f(e.get("sma20_pct")),
        "sma50_pct": _f(e.get("sma50_pct")),
        "sma200_pct": _f(e.get("sma200_pct")),
        "rsi": _f(e.get("rsi")),
        "gap_pct": gap_pct,
        "direction": direction,
        "price": px,
    }