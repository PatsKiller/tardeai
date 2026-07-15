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

# ── stop_policy.yaml (2026-07-14): tiers/bands/maps are operator config, not code ──
# Fail-soft: a missing or invalid file leaves the legacy constants above in force.
_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "stop_policy.yaml"
_ETF_OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "config" / "etf_classification_overrides.json"
_POLICY_CACHE: Optional[dict] = None
_POLICY_MTIME: float = 0.0


def _policy() -> dict:
    """Load stop_policy.yaml with mtime-based reload; {} on any failure (legacy fallback)."""
    global _POLICY_CACHE, _POLICY_MTIME
    try:
        m = _POLICY_PATH.stat().st_mtime
        if _POLICY_CACHE is None or m != _POLICY_MTIME:
            import yaml
            raw = yaml.safe_load(_POLICY_PATH.read_text()) or {}
            _POLICY_CACHE = raw if raw.get("enabled", True) else {}
            _POLICY_MTIME = m
    except Exception:
        _POLICY_CACHE = {}
    return _POLICY_CACHE or {}


def _etf_asset_class(symbol: str) -> str:
    try:
        d = json.loads(_ETF_OVERRIDES_PATH.read_text())
        return str(((d.get("symbols") or {}).get(symbol) or {}).get("asset_class") or "").lower()
    except Exception:
        return ""


def policy_tiers() -> dict:
    """Active tier table: stop_policy.yaml tiers when present, else the legacy constants."""
    tiers = (_policy().get("tiers") or {})
    if tiers:
        return tiers
    return {k: dict(v) for k, v in FAMILY_PROTECTION.items()}

# Trailing activation gates (STOP_METHODOLOGY §3; operator 2026-07-06: normal lowered 10→9%).
TRAIL_PNL_PCT_NORMAL = 9.0
TRAIL_PNL_PCT_INCOME = 20.0
TRAIL_PNL_PCT_RUNNER = 20.0   # extended runner override in protection_advisor post-processing


def trail_pnl_threshold(family: str) -> float:
    """Min unrealized % gain before trailing is recommended. Per-tier value from
    stop_policy.yaml when present; legacy income/normal split otherwise."""
    b = protection_bounds(family)
    v = b.get("trail_pnl_threshold_pct")
    if v is not None:
        return float(v)
    return TRAIL_PNL_PCT_INCOME if not b.get("trail_norm") else TRAIL_PNL_PCT_NORMAL


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


_ENRICH_PATH = _POLICY_PATH.parent.parent / "data" / "state" / "ticker_enrichment_cache.json"
_VOLTIER_PATH = _POLICY_PATH.parent.parent / "data" / "state" / "volatility_tiers_latest.json"
_VOLTIER_CACHE: tuple[float, dict] | None = None
_ENRICH_CACHE: tuple[float, dict] | None = None
_REGIME_CACHE: tuple[float, dict] | None = None


def _state_json(path, cache_attr: str) -> dict:
    """mtime-cached JSON state file read; {} fail-soft."""
    global _VOLTIER_CACHE, _ENRICH_CACHE
    try:
        mt = path.stat().st_mtime
    except OSError:
        return {}
    cached = globals().get(cache_attr)
    if cached and cached[0] == mt:
        return cached[1]
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = {}
    globals()[cache_attr] = (mt, data)
    return data


def classify_volatility_tier(beta: float | None, atr_pct: float | None,
                             div_yield_pct: float | None = None,
                             sector: str | None = None) -> str | None:
    """Dynamic low/medium/high volatility tier — pure function of the inputs, rules
    from stop_policy.yaml volatility_classification (NO hardcoded symbols).
    Returns None when there is no usable data (caller falls through resolution)."""
    vc = _policy().get("volatility_classification") or {}
    if not vc.get("enabled", True):
        return None
    if beta is None and atr_pct is None:
        return None
    b = float(beta) if beta is not None else None
    a = float(atr_pct) if atr_pct is not None else None
    y = float(div_yield_pct) if div_yield_pct is not None else None
    # LOW: outright low beta, or a modest-beta income/low-volatility name
    if b is not None:
        if b <= float(vc.get("beta_low_max", 0.6)):
            return "low"
        if b <= float(vc.get("defensive_beta_max", 0.85)):
            if y is not None and y >= float(vc.get("defensive_yield_min_pct", 3.0)):
                return "low"
            if a is not None and a <= float(vc.get("atr_low_max_pct", 1.5)):
                return "low"
    # HIGH: high beta, high realized volatility, or a high-vol sector with real beta
    if b is not None and b >= float(vc.get("beta_high_min", 1.0)):
        return "high"
    if a is not None and a >= float(vc.get("atr_high_min_pct", 3.5)):
        return "high"
    if (sector and b is not None
            and sector in (vc.get("high_vol_sectors") or [])
            and b >= float(vc.get("sector_beta_min", 0.9))):
        return "high"
    if b is None and a is not None and a <= float(vc.get("atr_low_max_pct", 1.5)):
        return "low"
    return "medium"


