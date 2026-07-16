"""Cross-theme relationship graph for Research Intelligence (v2.7).

Zero new network calls — uses portfolio sleeves/capacity + primary category.
"""
from __future__ import annotations

from typing import Any

# Map RI primary categories → theme ids used in capacity/sleeves
PRIMARY_TO_THEME: dict[str, str] = {
    "dividend_income": "dividend_income",
    "retirement_tax": "retirement",
    "sector_thematic": "sector",  # refined by title themes
    "macro_geo": "macro",
    "compounding_wealth": "growth",
    "company_ticker": "company",
    "risk_regime": "risk",
    "catalyst_event": "catalyst",
    "academic_pro": "academic",
}

THEME_RELATIONSHIPS: list[dict[str, Any]] = [
    {
        "primary": "dividend_income",
        "related": ["retirement"],
        "strength": "strong",
        "reason": "Taxable yield affects MAGI / IRMAA",
        "impact_note": "Further taxable income raises MAGI / IRMAA risk — check Retirement pillar.",
    },
    {
        "primary": "retirement",
        "related": ["dividend_income"],
        "strength": "strong",
        "reason": "Conversion pacing vs income sleeve MAGI",
        "impact_note": "Income sleeve weight feeds MAGI; prefer quality SCHD over stacking yield.",
    },
    {
        "primary": "growth",
        "related": ["ai_infra", "power_infra"],
        "strength": "strong",
        "reason": "SCHG funds growth-adjacent themes",
        "impact_note": "New positions prefer funded adds (trim SCHG first).",
    },
    {
        "primary": "power_infra",
        "related": ["ai_infra", "industrials", "defense", "growth"],
        "strength": "moderate",
        "reason": "Infrastructure / re-industrialization cluster",
        "impact_note": "Related cyclical + data-center power exposure.",
    },
    {
        "primary": "ai_infra",
        "related": ["power_infra", "growth"],
        "strength": "strong",
        "reason": "AI demand + growth funding (SCHG)",
        "impact_note": "Prefer funded adds; check power capacity.",
    },
    {
        "primary": "industrials",
        "related": ["defense", "power_infra"],
        "strength": "moderate",
        "reason": "Infrastructure cluster",
        "impact_note": "Related cyclical exposure.",
    },
    {
        "primary": "defense",
        "related": ["industrials", "power_infra"],
        "strength": "moderate",
        "reason": "Infrastructure cluster",
        "impact_note": "Related defense/industrial exposure.",
    },
]

THEME_LABELS: dict[str, str] = {
    "dividend_income": "Dividend Income",
    "retirement": "Retirement / Tax",
    "growth": "Growth",
    "ai_infra": "AI Infra",
    "power_infra": "Power Infra",
    "industrials": "Industrials",
    "defense": "Defense",
    "bonds": "Bonds",
    "sector": "Sector",
    "macro": "Macro",
    "company": "Company",
    "risk": "Risk",
    "catalyst": "Catalyst",
    "academic": "Academic",
}


def _theme_from_card(
    primary: str | None,
    title: str | None,
    detected_themes: list[str] | None = None,
) -> list[str]:
    out: list[str] = []
    pc = primary or ""
    if pc == "dividend_income":
        out.append("dividend_income")
    elif pc == "retirement_tax":
        out.append("retirement")
    elif pc == "compounding_wealth":
        out.append("growth")
    elif pc in ("sector_thematic", "macro_geo"):
        for t in detected_themes or []:
            if t not in out:
                out.append(t)
        if not out and pc == "macro_geo":
            out.append("macro")
        if not out:
            out.append("sector")
    elif pc == "risk_regime":
        out.append("risk")
    # Title fallbacks
    tl = (title or "").lower()
    if "dividend" in tl or "income" in tl or "jepi" in tl or "schd" in tl:
        if "dividend_income" not in out:
            out.append("dividend_income")
    if "roth" in tl or "irmaa" in tl or "magi" in tl or "retirement" in tl:
        if "retirement" not in out:
            out.append("retirement")
    if "power" in tl or "utility" in tl or "nuclear" in tl or "data center" in tl:
        if "power_infra" not in out:
            out.append("power_infra")
    if "defense" in tl or "aerospace" in tl:
        if "defense" not in out:
            out.append("defense")
    if " semiconductor" in f" {tl}" or "chip" in tl or tl.startswith("ai ") or " ai " in f" {tl} " or "nvidia" in tl:
        if "ai_infra" not in out:
            out.append("ai_infra")
    return out[:4]


