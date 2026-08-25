"""R20 — Canonical-universe graph impact propagation.

Produces an impact *candidate set*, never an automatic research sweep of the
whole universe. Shared sector/industry is not a supplier/customer edge.
Activation default OFF.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI, gated_live_run, require_evidence_class
from scripts.lib.cio_institutional_learning import identity_safe_subject
from scripts.lib.transferson_universe import (
    get_related_by_catalyst,
    get_related_by_industry,
    get_related_by_sector,
    get_symbol,
)

SCHEMA = "ImpactCandidateSet@v1"
TIER_WEIGHT = {"T0-HOLD": 1.0, "T0-PROP": 0.9, "T1-WATCH": 0.6, "T2-INCUB": 0.3, "T3-COLD": 0.1}
MAX_DEFAULT = 40


def _score(rec: dict[str, Any], *, path: str, materiality: float) -> float:
    tier = rec.get("current_research_tier") or "T3-COLD"
    tw = TIER_WEIGHT.get(str(tier), 0.1)
    held = 1.2 if rec.get("currently_held") else 1.0
    ident = 1.1 if rec.get("security_guid") else 0.8
    path_w = {
        "security": 1.0,
        "industry": 0.55,
        "sector": 0.35,
        "catalyst": 0.7,
        "mention": 0.65,
        "sourced_economic": 0.85,
    }.get(path, 0.3)
    return round(materiality * tw * held * ident * path_w, 4)


def impact_candidates(
    manifest: dict[str, Any],
    origin_symbol: str,
    *,
    evidence_class: str,
    materiality: float = 0.5,
    max_n: int = MAX_DEFAULT,
    sourced_economic: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("R20", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SCHEMA}
    origin = get_symbol(manifest, origin_symbol) or {}
    if not origin:
        return {"schema": SCHEMA, "ok": False, "reason": "origin_not_in_canonical_universe", "authority": AUTHORITY}
    scored: dict[str, dict[str, Any]] = {}

    def add(sym: str, path: str) -> None:
        rec = get_symbol(manifest, sym) or {}
        if not rec or rec.get("symbol") == origin.get("symbol"):
            return
        row = scored.setdefault(rec["symbol"], {
            "symbol": rec["symbol"],
            "subject_guid": identity_safe_subject(rec),
            "paths": [],
            "tier": rec.get("current_research_tier"),
            "membership_reasons": rec.get("membership_reasons") or [],
            "currently_held": rec.get("currently_held"),
            "score": 0.0,
            "not_supply_chain": True,
        })
        if path not in row["paths"]:
            row["paths"].append(path)
        row["score"] = round(row["score"] + _score(rec, path=path, materiality=materiality), 4)

    add(origin.get("symbol"), "security")
    for sym in (get_related_by_industry(manifest, origin_symbol).get("related_symbols") or [])[:80]:
        add(sym, "industry")
    for sym in (get_related_by_sector(manifest, origin_symbol).get("related_symbols") or [])[:80]:
        add(sym, "sector")
    for sym in (get_related_by_catalyst(manifest, origin_symbol).get("related_symbols") or [])[:80]:
        add(sym, "catalyst")
        add(sym, "mention")
    for edge in sourced_economic or []:
        if edge.get("kind") in {"peer", "competitor", "customer", "supplier"} and edge.get("evidence"):
            add(str(edge.get("symbol")), "sourced_economic")

    ranked = sorted(scored.values(), key=lambda r: (-r["score"], r["symbol"]))[: max(1, int(max_n))]
    return {
        "schema": SCHEMA,
        "evidence_class": cls,
        "origin": origin.get("symbol"),
        "origin_subject_guid": identity_safe_subject(origin),
        "candidates": ranked,
        "n": len(ranked),
        "truncated": len(scored) > len(ranked),
        "auto_research_entire_universe": False,
        "not_supply_chain_from_shared_sector": True,
        "canonical_contract": manifest.get("schema"),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "activated": False,
    }
