"""Active Trader Stage 1b — near-ready candidate read model (pure; NO orders, NO fire).

A near-ready candidate is a symbol that is NOT (yet) a classic Trade AI scanner GO
(it is below the ~5x RVOL / actionable-GO bar) but shows *building* characteristics:
elevated-but-sub-GO relative volume, constructive momentum, a pullback-break setup, and
a constructive (not overbought) RSI. It is a WATCH-QUALITY read only — the operator opts
in later; nothing here routes, fires, or authorizes anything.

**Not equivalent to a Trade AI GO.** A candidate at/above the GO RVOL bar (or already
flagged actionable-GO) is EXCLUDED here — it belongs to the main scanner, not this desk.

PURE: `score_candidate` / `select_near_ready` take candidate dicts (from a fixture or an
existing scanner/watch payload) + optional config and return scored dicts. No I/O, no
network, no broker writes. Deterministic given the same input + config.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

CONTRACT = "active-trader-near-ready-v1"

# Tiers
NEAR_READY = "near_ready"
WATCH = "watch"
EXCLUDED = "excluded"
EXCLUDED_ALREADY_GO = "excluded_already_go"

# Deterministic default thresholds (config-overridable).
DEFAULT_CONFIG: dict[str, Any] = {
    "go_rvol": 5.0,             # classic Trade AI GO relative-volume bar; >= => already GO
    "near_rvol_min": 1.5,       # building-volume floor (elevated but below GO)
    "momentum_min_pct": 1.0,    # constructive up-move floor
    "momentum_max_pct": 60.0,   # above this is parabolic/GO territory, not "building"
    "rsi_min": 45.0,            # constructive band — not oversold-dead
    "rsi_max": 68.0,            # ...not overbought
    "pullback_setups": ("pullback", "pullback_break", "breakout", "flag",
                        "bull_flag", "base", "vwap_reclaim"),
    "min_signals": 2,           # >= this many building signals => near_ready
}

_SIGNAL_KEYS = ("building_volume", "momentum", "pullback_break", "constructive_rsi")


def _f(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cfg(config: Mapping[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_CONFIG)
    if isinstance(config, Mapping):
        for k, v in config.items():
            if k in out and v is not None:
                out[k] = v
    return out


def _get(cand: Mapping[str, Any], *names: str) -> Any:
    for n in names:
        if n in cand and cand.get(n) is not None:
            return cand.get(n)
    return None


def score_candidate(candidate: Mapping[str, Any], config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Score one candidate. Never raises on a partial record — missing fields just fail
    their signal. Returns the candidate's near-ready assessment (read-only)."""
    cfg = _cfg(config)
    cand = candidate if isinstance(candidate, Mapping) else {}
    symbol = str(_get(cand, "symbol", "ticker") or "").upper()

    rvol = _f(_get(cand, "rvol", "relative_volume"))
    chg = _f(_get(cand, "change_pct", "change_percent"))
    rsi = _f(_get(cand, "rsi", "rsi_14"))
    setup = str(_get(cand, "entry_setup", "setup", "setup_type") or "").lower()
    actionable_go = bool(_get(cand, "decision_actionable") is True
                         and str(_get(cand, "verdict", "decision", "operator_pill") or "").upper() in ("GO", "STRONG_GO"))

    # already a classic GO -> excluded from this desk
    is_trade_ai_go = (rvol is not None and rvol >= cfg["go_rvol"]) or actionable_go

    signals: dict[str, bool] = {
        "building_volume": rvol is not None and cfg["near_rvol_min"] <= rvol < cfg["go_rvol"],
        "momentum": chg is not None and cfg["momentum_min_pct"] <= chg <= cfg["momentum_max_pct"],
        "pullback_break": any(s in setup for s in cfg["pullback_setups"]) if setup else False,
        "constructive_rsi": rsi is not None and cfg["rsi_min"] <= rsi <= cfg["rsi_max"],
    }
    n = sum(1 for v in signals.values() if v)

    reasons: list[str] = []
    if signals["building_volume"]:
        reasons.append(f"building volume rvol={rvol:.1f} (below {cfg['go_rvol']:g}x GO)")
    if signals["momentum"]:
        reasons.append(f"constructive momentum {chg:+.1f}%")
    if signals["pullback_break"]:
        reasons.append(f"pullback/break setup ({setup})")
    if signals["constructive_rsi"]:
        reasons.append(f"constructive RSI {rsi:.0f}")

    if is_trade_ai_go:
        tier = EXCLUDED_ALREADY_GO
    elif n >= cfg["min_signals"]:
        tier = NEAR_READY
    elif n >= 1:
        tier = WATCH
    else:
        tier = EXCLUDED

    return {
        "symbol": symbol,
        "tier": tier,
        "score": n,                       # 0..4 building signals
        "max_score": len(_SIGNAL_KEYS),
        "signals": signals,
        "reasons": reasons,
        "is_trade_ai_go": is_trade_ai_go,
        "rvol": rvol,
        "change_pct": chg,
        "rsi": rsi,
        "setup": setup or None,
        "not_a_go_note": "Near-ready is a weaker, building-characteristics read — NOT a Trade AI GO.",
    }


def select_near_ready(
    candidates: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any] | None = None,
    *,
    include_watch: bool = False,
) -> list[dict[str, Any]]:
    """Score all candidates and return the near-ready list (highest score first).

    include_watch=True also returns 1-signal `watch` rows. Already-GO and 0-signal rows are
    always excluded. Pure and deterministic."""
    scored = [score_candidate(c, config) for c in (candidates or [])]
    keep = {NEAR_READY} | ({WATCH} if include_watch else set())
    out = [s for s in scored if s["tier"] in keep]
    out.sort(key=lambda s: (s["score"], s.get("rvol") or 0.0), reverse=True)
    return out