def build_cross_theme_context(portfolio: dict[str, Any] | None) -> dict[str, Any]:
    """Desk-level concentration + sleeve capacity for banners."""
    portfolio = portfolio or {}
    by_sym = portfolio.get("by_symbol") or {}
    sleeves = portfolio.get("sleeves") or {}
    capacity = portfolio.get("theme_capacity") or {}
    conc = portfolio.get("concentration") or {}
    heat = portfolio.get("heat") or {}

    schg = float((by_sym.get("SCHG") or {}).get("weight_pct") or 0)
    schd = float((by_sym.get("SCHD") or {}).get("weight_pct") or 0)
    top3 = float(conc.get("top3_pct") or 0)
    book_lvl = conc.get("book_level") or "normal"

    constrained = []
    if schg >= 24:
        constrained.append({
            "ticker": "SCHG", "weight": schg,
            "reason": "high concentration — prefer funded adds / trim first",
        })
    elif schg >= 20:
        constrained.append({
            "ticker": "SCHG", "weight": schg,
            "reason": "elevated — preferred funding source",
        })
    if schd >= 15:
        constrained.append({
            "ticker": "SCHD", "weight": schd,
            "reason": "elevated income anchor — trim only if income target lower",
        })

    banner = None
    if schg >= 24 or top3 >= 50 or book_lvl == "high":
        banner = {
            "active": True,
            "title": "Concentration active",
            "body": (
                f"SCHG {schg:.1f}% · Top-3 {top3:.0f}% · book {book_lvl}. "
                f"Most new ideas require funded adds (trim SCHG) or reduced size. "
                f"Heat ~{float(heat.get('portfolio_heat_pct') or 0):.1f}% ({heat.get('level') or 'n/a'})."
            ),
            "schg_pct": schg,
            "top3_pct": top3,
        }

    weights = {k: float(sleeves.get(k) or 0) for k in (
        "dividend_income", "growth", "ai_infra", "industrials", "defense", "power_infra", "bonds"
    )}
    soft_max = {
        k: float((capacity.get(k) or {}).get("target_max_pct") or 0)
        for k in weights
    }
    return {
        "current_weights": weights,
        "soft_max": soft_max,
        "constrained_names": constrained,
        "concentration_banner": banner,
        "income_over_capacity": weights.get("dividend_income", 0) >= soft_max.get("dividend_income", 35) * 0.95
            if soft_max.get("dividend_income") else weights.get("dividend_income", 0) >= 35,
    }


def related_themes_for_card(
    *,
    primary: str | None,
    title: str | None,
    portfolio: dict[str, Any] | None,
    detected_themes: list[str] | None = None,
    active_theme_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Card-level related themes strip payload."""
    ctx = build_cross_theme_context(portfolio)
    themes = _theme_from_card(primary, title, detected_themes)
    if not themes:
        return {"items": [], "impact_note": None, "lines": []}

    # Active themes for moderate-strength gating
    active = set(active_theme_ids or [])
    for tid, w in (ctx.get("current_weights") or {}).items():
        cap = (ctx.get("soft_max") or {}).get(tid) or 10
        room = max(0.0, cap - w)
        if room >= 3 or w > 0:
            active.add(tid)

    items: list[dict[str, Any]] = []
    impact_notes: list[str] = []
    seen: set[str] = set()

    for th in themes:
        for rel in THEME_RELATIONSHIPS:
            if rel["primary"] != th and th not in rel.get("related", []):
                continue
            strength = rel.get("strength") or "moderate"
            related = list(rel.get("related") or [])
            if rel["primary"] != th and rel["primary"] not in related:
                related = [rel["primary"]] + related
            # moderate only if cluster activity
            if strength == "moderate":
                cluster = {rel["primary"], *related}
                if len(cluster & active) < 2 and not any(
                    (ctx.get("current_weights") or {}).get(c, 0) > 0 for c in cluster
                ):
                    continue
            for r in related:
                if r == th or r in seen or r in themes:
                    # still allow retirement link from income even if both in themes
                    if not (th == "dividend_income" and r == "retirement"):
                        if r in themes and r != "retirement":
                            continue
                if r in seen:
                    continue
                seen.add(r)
                w = (ctx.get("current_weights") or {}).get(r)
                label = THEME_LABELS.get(r, r.replace("_", " ").title())
                extra = ""
                if r == "growth":
                    schg = next(
                        (c for c in (ctx.get("constrained_names") or []) if c.get("ticker") == "SCHG"),
                        None,
                    )
                    if schg:
                        extra = f" (SCHG {schg['weight']:.1f}%)"
                if r == "dividend_income" and ctx.get("income_over_capacity"):
                    extra = f" ({(ctx.get('current_weights') or {}).get('dividend_income', 0):.1f}% over soft max)"
                if r == "retirement" and ctx.get("income_over_capacity"):
                    extra = " (income sleeve heavy)"
                items.append({
                    "id": r,
                    "label": label + extra,
                    "strength": strength,
                    "reason": rel.get("reason"),
                })
                if rel.get("impact_note") and rel["impact_note"] not in impact_notes:
                    impact_notes.append(rel["impact_note"])
                if len(items) >= 3:
                    break
            if len(items) >= 3:
                break
        if len(items) >= 3:
            break

    # Always add SCHG funding note for power/ai/growth when constrained
    schg = next((c for c in (ctx.get("constrained_names") or []) if c["ticker"] == "SCHG"), None)
    if schg and any(t in ("power_infra", "ai_infra", "growth", "industrials", "defense") for t in themes):
        note = f"Prefer funded add — SCHG {schg['weight']:.1f}% ({schg['reason']})"
        if note not in impact_notes:
            impact_notes.insert(0, note)

    if "dividend_income" in themes or "retirement" in themes:
        inc = (ctx.get("current_weights") or {}).get("dividend_income") or 0
        if ctx.get("income_over_capacity"):
            n = f"Income sleeve ~{inc:.1f}% over soft max — no net new taxable yield without MAGI room."
            if n not in impact_notes:
                impact_notes.append(n)

    return {
        "themes": themes,
        "items": items[:3],
        "impact_note": impact_notes[0] if impact_notes else None,
        "impact_notes": impact_notes[:2],
        "lines": [
            " · ".join(i["label"] for i in items[:3]),
            impact_notes[0] if impact_notes else None,
        ],
    }