def volatility_tier(symbol: str) -> dict | None:
    """Stored volatility tier for a symbol: prefers the daily-refreshed state file
    (volatility_tier_refresh.py), falls back to classifying live from the enrichment
    cache. Returns {tier, beta, atr_pct, ...} or None."""
    s = _resolve(symbol)
    row = (_state_json(_VOLTIER_PATH, "_VOLTIER_CACHE").get("tiers") or {}).get(s)
    if isinstance(row, dict) and row.get("tier") in ("low", "medium", "high"):
        return row
    rec = _state_json(_ENRICH_PATH, "_ENRICH_CACHE").get(s) or {}
    # atr_pct deliberately None here: the cache's volatility_w_pct is a misparsed
    # Finviz column (values like 46.58 for V) and atr is in dollars with no price.
    # The daily refresh (volatility_tier_refresh.py) computes a real ATR% with live
    # prices and writes it to the state file, which is preferred above.
    tier = classify_volatility_tier(rec.get("beta"), None,
                                    rec.get("div_yield_pct"), rec.get("sector"))
    if tier:
        return {"tier": tier, "beta": rec.get("beta"), "atr_pct": None,
                "div_yield_pct": rec.get("div_yield_pct"),
                "sector": rec.get("sector"), "source": "enrichment_cache_live"}
    return None


