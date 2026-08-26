"""Symbol- and decision-aware live research packet.

Calendar/Almanac is context only. ETF/valuation mechanics are conditional.
R8 fixture families are never labeled OOS_SUPPORTED.

Authority: READ_ONLY_ADVISORY. Methodology may block; nothing trades.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"


def _item(
    *,
    fact: str,
    source: str,
    source_type: str,
    as_of: str,
    quality: str,
    grade: str,
    status: str,
    support: str = "",
    counter: str = "",
    specialist: str = "",
    cio_use: str = "context",
    age: str = "",
) -> dict[str, Any]:
    return {
        "fact": fact,
        "source": source,
        "source_type": source_type,
        "as_of": as_of,
        "age": age,
        "quality": quality,
        "grade": grade,
        "status": status,
        "support": support,
        "counterevidence": counter,
        "specialist": specialist,
        "cio_use": cio_use,
        "authority": AUTHORITY,
        "creates_trade_authority": False,
    }


def retrieve_symbol_research(
    symbol: str,
    *,
    now: Optional[datetime] = None,
    holdings_row: Optional[dict[str, Any]] = None,
    decision: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    as_of = now.date().isoformat()
    sym = str(symbol or "").strip().upper()
    items: list[dict[str, Any]] = []

    # R3 Almanac — context only
    try:
        from scripts.lib.research_governance.almanac import bundle
        pack = bundle(as_of_year=int(now.year))
        items.append(_item(
            fact=(
                f"Calendar context {pack.get('cycle_label')}; weak months "
                f"{pack.get('reproduced_weak_months')}. Never a standalone sell."
            ),
            source="stock_traders_almanac",
            source_type="SEASONALITY",
            as_of=as_of,
            quality="fixture_reproduction",
            grade="C",
            status="IN_SAMPLE_REPRODUCED",
            counter="STW family challenge is whole-family, not winner-only",
            specialist="seasonality modifies staging/timing only",
            cio_use="context_modifier",
        ))
    except Exception as exc:
        items.append(_item(
            fact="Almanac unavailable",
            source="stock_traders_almanac",
            source_type="SEASONALITY",
            as_of=as_of,
            quality="unavailable",
            grade="D",
            status="SOURCE_CLAIM_INCOMPLETE",
            specialist=str(exc)[:160],
            cio_use="unavailable",
        ))

    # R2 ETF mechanics — fail-closed without official NAV
    nav = None
    px = None
    if holdings_row:
        try:
            px = float(holdings_row.get("market_value") or 0) / max(
                float(holdings_row.get("shares") or holdings_row.get("quantity") or 0), 1e-12
            )
        except Exception:
            px = None
    if nav is None:
        items.append(_item(
            fact=f"{sym} official NAV not present — premium/discount UNAVAILABLE",
            source="r2_etf_mechanics",
            source_type="DETERMINISTIC_MECHANICS",
            as_of=as_of,
            quality="missing_official_nav",
            grade="D",
            status="UNAVAILABLE",
            specialist="PROXY/INDICATIVE cannot stand in for OFFICIAL_NAV",
            cio_use="conditional_fact",
        ))

    # R7 behavioral — citation-only
    try:
        from scripts.lib.research_governance.behavioral import bundle as beh
        b = beh()
        items.append(_item(
            fact="Behavioral frames are citation-only context; no partisan conclusion.",
            source="behavioral_framework",
            source_type="BEHAVIORAL_FRAMEWORK",
            as_of=as_of,
            quality="citation_only",
            grade="D",
            status="SOURCE_CLAIM",
            specialist="challenges framing only",
            cio_use="context_modifier",
        ))
        _ = b
    except Exception:
        pass

    # R8 must not claim OOS
    items.append(_item(
        fact="R8 fixture empirical family is not an OOS edge and anoints no winner.",
        source="r8_empirical_family",
        source_type="EMPIRICAL_STRATEGY",
        as_of=as_of,
        quality="fixture_only",
        grade="C",
        status="IN_SAMPLE_REPRODUCED",
        counter="selected_winner must remain None",
        specialist="cannot promote to OOS_SUPPORTED from the monthly fixture",
        cio_use="blocked_from_trade_authority",
    ))

    if holdings_row:
        try:
            mv = float(holdings_row.get("market_value") or holdings_row.get("current_value_usd") or 0)
        except (TypeError, ValueError):
            mv = 0.0
        residual = mv > 0 and mv < 100
        items.append(_item(
            fact=(
                f"{sym} held {holdings_row.get('shares') or holdings_row.get('quantity')} sh "
                f"in {holdings_row.get('account')} value={holdings_row.get('market_value')}"
                + ("; residual sleeve — not a new purchase" if residual else "")
            ),
            source="verified_holdings",
            source_type="PORTFOLIO_TRUTH",
            as_of=str(holdings_row.get("updated_at") or as_of),
            quality="broker_synced",
            grade="B",
            status="VERIFIED",
            specialist="portfolio construction / residual-size awareness",
            cio_use="portfolio_construction",
            counter="Do not treat a leftover fractional sleeve as a fresh buy.",
        ))

    # Portfolio overlap (holdings.json overlap_analysis) — honest if empty
    try:
        from scripts.lib.cio_office_state import load_holdings_document
        hdoc = load_holdings_document()
        oa = (hdoc.get("overlap_analysis") or {}) if isinstance(hdoc, dict) else {}
        overlaps = oa.get("overlaps") if isinstance(oa, dict) else []
        hits = []
        if isinstance(overlaps, list):
            for o in overlaps:
                blob = json.dumps(o, default=str).upper() if not isinstance(o, str) else o.upper()
                if sym and sym in blob:
                    hits.append(o)
        if hits:
            items.append(_item(
                fact=f"{sym} appears in overlap_analysis ({len(hits)} hit(s)).",
                source="holdings_overlap_analysis",
                source_type="PORTFOLIO_TRUTH",
                as_of=str((oa or {}).get("generated_at") or as_of),
                quality="computed",
                grade="C",
                status="VERIFIED",
                specialist="sleeve overlap / concentration",
                cio_use="portfolio_construction",
            ))
        else:
            items.append(_item(
                fact=f"{sym} overlap_analysis has no computed pairs (count={oa.get('overlap_count') if isinstance(oa, dict) else 'n/a'}).",
                source="holdings_overlap_analysis",
                source_type="PORTFOLIO_TRUTH",
                as_of=str((oa or {}).get("generated_at") or as_of) if isinstance(oa, dict) else as_of,
                quality="empty_or_unavailable",
                grade="D",
                status="UNAVAILABLE",
                specialist="Steph overlap packet not present",
                cio_use="unavailable",
            ))
    except Exception as exc:
        items.append(_item(
            fact="overlap_analysis unavailable",
            source="holdings_overlap_analysis",
            source_type="PORTFOLIO_TRUTH",
            as_of=as_of,
            quality="unavailable",
            grade="D",
            status="UNAVAILABLE",
            specialist=str(exc)[:160],
            cio_use="unavailable",
        ))

    # Prior production cases for this symbol
    try:
        from scripts.lib.cio_production_case import load_cases
        prior = [c for c in load_cases() if str(c.get("symbol") or "").upper() == sym][-3:]
        if prior:
            items.append(_item(
                fact=f"{len(prior)} prior production case(s) for {sym}: " +
                     ", ".join(str(c.get("case_id")) for c in prior),
                source="cio_production_cases",
                source_type="PORTFOLIO_TRUTH",
                as_of=as_of,
                quality="ledger",
                grade="C",
                status="VERIFIED",
                specialist="prior case context",
                cio_use="context_modifier",
            ))
        else:
            items.append(_item(
                fact=f"No prior production case for {sym}.",
                source="cio_production_cases",
                source_type="PORTFOLIO_TRUTH",
                as_of=as_of,
                quality="empty",
                grade="D",
                status="UNAVAILABLE",
                specialist="learning evidence still accumulating",
                cio_use="context_modifier",
            ))
    except Exception:
        pass

    # R4 audit over these items
    audit = {"status": "UNAVAILABLE"}
    try:
        from scripts.lib.research_governance.decision_use_audit import DecisionUseLedger
        from scripts.lib.research_governance.models import ResearchEvidence
        from scripts.lib.research_governance.enums import (
            EvidenceGrade, EvidenceType, InfluenceClass, ResearchStatus,
        )
        evs = []
        for i, it in enumerate(items):
            try:
                evs.append(ResearchEvidence(
                    fact_id=f"{sym}:rs:{i}",
                    fact=it["fact"],
                    source_id=it["source"],
                    evidence_type=EvidenceType.SOURCE_NARRATIVE,
                    research_status=ResearchStatus.SOURCE_CLAIM,
                    evidence_grade=EvidenceGrade.D,
                    influence_class=InfluenceClass.CONTEXT_MODIFIER,
                    role_in_decision="risk_modifier_or_context",
                ))
            except Exception:
                continue
        rec = DecisionUseLedger().record(
            decision_id=str((decision or {}).get("decision_id") or f"rs_{sym}_{as_of}"),
            query={"symbol": sym, "hook": "cio_symbol_research"},
            evidence=evs,
            as_of=now.isoformat(),
        )
        audit = {
            "status": "OK",
            "signature_ok": rec.verify(),
            "record_digest": rec.record_digest,
            "decision_id": rec.decision_id,
            "durable": False,
            "note": "ephemeral unless R6 store is invoked",
        }
    except Exception as exc:
        audit = {"status": "UNAVAILABLE", "reason": str(exc)[:200]}

    return {
        "symbol": sym,
        "as_of": now.isoformat(),
        "authority": AUTHORITY,
        "creates_trade_authority": False,
        "items": items,
        "decision_use_audit": audit,
        "memory_consulted": True,
        "retrieval_query": {"symbol": sym, "families": ["seasonality", "etf", "behavioral", "empirical"]},
    }
