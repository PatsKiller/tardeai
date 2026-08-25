"""R20 — Canonical-universe graph impact propagation.

Produces an impact *candidate set*, never an automatic research sweep of the
whole universe. Shared sector/industry is not a supplier/customer edge.
Activation default OFF.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI, gated_live_run, require_evidence_class
from scripts.lib.ticker_knowledge_graph import entity_guid, relationship_guid
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


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


REQUIRED_EDGE_FIELDS = (
    "relationship_guid", "source_entity_guid", "target_entity_guid",
    "relationship_type", "relationship_class", "source_type", "source_id",
    "observed_at", "recorded_at", "confidence", "status", "producer",
    "derivation_method",
)


def _complete(edge: dict[str, Any]) -> bool:
    return all(edge.get(k) not in (None, "", []) for k in REQUIRED_EDGE_FIELDS)


def classification_edge(origin: dict[str, Any], target: dict[str, Any], field: str) -> dict[str, Any] | None:
    value = target.get(field)
    if not value:
        return None
    src = origin.get("security_guid") or origin.get("ticker_guid")
    tgt = entity_guid(field, value)
    producer = target.get("classification_source") or origin.get("classification_source")
    observed = str(target.get("classification_observed_at") or origin.get("classification_observed_at") or "")
    if not src or not tgt:
        return None
    rel = "VERTICAL" if field == "industry" else "LATERAL"
    guid = relationship_guid(str(src), str(tgt), f"CLASSIFICATION:{field}")
    edge = {
        "relationship_guid": guid,
        "source_entity_guid": src,
        "target_entity_guid": tgt,
        "relationship_type": "CLASSIFICATION",
        "relationship_class": field,
        "source_type": "symbol_profiles",
        "source_id": producer,
        "source_url": None,
        "evidence_artifact_guid": None,
        "derivation_method": f"symbol_profiles.{field}",
        "observed_at": observed or None,
        "recorded_at": _now(),
        "valid_from": observed or None,
        "valid_to": None,
        "confidence": 0.7 if producer else None,
        "status": "CANDIDATE" if producer else None,
        "producer": producer,
        "producer_version": None,
    }
    edge["provenance_complete"] = _complete(edge)
    return edge


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
            out = {
                "relationship_guid": edge.get("relationship_guid"),
                "source_entity_guid": edge.get("source_entity_guid") or edge.get("source_guid"),
                "target_entity_guid": edge.get("target_entity_guid") or edge.get("target_guid"),
                "relationship_type": edge.get("relationship_type") or edge.get("relationship"),
                "relationship_class": edge.get("relationship_class") or edge.get("target_kind"),
                "source_type": edge.get("source_type"),
                "source_id": edge.get("source_id"),
                "source_url": edge.get("source_url"),
                "evidence_artifact_guid": edge.get("evidence_artifact_guid"),
                "derivation_method": edge.get("derivation_method") or "ticker_research_graph.jsonl",
                "observed_at": edge.get("observed_at"),
                "recorded_at": edge.get("recorded_at"),
                "valid_from": edge.get("valid_from"),
                "valid_to": edge.get("valid_to"),
                "confidence": edge.get("confidence"),
                "status": edge.get("status"),
                "producer": edge.get("producer"),
                "producer_version": edge.get("producer_version"),
            }
            out["provenance_complete"] = _complete(out)
            return out
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
    incomplete: dict[str, dict[str, Any]] = {}
    edges_complete = 0
    edges_incomplete = 0
    edges_disputed = 0

    def add(sym: str, path: str) -> None:
        nonlocal edges_complete, edges_incomplete, edges_disputed
        rec = get_symbol(manifest, sym) or {}
        if not rec or rec.get("symbol") == origin.get("symbol"):
            return
        if path in {"industry", "sector"}:
            edge = classification_edge(origin, rec, path)
        elif path == "sourced_economic":
            return
        else:
            edge = _edge_for_path(origin_profile, path)
        if edge is None:
            return
        if not edge.get("provenance_complete"):
            edges_incomplete += 1
            inc = incomplete.setdefault(rec["symbol"], {
                "symbol": rec["symbol"],
                "subject_guid": identity_safe_subject(rec),
                "paths": [],
                "status": "PROVENANCE_INCOMPLETE",
                "edges": [],
                "not_supply_chain": True,
            })
            if path not in inc["paths"]:
                inc["paths"].append(path)
            inc["edges"].append(edge)
            return
        edges_complete += 1
        if edge.get("status") in {"DISPUTED", "EXPIRED", "SUPERSEDED"}:
            edges_disputed += 1
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
            "status": "PROVENANCE_COMPLETE",
            "not_supply_chain": True,
        })
        if path not in row["paths"]:
            row["paths"].append(path)
            row["why_included"].append(f"path={path};provenance_complete")
        row["score"] = round(row["score"] + _score(rec, path=path, materiality=materiality), 4)
        if edge.get("relationship_guid") not in {e.get("relationship_guid") for e in row["edges"]}:
            row["edges"].append(edge)

    for sym in (get_related_by_industry(manifest, origin_symbol).get("related_symbols") or []):
        add(sym, "industry")
    for sym in (get_related_by_sector(manifest, origin_symbol).get("related_symbols") or []):
        add(sym, "sector")
    for sym in (get_related_by_catalyst(manifest, origin_symbol).get("related_symbols") or []):
        add(sym, "catalyst")
        add(sym, "mention")
    for econ in sourced_economic or []:
        if econ.get("kind") in {"peer", "competitor", "customer", "supplier"} and econ.get("evidence"):
            add(str(econ.get("symbol")), "sourced_economic")

    used = edges_complete + edges_incomplete
    cap = max(1, int(max_n))
    ranked_all = sorted(scored.values(), key=lambda r: (-r["score"], r["symbol"]))
    kept = ranked_all[:cap]
    excluded = [
        {"symbol": r["symbol"], "score": r["score"], "paths": r["paths"], "why_excluded": "RANK_BELOW_CUTOFF"}
        for r in ranked_all[cap:cap + 20]
    ]
    coverage = {
        "securities_in_universe": manifest.get("canonical_universe_count"),
        "graph_profiled_securities": sum(1 for r in (manifest.get("securities") or []) if "GRAPH_PROFILE" in (r.get("membership_reasons") or [])),
        "identity_resolved_securities": sum(1 for r in (manifest.get("securities") or []) if r.get("security_guid")),
        "edges_total": used,
        "fully_provenance_complete_edges": edges_complete,
        "candidate_incomplete_edges": edges_incomplete,
        "disputed_edges": edges_disputed,
        "expired_superseded_edges": 0,
        "provenance_complete_ratio": round(edges_complete / used, 4) if used else None,
    }
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
        "incomplete_candidates": list(incomplete.values())[:20],
        "excluded_sample": excluded,
        "related_n": len(ranked_all),
        "n": len(kept),
        "canonical_universe_count": manifest.get("canonical_universe_count"),
        "truncated": len(ranked_all) > len(kept),
        "provenance_coverage": coverage,
        "silent_incomplete_edges_used_for_score": False,
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
