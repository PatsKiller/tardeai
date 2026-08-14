"""cio_research_library.py — Phases 11–16 research families.

Families: seasonality, trend, value, risk, breadth, macro, wealth/tax.

Holds compact, citable facts. Seasonality includes independent Almanac
reproductions. Other families are honest D/C placeholders until reproduced.

READ_ONLY_ADVISORY. Never full-text books. Never partisan presidential conclusions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from scripts.lib.cio_research_grader import fact_counts_by_grade
from scripts.lib.cio_research_registry import (
    AUTHORITY,
    FAMILY_IDS,
    ResearchSourceRegistry,
    default_registry,
)
from scripts.lib.cio_seasonality_analytics import (
    MAX_INFLUENCE_PCT,
    almanac_bundle,
    august_general,
    august_midterm,
    best_six_months,
    september_general,
    september_midterm,
)

RESEARCH_LIBRARY_VERSION = "research_library_1.0.0"

FAMILY_ALIASES = {
    "wealth/tax": "wealth_tax",
    "wealth": "wealth_tax",
    "tax": "wealth_tax",
}

FAMILY_META: dict[str, dict[str, str]] = {
    "seasonality": {
        "title": "Seasonality & calendar",
        "role": "month/cycle context after independent reproduction",
    },
    "trend": {
        "title": "Trend / time-series momentum",
        "role": "public-literature claim; not yet internally reproduced here",
    },
    "value": {
        "title": "Value / relative cheapness",
        "role": "public-literature claim; not yet internally reproduced here",
    },
    "risk": {
        "title": "Risk / drawdown / volatility",
        "role": "risk-modifier context; no execution",
    },
    "breadth": {
        "title": "Market breadth",
        "role": "participation context; not a standalone signal",
    },
    "macro": {
        "title": "Macro regime",
        "role": "background regime context; not a presidential partisan call",
    },
    "wealth_tax": {
        "title": "Wealth / tax calendar",
        "role": "tax-window awareness; not tax advice",
    },
}


def normalize_family(name: str) -> str:
    key = (name or "").strip().lower().replace(" ", "_").replace("-", "_")
    return FAMILY_ALIASES.get(key, key)


def _claim(
    *,
    source_id: str,
    family: str,
    title: str,
    claim: str,
    evidence_grade: str,
    reproduction: str,
    applicability: str,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    rec = {
        "source_id": source_id,
        "family": family,
        "title": title,
        "claim": claim,
        "evidence_grade": evidence_grade,
        "trade_ai_reproduction": reproduction,
        "current_applicability": applicability,
        "layers": {
            "source_claim": claim,
            "trade_ai_reproduction": reproduction,
            "current_application": applicability,
        },
        "authority": AUTHORITY,
        "fulltext": False,
        "max_influence_pct": MAX_INFLUENCE_PCT,
        "standalone_sell": False,
        "execution_engine": False,
    }
    if extra:
        rec.update(extra)
    return rec


def _seasonality_facts() -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for fn in (august_general, august_midterm, september_general, september_midterm):
        rec = fn()
        src = rec["source_claim"]
        facts.append(
            _claim(
                source_id=src["source_id"],
                family="seasonality",
                title=src["title"],
                claim=src["summary"],
                evidence_grade=rec["evidence_grade"],
                reproduction=rec["trade_ai_reproduction"],
                applicability=rec["current_applicability"],
                extra={
                    "n": rec["n"],
                    "mean": rec["mean"],
                    "win_rate": rec["win_rate"],
                    "median": rec.get("median"),
                    "std": rec.get("std"),
                    "oos_note": rec["oos_note"],
                    "citation": {"title": src["title"], "url": src["url"], "date": src["date"]},
                    "month": rec["month"],
                    "cycle_label": rec["cycle_label"],
                    "almanac": rec,
                },
            )
        )
    b6 = best_six_months()
    facts.append(
        _claim(
            source_id="sta_best_six_months_summary",
            family="seasonality",
            title="Best six months hypothesis (almanac tradition — structured summary)",
            claim=str(b6["source_claim"]),
            evidence_grade=b6["evidence_grade"],
            reproduction=b6["trade_ai_reproduction"],
            applicability=b6["current_applicability"],
            extra={"n": b6["n"], "mean": b6["mean"], "win_rate": b6["win_rate"], "spread": b6.get("spread")},
        )
    )
    return facts


def _static_family_facts() -> list[dict[str, Any]]:
    """Honest D/C seeds for non-seasonality families (no fake reproductions)."""
    app = (
        "Context only. Not independently reproduced in this research-brain "
        "foundation. Max 10% language modifier if later reproduced. Never a standalone sell."
    )
    awaiting = "Not yet independently reproduced in Trade AI from raw series."
    return [
        _claim(
            source_id="pub_tsmom_literature",
            family="trend",
            title="Time-series momentum (public literature claim)",
            claim=(
                "Public academic literature documents time-series momentum across "
                "asset classes over 1–12 month lookbacks (source claim only)."
            ),
            evidence_grade="D",
            reproduction=awaiting,
            applicability=app,
        ),
        _claim(
            source_id="pub_value_spread_literature",
            family="value",
            title="Value spread / cheap vs expensive (public literature claim)",
            claim=(
                "Public asset-pricing literature documents a long-run value premium "
                "that is sample- and definition-dependent (source claim only)."
            ),
            evidence_grade="D",
            reproduction=awaiting,
            applicability=app,
        ),
        _claim(
            source_id="pub_vol_risk_context",
            family="risk",
            title="Elevated realized volatility as a risk modifier",
            claim=(
                "Elevated realized volatility and drawdown are commonly used as "
                "risk-off modifiers, not as standalone liquidation rules."
            ),
            evidence_grade="C",
            reproduction=(
                "Exploratory framing only in this foundation — no new vol-timing "
                "backtest is claimed."
            ),
            applicability=app,
        ),
        _claim(
            source_id="pub_breadth_participation",
            family="breadth",
            title="Advance/decline participation (public market-structure claim)",
            claim=(
                "Narrow leadership with weak advance/decline participation is a "
                "commonly cited caution for index strength (source claim only)."
            ),
            evidence_grade="D",
            reproduction=awaiting,
            applicability=app,
        ),
        _claim(
            source_id="pub_macro_regime_nonpartisan",
            family="macro",
            title="Macro regime context (non-partisan)",
            claim=(
                "Growth, inflation, and policy-rate regimes are background context. "
                "No partisan presidential performance conclusion is encoded."
            ),
            evidence_grade="D",
            reproduction=awaiting,
            applicability=(
                "Regime label only. partisan_conclusion is always null. "
                "Never a standalone sell."
            ),
            extra={"partisan_conclusion": None},
        ),
        _claim(
            source_id="pub_tax_loss_window",
            family="wealth_tax",
            title="Tax-loss harvesting calendar window (not tax advice)",
            claim=(
                "Year-end tax-loss harvesting is a well-known calendar window in "
                "taxable accounts. This is awareness, not tax advice."
            ),
            evidence_grade="C",
            reproduction=(
                "Calendar-mechanical window only; no claim about after-tax alpha "
                "is reproduced here."
            ),
            applicability=(
                "Taxable-account awareness only. Not tax advice. Not a sell signal."
            ),
        ),
    ]


def library_facts() -> list[dict[str, Any]]:
    return _seasonality_facts() + _static_family_facts()


def facts_for_family(family: str) -> list[dict[str, Any]]:
    fam = normalize_family(family)
    return [f for f in library_facts() if f.get("family") == fam]


def family_catalog() -> dict[str, Any]:
    facts = library_facts()
    by = {fam: [] for fam in FAMILY_IDS}
    for f in facts:
        by.setdefault(f["family"], []).append(f["source_id"])
    return {
        "version": RESEARCH_LIBRARY_VERSION,
        "authority": AUTHORITY,
        "families": [
            {
                "id": fam,
                "title": FAMILY_META[fam]["title"],
                "role": FAMILY_META[fam]["role"],
                "fact_ids": by.get(fam) or [],
                "fact_count": len(by.get(fam) or []),
            }
            for fam in FAMILY_IDS
        ],
        "grade_counts": fact_counts_by_grade(facts),
        "almanac": {
            "weak_months_reproduced": almanac_bundle()["weak_months_reproduced"],
        },
    }


def build_library(*, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    facts = library_facts()
    return {
        "version": RESEARCH_LIBRARY_VERSION,
        "as_of": now.isoformat(),
        "authority": AUTHORITY,
        "families": list(FAMILY_IDS),
        "facts": facts,
        "fact_count": len(facts),
        "grade_counts": fact_counts_by_grade(facts),
        "registry": default_registry().grade_counts(),
        "note": (
            "SOURCE CLAIM ≠ TRADE AI REPRODUCTION ≠ CURRENT APPLICATION. "
            "Copyrighted books are cited, never reproduced as full text."
        ),
    }


def empty_registry() -> ResearchSourceRegistry:
    return default_registry()
