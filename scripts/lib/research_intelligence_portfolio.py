"""Portfolio context for Research Intelligence advisory recommendations.

Loads holdings SSOT and produces weights, concentration flags, and sleeve
summaries so briefs can cite real allocations (not generic advice).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"

# Theme → related symbols (public ETFs/names already in or near the book)
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

_THEME_RX: list[tuple[str, re.Pattern[str]]] = [
    ("defense", re.compile(r"\bdefense\b|aerospace|military|pentagon|\bxar\b", re.I)),
    ("power_infra", re.compile(r"power|utility|utilities|data\s*center|infrastructure|nuclear|grid|\bvst\b|\bceg\b", re.I)),
    ("ai_infra", re.compile(r"\bai\b|semiconductor|chip|networking|datacenter|nvidia", re.I)),
    ("dividend_income", re.compile(r"dividend|covered.?call|income sleeve|yield|\bjepi\b|\bschd\b|\bbdc\b", re.I)),
    ("growth", re.compile(r"growth|nasdaq|megacap|\bschg\b", re.I)),
    ("materials", re.compile(r"materials|\bxlb\b|commodit", re.I)),
    ("industrials", re.compile(r"industrial|\bxli\b", re.I)),
    ("healthcare", re.compile(r"healthcare|biotech|pharma|\bdxcm\b", re.I)),
    ("bonds", re.compile(r"\bbond\b|treasury|fixed.?income|\bbnd\b|rates?", re.I)),
]

_TICKER_TOKEN = re.compile(r"\b([A-Z]{1,5})\b")


@lru_cache(maxsize=1)
def load_portfolio_context() -> dict[str, Any]:
    """Aggregate household holdings by symbol with weights."""
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
        mv = h.get("market_value")
        try:
            mv = float(mv) if mv is not None else 0.0
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
            "symbol": sym,
            "market_value": 0.0,
            "accounts": set(),
            "name": h.get("name"),
        })
        row["market_value"] += mv
        if h.get("account"):
            row["accounts"].add(str(h["account"]))

    total = sum(r["market_value"] for r in by_sym.values()) or 1.0
    for sym, r in by_sym.items():
        r["weight_pct"] = round(100.0 * r["market_value"] / total, 2)
        r["accounts"] = sorted(r["accounts"])
        r["market_value"] = round(r["market_value"], 2)

    top = sorted(by_sym.values(), key=lambda x: -x["weight_pct"])
    flags = []
    for r in top:
        if r["weight_pct"] >= 20:
            flags.append(f"{r['symbol']} is {r['weight_pct']:.1f}% of book (high concentration)")
        elif r["weight_pct"] >= 12:
            flags.append(f"{r['symbol']} is {r['weight_pct']:.1f}% of book (elevated weight)")

    # Sleeve aggregates
    sleeves = {
        "income": _sleeve_pct(by_sym, THEME_TICKERS["dividend_income"]),
        "growth": _sleeve_pct(by_sym, THEME_TICKERS["growth"]),
        "defense": _sleeve_pct(by_sym, THEME_TICKERS["defense"]),
        "power_infra": _sleeve_pct(by_sym, THEME_TICKERS["power_infra"]),
        "ai_infra": _sleeve_pct(by_sym, THEME_TICKERS["ai_infra"]),
    }

    return {
        "ok": True,
        "total_mv": round(total, 2),
        "by_symbol": by_sym,
        "top": [
            {"symbol": r["symbol"], "weight_pct": r["weight_pct"], "market_value": r["market_value"]}
            for r in top[:15]
        ],
        "flags": flags[:8],
        "sleeves": sleeves,
        "holdings_symbols": sorted(by_sym.keys()),
    }


def _sleeve_pct(by_sym: dict[str, dict], tickers: list[str]) -> float:
    return round(sum(by_sym[t]["weight_pct"] for t in tickers if t in by_sym), 2)


def detect_themes(*text_parts: str | None) -> list[str]:
    blob = " ".join(p for p in text_parts if p)
    out = []
    for tid, rx in _THEME_RX:
        if rx.search(blob) and tid not in out:
            out.append(tid)
    return out[:4]


def extract_mentioned_tickers(text: str, *, known: set[str] | None = None) -> list[str]:
    """Pull ticker-like tokens; prefer known holdings / theme lists."""
    known = known or set()
    theme_all = {t for ts in THEME_TICKERS.values() for t in ts}
    found: list[str] = []
    for m in _TICKER_TOKEN.finditer(text or ""):
        t = m.group(1)
        if t in {"A", "I", "OR", "AND", "THE", "FOR", "TO", "OF", "ON", "IN", "AT", "BY", "ETF", "CEO", "CFO", "USA", "NY", "AI"}:
            continue
        if t in known or t in theme_all or (len(t) >= 2 and t.isupper()):
            if t not in found and (t in known or t in theme_all):
                found.append(t)
    return found[:8]


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
    """Deterministic portfolio-aware investment implications + ticker/sizing."""
    portfolio = portfolio or load_portfolio_context()
    by_sym = portfolio.get("by_symbol") or {}
    held = set(portfolio.get("holdings_symbols") or [])
    sleeves = portfolio.get("sleeves") or {}
    flags = portfolio.get("flags") or []
    blob = f"{title} {summary or ''} {thesis or ''}"
    themes = detect_themes(title, summary, thesis)
    mentioned = extract_mentioned_tickers(blob, known=held | {t for ts in THEME_TICKERS.values() for t in ts})
    if symbol:
        mentioned = [symbol.upper()] + [m for m in mentioned if m != symbol.upper()]

    tickers: list[dict[str, Any]] = []
    sizing_bits: list[str] = []
    implications: list[str] = []
    action = "review"
    action_label = "Review desk implications"
    action_detail = "Open the full brief, verify sources, then decide watch / hold / act with stops."

    # ── Retirement ─────────────────────────────────────────────────────
    if primary == "retirement_tax":
        action = "retirement_plan"
        action_label = "Review Roth / tax plan"
        action_detail = (
            "Map conversion pacing to Golden Window and IRMAA two-year lookback before any large conversion batch."
        )
        implications.append(
            "This is a tax/retirement sequencing decision, not a new equity risk bet. "
            "Prioritize MAGI management over chasing yield."
        )
        # Income sleeve context
        inc = sleeves.get("income") or 0
        if inc >= 20:
            sizing_bits.append(
                f"Income-oriented sleeve is already ~{inc:.1f}% of book "
                f"(SCHD/JEPI/JEPQ/DIVI etc.) — do not pile new high-yield risk solely for cash flow."
            )
        schg = by_sym.get("SCHG", {}).get("weight_pct")
        if schg and schg >= 15:
            sizing_bits.append(
                f"SCHG is ~{schg:.1f}% of household book — growth concentration is already high; "
                f"Roth conversion cash sourcing should avoid forcing growth sales at bad levels."
            )
        for f in flags[:2]:
            sizing_bits.append(f)
        tickers.append({
            "symbol": "—",
            "role": "plan",
            "suggested_weight_pct": None,
            "rationale": "No new ticker required — execution is account-type sequencing (Roth/Traditional/taxable).",
        })

    # ── Risk / stops ───────────────────────────────────────────────────
    elif primary == "risk_regime" or (research_type or "") in (
        "stop_health", "stop_curation", "protection_advisory"
    ):
        action = "review_stop"
        sym = (symbol or (mentioned[0] if mentioned else None) or "").upper() or None
        if sym and sym in by_sym:
            w = by_sym[sym]["weight_pct"]
            action_label = f"Review {sym} stop / protection"
            action_detail = (
                f"{sym} is ~{w:.1f}% of book (${by_sym[sym]['market_value']:,.0f}). "
                f"Use Stop Management Replace mode — do not leave cancelled stops."
            )
            tickers.append({
                "symbol": sym,
                "role": "protect",
                "suggested_weight_pct": f"keep ~{w:.1f}% until thesis breaks",
                "rationale": "Holdings-linked stop quality issue — fix protection before adding risk.",
            })
            implications.append(
                f"Capital preservation on {sym} comes before new theme adds while stops are weak or cancelled."
            )
            sizing_bits.append(
                f"Do not increase {sym} until stop is healthy; if concentration is elevated, "
                f"consider trimming 5–10% of the position only after stop is set."
            )
        else:
            action_label = "Inspect risk / stops"
            action_detail = "Open Stop Management for holdings without healthy protection."
            implications.append("Book-level stop hygiene dominates alpha until heat and near-triggers are clean.")

    # ── Dividend / income ──────────────────────────────────────────────
    elif primary == "dividend_income" or "dividend_income" in themes:
        action = "income_sleeve"
        inc = sleeves.get("income") or 0
        action_label = "Check income sleeve vs IRMAA"
        held_income = [t for t in THEME_TICKERS["dividend_income"] if t in by_sym]
        for t in held_income[:5]:
            w = by_sym[t]["weight_pct"]
            tickers.append({
                "symbol": t,
                "role": "hold_review",
                "suggested_weight_pct": f"current {w:.1f}%",
                "rationale": "Existing income holding — review yield quality vs NAV/credit risk.",
            })
        # Suggest quality over junk
        if inc >= 25:
            sizing_bits.append(
                f"Income sleeve ~{inc:.1f}% of book — prefer quality (SCHD) over stacking BDCs; "
                f"any add should be small (1–3% book) and stop-managed."
            )
            action_detail = (
                f"Income already ~{inc:.1f}%. Avoid high-yield traps; if adding, cap new BDC/CEF at 1–2% of book."
            )
        else:
            sizing_bits.append(
                f"Income sleeve ~{inc:.1f}% of book — room for +2–4% quality dividend exposure if IRMAA budget allows."
            )
            if "SCHD" in by_sym:
                tickers.append({
                    "symbol": "SCHD",
                    "role": "add_candidate",
                    "suggested_weight_pct": f"+1–3% (now {by_sym['SCHD']['weight_pct']:.1f}%)",
                    "rationale": "Quality dividend core already held — scale modestly rather than new speculative yield.",
                })
        implications.append(
            "Income decisions must clear SSDI/IRMAA constraints: more yield is not always more after-tax spending power."
        )

    # ── Sector / macro themes ──────────────────────────────────────────
    elif primary in ("sector_thematic", "macro_geo") or themes:
        theme = themes[0] if themes else ("defense" if primary == "sector_thematic" else "macro")
        theme_tickers = THEME_TICKERS.get(theme, [])
        held_theme = [t for t in theme_tickers if t in by_sym]
        sleeve_pct = sleeves.get(theme) or _sleeve_pct(by_sym, theme_tickers)
        growth = sleeves.get("growth") or 0

        action = "theme_position"
        if held_theme:
            action_label = f"Align {theme.replace('_', ' ')} sleeve"
            for t in held_theme[:4]:
                w = by_sym[t]["weight_pct"]
                tickers.append({
                    "symbol": t,
                    "role": "hold_review",
                    "suggested_weight_pct": f"current {w:.1f}%",
                    "rationale": f"Already held in {theme.replace('_', ' ')} theme.",
                })
            # candidates not held
            for t in theme_tickers:
                if t not in by_sym and len(tickers) < 6:
                    tickers.append({
                        "symbol": t,
                        "role": "add_candidate",
                        "suggested_weight_pct": "1–3% starter" if sleeve_pct < 10 else "only if trimming elsewhere",
                        "rationale": f"Theme peer not currently held; use only with stop and heat check.",
                    })
        else:
            action_label = f"Consider {theme.replace('_', ' ')} exposure"
            for t in theme_tickers[:3]:
                tickers.append({
                    "symbol": t,
                    "role": "add_candidate",
                    "suggested_weight_pct": "2–4% total theme",
                    "rationale": f"Not held — candidate for {theme.replace('_', ' ')} expression.",
                })

        if sleeve_pct >= 12:
            sizing_bits.append(
                f"{theme.replace('_', ' ').title()} exposure already ~{sleeve_pct:.1f}% — "
                f"prefer rebalancing within sleeve over net new risk."
            )
            action_detail = (
                f"Theme sleeve ~{sleeve_pct:.1f}%. Prefer rotate/upgrade holdings; avoid adding if portfolio heat is elevated."
            )
        else:
            room = max(0.0, 8.0 - sleeve_pct)
            sizing_bits.append(
                f"{theme.replace('_', ' ').title()} sleeve ~{sleeve_pct:.1f}% of book — "
                f"room for roughly +{room:.0f}% total theme if funded by trims elsewhere."
            )
            action_detail = (
                f"If thesis is high conviction, stage +2–4% theme exposure with stops; "
                f"fund from overweight growth if SCHG concentration is high."
            )

        if growth >= 20:
            schg_w = by_sym.get("SCHG", {}).get("weight_pct")
            if schg_w:
                sizing_bits.append(
                    f"Growth concentration: SCHG ~{schg_w:.1f}% — funding new themes by trimming 3–6% of SCHG "
                    f"reduces single-name/ETF concentration."
                )
                tickers.append({
                    "symbol": "SCHG",
                    "role": "trim_candidate",
                    "suggested_weight_pct": f"trim 3–6% of book weight (now {schg_w:.1f}%)",
                    "rationale": "Primary funding source if rotating into new thematic risk.",
                })

        implications.append(
            f"Theme alignment for {theme.replace('_', ' ')} should be expressed with names already on the "
            f"desk watchlist/holdings when possible, and always with protective stops (Replace mode)."
        )

    # ── Company / holdings ─────────────────────────────────────────────
    elif is_held and symbol and symbol.upper() in by_sym:
        sym = symbol.upper()
        w = by_sym[sym]["weight_pct"]
        action = "position_review"
        action_label = f"Review {sym} position"
        tickers.append({
            "symbol": sym,
            "role": "hold_review",
            "suggested_weight_pct": f"current {w:.1f}%",
            "rationale": "Holding-linked intelligence — update thesis, stop, and size.",
        })
        if w >= 12:
            sizing_bits.append(
                f"{sym} is ~{w:.1f}% of book — if thesis weakens, trim 10–20% of the position "
                f"(~{w*0.1:.1f}–{w*0.2:.1f}% of portfolio) rather than all-or-nothing."
            )
            action_detail = f"{sym} is oversized at ~{w:.1f}%. Confirm stop health; consider staged trim if conviction drops."
        else:
            sizing_bits.append(f"{sym} is a moderate ~{w:.1f}% weight — size changes should stay within ±1–2% of book.")
            action_detail = f"Update {sym} thesis and stops; size is not a concentration emergency."
        implications.append(
            f"Any add to {sym} must clear stop policy and not push heat higher without a plan."
        )

    else:
        # Generic with any mentioned holdings
        for t in mentioned[:4]:
            if t in by_sym:
                tickers.append({
                    "symbol": t,
                    "role": "hold_review",
                    "suggested_weight_pct": f"current {by_sym[t]['weight_pct']:.1f}%",
                    "rationale": "Mentioned and held.",
                })
        implications.append(
            "Treat as advisory context until linked to a holding, theme sleeve, or retirement action."
        )
        if portfolio.get("top"):
            tops = ", ".join(f"{t['symbol']} {t['weight_pct']}%" for t in portfolio["top"][:5])
            sizing_bits.append(f"Largest weights today: {tops}.")

    # Risk caveat always
    risk_caveat = (
        "Advisory only — not an order. Size within risk limits; place/refresh stops via Stop Management "
        "(Replace mode). Recheck portfolio heat before net new risk."
    )
    if flags:
        risk_caveat += " Concentration flags: " + "; ".join(flags[:2]) + "."

    # Drop placeholders; retirement often has no ticker add — sizing/plan text is enough
    tickers = [t for t in tickers if t.get("symbol") and t["symbol"] not in ("—", "PLAN")][:6]

    investment_implications = " ".join(implications) if implications else (
        "Map this intelligence to holdings weights and retirement constraints before acting."
    )
    sizing_note = " ".join(sizing_bits) if sizing_bits else (
        f"Household book ~${(portfolio.get('total_mv') or 0)/1e6:.2f}M across {len(by_sym)} symbols — "
        f"keep any single add small unless funding a trim."
    )

    return {
        "investment_implications": investment_implications[:700],
        "ticker_recommendations": tickers,
        "sizing_guidance": sizing_note[:700],
        "risk_caveat": risk_caveat[:500],
        "portfolio_snapshot": {
            "total_mv": portfolio.get("total_mv"),
            "top": portfolio.get("top", [])[:8],
            "sleeves": sleeves,
            "related_weights": {
                t["symbol"]: by_sym[t["symbol"]]["weight_pct"]
                for t in tickers
                if t.get("symbol") in by_sym
            },
            "flags": flags[:5],
            "themes": themes,
        },
        "next_action": {
            "label": action_label,
            "detail": action_detail,
            "href_hint": (
                "retirement" if action == "retirement_plan" else
                "risk" if action == "review_stop" else
                "portfolio" if action in ("position_review", "theme_position", "income_sleeve") else
                "detail"
            ),
            "action_type": action,
        },
    }


def clear_portfolio_cache() -> None:
    load_portfolio_context.cache_clear()
