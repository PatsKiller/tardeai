"""cio_strategy_knowledge.py — Phases 12–17 strategy knowledge foundation.

Governed research memory for seasonality, cycle context, and operator-approved
strategy literature. **Context and evidence only — never an execution engine.**

Three layers (never collapsed):
  SOURCE CLAIM → TRADE AI REPRODUCTION → CURRENT APPLICATION

READ_ONLY_ADVISORY. No broker authority.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

STRATEGY_KNOWLEDGE_VERSION = "strategy_knowledge_1.1.0"

# Influence policy: how strategy facts may affect CIO language (never auto-trade)
INFLUENCE_POLICY = {
    "version": "strategy_influence_1.0.0",
    "max_role": "risk_modifier_or_context",  # never standalone sell/buy
    "forbidden": [
        "autonomous_execution",
        "hard_coded_partisan_presidency_conclusions",
        "collapse_claim_reproduction_application",
        "overfit_promotion_without_oos",
    ],
    "allowed_uses": [
        "risk_modifier",
        "timing_context",
        "challenge_prompt",
        "report_methodology_note",
        "telegram_context_line",
    ],
    "min_internal_validation_for_weight": "reproduced_or_partial",
    "license": "internal_analysis_only_no_fulltext_republication",
}

SOURCE_TYPES = frozenset({
    "book", "paper", "official_research", "licensed_service",
    "operator_note", "internal_backtest", "public_dataset",
})

VALIDATION_GRADES = frozenset({
    "unverified_source_claim",
    "partially_reproduced",
    "reproduced",
    "reproduced_oos",
    "failed_reproduction",
    "not_applicable",
})


def make_research_fact(
    *,
    source_id: str,
    source_type: str,
    title: str,
    claim: str,
    claim_type: str = "seasonality",
    author: str = "",
    edition: str = "",
    publication_date: str = "",
    page_or_section: str = "",
    license_class: str = "operator_provided_or_public_summary",
    market: str = "US_equity",
    asset_scope: str = "broad_index",
    time_horizon: str = "monthly",
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    sample_n: Optional[int] = None,
    average_return: Optional[float] = None,
    win_rate: Optional[float] = None,
    cycle_context: str = "",
    conditions: Optional[list[str]] = None,
    exceptions: Optional[list[str]] = None,
    source_confidence: float = 0.5,
    reproduction_status: str = "unverified_source_claim",
    internal_validation_status: str = "unverified_source_claim",
    internal_result: str = "",
    out_of_sample_result: str = "",
    current_applicability: str = "context_only",
    citation: str = "",
) -> dict[str, Any]:
    """Canonical research_fact object (Phase 12.1)."""
    st = source_type if source_type in SOURCE_TYPES else "operator_note"
    val = internal_validation_status if internal_validation_status in VALIDATION_GRADES else "unverified_source_claim"
    body = {
        "source_id": source_id,
        "source_type": st,
        "title": title,
        "author": author,
        "edition": edition,
        "publication_date": publication_date,
        "page_or_section": page_or_section,
        "license_class": license_class,
        "market": market,
        "asset_scope": asset_scope,
        "claim": claim,
        "claim_type": claim_type,
        "time_horizon": time_horizon,
        "start_year": start_year,
        "end_year": end_year,
        "sample_n": sample_n,
        "average_return": average_return,
        "win_rate": win_rate,
        "cycle_context": cycle_context,
        "conditions": conditions or [],
        "exceptions": exceptions or [],
        "source_confidence": source_confidence,
        "reproduction_status": reproduction_status,
        "internal_validation_status": val,
        "internal_result": internal_result,
        "out_of_sample_result": out_of_sample_result,
        "current_applicability": current_applicability,
        "citation": citation,
        "last_verified": datetime.now(timezone.utc).date().isoformat(),
        "layers": {
            "source_claim": claim,
            "trade_ai_reproduction": internal_result or reproduction_status,
            "current_application": current_applicability,
        },
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    body["source_hash"] = hashlib.sha256(raw.encode()).hexdigest()[:24]
    body["research_fact_id"] = f"rf_{body['source_hash']}"
    body["knowledge_version"] = STRATEGY_KNOWLEDGE_VERSION
    return body


def _validation_from_grade(grade: str) -> str:
    g = (grade or "").upper()
    if g == "A":
        return "reproduced_oos"
    if g == "B":
        return "partially_reproduced"
    if g == "C":
        return "partially_reproduced"
    if g == "X":
        return "failed_reproduction"
    return "unverified_source_claim"


def _almanac_seed_overlay(fn_name: str) -> dict[str, Any]:
    """Pull independent reproduction stats when the fixture/engine is available."""
    try:
        from scripts.lib import cio_seasonality_analytics as _sa

        rec = getattr(_sa, fn_name)()
    except Exception:
        return {}
    status = _validation_from_grade(str(rec.get("evidence_grade") or ""))
    return {
        "sample_n": rec.get("n"),
        "average_return": rec.get("mean"),
        "win_rate": rec.get("win_rate"),
        "reproduction_status": status,
        "internal_validation_status": status,
        "internal_result": rec.get("trade_ai_reproduction") or "",
        "out_of_sample_result": rec.get("oos_note") or "",
        "evidence_grade": rec.get("evidence_grade"),
    }


def default_seed_facts() -> list[dict[str, Any]]:
    """Seed registry: STA public-alert citations + independent reproductions.

    Stock Trader's Almanac-style facts are structured summaries for internal
    analysis — not full-text republication of copyrighted books.
    Layers are never collapsed: source_claim ≠ reproduction ≠ application.
    """
    sep = _almanac_seed_overlay("september_general")
    aug = _almanac_seed_overlay("august_general")
    b6 = _almanac_seed_overlay("best_six_months")
    return [
        make_research_fact(
            source_id="sta_september_seasonality_summary",
            source_type="book",
            title="Stock Trader's Almanac (seasonality summary — operator structured note)",
            author="Hirsch / Stock Trader's Almanac tradition",
            claim=(
                "September has historically been among the weaker calendar months for "
                "broad US equity indexes in long multi-decade samples cited in almanac literature."
            ),
            claim_type="seasonality_month",
            page_or_section="monthly performance tables (summary)",
            license_class="operator_structured_summary_no_fulltext",
            time_horizon="month_of_year",
            cycle_context="none",
            conditions=["broad_us_equity_index", "long_sample_historical"],
            exceptions=["trend_and_breadth_can_dominate", "sample_dependent"],
            source_confidence=0.55,
            reproduction_status=sep.get("reproduction_status", "unverified_source_claim"),
            internal_validation_status=sep.get(
                "internal_validation_status", "unverified_source_claim"
            ),
            internal_result=sep.get(
                "internal_result",
                "Not yet independently reproduced in Trade AI from raw returns.",
            ),
            out_of_sample_result=sep.get("out_of_sample_result", ""),
            sample_n=sep.get("sample_n"),
            average_return=sep.get("average_return"),
            win_rate=sep.get("win_rate"),
            current_applicability=(
                "Context / risk modifier only (≤10% conviction/sizing language). "
                "Never a standalone sell signal."
            ),
            citation=(
                "Operator-structured summary of public STA September alerts "
                "(title/URL/date only). Not a verbatim book extract."
            ),
        ),
        make_research_fact(
            source_id="sta_august_seasonality_summary",
            source_type="book",
            title="Stock Trader's Almanac August (operator structured note)",
            author="Hirsch / Stock Trader's Almanac tradition",
            claim=(
                "August is described in public STA alerts as among the weaker modern-sample "
                "months for broad US indexes — a source claim until independently reproduced."
            ),
            claim_type="seasonality_month",
            license_class="operator_structured_summary_no_fulltext",
            time_horizon="month_of_year",
            cycle_context="none",
            conditions=["broad_us_equity_index", "long_sample_historical"],
            exceptions=["trend_and_breadth_can_dominate", "sample_dependent"],
            source_confidence=0.5,
            reproduction_status=aug.get("reproduction_status", "unverified_source_claim"),
            internal_validation_status=aug.get(
                "internal_validation_status", "unverified_source_claim"
            ),
            internal_result=aug.get(
                "internal_result",
                "Awaiting Trade AI independent monthly-return reproduction.",
            ),
            out_of_sample_result=aug.get("out_of_sample_result", ""),
            sample_n=aug.get("sample_n"),
            average_return=aug.get("average_return"),
            win_rate=aug.get("win_rate"),
            current_applicability=(
                "Context / risk modifier only (≤10% conviction/sizing language). "
                "Never a standalone sell. Does not create TRIM."
            ),
            citation=(
                "Operator-structured summary of public STA August alerts "
                "(title/URL/date only). Not a verbatim book extract."
            ),
        ),
        make_research_fact(
            source_id="sta_best_six_months_summary",
            source_type="book",
            title="Best six months hypothesis (almanac tradition — structured summary)",
            author="Hirsch / Stock Trader's Almanac tradition",
            claim=(
                "November–April has often been stronger than May–October for broad US equities "
                "in long samples popularized as the 'best six months' hypothesis."
            ),
            claim_type="seasonality_six_month",
            license_class="operator_structured_summary_no_fulltext",
            time_horizon="six_month_window",
            conditions=["broad_us_equity_index"],
            exceptions=["regime_breaks", "crisis_years"],
            source_confidence=0.5,
            reproduction_status=b6.get("reproduction_status", "unverified_source_claim"),
            internal_validation_status=b6.get(
                "internal_validation_status", "unverified_source_claim"
            ),
            internal_result=b6.get(
                "internal_result",
                "Awaiting Trade AI independent monthly-return reproduction.",
            ),
            out_of_sample_result=b6.get("out_of_sample_result", ""),
            sample_n=b6.get("sample_n"),
            average_return=b6.get("average_return"),
            win_rate=b6.get("win_rate"),
            current_applicability="Context only; not an automatic portfolio rule.",
            citation="Operator-structured summary; not a verbatim book extract.",
        ),
        make_research_fact(
            source_id="presidential_cycle_mechanical",
            source_type="public_dataset",
            title="US presidential market-cycle year classification (mechanical)",
            author="Trade AI / public calendar",
            claim=(
                "US equity calendar years can be labeled post-election, midterm, pre-election, "
                "or election year by inauguration-year arithmetic — without partisan conclusions."
            ),
            claim_type="presidential_cycle",
            license_class="public",
            time_horizon="calendar_year",
            source_confidence=0.9,
            reproduction_status="reproduced",
            internal_validation_status="reproduced",
            internal_result="Mechanical year class derived from election-year modulo arithmetic.",
            current_applicability="Cycle context label only; never partisan hard-code.",
            citation="Internal mechanical classifier (cio_seasonality_engine).",
        ),
    ]


def load_strategy_store(path: Optional[Path] = None) -> dict[str, Any]:
    """Load or seed the strategy knowledge store."""
    facts = default_seed_facts()
    store = {
        "version": STRATEGY_KNOWLEDGE_VERSION,
        "influence_policy": INFLUENCE_POLICY,
        "facts": facts,
        "fact_count": len(facts),
        "authority": "READ_ONLY_ADVISORY",
        "note": (
            "Strategy knowledge is contextual evidence. "
            "SOURCE CLAIM ≠ TRADE AI REPRODUCTION ≠ CURRENT APPLICATION."
        ),
    }
    if path and path.is_file():
        try:
            disk = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(disk.get("facts"), list) and disk["facts"]:
                store["facts"] = disk["facts"]
                store["fact_count"] = len(store["facts"])
                store["loaded_from"] = str(path)
        except Exception:
            pass
    return store


def compose_strategy_context(
    *,
    now: Optional[datetime] = None,
    store: Optional[dict[str, Any]] = None,
    seasonality: Optional[dict[str, Any]] = None,
    research_context: Optional[dict[str, Any]] = None,
    symbols: Optional[list[str]] = None,
) -> dict[str, Any]:
    """CIO context composer: retrieve research first, then seasonality + facts."""
    now = now or datetime.now(timezone.utc)
    store = store or load_strategy_store()
    if research_context is None:
        try:
            from scripts.lib.cio_research_retriever import retrieve_research_context

            research_context = retrieve_research_context(now, symbols=symbols)
        except Exception as exc:
            research_context = {
                "error": str(exc)[:200],
                "role": "risk_modifier_or_context",
                "authority": "READ_ONLY_ADVISORY",
                "execution_engine": False,
            }
    facts = store.get("facts") or []
    month = now.month
    month_facts = [
        f for f in facts
        if f.get("claim_type") in ("seasonality_month", "seasonality_six_month")
        or (month == 9 and "September" in str(f.get("claim") or ""))
        or (month == 8 and "August" in str(f.get("claim") or ""))
    ]
    lines = []
    for f in (seasonality.get("narrative_lines") if seasonality else None) or []:
        lines.append(f)
    modifier = (research_context or {}).get("modifier_note")
    if modifier:
        lines.append(modifier)
    for f in month_facts[:3]:
        layers = f.get("layers") or {}
        lines.append(
            f"Source claim ({f.get('source_id')}): {layers.get('source_claim', f.get('claim'))} "
            f"| Reproduction: {layers.get('trade_ai_reproduction')} "
            f"| Application: {layers.get('current_application')}"
        )
    influence = dict(store.get("influence_policy") or INFLUENCE_POLICY)
    influence["max_conviction_sizing_modifier_pct"] = 10.0
    return {
        "version": STRATEGY_KNOWLEDGE_VERSION,
        "as_of": now.isoformat(),
        "influence_policy": influence,
        "seasonality": seasonality,
        "research_context": research_context,
        "relevant_facts": month_facts[:5],
        "context_lines": lines[:10],
        "role": "risk_modifier_or_context",
        "authority": "READ_ONLY_ADVISORY",
        "execution_engine": False,
        "creates_trim": False,
        "standalone_sell": False,
        "disclaimer": (
            "Strategy context is not a trade instruction. "
            "Do not collapse source claims into Trade AI facts without validation. "
            "August/September seasonality is a ≤10% language modifier, never a standalone sell."
        ),
    }
