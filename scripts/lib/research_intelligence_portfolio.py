"""Portfolio context + multi-factor sizing for Research Intelligence.

v2.5: Security-level data (RSI, relative strength, earnings, valuation,
liquidity) plus concentration/heat drive ticker selection and size bands.

Advisory is gated by PRIMARY category — company_ticker briefs never recycle
the full SCHD/JEPI income sleeve unless the item is clearly dividend-primary.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
RISK_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "risk_management.json"

# Soft single-name max for non-core adds (% of book)
SINGLE_NAME_SOFT_MAX = 6.0
SINGLE_NAME_HARD_MAX = 10.0

# ── Theme universes ────────────────────────────────────────────────────
THEME_TICKERS: dict[str, list[str]] = {
    "defense": ["XAR", "RTX", "LDOS", "NOC", "CACI", "BAH", "LMT", "GD"],
    "power_infra": ["VST", "CEG", "EOSE", "VRT", "EQIX", "DLR", "NEE"],
    "ai_infra": ["ANET", "NVDA", "AVGO", "AMD", "MRVL", "SMCI", "CSCO"],
    "dividend_income": ["SCHD", "JEPI", "JEPQ", "DIVI", "DIV", "CSWC", "PFLT", "BND"],
    "growth": ["SCHG", "QQQ", "SPY", "V"],
    "materials": ["XLB", "FCX", "NUE"],
    "industrials": ["XLI", "CAT", "DE", "GE"],
    "healthcare": ["DXCM", "UNH", "LLY", "JNJ"],
    "bonds": ["BND", "TLT", "IEF", "AGG"],
}

# Soft max theme weight (% of book) — above this prefer rotate/upgrade, not net add
THEME_TARGET_MAX: dict[str, float] = {
    "defense": 10.0,
    "power_infra": 10.0,
    "ai_infra": 12.0,
    "dividend_income": 35.0,
    "growth": 42.0,
    "materials": 8.0,
    "industrials": 10.0,
    "healthcare": 10.0,
    "bonds": 15.0,
}

# Core long-horizon holdings — elevated weight is expected but still measured
CORE_HOLDINGS = frozenset({"SCHG", "SCHD", "V"})

# ── Concentration thresholds (single-name % of book) ───────────────────
CONC_ELEVATED = 12.0   # elevated weight
CONC_CAUTION = 20.0    # caution — prefer fund new risk from here
CONC_HIGH = 25.0       # high concentration — require trim for net new risk
CONC_EXTREME = 30.0    # extreme — block net new until rebalanced

# Non-core single-name soft cap
CONC_NONCORE_SOFT = 8.0
CONC_NONCORE_HARD = 12.0

# Portfolio heat (% risk at stop of total MV) from risk_management.json
HEAT_LOW = 5.0
HEAT_MODERATE = 8.0
HEAT_HIGH = 12.0
HEAT_EXTREME = 18.0

# Title/primary-gated theme detection
_THEME_RX_TITLE: list[tuple[str, re.Pattern[str]]] = [
    ("defense", re.compile(r"\bdefense\b|aerospace|military|\bxar\b", re.I)),
    ("power_infra", re.compile(r"power|utility|data\s*center|infrastructure|nuclear|\bvst\b|\bceg\b", re.I)),
    ("ai_infra", re.compile(r"\bai\b|semiconductor|chip|networking|nvidia", re.I)),
    ("dividend_income", re.compile(r"\bdividend\b|covered.?call|income sleeve|\byield\b|\bjepi\b|\bschd\b|\bbdc\b", re.I)),
    ("growth", re.compile(r"\bgrowth\b|nasdaq|megacap|\bschg\b", re.I)),
    ("materials", re.compile(r"materials|\bxlb\b|commodit", re.I)),
    ("industrials", re.compile(r"\bindustrial\b|\bxli\b", re.I)),
    ("healthcare", re.compile(r"healthcare|biotech|pharma|\bdxcm\b", re.I)),
    ("bonds", re.compile(r"\bbond\b|bond ladder|\btips\b|fixed.?income|\btreasur|\bbnd\b", re.I)),
]

_TICKER_TOKEN = re.compile(r"\b([A-Z]{1,5})\b")
_STOP_TYPES = {"stop_health", "stop_curation", "protection_advisory"}
_NOISE_TOKENS = frozenset({
    "AUTO", "RESEARCH", "OPTIONS", "DESK", "GROK", "STOP", "NEAR", "HEALTH",
    "PORT", "RISK", "MACRO", "RATES", "ETF", "CEO", "CFO", "USA", "IRS",
    "IRA", "MAPT", "SSDI", "IRMAA", "ROTH", "MAGI", "CMS", "FDA", "SEC",
})


# ═══════════════════════════════════════════════════════════════════════
# Loaders
# ═══════════════════════════════════════════════════════════════════════

def _load_risk_snapshot() -> dict[str, Any]:
    if not RISK_PATH.exists():
        return {}
    try:
        return json.loads(RISK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _name_level(weight: float, *, is_core: bool = False) -> str:
    if weight >= CONC_EXTREME:
        return "extreme"
    if weight >= CONC_HIGH:
        return "high"
    if weight >= CONC_CAUTION:
        return "caution"
    if is_core and weight >= CONC_ELEVATED:
        return "elevated"
    if not is_core and weight >= CONC_NONCORE_HARD:
        return "caution"
    if not is_core and weight >= CONC_NONCORE_SOFT:
        return "elevated"
    if weight >= CONC_ELEVATED:
        return "elevated"
    return "normal"


def _heat_level(heat: float) -> str:
    if heat >= HEAT_EXTREME:
        return "extreme"
    if heat >= HEAT_HIGH:
        return "high"
    if heat >= HEAT_MODERATE:
        return "moderate"
    if heat >= HEAT_LOW:
        return "elevated"
    return "low"


@lru_cache(maxsize=1)
def load_portfolio_context() -> dict[str, Any]:
    if not HOLDINGS_PATH.exists():
        return {"ok": False, "total_mv": 0.0, "by_symbol": {}, "top": [], "flags": []}
    try:
        doc = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "total_mv": 0.0, "by_symbol": {}, "top": [], "flags": []}

    by_sym: dict[str, dict[str, Any]] = {}
    for h in doc.get("holdings") or []:
        if h.get("is_cash"):
            continue
        sym = str(h.get("symbol") or "").upper().strip()
        if not sym or not re.fullmatch(r"[A-Z]{1,5}", sym):
            continue
        try:
            mv = float(h.get("market_value") or 0)
        except (TypeError, ValueError):
            mv = 0.0
        if mv <= 0:
            try:
                mv = float(h.get("shares") or 0) * float(h.get("price") or 0)
            except (TypeError, ValueError):
                mv = 0.0
        if mv <= 0:
            continue
        row = by_sym.setdefault(sym, {
            "symbol": sym, "market_value": 0.0, "accounts": set(), "name": h.get("name"),
        })
        row["market_value"] += mv
        if h.get("account"):
            row["accounts"].add(str(h["account"]))

    # Cash across accounts (is_cash holdings)
    cash_mv = 0.0
    try:
        doc2 = doc  # from load above
        for h in doc2.get("holdings") or []:
            if h.get("is_cash"):
                try:
                    cash_mv += float(h.get("market_value") or 0)
                except (TypeError, ValueError):
                    pass
    except Exception:
        cash_mv = 0.0

    total = sum(r["market_value"] for r in by_sym.values()) or 1.0
    # Household total including cash for dollar sizing
    total_with_cash = total + cash_mv if cash_mv > 0 else total
    for r in by_sym.values():
        r["weight_pct"] = round(100.0 * r["market_value"] / total, 2)
        r["accounts"] = sorted(r["accounts"])
        r["market_value"] = round(r["market_value"], 2)
        r["is_core"] = r["symbol"] in CORE_HOLDINGS
        r["concentration_level"] = _name_level(r["weight_pct"], is_core=r["is_core"])

    top = sorted(by_sym.values(), key=lambda x: -x["weight_pct"])

    # Single-name flags
    flags: list[str] = []
    name_conc: list[dict[str, Any]] = []
    for r in top:
        lvl = r["concentration_level"]
        if lvl in ("high", "extreme"):
            flags.append(
                f"{r['symbol']} is {r['weight_pct']:.1f}% of book ({lvl} concentration)"
            )
            name_conc.append({
                "symbol": r["symbol"], "weight_pct": r["weight_pct"],
                "level": lvl, "is_core": r["is_core"],
            })
        elif lvl == "caution":
            flags.append(
                f"{r['symbol']} is {r['weight_pct']:.1f}% of book (caution — prefer funding source)"
            )
            name_conc.append({
                "symbol": r["symbol"], "weight_pct": r["weight_pct"],
                "level": lvl, "is_core": r["is_core"],
            })
        elif lvl == "elevated" and r["weight_pct"] >= CONC_ELEVATED:
            if r["is_core"]:
                flags.append(
                    f"{r['symbol']} is {r['weight_pct']:.1f}% of book (core elevated)"
                )
            else:
                flags.append(
                    f"{r['symbol']} is {r['weight_pct']:.1f}% of book (elevated weight)"
                )
            name_conc.append({
                "symbol": r["symbol"], "weight_pct": r["weight_pct"],
                "level": lvl, "is_core": r["is_core"],
            })

    sleeves = {k: _sleeve_pct(by_sym, v) for k, v in THEME_TICKERS.items()}

    # Theme concentration + capacity
    theme_capacity: dict[str, dict[str, Any]] = {}
    theme_flags: list[str] = []
    for tid, tgt in THEME_TARGET_MAX.items():
        cur = float(sleeves.get(tid) or 0.0)
        room = round(max(0.0, tgt - cur), 2)
        util = round(100.0 * cur / tgt, 1) if tgt else 0.0
        if cur >= tgt:
            t_lvl = "full"
        elif cur >= tgt * 0.85:
            t_lvl = "elevated"
        elif cur >= tgt * 0.5:
            t_lvl = "moderate"
        else:
            t_lvl = "room"
        theme_capacity[tid] = {
            "current_pct": cur,
            "target_max_pct": tgt,
            "room_pct": room,
            "utilization_pct": util,
            "level": t_lvl,
        }
        if t_lvl == "full":
            theme_flags.append(
                f"{tid.replace('_', ' ')} sleeve ~{cur:.1f}% at/over soft max {tgt:.0f}%"
            )
        elif t_lvl == "elevated":
            theme_flags.append(
                f"{tid.replace('_', ' ')} sleeve ~{cur:.1f}% near soft max {tgt:.0f}% (room ~{room:.1f}%)"
            )

    # Heat / stop risk snapshot
    risk = _load_risk_snapshot()
    try:
        heat = float(risk.get("portfolio_heat_pct") or 0.0)
    except (TypeError, ValueError):
        heat = 0.0
    try:
        pct_protected = float(risk.get("pct_protected") or 0.0)
    except (TypeError, ValueError):
        pct_protected = 0.0
    heat_lvl = _heat_level(heat)
    if heat_lvl in ("high", "extreme"):
        flags.insert(0, f"Portfolio heat ~{heat:.1f}% ({heat_lvl}) — size new risk down")
    elif heat_lvl == "moderate":
        flags.insert(0, f"Portfolio heat ~{heat:.1f}% (moderate) — prefer funded adds")

    # Overall concentration score 0–100 (higher = more concentrated)
    hhi = sum((r["weight_pct"] / 100.0) ** 2 for r in by_sym.values())
    top3 = sum(r["weight_pct"] for r in top[:3])
    conc_score = round(min(100.0, hhi * 1000 + max(0, top3 - 40)), 1)
    if top3 >= 55 or any(r["concentration_level"] in ("high", "extreme") for r in top[:3]):
        book_conc_level = "high"
    elif top3 >= 45 or any(r["concentration_level"] == "caution" for r in top[:3]):
        book_conc_level = "elevated"
    else:
        book_conc_level = "normal"

    return {
        "ok": True,
        "total_mv": round(total_with_cash if cash_mv else total, 2),
        "invested_mv": round(total, 2),
        "cash_mv": round(cash_mv, 2),
        "by_symbol": by_sym,
        "top": [
            {
                "symbol": r["symbol"],
                "weight_pct": r["weight_pct"],
                "market_value": r["market_value"],
                "concentration_level": r["concentration_level"],
                "is_core": r["is_core"],
            }
            for r in top[:15]
        ],
        "flags": (flags + theme_flags)[:10],
        "sleeves": sleeves,
        "holdings_symbols": sorted(by_sym.keys()),
        "concentration": {
            "book_level": book_conc_level,
            "score": conc_score,
            "top3_pct": round(top3, 2),
            "hhi": round(hhi, 4),
            "names": name_conc[:8],
            "thresholds": {
                "elevated": CONC_ELEVATED,
                "caution": CONC_CAUTION,
                "high": CONC_HIGH,
                "extreme": CONC_EXTREME,
                "noncore_soft": CONC_NONCORE_SOFT,
            },
        },
        "theme_capacity": theme_capacity,
        "heat": {
            "portfolio_heat_pct": heat,
            "level": heat_lvl,
            "pct_protected": pct_protected,
            "stop_count": risk.get("stop_count"),
            "unprotected_n": len(risk.get("unprotected") or []) if isinstance(risk.get("unprotected"), list) else None,
            "thresholds": {
                "low": HEAT_LOW,
                "moderate": HEAT_MODERATE,
                "high": HEAT_HIGH,
                "extreme": HEAT_EXTREME,
            },
        },
    }


def _sleeve_pct(by_sym: dict[str, dict], tickers: list[str]) -> float:
    return round(sum(by_sym[t]["weight_pct"] for t in tickers if t in by_sym), 2)


def detect_themes_from_title(title: str | None) -> list[str]:
    blob = title or ""
    out = []
    for tid, rx in _THEME_RX_TITLE:
        if rx.search(blob) and tid not in out:
            out.append(tid)
    return out[:3]


def extract_mentioned_tickers(text: str, *, known: set[str] | None = None) -> list[str]:
    known = known or set()
    theme_all = {t for ts in THEME_TICKERS.values() for t in ts}
    found: list[str] = []
    for m in _TICKER_TOKEN.finditer(text or ""):
        t = m.group(1)
        if t in {
            "A", "I", "OR", "AND", "THE", "FOR", "TO", "OF", "ON", "IN", "AT", "BY",
            "ETF", "CEO", "CFO", "USA", "NY", "AI", "CMS", "IRS", "IRA", "MAPT", "SSDI",
        }:
            continue
        if t not in found and (t in known or t in theme_all):
            found.append(t)
    return found[:8]


# ═══════════════════════════════════════════════════════════════════════
# Sizing engine
# ═══════════════════════════════════════════════════════════════════════

def _heat_size_mult(heat_lvl: str) -> float:
    return {
        "low": 1.0,
        "elevated": 0.85,
        "moderate": 0.65,
        "high": 0.45,
        "extreme": 0.25,
    }.get(heat_lvl, 0.75)


def _book_conc_size_mult(book_lvl: str) -> float:
    return {
        "normal": 1.0,
        "elevated": 0.75,
        "high": 0.5,
    }.get(book_lvl, 0.8)


def funding_sources(portfolio: dict[str, Any], *, need_pct: float = 3.0) -> list[dict[str, Any]]:
    """Prefer high-concentration names as funding sources for new risk."""
    by_sym = portfolio.get("by_symbol") or {}
    sources: list[dict[str, Any]] = []
    for r in portfolio.get("top") or []:
        sym = r.get("symbol")
        if not sym or sym not in by_sym:
            continue
        w = float(by_sym[sym]["weight_pct"])
        lvl = by_sym[sym].get("concentration_level") or _name_level(
            w, is_core=sym in CORE_HOLDINGS
        )
        if lvl in ("high", "extreme", "caution") or (sym in CORE_HOLDINGS and w >= CONC_CAUTION):
            # Suggest trim band: fund the add, capped at ~20% of position or 6% of book
            need = max(float(need_pct or 2.0), 1.0)
            trim_lo = round(min(max(need, 1.0), max(1.0, w * 0.08), 4.0), 1)
            trim_hi = round(min(max(need * 1.8, trim_lo + 1.0), max(2.0, w * 0.18), 6.0), 1)
            if trim_hi <= trim_lo:
                trim_hi = round(trim_lo + 1.0, 1)
            sources.append({
                "symbol": sym,
                "role": "trim_candidate",
                "weight_pct": w,
                "level": lvl,
                "suggested_weight_pct": f"trim {trim_lo:.1f}–{trim_hi:.1f}% of book (now {w:.1f}%)",
                "rationale": (
                    f"Funding source — {sym} at {w:.1f}% ({lvl} concentration). "
                    f"Stage trims with stops intact (Replace mode)."
                ),
            })
        if len(sources) >= 2:
            break
    return sources


def size_new_position(
    portfolio: dict[str, Any],
    *,
    symbol: str | None = None,
    theme: str | None = None,
    conviction: str = "medium",  # low | medium | high  (operator thesis)
    risk_profile: str = "normal",  # low_vol | normal | high_vol (theme default)
    already_held: bool = False,
) -> dict[str, Any]:
    """Multi-factor size band: theme capacity × heat × concentration × vol × security conviction.

    Returns min/max % of book, human label, reasons, and whether a funding trim is required.
    """
    heat = portfolio.get("heat") or {}
    conc = portfolio.get("concentration") or {}
    heat_lvl = heat.get("level") or "low"
    book_lvl = conc.get("book_level") or "normal"
    heat_pct = float(heat.get("portfolio_heat_pct") or 0.0)
    top3 = float(conc.get("top3_pct") or 0.0)
    by_sym = portfolio.get("by_symbol") or {}
    schg_w = float((by_sym.get("SCHG") or {}).get("weight_pct") or 0.0)

    # 1) Base from theme capacity / conviction (not a flat 2%)
    conv_base = {"low": 1.5, "medium": 2.5, "high": 3.75}.get(conviction, 2.5)
    reasons: list[str] = []
    factors: list[str] = []

    theme_room = None
    theme_cur = None
    theme_tgt = None
    if theme:
        cap = (portfolio.get("theme_capacity") or {}).get(theme) or {}
        theme_room = float(cap.get("room_pct") or 0.0)
        theme_cur = float(cap.get("current_pct") or 0.0)
        theme_tgt = float(cap.get("target_max_pct") or THEME_TARGET_MAX.get(theme, 10.0))
        t_lvl = cap.get("level") or "room"
        if t_lvl == "full" or theme_room <= 0.25:
            reasons.append(
                f"{theme.replace('_', ' ')} sleeve ~{theme_cur:.1f}% at soft max {theme_tgt:.0f}% — no net add"
            )
            return {
                "allow_add": False,
                "min_pct": 0.0,
                "max_pct": 0.0,
                "label": "no net add — rebalance within sleeve",
                "require_funding_trim": True,
                "reasons": reasons,
                "theme_current_pct": theme_cur,
                "theme_room_pct": 0.0,
                "theme_target_pct": theme_tgt,
                "factors": factors,
            }
        # Base size = min(conviction base, ~40% of remaining theme room)
        room_cap = max(0.6, theme_room * 0.40)
        base = min(conv_base, room_cap)
        factors.append(f"theme_room→base {base:.2f}%")
        reasons.append(
            f"{theme.replace('_', ' ')} ~{theme_cur:.1f}% / max {theme_tgt:.0f}% "
            f"(room ~{theme_room:.1f}%) → base {base:.1f}%"
        )
    else:
        base = conv_base
        factors.append(f"conviction_base {base:.2f}%")

    # 2) Heat multiplier
    h_mult = _heat_size_mult(heat_lvl)
    if heat_lvl != "low":
        reasons.append(f"heat ~{heat_pct:.1f}% ({heat_lvl}) → ×{h_mult:.2f}")
        factors.append(f"heat×{h_mult:.2f}")

    # 3) Book concentration + proactive top-3 rule
    c_mult = _book_conc_size_mult(book_lvl)
    if top3 >= 50:
        c_mult *= 0.75
        reasons.append(f"top-3 concentration ~{top3:.0f}% > 50% → extra ×0.75")
        factors.append("top3>50×0.75")
    elif book_lvl != "normal":
        reasons.append(
            f"book concentration {book_lvl}"
            + (f" (top-3 ~{top3:.0f}%)" if top3 else "")
            + f" → ×{c_mult:.2f}"
        )
        factors.append(f"book×{c_mult:.2f}")

    # 4) Theme default vol profile
    profile_mult = {"low_vol": 1.1, "normal": 1.0, "high_vol": 0.75}.get(risk_profile, 1.0)

    # 5) Security-level vol + conviction (when symbol known)
    sec_vol_mult = 1.0
    sec_conv_mult = 1.0
    sec_tier = None
    sec_score = None
    if symbol:
        try:
            from lib.research_intelligence_security import get_security_snapshot
            snap = get_security_snapshot(symbol)
            sec_vol_mult = float(snap.get("vol_size_mult") or 1.0)
            sec_conv_mult = float(snap.get("conviction_size_mult") or 1.0)
            sec_tier = snap.get("conviction_tier")
            sec_score = snap.get("conviction_score")
            if sec_vol_mult != 1.0:
                reasons.append(
                    f"{symbol} vol/liquidity → ×{sec_vol_mult:.2f}"
                    + (f" (beta {snap.get('beta')})" if snap.get("beta") is not None else "")
                )
                factors.append(f"sec_vol×{sec_vol_mult:.2f}")
            if sec_tier:
                reasons.append(
                    f"{symbol} conviction {sec_tier} ({sec_score}) → ×{sec_conv_mult:.2f}"
                )
                factors.append(f"conv×{sec_conv_mult:.2f}")
            if not snap.get("has_min_data"):
                sec_conv_mult *= 0.7
                reasons.append(f"{symbol} missing RSI/min data → ×0.70")
                factors.append("sparse_data×0.70")
        except Exception:
            pass

    # 6) Held headroom
    if already_held and symbol and symbol in by_sym:
        cur = float(by_sym[symbol]["weight_pct"])
        soft = (
            CONC_CAUTION if symbol in CORE_HOLDINGS
            else min(CONC_NONCORE_HARD, SINGLE_NAME_SOFT_MAX)
        )
        headroom = max(0.0, soft - cur)
        if headroom <= 0:
            reasons.append(f"{symbol} already ~{cur:.1f}% — at soft cap, prefer hold/trim not add")
            return {
                "allow_add": False,
                "min_pct": 0.0,
                "max_pct": 0.0,
                "label": f"no add — {symbol} at ~{cur:.1f}% soft cap",
                "require_funding_trim": False,
                "reasons": reasons,
                "theme_current_pct": theme_cur,
                "theme_room_pct": theme_room,
                "theme_target_pct": theme_tgt,
                "factors": factors,
                "conviction_tier": sec_tier,
            }
        base = min(base, max(0.5, headroom * 0.5))
        reasons.append(f"{symbol} held ~{cur:.1f}% — headroom to soft cap ~{headroom:.1f}%")

    mult = h_mult * c_mult * profile_mult * sec_vol_mult * sec_conv_mult
    sized = base * mult

    # Hard caps
    hard_cap = SINGLE_NAME_HARD_MAX if not already_held else SINGLE_NAME_SOFT_MAX
    max_pct = round(min(hard_cap, max(0.4, sized)), 2)
    min_pct = round(max(0.4, max_pct * 0.55), 2)
    if max_pct < 0.7:
        min_pct, max_pct = 0.4, 0.7

    # Funded vs unfunded — proactive concentration rules
    require_trim = (
        book_lvl == "high"
        or heat_lvl in ("high", "extreme")
        or top3 >= 50
        or schg_w >= 24.0
    )
    prefer_funded = require_trim or book_lvl == "elevated" or heat_lvl in ("moderate", "elevated")
    if schg_w >= 24.0:
        reasons.append(
            f"SCHG ~{schg_w:.1f}% ≥ 24% → strongly prefer trim SCHG before unfunded add"
        )
        factors.append("SCHG≥24 fund")
    elif prefer_funded:
        reasons.append("prefer funding trim over cash/new beta (concentration/heat)")
        factors.append("funded")

    total_mv = float(portfolio.get("total_mv") or 0.0)
    cash = float(portfolio.get("cash_mv") or 0.0)
    # Risk-aware: risk $ at ~1% of book for mid of band (stop ~8% below entry heuristic)
    mid_pct = (min_pct + max_pct) / 2.0
    dollar_lo = round(total_mv * min_pct / 100.0, 0) if total_mv else None
    dollar_hi = round(total_mv * max_pct / 100.0, 0) if total_mv else None
    risk_1pct = round(total_mv * 0.01, 0) if total_mv else None
    # Cap size by cash if unfunded and cash is scarce
    if not prefer_funded and cash > 0 and dollar_hi and dollar_hi > cash * 0.9:
        # Shrink to available cash
        max_from_cash = max(0.4, 100.0 * (cash * 0.85) / total_mv) if total_mv else max_pct
        if max_from_cash < max_pct:
            reasons.append(
                f"cash ~${cash:,.0f} caps unfunded add → max ~{max_from_cash:.1f}% of book"
            )
            max_pct = round(max_from_cash, 2)
            min_pct = round(max(0.4, max_pct * 0.55), 2)
            dollar_lo = round(total_mv * min_pct / 100.0, 0)
            dollar_hi = round(total_mv * max_pct / 100.0, 0)
            mid_pct = (min_pct + max_pct) / 2.0

    label = f"{min_pct:.1f}–{max_pct:.1f}% of book"
    if dollar_lo is not None and dollar_hi is not None:
        label += f" (${dollar_lo:,.0f}–${dollar_hi:,.0f})"
    if prefer_funded:
        label += " (funded)"
    if not already_held:
        label += " starter after diligence"
    if sec_tier:
        label += f" · conv {sec_tier}"

    if risk_1pct:
        reasons.append(
            f"risk budget: ~1% of book ≈ ${risk_1pct:,.0f} (size so a ~8% stop ≈ that risk)"
        )
        factors.append("risk_1pct")

    return {
        "allow_add": True,
        "min_pct": min_pct,
        "max_pct": max_pct,
        "label": label,
        "dollar_lo": dollar_lo,
        "dollar_hi": dollar_hi,
        "risk_budget_1pct_usd": risk_1pct,
        "cash_mv": cash,
        "require_funding_trim": prefer_funded,
        "reasons": reasons,
        "factors": factors,
        "theme_current_pct": theme_cur,
        "theme_room_pct": theme_room,
        "theme_target_pct": theme_tgt,
        "heat_level": heat_lvl,
        "book_concentration": book_lvl,
        "conviction_tier": sec_tier,
        "conviction_score": sec_score,
        "diversification_note": (
            f"Top-3 is ~{top3:.0f}% today; a funded {max_pct:.1f}% add from SCHG "
            f"slightly improves diversification if SCHG is trimmed first."
            if prefer_funded and schg_w >= 20
            else f"Top-3 ~{top3:.0f}% — unfunded adds worsen concentration."
            if top3 >= 50
            else None
        ),
    }


def _finalize_ticker_recs(
    tickers: list[dict[str, Any]],
    *,
    portfolio: dict[str, Any],
) -> list[dict[str, Any]]:
    """Attach security conviction; rank/filter low-quality add candidates."""
    try:
        from lib.research_intelligence_security import (
            enrich_ticker_recommendation,
            get_security_snapshot,
        )
    except Exception:
        return tickers[:6]

    total_mv = float(portfolio.get("total_mv") or 0)
    out: list[dict[str, Any]] = []
    for t in tickers:
        role = t.get("role") or "hold_review"
        sym = (t.get("symbol") or "").upper()
        if role == "add_candidate" and sym:
            snap = get_security_snapshot(sym)
            rsi = snap.get("rsi")
            if rsi is not None and rsi >= 78 and snap.get("conviction_tier") == "C":
                t = dict(t)
                t["role"] = "watchlist"
                t["suggested_weight_pct"] = "watch — overbought / low conviction"
            if snap.get("liquidity") == "thin":
                t = dict(t)
                t["role"] = "watchlist"
                t["suggested_weight_pct"] = "watch — thin liquidity"
            if not snap.get("data_complete"):
                t = dict(t)
                t["role"] = "watchlist"
                t["suggested_weight_pct"] = "watch — incomplete RSI/RS"
        out.append(enrich_ticker_recommendation(
            t, role=t.get("role"), portfolio_total_mv=total_mv,
        ))
    return out[:6]


def _pick_theme_adds(
    theme_tickers: list[str],
    *,
    held: set[str],
    portfolio: dict[str, Any],
    size: dict[str, Any],
    max_n: int = 3,
) -> list[dict[str, Any]]:
    """Select add candidates using security ranking, not raw theme list order."""
    try:
        from lib.research_intelligence_security import filter_add_candidates
    except Exception:
        filter_add_candidates = None  # type: ignore

    candidates = [t for t in theme_tickers if t not in held]
    if not candidates:
        return []
    if filter_add_candidates:
        ranked = filter_add_candidates(candidates, min_conviction=45.0, require_rsi=True, max_n=max_n)
        symbols = [s.get("symbol") for s in ranked if s.get("symbol")]
    else:
        symbols = candidates[:max_n]

    recs = []
    for sym in symbols:
        if not size.get("allow_add"):
            recs.append({
                "symbol": sym,
                "role": "watchlist",
                "suggested_weight_pct": "watch only — theme at capacity",
                "rationale": "Theme capacity full — research/watch, not fund.",
            })
        else:
            # Re-size per symbol for vol/conviction
            sym_size = size_new_position(
                portfolio,
                symbol=sym,
                theme=None,  # already capacity-checked
                conviction="medium",
                already_held=False,
            )
            # Re-apply theme room cap from parent size
            if size.get("max_pct") and sym_size.get("max_pct"):
                cap = float(size["max_pct"])
                if float(sym_size["max_pct"]) > cap:
                    sym_size = dict(sym_size)
                    sym_size["max_pct"] = cap
                    sym_size["min_pct"] = round(max(0.4, cap * 0.55), 2)
                    sym_size["label"] = (
                        f"{sym_size['min_pct']:.1f}–{sym_size['max_pct']:.1f}% of book"
                        + (" (funded)" if size.get("require_funding_trim") else "")
                        + " starter after diligence"
                        + (f" · conv {sym_size.get('conviction_tier')}" if sym_size.get("conviction_tier") else "")
                    )
            recs.append({
                "symbol": sym,
                "role": "add_candidate" if sym_size.get("allow_add") else "watchlist",
                "suggested_weight_pct": sym_size.get("label") if sym_size.get("allow_add") else "research only",
                "rationale": "Theme peer ranked by RSI/relative strength/valuation/earnings factors.",
            })
    return recs


def size_held_review(
    portfolio: dict[str, Any],
    symbol: str,
) -> dict[str, Any]:
    """Sizing language for an existing holding based on concentration."""
    by_sym = portfolio.get("by_symbol") or {}
    if symbol not in by_sym:
        return {"label": "not held", "role": "watchlist", "bits": []}
    w = float(by_sym[symbol]["weight_pct"])
    mv = float(by_sym[symbol]["market_value"])
    lvl = by_sym[symbol].get("concentration_level") or _name_level(
        w, is_core=symbol in CORE_HOLDINGS
    )
    heat_lvl = (portfolio.get("heat") or {}).get("level") or "low"
    bits: list[str] = []
    role = "hold_review"

    if lvl in ("high", "extreme"):
        role = "trim_candidate" if w >= CONC_HIGH else "hold_review"
        bits.append(
            f"{symbol} is ~{w:.1f}% of book ({lvl} concentration, ${mv:,.0f}). "
            f"If thesis weakens, stage trim 10–20% of the position "
            f"(~{w * 0.1:.1f}–{w * 0.2:.1f}% of portfolio) — not all-or-nothing. "
            f"Confirm stop health (Replace mode) first."
        )
    elif lvl == "caution":
        bits.append(
            f"{symbol} ~{w:.1f}% (caution band). Prefer this name as a funding source "
            f"for diversifying adds; size changes ±1–2% of book max per action. "
            f"Keep a healthy stop."
        )
    elif lvl == "elevated":
        bits.append(
            f"{symbol} ~{w:.1f}% — material weight. Size changes ±1–2% of book; "
            f"any add must clear stop policy and heat ({heat_lvl})."
        )
    else:
        bits.append(
            f"{symbol} is a small ~{w:.1f}% sleeve (${mv:,.0f}) — prefer fix stops over rebalancing noise. "
            f"Add only if thesis is high conviction and heat allows."
        )
    return {
        "label": f"current {w:.1f}% (${mv:,.0f})",
        "role": role,
        "weight_pct": w,
        "level": lvl,
        "bits": bits,
        "rationale": f"Holding-linked ({lvl}) — update thesis, stop, and size only for this name.",
    }


def _risk_caveat(portfolio: dict[str, Any]) -> str:
    flags = list(portfolio.get("flags") or [])
    heat = portfolio.get("heat") or {}
    conc = portfolio.get("concentration") or {}
    parts = [
        "Advisory only — not an order. Size within risk limits; place/refresh stops via "
        "Stop Management (Replace mode)."
    ]
    if heat.get("portfolio_heat_pct") is not None:
        parts.append(
            f"Portfolio heat ~{float(heat.get('portfolio_heat_pct') or 0):.1f}% "
            f"({heat.get('level') or 'n/a'}); protected ~{float(heat.get('pct_protected') or 0):.0f}%."
        )
    if conc.get("book_level"):
        parts.append(
            f"Book concentration {conc.get('book_level')} "
            f"(top-3 ~{float(conc.get('top3_pct') or 0):.0f}%)."
        )
    if flags:
        parts.append("Flags: " + "; ".join(flags[:2]) + ".")
    return " ".join(parts)[:600]


def _fmt_size_reasons(size: dict[str, Any]) -> str:
    rs = size.get("reasons") or []
    if not rs:
        return ""
    return "Why this size: " + "; ".join(rs[:4]) + "."


def _context_concentration_tickers(portfolio: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    """Surface concentrated names as context (not a buy list) when category has no natural tickers."""
    out: list[dict[str, Any]] = []
    by_sym = portfolio.get("by_symbol") or {}
    for n in (portfolio.get("concentration") or {}).get("names") or []:
        sym = n.get("symbol")
        if not sym or sym not in by_sym:
            continue
        w = by_sym[sym]["weight_pct"]
        lvl = n.get("level") or "elevated"
        role = "trim_candidate" if lvl in ("high", "extreme") else "hold_review"
        out.append({
            "symbol": sym,
            "role": role,
            "suggested_weight_pct": f"current {w:.1f}% ({lvl})",
            "rationale": (
                f"Concentration context — {sym} is a {lvl} weight. "
                f"Not a buy signal; size any related action against this weight."
            ),
        })
        if len(out) >= limit:
            break
    return out


# ═══════════════════════════════════════════════════════════════════════
# Advisory builder
# ═══════════════════════════════════════════════════════════════════════

def build_advisory(
    *,
    title: str,
    summary: str,
    thesis: str | None,
    cats: list[str],
    primary: str,
    symbol: str | None,
    is_held: bool,
    research_type: str | None,
    portfolio: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Portfolio-aware advisory — gated by primary category; sized by concentration + heat."""
    portfolio = portfolio or load_portfolio_context()
    by_sym = portfolio.get("by_symbol") or {}
    held = set(portfolio.get("holdings_symbols") or [])
    sleeves = portfolio.get("sleeves") or {}
    flags = list(portfolio.get("flags") or [])
    heat = portfolio.get("heat") or {}
    conc = portfolio.get("concentration") or {}
    primary = primary or (cats[0] if cats else "company_ticker")
    rtype = research_type or ""

    tickers: list[dict[str, Any]] = []
    sizing_bits: list[str] = []
    implications: list[str] = []
    size_reasons: list[str] = []
    action_label = "Review desk implications"
    action_detail = "Open the full brief, verify sources, then decide with stops if any position change."
    href = "detail"
    action = "review"

    heat_pct = float(heat.get("portfolio_heat_pct") or 0.0)
    heat_lvl = heat.get("level") or "low"
    book_lvl = conc.get("book_level") or "normal"

    # ── Stops / risk ───────────────────────────────────────────────────
    if primary == "risk_regime" or rtype in _STOP_TYPES:
        action, href = "review_stop", "risk"
        sym = (symbol or "").upper() or None
        if not sym:
            mentioned = extract_mentioned_tickers(f"{title} {summary}", known=held)
            sym = mentioned[0] if mentioned else None
        if sym and sym in by_sym:
            rev = size_held_review(portfolio, sym)
            action_label = f"Review {sym} stop / protection"
            action_detail = (
                f"{sym} is ~{rev.get('weight_pct', 0):.1f}% of book. "
                f"Use Stop Management Replace mode — do not leave cancelled stops. "
                f"Heat ~{heat_pct:.1f}% ({heat_lvl})."
            )
            tickers.append({
                "symbol": sym, "role": "protect",
                "suggested_weight_pct": rev.get("label"),
                "rationale": "Holdings-linked stop quality — fix protection before adding risk.",
            })
            implications.append(
                f"Capital preservation on {sym} comes before new theme adds while stops are weak. "
                f"Book concentration is {book_lvl}."
            )
            sizing_bits.extend(rev.get("bits") or [])
            sizing_bits.append(
                f"Do not increase {sym} until stop is healthy; if conviction drops, "
                f"trim 5–10% of the position after stop is set."
            )
        else:
            action_label = "Inspect risk / stops"
            action_detail = (
                f"Open Stop Management for unprotected names first. "
                f"Heat ~{heat_pct:.1f}% ({heat_lvl}); protected ~{float(heat.get('pct_protected') or 0):.0f}%."
            )
            implications.append(
                "Book-level stop hygiene dominates alpha until near-triggers are clean. "
                "No net new risk while protection is incomplete on large weights."
            )
            for r in (portfolio.get("top") or [])[:4]:
                t = r.get("symbol")
                if not t or t not in by_sym:
                    continue
                w = by_sym[t]["weight_pct"]
                lvl = by_sym[t].get("concentration_level") or "normal"
                tickers.append({
                    "symbol": t, "role": "protect",
                    "suggested_weight_pct": f"current {w:.1f}% — protect first ({lvl})",
                    "rationale": "Large weight — confirm stop health before net new risk.",
                })
            sizing_bits.append(
                f"Heat ~{heat_pct:.1f}% ({heat_lvl}). "
                + ("Concentration: " + "; ".join(flags[:3]) + "." if flags else
                   "No size adds until stops on top weights are healthy.")
            )

    # ── Retirement / tax ───────────────────────────────────────────────
    elif primary == "retirement_tax":
        action, href = "retirement_plan", "retirement"
        title_l = (title or "").lower()
        blob_l = f"{title} {summary or ''}".lower()
        schg = by_sym.get("SCHG", {}).get("weight_pct")
        schd = by_sym.get("SCHD", {}).get("weight_pct")
        inc = sleeves.get("dividend_income") or 0

        # Always attach concentration context tickers (not buy list)
        for t in _context_concentration_tickers(portfolio, limit=2):
            t = dict(t)
            t["rationale"] = (
                f"Portfolio context for tax planning — {t['symbol']} weight is a funding/IRMAA "
                f"consideration, not a new equity ticket."
            )
            tickers.append(t)

        if re.search(r"monitor|integration|workflow|dashboard|alert", title_l):
            action_label = "Wire IRMAA / conversion alerts into the desk"
            action_detail = (
                "Ops task: alert on IRMAA thresholds and conversion calendar in Command Center — not a new buy list."
            )
            implications.append(
                "Monitoring stack tracks MAGI path and Medicare dates; equity weights are context only."
            )
            if schg and schg >= CONC_CAUTION:
                sizing_bits.append(
                    f"Surface SCHG concentration (~{schg:.1f}%, {book_lvl} book) as a dashboard risk flag, "
                    f"not conversion funding default."
                )
        elif re.search(r"irmaa|medicare|premium", title_l) or (
            re.search(r"irmaa|medicare\s+part|premium", blob_l)
            and not re.search(r"roth|ladder|conversion", title_l)
        ):
            action_label = "Model IRMAA / MAGI before conversions"
            action_detail = (
                "Confirm 2026 IRMAA brackets and the two-year MAGI lookback. "
                "Stage Roth conversions so MAGI stays under cliff tiers before Medicare ~Dec 2026."
            )
            implications.append(
                "IRMAA is MAGI-driven (two-year lookback) — conversion timing is a premium decision, not equity beta. "
                f"Income sleeve ~{inc:.1f}% already affects taxable MAGI."
            )
            sizing_bits.append(
                "No new equity ticket. Cap conversion batches to remaining room under the next IRMAA tier "
                "(verify SSA/CMS tables)."
            )
            if inc >= 30:
                sizing_bits.append(
                    f"Taxable income sleeve ~{inc:.1f}% already distributes — avoid stacking more taxable yield that lifts MAGI."
                )
            if schg and schg >= CONC_CAUTION:
                sizing_bits.append(
                    f"If liquidating to manage MAGI, plan SCHG trims (~{schg:.1f}%) with stops — not panic sales."
                )
        elif re.search(r"\bmapt\b|medicaid|asset protection|estate", title_l + " " + blob_l[:200]):
            action_label = "Coordinate MAPT / estate with tax counsel"
            action_detail = (
                "Legal/asset-protection decision — coordinate with elder-law counsel before re-titling. "
                "Do not conflate with IRMAA MAGI."
            )
            implications.append(
                "Asset-protection moves interact with ownership and distributions; keep brokerage risk sizing separate."
            )
            sizing_bits.append(
                "No default ticker add. Freeze large re-titling until counsel confirms look-back triggers. "
                f"Book concentration remains {book_lvl} regardless of legal structure."
            )
        elif re.search(r"ssdi|social security disability", title_l + " " + blob_l[:200]):
            action_label = "Verify SSDI / SGA vs portfolio income"
            action_detail = (
                "Investment income and Roth conversions generally do not count toward SGA — confirm current rules."
            )
            implications.append(
                "SSDI shapes Medicare start and tax sequencing; equity risk policy stays unless cash-flow needs shift."
            )
            if schd:
                sizing_bits.append(
                    f"Quality income (SCHD ~{schd:.1f}%) supports spending without wages — avoid junk yield swaps."
                )
            sizing_bits.append(f"Heat ~{heat_pct:.1f}% — do not add speculative risk while income planning is primary.")
        elif re.search(r"roth|conversion|ladder|golden window|drawdown", title_l):
            action_label = "Set 2026 conversion batch calendar"
            action_detail = (
                "Define multi-year Roth conversion batches to fill lower brackets without IRMAA cliffs "
                "before the Golden Window closes into Medicare."
            )
            implications.append(
                "Conversion ladder is account-type sequencing — size by tax bracket room, not equity conviction."
            )
            if schg and schg >= 15:
                sizing_bits.append(
                    f"If sales fund conversions, avoid auto-liquidating SCHG at ~{schg:.1f}% — plan staged trims with stops."
                )
            if schd:
                sizing_bits.append(
                    f"SCHD ~{schd:.1f}% can remain the quality income anchor while conversions run in tax-advantaged accounts."
                )
        else:
            action_label = "Review Roth / tax plan"
            action_detail = "Map action to Golden Window, IRMAA lookback, and account placement."
            implications.append(
                "Retirement/tax intelligence — prioritize MAGI and sequencing over new equity risk."
            )
            if schg and schg >= CONC_CAUTION:
                sizing_bits.append(
                    f"SCHG concentration ~{schg:.1f}% is separate from tax sequencing but is the primary funding lever if needed."
                )

        if not sizing_bits:
            sizing_bits.append(
                f"No equity ticket from this tax brief. Book concentration {book_lvl}; heat ~{heat_pct:.1f}%."
            )

    # ── Dividend ───────────────────────────────────────────────────────
    elif primary == "dividend_income":
        action, href = "income_sleeve", "portfolio"
        inc = sleeves.get("dividend_income") or 0
        cap = (portfolio.get("theme_capacity") or {}).get("dividend_income") or {}
        room = float(cap.get("room_pct") or 0.0)
        title_l = (title or "").lower()
        strategy_title = bool(re.search(
            r"dividend|income etf|income sleeve|covered.?call|jepi|jepq|schd|yield strategy|"
            r"bdc|aristocrat|retirement-focused dividend",
            title_l, re.I,
        ))
        one = None
        m = re.search(r"\b([A-Z]{2,5})\b", title or "")
        if m and m.group(1) in by_sym:
            one = m.group(1)

        if one and not strategy_title:
            rev = size_held_review(portfolio, one)
            action_label = f"Review {one} as income holding"
            action_detail = (
                f"{one} is ~{rev.get('weight_pct', 0):.1f}% of book — confirm yield quality, stop, "
                f"and IRMAA impact of distributions."
            )
            tickers.append({
                "symbol": one, "role": rev.get("role") or "hold_review",
                "suggested_weight_pct": rev.get("label"),
                "rationale": "Named holding — not a full-sleeve recommendation.",
            })
            implications.append(
                f"Treat {one} on its own merits; do not extrapolate to the entire income sleeve (~{inc:.1f}%)."
            )
            sizing_bits.extend(rev.get("bits") or [])
        else:
            action_label = "Check income sleeve vs IRMAA"
            held_income = [t for t in THEME_TICKERS["dividend_income"] if t in by_sym]
            held_income.sort(key=lambda t: -by_sym[t]["weight_pct"])
            for t in held_income[:4]:
                w = by_sym[t]["weight_pct"]
                lvl = by_sym[t].get("concentration_level") or "normal"
                tickers.append({
                    "symbol": t, "role": "hold_review",
                    "suggested_weight_pct": f"current {w:.1f}% ({lvl})",
                    "rationale": "Core income holding — review yield quality vs credit/NAV risk.",
                })
            size = size_new_position(
                portfolio, theme="dividend_income", conviction="low", risk_profile="low_vol",
            )
            size_reasons.extend(size.get("reasons") or [])
            if not size.get("allow_add") or room < 1.0 or inc >= (THEME_TARGET_MAX["dividend_income"] * 0.9):
                sizing_bits.append(
                    f"Income sleeve ~{inc:.1f}% of book (soft max {THEME_TARGET_MAX['dividend_income']:.0f}%, "
                    f"room ~{room:.1f}%). Prefer quality SCHD / rotate within sleeve — "
                    f"no net new income risk; upgrades only, with a stop."
                )
                action_detail = (
                    f"Income already ~{inc:.1f}%. Do not add high-yield for MAGI-heavy years; rebalance within sleeve."
                )
                if by_sym.get("SCHD", {}).get("weight_pct", 0) >= 15:
                    sizing_bits.append(
                        f"SCHD alone is ~{by_sym['SCHD']['weight_pct']:.1f}% — trim only if total income target is lower."
                    )
            else:
                sizing_bits.append(
                    f"Income sleeve ~{inc:.1f}% (room ~{room:.1f}% to soft max). "
                    f"Quality dividend add band: {size.get('label')} — SCHD first if IRMAA budget allows. "
                    f"{_fmt_size_reasons(size)}"
                )
                action_detail = "Scale quality dividend modestly; clear MAGI before adding taxable yield."
                if size.get("require_funding_trim"):
                    for src in funding_sources(portfolio, need_pct=size.get("max_pct", 2)):
                        if src["symbol"] not in {t["symbol"] for t in tickers}:
                            tickers.append(src)
            implications.append(
                "Income decisions must clear SSDI/IRMAA: more yield is not always more after-tax spending power. "
                f"Heat ~{heat_pct:.1f}% ({heat_lvl})."
            )

    # ── Sector / macro ─────────────────────────────────────────────────
    elif primary in ("sector_thematic", "macro_geo"):
        themes = detect_themes_from_title(title)
        if primary == "macro_geo" and re.search(r"bond|tips|treasury|fixed.?income", title or "", re.I):
            themes = ["bonds"] + [t for t in themes if t != "bonds"]
        theme = themes[0] if themes else None
        if not theme:
            action_label = "Map thesis to sleeves"
            action_detail = "Identify which held ETFs express this theme before adding new names."
            implications.append(
                "No clear theme tickers from title — do not invent lists from body keywords. "
                f"Book concentration {book_lvl}; heat ~{heat_pct:.1f}%."
            )
            tickers.extend(_context_concentration_tickers(portfolio, limit=3))
            sizing_bits.append(
                f"Until a theme maps cleanly, no new ticket. Concentration: "
                + ("; ".join(flags[:2]) if flags else f"top-3 ~{float(conc.get('top3_pct') or 0):.0f}%.")
            )
        else:
            action, href = "theme_position", "portfolio"
            theme_tickers = THEME_TICKERS.get(theme, [])
            held_theme = [t for t in theme_tickers if t in by_sym]
            cap = (portfolio.get("theme_capacity") or {}).get(theme) or {}
            sleeve_pct = float(cap.get("current_pct") or sleeves.get(theme) or 0.0)
            room = float(cap.get("room_pct") or 0.0)
            tgt = float(cap.get("target_max_pct") or THEME_TARGET_MAX.get(theme, 10.0))
            label_theme = theme.replace("_", " ")
            size = size_new_position(
                portfolio, theme=theme, conviction="medium",
                risk_profile="high_vol" if theme in ("ai_infra", "materials") else "normal",
            )
            size_reasons.extend(size.get("reasons") or [])

            if held_theme:
                action_label = f"Align {label_theme} sleeve"
                for t in held_theme[:4]:
                    w = by_sym[t]["weight_pct"]
                    tickers.append({
                        "symbol": t, "role": "hold_review",
                        "suggested_weight_pct": f"current {w:.1f}%",
                        "rationale": f"Already held in {label_theme} (~{sleeve_pct:.1f}% sleeve).",
                    })
                if size.get("allow_add") and room >= 1.0:
                    tickers.extend(_pick_theme_adds(
                        theme_tickers, held=held, portfolio=portfolio, size=size, max_n=3,
                    ))
            else:
                action_label = f"Consider {label_theme} exposure"
                tickers.extend(_pick_theme_adds(
                    theme_tickers, held=held, portfolio=portfolio, size=size, max_n=3,
                ))

            if not size.get("allow_add") or sleeve_pct >= tgt * 0.95:
                sizing_bits.append(
                    f"{label_theme.title()} ~{sleeve_pct:.1f}% (soft max {tgt:.0f}%) — rebalance within sleeve; "
                    f"avoid net new risk. {_fmt_size_reasons(size)}"
                )
                action_detail = f"Theme sleeve ~{sleeve_pct:.1f}%. Prefer rotate/upgrade vs add."
            else:
                sizing_bits.append(
                    f"{label_theme.title()} ~{sleeve_pct:.1f}% / max {tgt:.0f}% (room ~{room:.1f}%). "
                    f"Suggested add band {size.get('label')}. {_fmt_size_reasons(size)}"
                )
                action_detail = (
                    f"If high conviction, stage {size.get('min_pct', 1):.1f}–{size.get('max_pct', 2):.1f}% "
                    f"with stops; fund from concentrated growth when book is {book_lvl}."
                )
            if size.get("diversification_note"):
                sizing_bits.append(size["diversification_note"])

            # Always fund when SCHG high / top-3 elevated
            schg_w = float((by_sym.get("SCHG") or {}).get("weight_pct") or 0.0)
            if size.get("require_funding_trim") or book_lvl in ("elevated", "high") or schg_w >= 24:
                for src in funding_sources(portfolio, need_pct=size.get("max_pct") or 3.0):
                    if src["symbol"] not in {t["symbol"] for t in tickers}:
                        tickers.append(src)
                        sizing_bits.append(
                            f"Funding: {src['symbol']} {src['suggested_weight_pct']}."
                        )
            implications.append(
                f"Express {label_theme} with held names when possible. "
                f"Adds ranked by RSI/relative strength/valuation when data exists. "
                f"Any add needs a stop (Replace mode). Heat ~{heat_pct:.1f}% ({heat_lvl}); "
                f"book concentration {book_lvl}."
            )

    # ── Company / catalyst ─────────────────────────────────────────────
    elif primary == "company_ticker" or primary == "catalyst_event":
        sym = (symbol or "").upper() or None
        if not sym:
            m = re.search(
                r"(?:auto-research:\s*|news_momentum:\s*|earnings:\s*|options:\s*)([A-Z]{1,5})\b",
                title or "",
            )
            if m and m.group(1) not in _NOISE_TOKENS:
                cand = m.group(1)
                if cand in held:
                    sym = cand
            if not sym:
                for m in _TICKER_TOKEN.finditer(title or ""):
                    t = m.group(1)
                    if t in held:
                        sym = t
                        break
        if sym and sym in by_sym:
            action, href = "position_review", "portfolio"
            rev = size_held_review(portfolio, sym)
            action_label = f"Review {sym} position"
            tickers.append({
                "symbol": sym,
                "role": rev.get("role") or "hold_review",
                "suggested_weight_pct": rev.get("label"),
                "rationale": rev.get("rationale"),
            })
            # Optional add only if soft headroom and heat allow
            size = size_new_position(
                portfolio, symbol=sym, already_held=True, conviction="medium",
            )
            size_reasons.extend(size.get("reasons") or [])
            sizing_bits.extend(rev.get("bits") or [])
            if size.get("allow_add"):
                sizing_bits.append(
                    f"If thesis strengthens, max add band {size.get('label')}. {_fmt_size_reasons(size)}"
                )
            action_detail = (
                f"{sym} at ~{rev.get('weight_pct', 0):.1f}% ({rev.get('level')}). "
                f"Confirm stop health (Replace mode) before any size change. Heat ~{heat_pct:.1f}%."
            )
            implications.append(
                f"Any add to {sym} must clear stop policy and not push concentration from {book_lvl} higher without a funding trim."
            )
        else:
            m2 = re.search(
                r"(?:auto-research:\s*|news_momentum:\s*|earnings:\s*|options:\s*)([A-Z]{1,5})\b",
                title or "",
            )
            cand = m2.group(1) if m2 else None
            if not cand:
                m3 = re.search(r"\b([A-Z]{2,5})\b", title or "")
                cand = m3.group(1) if m3 else None
            if cand and cand not in _NOISE_TOKENS and cand not in held:
                size = size_new_position(
                    portfolio, symbol=cand, conviction="low", already_held=False,
                )
                size_reasons.extend(size.get("reasons") or [])
                action_label = f"Watchlist only — {cand} not held"
                if size.get("allow_add"):
                    action_detail = (
                        f"{cand} is off-book. After diligence, starter {size.get('label')}; "
                        f"stop via Replace mode required. Heat ~{heat_pct:.1f}% ({heat_lvl})."
                    )
                    tickers.append({
                        "symbol": cand, "role": "watchlist",
                        "suggested_weight_pct": size.get("label"),
                        "rationale": (
                            f"Not held — watchlist/research path. Size already cut for heat "
                            f"({heat_lvl}) and book concentration ({book_lvl})."
                        ),
                    })
                else:
                    action_detail = (
                        f"{cand} is off-book and book constraints block a starter size — research only."
                    )
                    tickers.append({
                        "symbol": cand, "role": "watchlist",
                        "suggested_weight_pct": "research only — no size",
                        "rationale": "Off-book with elevated concentration/heat — no funded add.",
                    })
                implications.append(
                    f"{cand} is off-book — do not size from this brief alone; run entry diligence first."
                )
                sizing_bits.append(
                    f"Starter guidance: {size.get('label')}. {_fmt_size_reasons(size)}"
                )
                if size.get("require_funding_trim"):
                    for src in funding_sources(portfolio, need_pct=size.get("max_pct") or 2.0):
                        tickers.append(src)
                        sizing_bits.append(f"Fund via {src['symbol']}: {src['suggested_weight_pct']}.")
            else:
                action_label = "Research only — no sleeve action"
                action_detail = (
                    "No held ticker linked. Do not auto-allocate; promote a symbol before sizing."
                )
                implications.append(
                    "Company/ticker brief without a portfolio link — context only, not a buy list."
                )
                tickers.extend(_context_concentration_tickers(portfolio, limit=3))
                sizing_bits.append(
                    "Book concentration context: " + (
                        "; ".join(flags[:2]) if flags else f"top-3 ~{float(conc.get('top3_pct') or 0):.0f}%."
                    )
                )

    # ── Compounding ────────────────────────────────────────────────────
    elif primary == "compounding_wealth":
        action, href = "growth_review", "portfolio"
        growth = sleeves.get("growth") or 0
        schg = by_sym.get("SCHG", {}).get("weight_pct")
        action_label = "Review growth / compounding sleeve"
        implications.append(
            "Compounding briefs map to long-horizon growth quality — size against concentration and heat, not headlines."
        )
        rev: dict[str, Any] = {}
        if schg:
            rev = size_held_review(portfolio, "SCHG")
            tickers.append({
                "symbol": "SCHG",
                "role": rev.get("role") or "hold_review",
                "suggested_weight_pct": rev.get("label"),
                "rationale": "Primary growth compounder — rebalance only on plan, not noise.",
            })
            sizing_bits.extend(rev.get("bits") or [])
        for t in ("QQQ", "SPY", "V"):
            if t in by_sym and t != "SCHG":
                tickers.append({
                    "symbol": t, "role": "hold_review",
                    "suggested_weight_pct": f"current {by_sym[t]['weight_pct']:.1f}%",
                    "rationale": "Growth/beta holding — keep unless thesis or tax plan requires a trim.",
                })
        size = size_new_position(portfolio, theme="growth", conviction="low", risk_profile="low_vol")
        size_reasons.extend(size.get("reasons") or [])
        if schg and schg >= CONC_CAUTION:
            action_detail = (
                f"Growth sleeve ~{growth:.1f}% (SCHG ~{schg:.1f}%, {book_lvl} concentration). "
                f"Avoid net new megacap beta without a funding trim. Heat ~{heat_pct:.1f}%."
            )
            if schg >= CONC_HIGH:
                for src in funding_sources(portfolio, need_pct=4.0):
                    if src["symbol"] == "SCHG" and not any(
                        x.get("symbol") == "SCHG" and x.get("role") == "trim_candidate" for x in tickers
                    ):
                        tickers.append(src)
        elif size.get("allow_add"):
            sizing_bits.append(
                f"Growth sleeve ~{growth:.1f}% — if underweight targets, staged add {size.get('label')}. "
                f"{_fmt_size_reasons(size)}"
            )
            action_detail = "Build compounding exposure gradually; never skip stop policy on new lots."
        else:
            action_detail = "Stay systematic: DCA/reinvest beats one-off adds unless a clear valuation edge."
            sizing_bits.append(
                f"Growth sleeve ~{growth:.1f}% near capacity — reinvest dividends rather than stack beta."
            )

    # ── Academic / other ───────────────────────────────────────────────
    else:
        action_label = "Review implications"
        action_detail = (
            f"Map to holdings only if a clear sleeve or symbol is identified. "
            f"Heat ~{heat_pct:.1f}%; book concentration {book_lvl}."
        )
        implications.append(
            "General intelligence — no automatic ticker shopping list for this category. "
            "Use concentrated names as context if any portfolio change is implied."
        )
        tickers.extend(_context_concentration_tickers(portfolio, limit=3))
        if flags:
            sizing_bits.append("Concentration: " + "; ".join(flags[:3]) + ".")
        else:
            sizing_bits.append(
                f"Largest weights: "
                + ", ".join(f"{t['symbol']} {t['weight_pct']}%" for t in (portfolio.get("top") or [])[:4])
                + "."
            )

    # Floor: always have sizing + at least context tickers on equity-relevant paths
    if not tickers and primary not in ("retirement_tax",):
        tickers.extend(_context_concentration_tickers(portfolio, limit=3))
    if not sizing_bits:
        tops = ", ".join(f"{t['symbol']} {t['weight_pct']}%" for t in (portfolio.get("top") or [])[:4])
        sizing_bits.append(
            f"Largest weights today: {tops}. Heat ~{heat_pct:.1f}% ({heat_lvl}); "
            f"book concentration {book_lvl}."
        )

    # Dedupe tickers by symbol keeping first role priority
    _role_pri = {
        "protect": 0, "trim_candidate": 1, "add_candidate": 2,
        "hold_review": 3, "watchlist": 4, "plan": 5,
    }
    dedup: dict[str, dict[str, Any]] = {}
    for t in tickers:
        sym = t.get("symbol")
        if not sym:
            continue
        prev = dedup.get(sym)
        if prev is None or _role_pri.get(t.get("role") or "", 9) < _role_pri.get(prev.get("role") or "", 9):
            dedup[sym] = t
    tickers = _finalize_ticker_recs(list(dedup.values()), portfolio=portfolio)

    sizing_text = " ".join(sizing_bits)
    if size_reasons and "Why this size" not in sizing_text:
        sizing_text = (sizing_text + " " + "Why this size: " + "; ".join(size_reasons[:4]) + ".").strip()

    # Cross-theme relationships
    related: dict[str, Any] = {"items": [], "impact_note": None, "impact_notes": [], "themes": []}
    try:
        from lib.research_intelligence_themes import related_themes_for_card
        related = related_themes_for_card(
            primary=primary,
            title=title,
            portfolio=portfolio,
            detected_themes=detect_themes_from_title(title),
        )
    except Exception:
        pass

    # Funding context for staging
    funding_symbol = None
    require_fund = book_lvl in ("high", "elevated") or heat_lvl in ("high", "extreme", "moderate")
    schg_w = float((by_sym.get("SCHG") or {}).get("weight_pct") or 0)
    if schg_w >= 20 or book_lvl == "high":
        require_fund = True
        funding_symbol = "SCHG"

    # Card-level actions — Stage Trade first when eligible
    stageable = [
        t for t in tickers
        if t.get("role") in ("add_candidate", "trim_candidate", "protect", "hold_review")
        and t.get("data_complete") is not False
        and t.get("symbol")
    ]
    card_actions: list[dict[str, Any]] = []
    if stageable:
        t0 = stageable[0]
        can_stage = t0.get("role") in ("add_candidate", "trim_candidate") and t0.get("data_complete") is not False
        if can_stage and t0.get("role") == "add_candidate":
            card_actions.append({
                "id": "stage_trade",
                "label": "Stage Trade",
                "primary": True,
                "symbol": t0.get("symbol"),
                "role": t0.get("role"),
                "side": "buy",
            })
        if funding_symbol or any(t.get("role") == "trim_candidate" for t in tickers):
            card_actions.append({
                "id": "propose_trim",
                "label": f"Propose Trim {funding_symbol or 'SCHG'}",
                "primary": bool(not can_stage),
                "symbol": funding_symbol or "SCHG",
                "role": "trim_candidate",
                "side": "sell",
            })
        if can_stage:
            card_actions.append({
                "id": "ri_ideas",
                "label": "Add to RI Ideas",
                "symbol": t0.get("symbol"),
                "role": t0.get("role"),
                "side": "buy" if t0.get("role") == "add_candidate" else "sell",
            })
    # Secondary links
    seen_act = {a["id"] for a in card_actions}
    for t in tickers[:2]:
        for a in t.get("actions") or []:
            aid = str(a.get("id") or "")
            if aid in seen_act or aid in ("trade_ticket",):
                # trade_ticket demoted — Stage Trade is primary
                if aid == "trade_ticket":
                    continue
            if aid in seen_act or len(card_actions) >= 6:
                continue
            seen_act.add(aid)
            card_actions.append({**a, "primary": False})
    if not card_actions:
        card_actions = [
            {"id": "watchlist", "label": "Add to Watchlist", "href": "/watch", "primary": False},
            {"id": "open_trading", "label": "Open in Trading", "href": "/trading", "primary": False},
            {"id": "stop", "label": "Set / Refresh Stop", "href": "/portfolio?tab=Stop%20Management", "primary": False},
        ]

    # Incomplete: demote Stage Trade
    incomplete_n = sum(1 for t in tickers if t.get("data_complete") is False)
    if incomplete_n and stageable and stageable[0].get("data_complete") is False:
        card_actions = [a for a in card_actions if a.get("id") not in ("stage_trade",)]
        card_actions = [
            {"id": "watchlist", "label": "Add to Watchlist", "href": f"/watch?symbol={stageable[0].get('symbol')}", "primary": True},
            {"id": "open_trading", "label": "Open in Trading", "href": f"/trading?symbol={stageable[0].get('symbol')}", "primary": False},
        ] + [a for a in card_actions if a.get("id") not in ("watchlist", "open_trading")]

    quality_gate = {
        "pass": incomplete_n == 0 or primary in ("retirement_tax", "risk_regime"),
        "incomplete_tickers": incomplete_n,
        "stage_eligible": bool(stageable and stageable[0].get("data_complete") is not False
                               and stageable[0].get("role") in ("add_candidate", "trim_candidate")),
        "note": (
            None if incomplete_n == 0
            else f"{incomplete_n} ticker(s) incomplete (missing RSI/RS) — demoted; Stage Trade disabled"
        ),
    }

    stage_payload = None
    if stageable and quality_gate.get("stage_eligible"):
        t0 = stageable[0]
        stage_payload = {
            "symbol": t0.get("symbol"),
            "role": t0.get("role"),
            "side": "sell" if t0.get("role") == "trim_candidate" else "buy",
            "suggested_weight_pct": t0.get("suggested_weight_pct"),
            "conviction_tier": t0.get("conviction_tier"),
            "conviction_score": t0.get("conviction_score"),
            "require_funding_trim": require_fund,
            "funding_symbol": funding_symbol,
            "funding_source": (
                f"Trim {funding_symbol}" if funding_symbol else "Cash / rebalance"
            ),
            "sizing_reason": "; ".join(size_reasons[:4]) if size_reasons else None,
            "data_complete": t0.get("data_complete") is not False,
            "primary_category": primary,
            "related_themes": [x.get("id") for x in (related.get("items") or [])],
        }

    return {
        "investment_implications": (" ".join(implications) or "Map to holdings before acting.")[:750],
        "ticker_recommendations": tickers,
        "sizing_guidance": sizing_text[:750],
        "sizing_reason": ("; ".join(size_reasons[:5]) if size_reasons else None),
        "risk_caveat": _risk_caveat(portfolio),
        "actions": card_actions,
        "quality_gate": quality_gate,
        "related_themes": related,
        "stage_payload": stage_payload,
        "funding_context": {
            "require_funding_trim": require_fund,
            "funding_symbol": funding_symbol,
            "schg_pct": schg_w,
        },
        "portfolio_snapshot": {
            "total_mv": portfolio.get("total_mv"),
            "cash_mv": portfolio.get("cash_mv"),
            "invested_mv": portfolio.get("invested_mv"),
            "top": portfolio.get("top", [])[:8],
            "sleeves": {
                k: sleeves.get(k)
                for k in ("dividend_income", "growth", "defense", "power_infra", "ai_infra", "bonds")
                if sleeves.get(k)
            },
            "theme_capacity": {
                k: v for k, v in (portfolio.get("theme_capacity") or {}).items()
                if v.get("current_pct")
            },
            "related_weights": {
                t["symbol"]: by_sym[t["symbol"]]["weight_pct"]
                for t in tickers if t.get("symbol") in by_sym
            },
            "flags": flags[:5],
            "concentration": portfolio.get("concentration"),
            "heat": portfolio.get("heat"),
        },
        "next_action": {
            "label": action_label,
            "detail": action_detail,
            "href_hint": href,
            "action_type": action,
        },
        "card_template": {
            "version": "2.6",
            "sections": [
                "executive_summary",
                "key_takeaways",
                "technical_snapshot",
                "analyst_snapshot",
                "options_flow",
                "bull_bear",
                "investment_implications",
                "tickers_allocation",
                "sizing_guidance",
                "sizing_reason",
                "action_bar",
                "concentration_heat",
                "risk_caveat",
            ],
        },
    }


def clear_portfolio_cache() -> None:
    load_portfolio_context.cache_clear()
    try:
        from lib.research_intelligence_security import clear_security_cache
        clear_security_cache()
    except Exception:
        pass
