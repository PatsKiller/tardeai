#!/usr/bin/env python3
"""holding_family.py — map a HOLDING to a trailing-stop strategy family + its protection bounds.

Reuses the EXISTING classification in config/asset_classification_rules.json (bucket_overrides +
asset_type_overrides + aliases) — no new per-symbol hardcoding. Buckets already tag holdings
(dividend_income / bond_income / swing_trade / growth_fund / defense_aerospace …); this module folds
those into the four trailing families (momentum / swing / income / position) from
strategy_trailing_policy and attaches per-family STOP/TRAIL width bounds the protection advisor uses.

  family, source = classify_family("BND")        # -> ("income", "bucket:bond_income")
  bounds = protection_bounds("position")          # -> {stop_min_pct, stop_max_pct, trail_min_pct, ...}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_CFG_PATH = Path(__file__).resolve().parent.parent / "config" / "asset_classification_rules.json"
_CFG_CACHE: Optional[dict] = None

# per-family protection profile — stop distance band (% below price) + trail band (% offset) + whether
# trailing is the norm for the family. Wider for long-hold families, tighter for fast ones. These are
# the BOUNDS the bounded prompt + sanity gate enforce; they sit alongside strategy_trailing_policy's
# R-tier model (which governs WHEN to tighten; this governs HOW WIDE).
FAMILY_PROTECTION = {
    "momentum": {"stop_min_pct": 2.0, "stop_max_pct": 6.0, "trail_min_pct": 3.0, "trail_max_pct": 6.0,
                 "trail_norm": True, "label": "Momentum", "hold": "fast / same-week"},
    "swing":    {"stop_min_pct": 3.0, "stop_max_pct": 8.0, "trail_min_pct": 4.0, "trail_max_pct": 8.0,
                 "trail_norm": True, "label": "Swing", "hold": "multi-day to weeks"},
    "income":   {"stop_min_pct": 4.0, "stop_max_pct": 10.0, "trail_min_pct": 5.0, "trail_max_pct": 10.0,
                 "trail_norm": False, "label": "Income", "hold": "long / held through noise"},
    "position": {"stop_min_pct": 5.0, "stop_max_pct": 12.0, "trail_min_pct": 6.0, "trail_max_pct": 12.0,
                 "trail_norm": True, "label": "Position / Core", "hold": "very long / compounder"},
}
DEFAULT_FAMILY = "position"   # conservative default: widest stop, no premature tightening

# Trailing activation gates (STOP_METHODOLOGY §3; operator 2026-07-06: normal lowered 10→9%).
TRAIL_PNL_PCT_NORMAL = 9.0
TRAIL_PNL_PCT_INCOME = 20.0
TRAIL_PNL_PCT_RUNNER = 20.0   # extended runner override in protection_advisor post-processing


def trail_pnl_threshold(family: str) -> float:
    """Min unrealized % gain before trailing is recommended (income families use the higher bar)."""
    return TRAIL_PNL_PCT_INCOME if not protection_bounds(family).get("trail_norm") else TRAIL_PNL_PCT_NORMAL


def trail_recommended_for_state(*, family: str, pnl_pct: float, price: float, sma50: float | None) -> bool:
    """Deterministic trail gate: profit threshold + price above 50d SMA."""
    if pnl_pct < trail_pnl_threshold(family):
        return False
    if sma50 is not None and sma50 > 0 and price <= sma50:
        return False
    return True


def trailing_floor(price: float, trail_pct: float) -> float:
    return round(price * (1 - trail_pct / 100.0), 2)


def lockin_eligible(*, live_price: float, trail_pct: float, fixed_stop: float) -> bool:
    """True when a trailing stop at trail_pct would lock a floor above the live fixed stop."""
    if live_price <= 0 or trail_pct <= 0 or fixed_stop <= 0:
        return False
    floor = trailing_floor(live_price, trail_pct)
    return floor > fixed_stop + max(0.01 * live_price, 0.01)

# bucket tag → family. First match wins, checked in this priority order.
_BUCKET_TO_FAMILY = [
    ("bond_income", "income"), ("dividend_income", "income"), ("dividend_etf", "income"),
    ("reit_income", "income"), ("high_yield", "income"), ("covered_call", "income"),
    ("scalp", "momentum"), ("gap", "momentum"), ("momentum", "momentum"),
    ("swing_trade", "swing"), ("breakout", "swing"), ("earnings", "swing"),
    ("growth_fund", "position"), ("core", "position"), ("index", "position"),
    ("compounder", "position"), ("defense_aerospace", "position"), ("space_defense", "position"),
]


def _cfg() -> dict:
    global _CFG_CACHE
    if _CFG_CACHE is None:
        try:
            _CFG_CACHE = json.loads(_CFG_PATH.read_text())
        except Exception:
            _CFG_CACHE = {}
    return _CFG_CACHE


def _resolve(symbol: str) -> str:
    """Apply config aliases (e.g. FID-CONTRA-F -> FCNTX)."""
    s = (symbol or "").strip().upper()
    return (_cfg().get("aliases") or {}).get(s, s)


def classify_family(symbol: str, atr_pct: float | None = None) -> tuple[str, str]:
    """Return (family, source). Priority: committed bucket tags → asset_type + volatility → default.
    source is human-readable provenance ('bucket:bond_income' / 'etf->position' / 'stock vol 6.1%')."""
    s = _resolve(symbol)
    cfg = _cfg()
    buckets = [str(b).lower() for b in (cfg.get("bucket_overrides") or {}).get(s, [])]
    for tag, fam in _BUCKET_TO_FAMILY:
        if any(tag in b for b in buckets):
            return fam, f"bucket:{tag}"
    # no bucket tag — fall back to asset type + volatility
    at = ((cfg.get("asset_type_overrides") or {}).get(s) or "").lower()
    if at in ("mutual_fund", "fund"):
        return "position", f"{at}->position"
    if at == "etf":
        return "position", "etf->position"   # broad/sector ETF; income ETFs are caught by buckets above
    if at == "stock":
        if atr_pct is not None:
            if atr_pct >= 8:
                return "momentum", f"stock vol {atr_pct:.1f}%"
            if atr_pct >= 4:
                return "swing", f"stock vol {atr_pct:.1f}%"
        return "position", "stock low-vol/large-cap"
    return DEFAULT_FAMILY, "default"


def is_mutual_fund(symbol: str) -> bool:
    """True for an open-end mutual fund — which CANNOT take an exchange stop order (it transacts at
    end-of-day NAV). Config asset_type_overrides first (authoritative); otherwise the standard US
    mutual-fund ticker convention: 5 letters ending in 'X' (FCNTX/FSELX/AMANX…). ETFs (SCHD/SCHG/JEPI)
    are ≤4 letters or tagged 'etf' in config, so they return False and remain stop-eligible."""
    s = _resolve(symbol)
    at = ((_cfg().get("asset_type_overrides") or {}).get(s) or "").lower()
    if at in ("mutual_fund", "fund"):
        return True
    if at in ("etf", "stock"):
        return False
    return len(s) == 5 and s.isalpha() and s.endswith("X")


def is_unstoppable_fund(symbol: str) -> bool:
    """True when NO exchange stop order can be placed on the holding — so a protective-stop advisory is
    not actionable (manage via trim / rebalance instead). Covers BOTH:
      • open-end mutual funds (is_mutual_fund) — transact at end-of-day NAV; and
      • 401(k) / separate-account / collective fund codes carried in holding_proxies.HOLDING_PROXY_MAP
        (e.g. SP500-D, JPM-LGCG, WM-BLAIR) — proxy-mapped to a tradeable ETF for technicals only; the
        plan holding itself can't take a stop."""
    s = (symbol or "").strip().upper()
    if is_mutual_fund(s):
        return True
    try:
        from holding_proxies import HOLDING_PROXY_MAP
        if s in HOLDING_PROXY_MAP:
            return True
    except Exception:
        pass
    # Not a standard US exchange ticker → a fund / plan / internal code with no exchange stop. A real
    # equity/ETF ticker is 1-5 letters (optionally a class suffix like BRK.B); Fidelity 401k codes read via
    # SnapTrade (OG51, 3905, O7Z6, OM09 …) contain digits / non-letters, so no stop order can be placed.
    core = s.split(".")[0]
    if core and not (core.isalpha() and 1 <= len(core) <= 5):
        return True
    return False


def protection_bounds(family: str) -> dict:
    return FAMILY_PROTECTION.get(family, FAMILY_PROTECTION[DEFAULT_FAMILY])


if __name__ == "__main__":
    import sys
    syms = sys.argv[1:] or ["BND", "JEPI", "SCHD", "AVAV", "KTOS", "RKLB", "LMT", "FCNTX", "SCHG", "V", "NVDA"]
    for s in syms:
        fam, src = classify_family(s)
        b = protection_bounds(fam)
        print(f"{s:6} -> {fam:9} ({src:28}) stop {b['stop_min_pct']}-{b['stop_max_pct']}% · "
              f"trail {b['trail_min_pct']}-{b['trail_max_pct']}% · trail_norm={b['trail_norm']}")