def current_regime() -> dict:
    """Market regime posture from the newest market_regime_snapshots row (the same
    source as /api/v2/risk-regime/status). In-process cached 10 minutes; a stale or
    unreadable snapshot degrades to neutral — never blocks, never raises."""
    global _REGIME_CACHE
    import time
    now = time.time()
    if _REGIME_CACHE and now - _REGIME_CACHE[0] < 600:
        return _REGIME_CACHE[1]
    ra = _policy().get("regime_adjustments") or {}
    out = {"posture": "neutral", "label": None, "stale": True}
    if ra.get("enabled", True):
        try:
            from db_adapter import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""SELECT regime_label, stale_data, generated_at,
                                  EXTRACT(EPOCH FROM (NOW() - generated_at))/3600
                           FROM market_regime_snapshots
                           ORDER BY created_at DESC LIMIT 1""")
            row = cur.fetchone()
            conn.rollback()
            if row:
                label, stale_flag, gen_at, age_h = row
                fresh = (not stale_flag) and float(age_h or 1e9) <= float(
                    ra.get("stale_after_hours", 24))
                lm = ra.get("label_map") or {}
                posture = "neutral"
                for p in ("risk_on", "risk_off"):
                    if label in (lm.get(p) or []):
                        posture = p
                out = {"posture": posture if fresh else "neutral", "label": label,
                       "generated_at": str(gen_at), "stale": not fresh}
        except Exception:
            pass
    _REGIME_CACHE = (now, out)
    return out


def classify_family(symbol: str, atr_pct: float | None = None) -> tuple[str, str]:
    """Return (tier, source). Resolution (stop_policy.yaml when present, legacy otherwise):
    symbol_tier_overrides → bucket tags → etf asset_class → asset_type + ATR volatility →
    default. source is human-readable provenance."""
    s = _resolve(symbol)
    cfg = _cfg()
    pol = _policy()
    tiers = policy_tiers()

    if pol:
        # 1. explicit operator pin
        ov = {str(k).upper(): v for k, v in (pol.get("symbol_tier_overrides") or {}).items()}
        if s in ov and ov[s] in tiers:
            return ov[s], "symbol_tier_override"
        # 2. bucket tags (asset_classification_rules.json)
        buckets = [str(b).lower() for b in (cfg.get("bucket_overrides") or {}).get(s, [])]
        for pair in (pol.get("bucket_map") or []):
            try:
                tag, tier = str(pair[0]).lower(), str(pair[1])
            except Exception:
                continue
            if tier in tiers and any(tag in b for b in buckets):
                return tier, f"bucket:{tag}"
        # 3. dynamic volatility tier (beta/volatility/yield/sector — no hardcoded symbols)
        vt = volatility_tier(s)
        if vt:
            tier = (pol.get("volatility_tier_map") or {}).get(vt["tier"])
            if tier and tier in tiers:
                b = vt.get("beta")
                return tier, (f"vol_tier:{vt['tier']}"
                              + (f" β{float(b):.2f}" if b is not None else ""))
        # 4. ETF asset class (etf_classification_overrides.json)
        ac = _etf_asset_class(s)
        tier = (pol.get("asset_class_map") or {}).get(ac)
        if tier and tier in tiers:
            return tier, f"asset_class:{ac}"
        # 5. asset type + volatility fallback (type-specific BEFORE the generic vol map:
        # a low-vol individual stock is stock_core 7-10%, not the wide position band)
        at = ((cfg.get("asset_type_overrides") or {}).get(s) or "").lower()
        if at in ("mutual_fund", "fund"):
            return (pol.get("default_tier") or DEFAULT_FAMILY), f"{at}->default"
        if at == "stock":
            if atr_pct is not None and atr_pct >= 8 and "momentum" in tiers:
                return "momentum", f"stock vol {atr_pct:.1f}%"
            if atr_pct is not None and atr_pct >= 4 and "stock_tactical" in tiers:
                return "stock_tactical", f"stock vol {atr_pct:.1f}%"
            return ("stock_core" if "stock_core" in tiers else DEFAULT_FAMILY,
                    f"stock low-vol{f' {atr_pct:.1f}%' if atr_pct is not None else ''}")
        if atr_pct is not None:
            for row in (pol.get("volatility_map") or []):
                try:
                    if atr_pct <= float(row.get("max_atr_pct", 999)) and row.get("tier") in tiers:
                        return row["tier"], f"vol {atr_pct:.1f}%"
                except Exception:
                    continue
        return (pol.get("default_tier") or DEFAULT_FAMILY), "default"

    # ── legacy path (no policy file) — unchanged behavior ──
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


def protection_bounds(family: str, lifecycle_stage: str | None = None,
                      regime: dict | str | None = None,
                      position_value_usd: float | None = None,
                      is_stock: bool | None = None) -> dict:
    """Band for a tier/family, adjusted (cap end only, never below stop_min + 0.5) by:
    - regime posture (risk_on widens vol_high trail cap; risk_off tightens all caps);
      pass current_regime() (or a posture string) to opt in — None means no adjustment
    - lifecycle stage (hermes_holdings_lifecycle: watch/trim bias toward the tight end)
    - conviction size (small stock positions get a tighter cap)
    Every applied adjustment is recorded in the returned dict for provenance."""
    tiers = policy_tiers()
    b = dict(tiers.get(family) or tiers.get(_policy().get("default_tier") or DEFAULT_FAMILY)
             or FAMILY_PROTECTION[DEFAULT_FAMILY])
    ra = _policy().get("regime_adjustments") or {}
    posture = (regime.get("posture") if isinstance(regime, dict) else regime) or None
    if posture and ra.get("enabled", True):
        b["regime"] = posture
        if isinstance(regime, dict) and regime.get("label"):
            b["regime_label"] = regime["label"]
        adj = ra.get(posture) or {}
        applies = adj.get("applies_to_tiers")
        if not applies or family in applies:
            widen = float(adj.get("trail_max_widen_pct") or 0.0)
            if widen > 0:
                b["trail_max_pct"] = float(b["trail_max_pct"]) + widen
                b["regime_adjustment_pct"] = widen
            shrink_s = float(adj.get("stop_max_shrink_pct") or 0.0)
            shrink_t = float(adj.get("trail_max_shrink_pct") or 0.0)
            if shrink_s > 0:
                b["stop_max_pct"] = max(float(b["stop_min_pct"]) + 0.5,
                                        float(b["stop_max_pct"]) - shrink_s)
                b["regime_adjustment_pct"] = -shrink_s
            if shrink_t > 0:
                b["trail_max_pct"] = max(float(b["trail_min_pct"]) + 0.5,
                                         float(b["trail_max_pct"]) - shrink_t)
    cm = _policy().get("conviction_modifiers") or {}
    if (cm.get("enabled") and is_stock and position_value_usd is not None
            and float(position_value_usd) < float(cm.get("small_position_max_usd", 10000))):
        shrink = float(cm.get("small_position_shrink_pct") or 0.0)
        if shrink > 0:
            b["stop_max_pct"] = max(float(b["stop_min_pct"]) + 0.5,
                                    float(b["stop_max_pct"]) - shrink)
            b["trail_max_pct"] = max(float(b["trail_min_pct"]) + 0.5,
                                     float(b["trail_max_pct"]) - shrink)
            b["conviction_tightened_pct"] = shrink
    if lifecycle_stage:
        mods = (_policy().get("lifecycle_modifiers") or {}).get(str(lifecycle_stage).lower()) or {}
        shrink = float(mods.get("stop_max_shrink_pct") or 0.0)
        if shrink > 0:
            b["stop_max_pct"] = max(float(b["stop_min_pct"]) + 0.5,
                                    float(b["stop_max_pct"]) - shrink)
            b["trail_max_pct"] = max(float(b["trail_min_pct"]) + 0.5,
                                     float(b["trail_max_pct"]) - shrink)
            b["lifecycle_stage"] = lifecycle_stage
            b["lifecycle_tightened_pct"] = shrink
    return b


if __name__ == "__main__":
    import sys
    syms = sys.argv[1:] or ["BND", "JEPI", "SCHD", "AVAV", "KTOS", "RKLB", "LMT", "FCNTX", "SCHG", "V", "NVDA"]
    for s in syms:
        fam, src = classify_family(s)
        b = protection_bounds(fam)
        print(f"{s:6} -> {fam:9} ({src:28}) stop {b['stop_min_pct']}-{b['stop_max_pct']}% · "
              f"trail {b['trail_min_pct']}-{b['trail_max_pct']}% · trail_norm={b['trail_norm']}")
