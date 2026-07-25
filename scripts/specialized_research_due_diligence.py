#!/usr/bin/env python3
"""Adapters from specialized research outputs into the shared diligence contract."""
from __future__ import annotations

from datetime import datetime, timezone

import research_due_diligence as diligence


def _source(provider, as_of, quality, provenance_ref):
    return {
        "provider": provider,
        "as_of": as_of,
        "quality": quality,
        "provenance_ref": provenance_ref,
    }


def sector_packet(row: dict) -> dict:
    truth = row.get("truth") or {}
    freshness = row.get("freshness") or {}
    breadth_quality = str(row.get("breadth_quality") or row.get("quality") or "missing")
    return diligence.evaluate(
        domain="SECTOR",
        subject=f"{row.get('sector') or 'unknown'} ({row.get('etf') or 'unknown'})",
        methodology_version=str(row.get("calculation_version") or ""),
        as_of=str(row.get("as_of") or truth.get("as_of") or ""),
        sources=[_source(
            truth.get("source") or "ticker_prices + covered membership",
            truth.get("as_of") or row.get("as_of"),
            truth.get("quality") or breadth_quality,
            truth.get("hash") or truth.get("snapshot_hash") or row.get("source_hash") or "sector-row",
        )],
        deterministic_checks=[
            {"name": "relative_strength_complete", "passed": all(row.get(k) is not None for k in ("rs5", "rs20", "rs60", "slope")), "reason": "aligned RS5/RS20/RS60 and RS20 slope required"},
            {"name": "state_classified", "passed": row.get("state") in {"LEADING", "WEAKENING", "LAGGING", "IMPROVING"}, "reason": "sector state is not deterministically classified"},
            {"name": "breadth_quality", "passed": breadth_quality == "ok", "severity": "warning" if breadth_quality == "narrow_participation" else "hard", "reason": f"breadth quality={breadth_quality}"},
            {"name": "not_quarantined", "passed": not bool(row.get("quarantined")), "reason": str(row.get("quarantine_reason") or "sector row quarantined")},
        ],
        coverage={
            "required": row.get("breadth_membership_n") or 0,
            "observed": row.get("breadth_coverage_n") or row.get("breadth_n") or 0,
        },
        freshness={
            "state": "CURRENT" if not freshness.get("stale") else "STALE",
            "stale": bool(freshness.get("stale")),
            "reason": freshness.get("reason") or "sector row stale",
        },
        warnings=["Hermes/news context is corroborative only; price-relative state remains authoritative"],
    )


def industry_packet(row: dict, snapshot: dict | None = None) -> dict:
    snapshot = snapshot or {}
    truth = row.get("truth") or {}
    capture_kind = snapshot.get("capture_kind") or row.get("capture_kind")
    quality = str(row.get("quality") or truth.get("quality") or "missing")
    return diligence.evaluate(
        domain="INDUSTRY",
        subject=str(row.get("industry") or "unknown"),
        methodology_version=str(snapshot.get("calculation_version") or truth.get("calculation_version") or ""),
        as_of=str(snapshot.get("captured_at") or truth.get("as_of") or ""),
        sources=[_source(
            truth.get("source") or "finviz_elite_view_141",
            truth.get("as_of") or snapshot.get("captured_at"),
            quality,
            truth.get("hash") or snapshot.get("snapshot_hash") or "industry-row",
        )],
        deterministic_checks=[
            {"name": "same_vendor_baseline", "passed": quality == "same_vendor_same_run", "reason": f"industry/SPY baseline quality={quality}"},
            {"name": "relative_inputs_complete", "passed": row.get("rel1w") is not None and row.get("rel1m") is not None, "reason": "relative week/month inputs missing"},
            {"name": "state_classified", "passed": row.get("state") in {"LEADING", "WEAKENING", "LAGGING", "IMPROVING"}, "reason": "industry quadrant is not classified"},
            {"name": "mapping_resolved", "passed": not bool(row.get("quarantined")), "reason": f"industry mapping quality={row.get('mapping_quality') or 'unmapped'}"},
            {"name": "close_confirmed_for_action", "passed": capture_kind == "close", "severity": "warning", "reason": f"capture_kind={capture_kind or 'missing'}; intraday is research-only"},
        ],
        coverage={"required": 1, "observed": 1 if row.get("stocks") else 0},
        freshness={"state": "CLOSE_CONFIRMED" if capture_kind == "close" else "PARTIAL"},
        warnings=[] if capture_kind == "close" else ["intraday industry state cannot support an actionable proposal"],
    )


def defense_packet(card: dict, sector: dict | None = None, industry_packets: list[dict] | None = None) -> dict:
    sector = sector or {}
    risk = card.get("risk_context") or {}
    exposure = card.get("account_exposure") or {}
    sizing = card.get("account_sizing") or {}
    quality = card.get("quality_gate") or {}
    dependent = [p for p in (industry_packets or []) if isinstance(p, dict)]
    return diligence.evaluate(
        domain="DEFENSE",
        subject=str(card.get("title") or card.get("id") or "defense recommendation"),
        methodology_version=str(quality.get("version") or ""),
        as_of=str(card.get("as_of") or ""),
        sources=[
            _source("sector_rotation_snapshot", sector.get("as_of") or card.get("as_of"), sector.get("quality") or "ok", (sector.get("truth") or {}).get("hash") or sector.get("source_hash") or "sector"),
            _source("account_exposure", card.get("as_of"), "ok" if exposure else "missing", "account-exposure"),
            _source("realized_risk", card.get("as_of"), "ok" if risk.get("annualized_vol_pct") is not None and risk.get("correlation") is not None else "missing", "risk-context"),
        ],
        deterministic_checks=[
            {"name": "sector_research_verified", "passed": (sector.get("due_diligence") or {}).get("state") == diligence.VERIFIED, "reason": f"sector diligence state={(sector.get('due_diligence') or {}).get('state') or 'MISSING'}"},
            {"name": "account_exposure_complete", "passed": bool(exposure) and all(row.get("current_sector_pct") is not None for row in exposure.values()), "reason": "account-specific sector exposure incomplete"},
            {"name": "account_sizing_complete", "passed": bool(sizing) and set(sizing) == set(card.get("accounts") or []), "reason": "account sizing does not cover every selected account"},
            {"name": "risk_context_complete", "passed": risk.get("annualized_vol_pct") is not None and risk.get("correlation") is not None, "reason": "realized volatility/correlation incomplete"},
            {"name": "industry_dependencies_verified", "passed": all(p.get("state") == diligence.VERIFIED for p in dependent), "severity": "warning" if not dependent else "hard", "reason": "one or more industry dependencies are not verified"},
            {"name": "shadow_only", "passed": card.get("mode") == "SHADOW", "reason": "Defense recommendation is outside shadow/advisory mode"},
        ],
        coverage={"required": len(card.get("accounts") or []), "observed": len(sizing)},
        warnings=[] if dependent else ["ETF-only recommendation has no verified constituent-industry dependency"],
        freshness={"state": "CURRENT"},
    )


def proposal_packet(subject: str, packets: list[dict]) -> dict:
    return diligence.proposal_gate(subject, packets)
