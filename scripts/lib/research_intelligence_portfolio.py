"""Portfolio context for Research Intelligence advisory recommendations.

Loads holdings SSOT and produces weights, concentration flags, and sleeve
summaries so briefs can cite real allocations (not generic advice).

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

# Title/primary-gated theme detection (body alone must not invent industrials from "distribution")
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

    total = sum(r["market_value"] for r in by_sym.values()) or 1.0
    for r in by_sym.values():
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

    sleeves = {k: _sleeve_pct(by_sym, v) for k, v in THEME_TICKERS.items()}
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


def _risk_caveat(flags: list[str]) -> str:
    base = (
        "Advisory only — not an order. Size within risk limits; place/refresh stops via "
        "Stop Management (Replace mode). Recheck portfolio heat before net new risk."
    )
    if flags:
        base += " Concentration flags: " + "; ".join(flags[:2]) + "."
    return base[:500]


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
    """Portfolio-aware advisory — gated strictly by primary category."""
    portfolio = portfolio or load_portfolio_context()
    by_sym = portfolio.get("by_symbol") or {}
    held = set(portfolio.get("holdings_symbols") or [])
    sleeves = portfolio.get("sleeves") or {}
    flags = list(portfolio.get("flags") or [])
    primary = primary or (cats[0] if cats else "company_ticker")
    rtype = research_type or ""

    tickers: list[dict[str, Any]] = []
    sizing_bits: list[str] = []
    implications: list[str] = []
    action_label = "Review desk implications"
    action_detail = "Open the full brief, verify sources, then decide with stops if any position change."
    href = "detail"
    action = "review"

    # ── Stops / risk (type map or primary) ──────────────────────────────
    if primary == "risk_regime" or rtype in _STOP_TYPES:
        action, href = "review_stop", "risk"
        sym = (symbol or "").upper() or None
        if not sym:
            mentioned = extract_mentioned_tickers(f"{title} {summary}", known=held)
            sym = mentioned[0] if mentioned else None
        if sym and sym in by_sym:
            w = by_sym[sym]["weight_pct"]
            action_label = f"Review {sym} stop / protection"
            action_detail = (
                f"{sym} is ~{w:.1f}% of book (${by_sym[sym]['market_value']:,.0f}). "
                f"Use Stop Management Replace mode — do not leave cancelled stops."
            )
            tickers.append({
                "symbol": sym, "role": "protect",
                "suggested_weight_pct": f"keep ~{w:.1f}% until thesis breaks",
                "rationale": "Holdings-linked stop quality — fix protection before adding risk.",
            })
            implications.append(
                f"Capital preservation on {sym} comes before new theme adds while stops are weak."
            )
            sizing_bits.append(
                f"Do not increase {sym} until stop is healthy; if conviction drops, trim 5–10% of the position after stop is set."
            )
        else:
            action_label = "Inspect risk / stops"
            action_detail = "Open Stop Management for holdings without healthy protection."
            implications.append("Book-level stop hygiene dominates alpha until near-triggers are clean.")

    # ── Retirement / tax (topic-specific — avoid identical blurb on every card) ─
    elif primary == "retirement_tax":
        action, href = "retirement_plan", "retirement"
        # Prefer TITLE for subtype so body IRMAA mentions don't mis-route every card
        title_l = (title or "").lower()
        blob_l = f"{title} {summary or ''}".lower()
        schg = by_sym.get("SCHG", {}).get("weight_pct")
        schd = by_sym.get("SCHD", {}).get("weight_pct")
        inc = sleeves.get("dividend_income") or 0

        if re.search(r"monitor|integration|workflow|dashboard|alert", title_l):
            action_label = "Wire IRMAA / conversion alerts into the desk"
            action_detail = (
                "Ops task: alert on IRMAA thresholds and conversion calendar in Command Center — not a new buy list."
            )
            implications.append(
                "Monitoring stack tracks MAGI path and Medicare dates; equity weights are context only."
            )
            if schg and schg >= 20:
                sizing_bits.append(
                    f"Surface SCHG concentration (~{schg:.1f}%) as a dashboard risk flag, not conversion funding default."
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
                "IRMAA is MAGI-driven (two-year lookback) — conversion timing is a premium decision, not equity beta."
            )
            sizing_bits.append(
                "No new equity ticket. Cap conversion batches to remaining room under the next IRMAA tier "
                "(verify SSA/CMS tables)."
            )
            if inc >= 30:
                sizing_bits.append(
                    f"Taxable income sleeve ~{inc:.1f}% already distributes — avoid stacking more taxable yield that lifts MAGI."
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
                "No default ticker add. Freeze large re-titling until counsel confirms look-back triggers."
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
                    f"If sales fund conversions, avoid auto-liquidating SCHG at ~{schg:.1f}% — plan trims with stops."
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
            if schg and schg >= 20:
                sizing_bits.append(f"Note: SCHG concentration ~{schg:.1f}% is separate from tax sequencing.")

    # ── Dividend (PRIMARY only) ────────────────────────────────────────
    elif primary == "dividend_income":
        action, href = "income_sleeve", "portfolio"
        inc = sleeves.get("dividend_income") or 0
        action_label = "Check income sleeve vs IRMAA"
        held_income = [t for t in THEME_TICKERS["dividend_income"] if t in by_sym]
        for t in held_income[:5]:
            tickers.append({
                "symbol": t, "role": "hold_review",
                "suggested_weight_pct": f"current {by_sym[t]['weight_pct']:.1f}%",
                "rationale": "Existing income holding — review yield quality vs credit/NAV risk.",
            })
        if inc >= 25:
            sizing_bits.append(
                f"Income sleeve ~{inc:.1f}% of book — prefer quality (SCHD) over stacking BDCs; "
                f"any add ≤1–2% of book with a stop."
            )
            action_detail = f"Income already ~{inc:.1f}%. Avoid high-yield traps."
        else:
            sizing_bits.append(
                f"Income sleeve ~{inc:.1f}% — room for +2–4% quality dividend if IRMAA budget allows."
            )
            action_detail = "Scale quality dividend modestly; clear MAGI before adding taxable yield."
        implications.append(
            "Income decisions must clear SSDI/IRMAA: more yield is not always more after-tax spending power."
        )

    # ── Sector / macro (PRIMARY only) ──────────────────────────────────
    elif primary in ("sector_thematic", "macro_geo"):
        themes = detect_themes_from_title(title)
        # Map macro bond language
        if primary == "macro_geo" and re.search(r"bond|tips|treasury|fixed.?income", title or "", re.I):
            themes = ["bonds"] + [t for t in themes if t != "bonds"]
        theme = themes[0] if themes else None
        if not theme:
            # Weak sector without clear theme — light advisory only
            action_label = "Map thesis to sleeves"
            action_detail = "Identify which held ETFs express this theme before adding new names."
            implications.append(
                "No clear theme tickers from title — do not invent CAT/DE/GE-style lists from body keywords."
            )
            if flags:
                sizing_bits.extend(flags[:2])
        else:
            action, href = "theme_position", "portfolio"
            theme_tickers = THEME_TICKERS.get(theme, [])
            held_theme = [t for t in theme_tickers if t in by_sym]
            sleeve_pct = sleeves.get(theme) or _sleeve_pct(by_sym, theme_tickers)
            growth = sleeves.get("growth") or 0
            label_theme = theme.replace("_", " ")

            if held_theme:
                action_label = f"Align {label_theme} sleeve"
                for t in held_theme[:4]:
                    tickers.append({
                        "symbol": t, "role": "hold_review",
                        "suggested_weight_pct": f"current {by_sym[t]['weight_pct']:.1f}%",
                        "rationale": f"Already held in {label_theme}.",
                    })
                for t in theme_tickers:
                    if t not in by_sym and len(tickers) < 5:
                        tickers.append({
                            "symbol": t, "role": "add_candidate",
                            "suggested_weight_pct": "1–3% starter" if sleeve_pct < 10 else "only if trimming elsewhere",
                            "rationale": "Theme peer not held — only with stop + heat check.",
                        })
            else:
                action_label = f"Consider {label_theme} exposure"
                for t in theme_tickers[:3]:
                    tickers.append({
                        "symbol": t, "role": "add_candidate",
                        "suggested_weight_pct": "2–4% total theme",
                        "rationale": f"Not held — candidate for {label_theme}.",
                    })

            if sleeve_pct >= 12:
                sizing_bits.append(
                    f"{label_theme.title()} ~{sleeve_pct:.1f}% — rebalance within sleeve; avoid net new risk."
                )
                action_detail = f"Theme sleeve ~{sleeve_pct:.1f}%. Prefer rotate/upgrade vs add."
            else:
                room = max(0.0, 8.0 - sleeve_pct)
                sizing_bits.append(
                    f"{label_theme.title()} ~{sleeve_pct:.1f}% — room for roughly +{room:.0f}% if funded by trims."
                )
                action_detail = (
                    "If high conviction, stage +2–4% with stops; fund from overweight growth if needed."
                )

            if growth >= 22 and by_sym.get("SCHG"):
                schg_w = by_sym["SCHG"]["weight_pct"]
                sizing_bits.append(
                    f"SCHG ~{schg_w:.1f}% — funding source: trim 3–6% of book weight if rotating into this theme."
                )
                tickers.append({
                    "symbol": "SCHG", "role": "trim_candidate",
                    "suggested_weight_pct": f"trim 3–6% of book (now {schg_w:.1f}%)",
                    "rationale": "Primary funding source if adding thematic risk.",
                })
            implications.append(
                f"Express {label_theme} with held names when possible; any add needs a stop (Replace mode)."
            )

    # ── Company / holdings (narrow) ────────────────────────────────────
    elif primary == "company_ticker" or primary == "catalyst_event":
        sym = (symbol or "").upper() or None
        if not sym:
            # Only extract from title (not body) to avoid random NY/AI tokens
            for m in _TICKER_TOKEN.finditer(title or ""):
                t = m.group(1)
                if t in held:
                    sym = t
                    break
        if sym and sym in by_sym:
            action, href = "position_review", "portfolio"
            w = by_sym[sym]["weight_pct"]
            action_label = f"Review {sym} position"
            tickers.append({
                "symbol": sym, "role": "hold_review",
                "suggested_weight_pct": f"current {w:.1f}%",
                "rationale": "Holding-linked — update thesis, stop, and size.",
            })
            if w >= 12:
                sizing_bits.append(
                    f"{sym} is ~{w:.1f}% of book — if thesis weakens, trim 10–20% of the position (not all-or-nothing)."
                )
                action_detail = f"{sym} elevated at ~{w:.1f}%. Confirm stop health; staged trim if conviction drops."
            else:
                sizing_bits.append(f"{sym} ~{w:.1f}% — size changes stay within ±1–2% of book.")
                action_detail = f"Update {sym} thesis and stops."
            implications.append(f"Any add to {sym} must clear stop policy and heat limits.")
        else:
            # Generic company research — NO recycled SCHD/JEPI list
            action_label = "Research only — no sleeve action"
            action_detail = (
                "No held ticker linked. Do not auto-allocate; promote to a watchlist symbol before sizing."
            )
            implications.append(
                "Company/ticker brief without a portfolio link — advisory context only, not a buy list."
            )
            if flags:
                sizing_bits.append(
                    "Book concentration context only: " + "; ".join(flags[:2]) + "."
                )

    # ── Academic / compounding / other ─────────────────────────────────
    else:
        action_label = "Review implications"
        action_detail = "Map to holdings only if a clear sleeve or symbol is identified."
        implications.append(
            "General intelligence — no automatic ticker shopping list for this category."
        )
        if flags:
            sizing_bits.extend(flags[:2])

    if not sizing_bits and portfolio.get("top"):
        tops = ", ".join(f"{t['symbol']} {t['weight_pct']}%" for t in portfolio["top"][:4])
        sizing_bits.append(f"Largest weights today: {tops}.")

    return {
        "investment_implications": (" ".join(implications) or "Map to holdings before acting.")[:700],
        "ticker_recommendations": tickers[:6],
        "sizing_guidance": (" ".join(sizing_bits) or "Keep any single add small unless funding a trim.")[:700],
        "risk_caveat": _risk_caveat(flags),
        "portfolio_snapshot": {
            "total_mv": portfolio.get("total_mv"),
            "top": portfolio.get("top", [])[:8],
            "sleeves": {k: sleeves.get(k) for k in ("dividend_income", "growth", "defense", "power_infra", "ai_infra", "bonds") if sleeves.get(k)},
            "related_weights": {
                t["symbol"]: by_sym[t["symbol"]]["weight_pct"]
                for t in tickers if t.get("symbol") in by_sym
            },
            "flags": flags[:5],
        },
        "next_action": {
            "label": action_label,
            "detail": action_detail,
            "href_hint": href,
            "action_type": action,
        },
    }


def clear_portfolio_cache() -> None:
    load_portfolio_context.cache_clear()
