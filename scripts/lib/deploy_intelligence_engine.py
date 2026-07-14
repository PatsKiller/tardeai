"""deploy_intelligence_engine — post-sale redeploy plans (advisory only).

Factors (all advisory — operator confirms sizing):
  • Look-through sleeve gaps (rotation_sector_targets floors/targets)
  • Hermes composite score + rank (hermes_score_history)
  • Hermes graded research (hermes_research_intelligence)
  • Hermes external lanes (Grok/ChatGPT opinions)
  • CIO holistic view (watchlist_final_synthesis)
  • Symbol-card news/sentiment (symbol_cards_latest)
  • Market regime + think-tank sector rotation signals
  • Geopolitical posture (think-tank catalysts, defense research, news themes)
  • Concentration / duplicate-proxy penalties (e.g. FCNTX→SCHG after heavy SCHG)
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE = PROJECT_ROOT / "data" / "portfolios" / "state"
RUNTIME = PROJECT_ROOT / "data" / "runtime"
ROTATION_TARGETS = PROJECT_ROOT / "config" / "rotation_sector_targets.json"

CIO_BUY = frozenset({"BUY", "ADD", "ADD_ON_PULLBACK"})
CIO_AVOID = frozenset({"AVOID", "IGNORE", "REBALANCE_TRIM"})

# Regime → sleeve tilt (additive score bonus, not orders)
_REGIME_SLEEVE_BIAS = {
    "risk_off": {"Defense / Aerospace": 12, "Energy": 8, "Fixed Income": 15, "Cybersecurity": 6},
    "risk_on": {"Semiconductors": 6, "AI mega-cap": 4, "Magnificent 7": 3},
    "defensive": {"Defense / Aerospace": 10, "Energy": 6, "S&P 500": -4},
}
_GEOPOLITICAL_NEWS_THEMES = frozenset({
    "geopolitical trade policy", "defense spending", "geopolitical",
})
_GEOPOLITICAL_RESEARCH_THEMES = frozenset({"defense spending", "geopolitical"})
_GEOPOLITICAL_SLEEVE_BIAS = {
    "elevated": {
        "Defense / Aerospace": 14, "Energy": 10, "Fixed Income": 8, "Cybersecurity": 8,
    },
    "moderate": {
        "Defense / Aerospace": 8, "Energy": 5, "Fixed Income": 4, "Cybersecurity": 4,
    },
}
_ETF_SLEEVE_MAP = {
    "ITA": "Defense / Aerospace", "XAR": "Defense / Aerospace", "PPA": "Defense / Aerospace",
    "SCHD": "S&P 500", "SCHG": "Nasdaq 100", "BND": "Fixed Income",
    "JEPI": "S&P 500", "JEPQ": "Nasdaq 100", "QQQM": "Nasdaq 100",
    "VXUS": "China / EM", "FXI": "China / EM", "MCHI": "China / EM",
    "XLI": "S&P 500", "XLB": "S&P 500",
    "XLE": "Energy", "VDE": "Energy", "XOP": "Energy",
    "CIBR": "Cybersecurity", "BUG": "Cybersecurity",
    "SMH": "Semiconductors", "SOXX": "Semiconductors",
}
_THEME_ETF_MAP: dict[str, list[str]] = {
    "Nasdaq 100": ["JEPQ", "QQQM"],
    "S&P 500": ["SCHD", "JEPI", "XLI"],
    "Defense / Aerospace": ["ITA", "XAR"],
    "Energy": ["XLE", "VDE"],
    "Fixed Income": ["BND"],
    "Cybersecurity": ["CIBR", "BUG"],
    "China / EM": ["VXUS", "FXI"],
    "Semiconductors": ["SMH", "SOXX"],
    "AI mega-cap": ["JEPQ", "SCHD"],
    "Magnificent 7": ["SCHD"],
}
_PROXY_SLEEVE_TO_THEME = {
    "US large-cap growth": "Nasdaq 100",
    "US large-cap blend (fund proxy)": "Nasdaq 100",
}
# ETF sold directly (no fund proxy row) — theme exposure reduced
_SOLD_ETF_THEME: dict[str, str] = {
    "ARKQ": "AI mega-cap",
    "ARKG": "Semiconductors",
    "ARKX": "Defense / Aerospace",
    "ARKK": "AI mega-cap",
    "SCHG": "Nasdaq 100",
    "SCHD": "S&P 500",
    "JEPQ": "Nasdaq 100",
    "ITA": "Defense / Aerospace",
    "XAR": "Defense / Aerospace",
}
MATERIAL_PROCEEDS_USD = 10_000.0
MAJOR_PROCEEDS_USD = 25_000.0


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        if v in (None, "", "—"):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _extract_geopolitical_context(tt: dict[str, Any]) -> dict[str, Any]:
    """Think-tank geopolitical posture: catalyst volume, defense research, news themes."""
    signals = tt.get("signals") or {}
    catalysts = signals.get("catalysts") or []
    hermes = signals.get("hermes_research") or []
    news_themes = (signals.get("news_feeds") or {}).get("themes") or []

    geo_catalyst_count = 0
    contract_win_count = 0
    top_catalyst = 1
    for row in catalysts:
        theme = str(row.get("theme") or "").lower()
        count = int(row.get("count") or 0)
        top_catalyst = max(top_catalyst, count)
        if theme == "geopolitical":
            geo_catalyst_count = count
        elif theme == "contract_win":
            contract_win_count = count

    defense_symbols: list[str] = []
    defense_research_count = 0
    active_themes: list[str] = []
    for row in hermes:
        theme = str(row.get("theme") or "")
        if theme.lower() not in _GEOPOLITICAL_RESEARCH_THEMES:
            continue
        defense_research_count += int(row.get("count") or 0)
        active_themes.append(theme)
        for sym in row.get("symbols") or []:
            if sym:
                defense_symbols.append(str(sym).upper())

    geo_news_mentions = 0
    for row in news_themes:
        theme = str(row.get("theme") or "")
        if theme.lower() not in _GEOPOLITICAL_NEWS_THEMES:
            continue
        geo_news_mentions += int(row.get("count") or 0)
        active_themes.append(theme)

    geo_share = geo_catalyst_count / top_catalyst if top_catalyst else 0.0
    posture = "neutral"
    if geo_catalyst_count >= 80 or geo_share >= 0.35 or (defense_research_count and geo_news_mentions >= 2):
        posture = "elevated"
    elif geo_catalyst_count >= 40 or defense_research_count or geo_news_mentions or contract_win_count >= 100:
        posture = "moderate"

    return {
        "posture": posture,
        "catalyst_count": geo_catalyst_count,
        "catalyst_share": round(geo_share, 3),
        "contract_win_count": contract_win_count,
        "defense_research_count": defense_research_count,
        "geo_news_mentions": geo_news_mentions,
        "defense_symbols": list(dict.fromkeys(defense_symbols))[:12],
        "active_themes": list(dict.fromkeys(active_themes))[:6],
    }


def load_market_context() -> dict[str, Any]:
    """Regime snapshot + think-tank sector rotation + VIX if available."""
    ctx: dict[str, Any] = {"as_of": datetime.now(timezone.utc).isoformat()}
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute(
            """SELECT regime_label, trend_state, confidence, volatility_state,
                      risk_appetite_state, breadth_state, summary, generated_at
               FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1"""
        )
        row = cur.fetchone()
        if row:
            keys = [d[0] for d in cur.description]
            snap = dict(zip(keys, row))
            ctx["regime"] = {
                "label": str(snap.get("regime_label") or "unknown"),
                "trend": snap.get("trend_state"),
                "confidence": _as_float(snap.get("confidence")),
                "volatility": snap.get("volatility_state"),
                "risk_appetite": snap.get("risk_appetite_state"),
                "breadth": snap.get("breadth_state"),
                "summary": (str(snap.get("summary") or ""))[:200],
                "as_of": str(snap.get("generated_at") or "")[:19],
            }
            label = str(snap.get("regime_label") or "").lower()
            if "risk_off" in label or "defensive" in label or str(snap.get("risk_appetite_state") or "").lower() == "bearish":
                ctx["regime_posture"] = "risk_off"
            elif "risk_on" in label:
                ctx["regime_posture"] = "risk_on"
            else:
                ctx["regime_posture"] = "neutral"
    except Exception as e:
        ctx["regime_error"] = str(e)[:120]

    tt = _load_json(RUNTIME / "think_tank_latest.json", {})
    signals = (tt.get("signals") or {})
    ctx["geopolitical"] = _extract_geopolitical_context(tt)
    ctx["think_tank"] = {
        "updated_at": tt.get("updated_at"),
        "hermes_research_themes": (signals.get("hermes_research") or [])[:6],
        "sector_rotation_mentions": signals.get("news_feeds", {}).get("sector_rotation_mentions"),
        "style_rotation": signals.get("style_rotation"),
    }
    # Finviz group / macro strip if present on overview cache
    ov = _load_json(STATE / "portfolio_overview_cache.json", {})
    if ov.get("trade_ai"):
        ctx["portfolio_pulse"] = ov.get("trade_ai")
    return ctx


def load_lookthrough_summary() -> dict[str, Any]:
    return _load_json(STATE / "lookthrough_themes.json", {"themes": {}, "portfolio_total": 0})


def sleeve_gaps(lt: dict[str, Any]) -> list[dict[str, Any]]:
    targets = _load_json(ROTATION_TARGETS, {}).get("themes") or {}
    total = _as_float(lt.get("portfolio_total"), 1.0)
    themes = lt.get("themes") or {}
    gaps = []
    for name, cfg in targets.items():
        if not isinstance(cfg, dict):
            continue
        floor = _as_float(cfg.get("floor"))
        target = _as_float(cfg.get("target"))
        tv = themes.get(name) or {}
        pct = _as_float(tv.get("pct"))
        if floor > 0 and pct < floor:
            gap_pct = round(floor - pct, 2)
            gaps.append({
                "theme": name,
                "pct": round(pct, 2),
                "floor": floor,
                "target": target,
                "gap_pct": gap_pct,
                "gap_usd": round(total * gap_pct / 100.0, 0),
            })
    gaps.sort(key=lambda g: -g["gap_pct"])
    return gaps


def _held_symbols() -> set[str]:
    hold = _load_json(STATE / "holdings.json", {}).get("holdings") or []
    return {str(h.get("symbol") or "").upper() for h in hold if h.get("symbol") and not h.get("is_cash")}


def _symbol_cards() -> dict[str, dict]:
    raw = _load_json(RUNTIME / "symbol_cards_latest.json", {})
    return (raw.get("data") or {}).get("cards") or raw.get("cards") or {}


def _watchlist_row(cur, symbol: str) -> dict[str, Any]:
    sym = symbol.upper()
    cur.execute(
        """SELECT w.symbol, w.hermes_rank, w.score, w.source, p.sector, p.instrument_type,
                  fs.recommendation AS cio_view, fs.decision_safety,
                  an.nop AS analyst_opinions
           FROM watchlist_items w
           LEFT JOIN symbol_profiles p ON upper(p.symbol)=upper(w.symbol)
           LEFT JOIN LATERAL (
               SELECT recommendation, decision_safety FROM watchlist_final_synthesis f
               WHERE upper(f.symbol)=upper(w.symbol) ORDER BY created_at DESC LIMIT 1
           ) fs ON true
           LEFT JOIN LATERAL (
               SELECT number_of_analyst_opinions nop FROM yahoo_analyst_targets_history y
               WHERE upper(y.symbol)=upper(w.symbol) ORDER BY created_at DESC LIMIT 1
           ) an ON true
           WHERE upper(w.symbol)=%s AND w.status IN ('active','researched')
           LIMIT 1""",
        (sym,),
    )
    row = cur.fetchone()
    if not row:
        return {"symbol": sym}
    keys = [d[0] for d in cur.description]
    return dict(zip(keys, row))


def _normalize_theme(name: str | None) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    return _PROXY_SLEEVE_TO_THEME.get(raw, raw)


def _sale_tier(event: dict[str, Any]) -> str:
    proceeds = _as_float(event.get("proceeds_usd"))
    inst = str(event.get("instrument_type") or "").lower()
    if proceeds >= MAJOR_PROCEEDS_USD or inst in ("mutual_fund", "fund"):
        return "major"
    if proceeds >= MATERIAL_PROCEEDS_USD:
        return "moderate"
    return "minor"


def _sale_context(event: dict[str, Any], lt: dict[str, Any]) -> dict[str, Any]:
    tier = _sale_tier(event)
    reduced: list[str] = []
    for row in lookthrough_delta_for_sale(event, lt):
        theme = _normalize_theme(str(row.get("theme") or ""))
        if theme and theme not in reduced:
            reduced.append(theme)
    proxy_sleeve = _normalize_theme(str(event.get("proxy_sleeve") or ""))
    if proxy_sleeve and proxy_sleeve not in reduced:
        reduced.append(proxy_sleeve)
    proxy = str(event.get("proxy_symbol") or "").upper()
    if proxy:
        mapped = _ETF_SLEEVE_MAP.get(proxy)
        if mapped and mapped not in reduced:
            reduced.append(mapped)
    sold = str(event.get("symbol") or "").upper()
    if sold in _SOLD_ETF_THEME:
        theme = _SOLD_ETF_THEME[sold]
        if theme not in reduced:
            reduced.append(theme)
    elif str(event.get("instrument_type") or "").lower() == "etf" and sold in _ETF_SLEEVE_MAP:
        theme = _ETF_SLEEVE_MAP[sold]
        if theme not in reduced:
            reduced.append(theme)
    return {
        "tier": tier,
        "proceeds_usd": _as_float(event.get("proceeds_usd")),
        "reduced_themes": reduced,
        "sold_symbol": str(event.get("symbol") or "").upper(),
        "proxy_symbol": proxy or None,
    }


def _sector_peers(cur, sold_symbol: str, *, limit: int = 4) -> list[str]:
    """Watchlist names in the same sector as the sold stock (stock trims only)."""
    sym = sold_symbol.upper()
    cur.execute(
        """SELECT p.sector FROM symbol_profiles p WHERE upper(p.symbol)=%s LIMIT 1""",
        (sym,),
    )
    row = cur.fetchone()
    sector = str(row[0] or "").strip() if row else ""
    if not sector:
        return []
    cur.execute(
        """SELECT w.symbol FROM watchlist_items w
           JOIN symbol_profiles p ON upper(p.symbol)=upper(w.symbol)
           JOIN LATERAL (
               SELECT recommendation FROM watchlist_final_synthesis f
               WHERE upper(f.symbol)=upper(w.symbol) ORDER BY created_at DESC LIMIT 1
           ) fs ON true
           WHERE w.status IN ('active','researched')
             AND p.sector=%s
             AND upper(w.symbol)<>%s
             AND w.symbol ~ '^[A-Z]{1,5}$'
             AND fs.recommendation IN ('BUY','ADD','ADD_ON_PULLBACK')
           ORDER BY w.hermes_rank ASC NULLS LAST LIMIT %s""",
        (sector, sym, limit),
    )
    return [str(r[0]).upper() for r in cur.fetchall() if r and r[0]]


def _candidate_pool(
    *,
    event: dict[str, Any],
    sale_ctx: dict[str, Any],
    sold_proxy: str | None,
    account: str,
    cur,
) -> list[str]:
    """Sale-specific candidates — replace reduced exposure first; portfolio gaps only on major sales."""
    tier = sale_ctx.get("tier") or "minor"
    if tier == "minor":
        return []

    reduced = list(sale_ctx.get("reduced_themes") or [])
    sold = str(event.get("symbol") or "").upper()
    pool: list[str] = []

    for theme in reduced:
        for sym in _THEME_ETF_MAP.get(theme, []):
            pool.append(sym)

    if tier == "major":
        gaps = sleeve_gaps(load_lookthrough_summary())
        for g in gaps[:3]:
            theme = g["theme"]
            if theme in reduced:
                continue
            for sym in _THEME_ETF_MAP.get(theme, [])[:2]:
                pool.append(sym)

    if not event.get("proxy_symbol") and tier in ("moderate", "major"):
        pool.extend(_sector_peers(cur, sold, limit=3))

    held = _held_symbols()
    if tier == "major":
        for sym in ("SCHD", "BND", "JEPI", "JEPQ"):
            if sym in held:
                pool.append(sym)

    out, seen = [], set()
    for sym in pool:
        su = sym.upper()
        if su in seen or su == sold:
            continue
        if sold_proxy and su == str(sold_proxy).upper():
            continue
        seen.add(su)
        out.append(su)
    return out[:16]


def _concentration_pct(symbol: str, lt: dict[str, Any]) -> float:
    themes = lt.get("themes") or {}
    ad = lt.get("accounts_detail") or {}
    total = _as_float(lt.get("portfolio_total"), 1.0)
    # direct holdings weight from holdings.json
    hold = _load_json(STATE / "holdings.json", {}).get("holdings") or []
    mv = sum(_as_float(h.get("market_value")) for h in hold if str(h.get("symbol") or "").upper() == symbol.upper())
    return round(mv / total * 100.0, 2) if total else 0.0


def score_candidate(
    symbol: str,
    *,
    event: dict[str, Any],
    market: dict[str, Any],
    gaps: list[dict[str, Any]],
    lt: dict[str, Any],
    cur,
    sale_ctx: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    sym = symbol.upper()
    wl = _watchlist_row(cur, sym)
    cio = str(wl.get("cio_view") or "").upper()
    is_sleeve_etf = sym in _ETF_SLEEVE_MAP
    sleeve = _ETF_SLEEVE_MAP.get(sym, wl.get("sector") or "Other")
    gap = next((g for g in gaps if g["theme"] == sleeve or (sleeve in g["theme"])), None)
    if not gap and is_sleeve_etf:
        gap = next((g for g in gaps if _ETF_SLEEVE_MAP[sym] == g["theme"]), None)
    closes_sleeve_gap = bool(gap and _as_float(gap.get("gap_pct")) >= 1.0)

    # CIO AVOID blocks speculative names — but sleeve-gap ETFs (ITA, BND, …) may be CIO IGNORE
    # while still being the operator's official underweight fill (rotation advisor surfaces them).
    if cio in CIO_AVOID and not (is_sleeve_etf and closes_sleeve_gap):
        return None

    card = _symbol_cards().get(sym) or {}
    sentiment = _as_float(card.get("news_score") or card.get("sentiment_score"))
    upside = _as_float((card.get("analyst") or {}).get("upside_pct"))

    try:
        from hermes_data_access import get_hermes_context
        hermes = get_hermes_context(sym, research_limit=2, external_limit=2)
    except Exception:
        hermes = {}

    h_score = _as_float((hermes.get("score") or {}).get("composite"))
    h_rank = (hermes.get("score") or {}).get("rank")
    research_n = len(hermes.get("research") or [])
    external_n = len(hermes.get("external_lanes") or [])

    score = 0.0
    evidence: dict[str, Any] = {"sleeve": sleeve, "instrument_type": wl.get("instrument_type") or ("etf" if is_sleeve_etf else "stock")}
    ctx = sale_ctx or {}
    tier = ctx.get("tier") or _sale_tier(event)
    reduced = list(ctx.get("reduced_themes") or [])
    fills_sale_gap = bool(reduced and (sleeve in reduced or any(rt in sleeve for rt in reduced)))

    if fills_sale_gap:
        score += 50.0
        evidence["fills_sale_gap"] = True
        evidence["replaces_theme"] = next((t for t in reduced if t in sleeve or sleeve in t), reduced[0])
    elif gap and closes_sleeve_gap:
        if tier == "major":
            score += min(18.0, gap["gap_pct"] * 5.0)
            evidence["rotation_to_portfolio_gap"] = gap["theme"]
            evidence["sleeve_gap_pct"] = gap["gap_pct"]
        else:
            score -= 12.0
            evidence["unrelated_portfolio_gap"] = gap["theme"]
    elif gap:
        evidence["sleeve_gap_pct"] = gap.get("gap_pct")

    if is_sleeve_etf and fills_sale_gap:
        score += 15.0
        evidence["sleeve_etf_replacement"] = True

    proceeds = _as_float(event.get("proceeds_usd"))
    if is_sleeve_etf and proceeds >= 25000:
        score += 12.0
        evidence["large_proceeds_etf_fit"] = True
    elif not is_sleeve_etf and proceeds >= 50000:
        score -= 15.0
        evidence["large_proceeds_stock_caution"] = True

    if cio in CIO_AVOID and is_sleeve_etf and closes_sleeve_gap:
        score -= 5.0
        evidence["cio_caution"] = cio

    if h_score > 0:
        score += min(25.0, h_score / 4.0)
        evidence["hermes_composite"] = h_score
    if h_rank is not None:
        try:
            score += max(0.0, 20.0 - float(h_rank) * 0.15)
            evidence["hermes_rank"] = h_rank
        except (TypeError, ValueError):
            pass
    if research_n:
        score += min(8.0, research_n * 3.0)
        evidence["hermes_research_notes"] = research_n
    if external_n:
        score += min(6.0, external_n * 2.0)
        evidence["hermes_external_lanes"] = external_n

    if cio in CIO_BUY:
        score += 15.0
        evidence["cio_view"] = cio
    elif cio == "HOLD" and is_sleeve_etf:
        score += 6.0
        evidence["cio_view"] = cio
    elif wl.get("cio_view"):
        evidence["cio_view"] = cio or wl.get("cio_view")
        if cio == "REBALANCE_TRIM":
            score -= 8.0
            evidence["cio_trim_caution"] = True

    if sentiment > 0.25:
        score += 8.0
        evidence["news_sentiment"] = round(sentiment, 3)
    elif sentiment < -0.25:
        score -= 12.0
        evidence["news_sentiment"] = round(sentiment, 3)

    if upside > 10:
        score += min(10.0, upside / 5.0)
        evidence["analyst_upside_pct"] = upside
    elif upside < -5:
        score -= 8.0
        evidence["analyst_upside_pct"] = upside

    posture = market.get("regime_posture") or "neutral"
    for sleeve_name, bonus in (_REGIME_SLEEVE_BIAS.get(posture) or {}).items():
        if sleeve_name in sleeve or sleeve == sleeve_name:
            score += bonus
            evidence["regime_alignment"] = f"{posture}+{bonus}"

    geo = market.get("geopolitical") or {}
    geo_posture = geo.get("posture") or "neutral"
    if geo_posture != "neutral":
        for sleeve_name, bonus in (_GEOPOLITICAL_SLEEVE_BIAS.get(geo_posture) or {}).items():
            if sleeve_name in sleeve or sleeve == sleeve_name:
                score += bonus
                evidence["geopolitical_alignment"] = f"{geo_posture}+{bonus}"
    if sym in (geo.get("defense_symbols") or []):
        score += 10.0
        evidence["geopolitical_research_symbol"] = True

    conc = _concentration_pct(sym, lt)
    if conc >= 8.0:
        score -= min(30.0, (conc - 5.0) * 4.0)
        evidence["concentration_pct"] = conc

    proxy = str(event.get("proxy_symbol") or "").upper()
    if proxy and sym == proxy:
        score -= 50.0
        evidence["duplicate_proxy_penalty"] = True

    if score < 5.0:
        return None

    share = min(0.45, max(0.12, score / 120.0))
    low = round(proceeds * share * 0.85, 0) if proceeds else None
    high = round(proceeds * share * 1.15, 0) if proceeds else None

    return {
        "symbol": sym,
        "score": round(score, 1),
        "sleeve": sleeve,
        "review_amount_range": {"low": low, "high": high, "basis": "score-weighted share of proceeds"},
        "rationale": _rationale(sym, evidence, event, market, sale_ctx=ctx),
        "evidence": evidence,
        "hermes": {
            "composite": h_score or None,
            "rank": h_rank,
            "research_count": research_n,
            "external_lane_count": external_n,
            "research_snippets": (hermes.get("research") or [])[:2],
            "external_snippets": (hermes.get("external_lanes") or [])[:2],
        },
        "market_context": {
            "regime_posture": posture,
            "regime_label": (market.get("regime") or {}).get("label"),
            "geopolitical_posture": geo_posture,
            "think_tank_updated": (market.get("think_tank") or {}).get("updated_at"),
        },
    }


def _rationale(sym: str, evidence: dict, event: dict, market: dict, *, sale_ctx: dict | None = None) -> str:
    parts = []
    sold = str(event.get("symbol") or "").upper()
    if evidence.get("fills_sale_gap") and evidence.get("replaces_theme"):
        parts.append(f"replaces {evidence['replaces_theme']} exposure lost from selling {sold}")
    elif evidence.get("rotation_to_portfolio_gap"):
        parts.append(
            f"rotation slice into underweight {evidence['rotation_to_portfolio_gap']} "
            f"(not replacing {sold} sleeve)"
        )
    elif evidence.get("unrelated_portfolio_gap"):
        return f"Deprioritized — portfolio gap fill unrelated to {sold} sale"
    if evidence.get("sleeve_gap_pct") and evidence.get("rotation_to_portfolio_gap"):
        parts.append(f"portfolio gap {evidence['sleeve_gap_pct']}% under floor")
    if evidence.get("hermes_rank"):
        parts.append(f"Hermes rank #{evidence['hermes_rank']}")
    if evidence.get("cio_view") in CIO_BUY:
        parts.append(f"CIO {evidence['cio_view']}")
    if evidence.get("news_sentiment") is not None and evidence["news_sentiment"] > 0.2:
        parts.append("positive news sentiment")
    if evidence.get("regime_alignment"):
        parts.append(f"aligns with {market.get('regime_posture')} regime")
    if evidence.get("geopolitical_alignment"):
        geo = market.get("geopolitical") or {}
        parts.append(f"geopolitical {geo.get('posture')} tilt")
    if evidence.get("geopolitical_research_symbol"):
        parts.append("flagged in defense/geopolitical Hermes research")
    if evidence.get("duplicate_proxy_penalty"):
        parts.append("avoid — duplicates sold fund proxy exposure")
    if evidence.get("concentration_pct"):
        parts.append(f"watch concentration ({evidence['concentration_pct']}%)")
    proxy = event.get("proxy_symbol")
    if sold and proxy and not parts:
        parts.insert(0, f"Proceeds from {sold} (proxy {proxy})")
    return "; ".join(parts) if parts else f"Review {sym} for redeploy"


def lookthrough_delta_for_sale(event: dict[str, Any], lt: dict[str, Any]) -> list[dict[str, Any]]:
    """Estimate theme exposure reduction from selling symbol (via proxy sleeve)."""
    proxy = event.get("proxy_symbol")
    sold = str(event.get("symbol") or "").upper()
    proceeds = _as_float(event.get("proceeds_usd"))
    total = _as_float(lt.get("portfolio_total"), 1.0)
    if not proceeds or not total:
        return []
    if not proxy and sold in _SOLD_ETF_THEME:
        sleeve = _SOLD_ETF_THEME[sold]
    elif not proxy and str(event.get("instrument_type") or "").lower() == "etf" and sold in _ETF_SLEEVE_MAP:
        sleeve = _ETF_SLEEVE_MAP[sold]
    elif not proxy:
        return []
    else:
        sleeve = _ETF_SLEEVE_MAP.get(str(proxy).upper()) or _normalize_theme(str(event.get("proxy_sleeve") or ""))
    if not sleeve:
        sleeve = "Unknown"
    delta_pct = round(-proceeds / total * 100.0, 2)
    return [{
        "theme": sleeve,
        "delta_pct": delta_pct,
        "proceeds_usd": proceeds,
        "note": f"Estimated reduction from selling {event.get('symbol')} (mapped proxy {proxy})",
    }]


def build_redeploy_plan(event: dict[str, Any]) -> dict[str, Any]:
    market = load_market_context()
    lt = load_lookthrough_summary()
    gaps = sleeve_gaps(lt)
    sale_ctx = _sale_context(event, lt)
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    tier = sale_ctx.get("tier") or "minor"
    advisory_note = None
    ranked: list[dict[str, Any]] = []
    if tier == "minor":
        advisory_note = (
            f"${sale_ctx.get('proceeds_usd', 0):,.0f} trim — below ${int(MATERIAL_PROCEEDS_USD):,} redeploy "
            "threshold; hold as cash unless part of a larger rebalance."
        )
    else:
        pool = _candidate_pool(
            event=event,
            sale_ctx=sale_ctx,
            sold_proxy=event.get("proxy_symbol"),
            account=str(event.get("account") or ""),
            cur=cur,
        )
        for sym in pool:
            row = score_candidate(
                sym, event=event, market=market, gaps=gaps, lt=lt, cur=cur, sale_ctx=sale_ctx,
            )
            if row and not str(row.get("rationale") or "").startswith("Deprioritized"):
                ranked.append(row)
        ranked.sort(key=lambda r: -r["score"])
    max_targets = 6 if tier == "major" else 4
    return {
        "market_context": market,
        "sale_context": sale_ctx,
        "sleeve_gaps": gaps[:6],
        "lookthrough_delta": lookthrough_delta_for_sale(event, lt),
        "targets": ranked[:max_targets],
        "advisory_note": advisory_note,
        "methodology": (
            "Sale-specific score: replace reduced sleeve from THIS sell first; portfolio-gap "
            "rotation only on major (≥$25k/fund) proceeds; minors suppressed. Hermes + CIO + "
            "regime + geopolitical. Advisory only."
        ),
    }


def enrich_event(event: dict[str, Any]) -> dict[str, Any]:
    try:
        from lib.redeploy_data_truth import enrich_event_phase_a
        event = enrich_event_phase_a(event)
    except Exception as e:
        meta = dict(event.get("metadata") or {})
        meta.setdefault("phase_a_error", str(e)[:200])
        event["metadata"] = meta
    plan = build_redeploy_plan(event)
    try:
        from lib.redeploy_plan_engine import enrich_event_phase_b
        event = enrich_event_phase_b(event, v1_plan=plan)
    except Exception as e:
        meta = dict(event.get("metadata") or {})
        meta.setdefault("phase_b_error", str(e)[:200])
        event["metadata"] = meta
    event["lookthrough_delta"] = plan.get("lookthrough_delta") or []
    # Legacy v1 targets preserved for backward-compatible UI strip
    event["redeploy_plan"] = plan.get("targets") or []
    meta = dict(event.get("metadata") or {})
    meta["market_context"] = plan.get("market_context")
    meta["sale_context"] = plan.get("sale_context")
    meta["sleeve_gaps"] = plan.get("sleeve_gaps")
    meta["advisory_note"] = plan.get("advisory_note")
    meta["methodology"] = plan.get("methodology")
    event["metadata"] = meta
    return event


def recompute_deploy_event(cur, event_id: int) -> dict[str, Any]:
    from lib.deploy_events_db import ensure_deploy_tables
    ensure_deploy_tables(cur)
    cur.execute(
        """SELECT id, event_key, symbol, account, sold_at, proceeds_usd, shares_sold,
                  realized_pnl, instrument_type, proxy_symbol, proxy_sleeve, status,
                  proceeds_settled, cash_visible_usd, source, txn_ref, metadata
           FROM deploy_events WHERE id=%s""",
        (event_id,),
    )
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "not_found"}
    keys = [d[0] for d in cur.description]
    ev = dict(zip(keys, row))
    if isinstance(ev.get("metadata"), str):
        try:
            ev["metadata"] = json.loads(ev["metadata"])
        except Exception:
            ev["metadata"] = {}
    enriched = enrich_event(ev)
    try:
        from lib.redeploy_phase_a_db import persist_phase_a
        from lib.redeploy_plan_db import persist_institutional_plans
        persist_phase_a(cur, event_id, enriched)
        persist_institutional_plans(cur, event_id, enriched)
    except Exception:
        cur.execute(
            """UPDATE deploy_events SET lookthrough_delta=%s::jsonb, redeploy_plan=%s::jsonb,
               metadata=%s::jsonb, updated_at=NOW() WHERE id=%s""",
            (json.dumps(enriched.get("lookthrough_delta") or []),
             json.dumps(enriched.get("redeploy_plan") or []),
             json.dumps(enriched.get("metadata") or {}),
             event_id),
        )
    else:
        cur.execute(
            """UPDATE deploy_events SET lookthrough_delta=%s::jsonb, redeploy_plan=%s::jsonb,
               updated_at=NOW() WHERE id=%s""",
            (json.dumps(enriched.get("lookthrough_delta") or []),
             json.dumps(enriched.get("redeploy_plan") or []),
             event_id),
        )
    pb = (enriched.get("metadata") or {}).get("phase_b") or {}
    return {
        "ok": True,
        "id": event_id,
        "targets": len(enriched.get("redeploy_plan") or []),
        "institutional_plans": len(pb.get("plans") or []),
        "plan_version": (enriched.get("metadata") or {}).get("phase_b_persisted_version"),
    }


def recompute_all_open(cur, *, limit: int = 200) -> dict[str, Any]:
    cur.execute(
        "SELECT id FROM deploy_events WHERE status='open' ORDER BY sold_at DESC LIMIT %s",
        (limit,),
    )
    ids = [r[0] for r in cur.fetchall()]
    results = [recompute_deploy_event(cur, i) for i in ids]
    return {"ok": True, "recomputed": len(results), "results": results}