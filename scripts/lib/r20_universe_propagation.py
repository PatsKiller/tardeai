"""R20 — Canonical-universe graph impact propagation.

Produces an impact *candidate set*, never an automatic research sweep of the
whole universe. Shared sector/industry is not a supplier/customer edge.
Activation default OFF.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI, gated_live_run, require_evidence_class
from scripts.lib.cio_institutional_learning import identity_safe_subject
from scripts.lib.security_identity import normalize_symbol
from scripts.lib.transferson_universe import (
    get_related_by_catalyst,
    get_related_by_industry,
    get_related_by_sector,
    get_symbol,
    load_universe,
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


def _edge_for_path(profile: dict[str, Any] | None, path: str) -> dict[str, Any] | None:
    if not profile:
        return None
    want = {
        "security": "issuer",
        "industry": "industry",
        "sector": "sector",
        "catalyst": "catalyst",
        "mention": "catalyst",
    }.get(path)
    for edge in profile.get("relationships") or []:
        if not isinstance(edge, dict):
            continue
        if want and edge.get("target_kind") == want:
            return {
                "relationship_guid": edge.get("relationship_guid"),
                "source_guid": edge.get("source_guid"),
                "target_guid": edge.get("target_guid"),
                "relationship": edge.get("relationship"),
                "target_kind": edge.get("target_kind"),
                "producer": edge.get("producer"),
                "source_type": edge.get("source_type"),
                "observed_at": edge.get("observed_at"),
                "recorded_at": edge.get("recorded_at"),
                "status": edge.get("status"),
                "confidence": edge.get("confidence"),
                "provenance_complete": bool(edge.get("producer") and edge.get("source_type") and edge.get("observed_at")),
            }
    return None


def impact_candidates(
    manifest: dict[str, Any],
    origin_symbol: str,
    *,
    evidence_class: str,
    materiality: float = 0.5,
    max_n: int = MAX_DEFAULT,
    sourced_economic: list[dict[str, Any]] | None = None,
    graph_profiles: list[dict[str, Any]] | None = None,
    starting_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("R20", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SCHEMA}
    origin = get_symbol(manifest, origin_symbol) or {}
    if not origin:
        return {"schema": SCHEMA, "ok": False, "reason": "origin_not_in_canonical_universe", "authority": AUTHORITY}
    gindex = {
        normalize_symbol(p.get("symbol")): p
        for p in (graph_profiles or [])
        if isinstance(p, dict) and p.get("symbol")
    }
    origin_profile = gindex.get(normalize_symbol(origin.get("symbol")))
    artifact = starting_artifact or {
        "kind": "TickerKnowledgeProfile@v1" if origin_profile else "universe_row",
        "ticker_guid": (origin_profile or {}).get("ticker_guid") or origin.get("ticker_guid"),
        "symbol": origin.get("symbol"),
        "catalyst_guids": origin.get("catalyst_guids") or (origin_profile or {}).get("catalyst_guids") or [],
    }
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
            "why_included": [],
            "edges": [],
            "not_supply_chain": True,
        })
        if path not in row["paths"]:
            row["paths"].append(path)
            row["why_included"].append(f"path={path}")
        row["score"] = round(row["score"] + _score(rec, path=path, materiality=materiality), 4)
        edge = _edge_for_path(origin_profile, path)
        if edge and edge.get("relationship_guid") not in {e.get("relationship_guid") for e in row["edges"]}:
            row["edges"].append(edge)

    for sym in (get_related_by_industry(manifest, origin_symbol).get("related_symbols") or []):
        add(sym, "industry")
    for sym in (get_related_by_sector(manifest, origin_symbol).get("related_symbols") or []):
        add(sym, "sector")
    for sym in (get_related_by_catalyst(manifest, origin_symbol).get("related_symbols") or []):
        add(sym, "catalyst")
        add(sym, "mention")
    for edge in sourced_economic or []:
        if edge.get("kind") in {"peer", "competitor", "customer", "supplier"} and edge.get("evidence"):
            add(str(edge.get("symbol")), "sourced_economic")

    cap = max(1, int(max_n))
    ranked_all = sorted(scored.values(), key=lambda r: (-r["score"], r["symbol"]))
    kept = ranked_all[:cap]
    excluded = [
        {"symbol": r["symbol"], "score": r["score"], "paths": r["paths"], "why_excluded": "RANK_BELOW_CUTOFF"}
        for r in ranked_all[cap:cap + 20]
    ]
    return {
        "schema": SCHEMA,
        "evidence_class": cls,
        "origin": origin.get("symbol"),
        "originating_entity": {
            "symbol": origin.get("symbol"),
            "subject_guid": identity_safe_subject(origin),
            "membership_reasons": origin.get("membership_reasons") or [],
            "tier": origin.get("current_research_tier"),
        },
        "starting_evidence_artifact": artifact,
        "candidates": kept,
        "excluded_sample": excluded,
        "related_n": len(ranked_all),
        "n": len(kept),
        "canonical_universe_count": manifest.get("canonical_universe_count"),
        "truncated": len(ranked_all) > len(kept),
        "auto_research_entire_universe": False,
        "not_supply_chain_from_shared_sector": True,
        "canonical_contract": manifest.get("schema"),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "activated": False,
    }


def propagate_from_canonical_root(
    root,
    origin_symbol: str,
    *,
    evidence_class: str,
    max_n: int = MAX_DEFAULT,
    materiality: float = 0.5,
) -> dict[str, Any]:
    """Executable entry: real collect_live_sources + load_universe. Not a fixture loader."""
    from scripts.lib.transferson_universe import collect_live_sources
    sources = collect_live_sources(root=root)
    manifest = load_universe(root=root, sources=sources)
    return impact_candidates(
        manifest,
        origin_symbol,
        evidence_class=evidence_class,
        max_n=max_n,
        materiality=materiality,
        graph_profiles=sources.get("graph_profiles"),
    )
