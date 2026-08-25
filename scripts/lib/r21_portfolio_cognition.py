"""R21 — Portfolio-level institutional reasoning (advisory).

Does not replace financial truth. Does not infer an action from graph proximity.
Activation default OFF.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI, gated_live_run, require_evidence_class
from scripts.lib.holdings_universe import held_equity_tickers
from scripts.lib.transferson_universe import get_related_by_industry, get_symbol

SCHEMA = "PortfolioCognition@v1"


def portfolio_cognition(
    manifest: dict[str, Any],
    *,
    held_symbols: list[str] | None = None,
    root=None,
    evidence_class: str,
) -> dict[str, Any]:
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("R21", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SCHEMA}
    held = [str(s).upper() for s in (held_symbols if held_symbols is not None else held_equity_tickers(root=root))]
    rows = [get_symbol(manifest, s) or {"symbol": s, "unresolved": True} for s in held]
    by_sector: dict[str, list[str]] = defaultdict(list)
    by_industry: dict[str, list[str]] = defaultdict(list)
    by_catalyst: dict[str, list[str]] = defaultdict(list)
    unresolved = []
    for rec in rows:
        if not rec.get("security_guid") and rec.get("identity_status") == "UNRESOLVED_WITH_REASON":
            unresolved.append(rec.get("symbol"))
        if rec.get("sector"):
            by_sector[str(rec["sector"])].append(rec["symbol"])
        if rec.get("industry"):
            by_industry[str(rec["industry"])].append(rec["symbol"])
        for g in rec.get("catalyst_guids") or []:
            by_catalyst[str(g)].append(rec["symbol"])

    concentrated_sectors = {k: v for k, v in by_sector.items() if len(v) >= 2}
    concentrated_industries = {k: v for k, v in by_industry.items() if len(v) >= 2}
    shared_catalysts = {k: v for k, v in by_catalyst.items() if len(set(v)) >= 2}

    substitutes = []
    for rec in rows:
        if not rec.get("industry"):
            continue
        related = get_related_by_industry(manifest, rec["symbol"]).get("related_symbols") or []
        alts = [s for s in related if s not in held][:5]
        if alts:
            substitutes.append({
                "held": rec["symbol"],
                "industry": rec.get("industry"),
                "alternatives": alts,
                "not_an_order": True,
            })

    gaps = [s for s in held if not (get_symbol(manifest, s) or {}).get("catalyst_guids")]
    findings = []
    for sector, names in concentrated_sectors.items():
        findings.append({
            "kind": "FACT",
            "claim": "duplicate_sector_exposure",
            "sector": sector,
            "symbols": names,
            "investment_recommendation": None,
        })
    for industry, names in concentrated_industries.items():
        findings.append({
            "kind": "FACT",
            "claim": "duplicate_industry_exposure",
            "industry": industry,
            "symbols": names,
            "investment_recommendation": None,
        })
    for guid, names in shared_catalysts.items():
        findings.append({
            "kind": "DERIVED_RELATIONSHIP",
            "claim": "shared_catalyst_exposure",
            "catalyst_guid": guid,
            "symbols": names,
            "not_supply_chain": True,
            "investment_recommendation": None,
        })
    if concentrated_industries:
        findings.append({
            "kind": "HYPOTHESIS",
            "claim": "thesis_correlation",
            "note": "shared industry among holdings may imply correlated invalidation; not a trade",
            "investment_recommendation": None,
        })
        findings.append({
            "kind": "HYPOTHESIS",
            "claim": "common_invalidation_exposure",
            "note": "a sector shock could invalidate multiple holdings together",
            "investment_recommendation": None,
        })
    for sub in substitutes[:12]:
        findings.append({
            "kind": "HYPOTHESIS",
            "claim": "substitute_opportunity",
            "held": sub["held"],
            "alternatives": sub["alternatives"],
            "investment_recommendation": None,
        })
    return {
        "schema": SCHEMA,
        "evidence_class": cls,
        "held_n": len(held),
        "unresolved_held": unresolved,
        "duplicated_sector_exposure": concentrated_sectors,
        "duplicated_industry_exposure": concentrated_industries,
        "shared_catalyst_dependency": shared_catalysts,
        "substitutes": substitutes[:12],
        "portfolio_research_gaps": gaps,
        "findings": findings,
        "graph_proximity_is_not_an_action": True,
        "advisory_only": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "activated": False,
    }
