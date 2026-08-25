"""R20 — Canonical-universe graph impact propagation.

Produces an impact *candidate set*, never an automatic research sweep of the
whole universe. Shared sector/industry is not a supplier/customer edge.
Incomplete edges are never used silently. Activation default OFF.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
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
COVERAGE_SCHEMA = "UniverseProvenanceCoverage@v1"
TRACE_SCHEMA = "PropagationTrace@v1"
TIER_WEIGHT = {"T0-HOLD": 1.0, "T0-PROP": 0.9, "T1-WATCH": 0.6, "T2-INCUB": 0.3, "T3-COLD": 0.1}
MAX_DEFAULT = 40
THESES = "data/cio/cio_theses.jsonl"

REQUIRED_EDGE_FIELDS = (
    "relationship_guid", "source_entity_guid", "target_entity_guid",
    "relationship_type", "relationship_class", "source_type", "source_id",
    "evidence_artifact_guid", "derivation_method", "observed_at", "recorded_at",
    "valid_from", "confidence", "status", "producer", "producer_version",
)
OPTIONAL_EDGE_FIELDS = ("source_url", "valid_to")


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


def _complete(edge: dict[str, Any]) -> bool:
    return all(edge.get(k) not in (None, "", []) for k in REQUIRED_EDGE_FIELDS)


def _evidence_guid(*parts: Any) -> str:
    payload = "|".join(str(p) for p in parts)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:evidence:{payload}"))


def _entity_id(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    return identity_safe_subject(row) or row.get("ticker_guid") or entity_guid("ticker", row.get("symbol"))


def classification_edge(origin: dict[str, Any], target: dict[str, Any], field: str) -> dict[str, Any] | None:
    """Auditable classification-peer edge. Target is the related security, not the industry string.

    Shared sector/industry is CLASSIFICATION, never supplier/customer/competitor.
    Both origin and target must carry classification_source + observed_at to be complete.
    """
    value = target.get(field)
    if not value or origin.get(field) != value:
        return None
    src = _entity_id(origin)
    tgt = _entity_id(target)
    if not src or not tgt:
        return None
    producer = target.get("classification_source") or origin.get("classification_source")
    observed = str(
        target.get("classification_observed_at")
        or origin.get("classification_observed_at")
        or ""
    )
    origin_src = origin.get("classification_source")
    target_src = target.get("classification_source")
    both_sourced = bool(origin_src and target_src and observed)
    rel = "VERTICAL" if field == "industry" else "LATERAL"
    guid = relationship_guid(str(src), str(tgt), f"CLASSIFICATION:{field}")
    artifact = _evidence_guid("symbol_profiles", field, target.get("symbol"), producer, observed)
    edge = {
        "relationship_guid": guid,
        "source_entity_guid": src,
        "target_entity_guid": tgt,
        "relationship_type": "CLASSIFICATION",
        "relationship_class": field,
        "class_entity_guid": entity_guid(field if field in {"sector", "industry"} else "theme", value),
        "class_label": value,
        "source_type": "symbol_profiles",
        "source_id": f"{origin_src}|{target_src}" if origin_src and target_src else producer,
        "source_url": None,
        "evidence_artifact_guid": artifact if both_sourced else None,
        "derivation_method": f"symbol_profiles.{field}",
        "observed_at": observed or None,
        "recorded_at": _now(),
        "valid_from": observed or None,
        "valid_to": None,
        "confidence": 0.7 if both_sourced else None,
        "status": "CANDIDATE" if both_sourced else None,
        "producer": producer if both_sourced else None,
        "producer_version": f"observed:{observed}" if both_sourced else None,
        "not_supply_chain": True,
    }
    edge["provenance_complete"] = _complete(edge)
    if not edge["provenance_complete"]:
        edge["incomplete_reason"] = "classification_source_or_observed_at_missing"
    return edge


def _edge_for_path(profile: dict[str, Any] | None, path: str) -> dict[str, Any] | None:
    if not profile:
        return None
    want = {
        "security": "issuer",
        "industry": "industry",
        "sector": "sector",
        "catalyst": "catalyst",
    }.get(path)
    for edge in profile.get("relationships") or []:
        if not isinstance(edge, dict):
            continue
        if want and (edge.get("target_kind") or edge.get("relationship_class")) == want:
            return enrich_graph_edge(edge, profile)
    return None


def enrich_graph_edge(edge: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Additive envelope projection. Does not rewrite the jsonl edge."""
    kind = edge.get("target_kind") or edge.get("relationship_class")
    observed = edge.get("observed_at") or profile.get("updated_at") or profile.get("enrichment_checked_at")
    out = {
        "relationship_guid": edge.get("relationship_guid"),
        "source_entity_guid": edge.get("source_entity_guid") or edge.get("source_guid"),
        "target_entity_guid": edge.get("target_entity_guid") or edge.get("target_guid"),
        "relationship_type": edge.get("relationship_type") or edge.get("relationship"),
        "relationship_class": kind,
        "source_type": edge.get("source_type") or "ticker_knowledge_profile",
        "source_id": edge.get("source_id") or profile.get("ticker_guid"),
        "source_url": edge.get("source_url"),
        "evidence_artifact_guid": edge.get("evidence_artifact_guid"),
        "derivation_method": edge.get("derivation_method") or "parent_profile_envelope",
        "observed_at": observed,
        "recorded_at": edge.get("recorded_at") or observed or _now(),
        "valid_from": edge.get("valid_from") or observed,
        "valid_to": edge.get("valid_to"),
        "confidence": edge.get("confidence") if edge.get("confidence") is not None else 0.3,
        "status": edge.get("status") or "CANDIDATE",
        "producer": edge.get("producer") or "ticker_knowledge_graph",
        "producer_version": edge.get("producer_version") or (f"profile:{observed}" if observed else None),
        "envelope_reconstructed": not bool(edge.get("producer") and edge.get("observed_at")),
    }
    if kind in {"catalyst", "ticker", "calendar"} and not out.get("evidence_artifact_guid"):
        out["evidence_artifact_guid"] = None
        out["incomplete_reason"] = "missing_evidence_artifact_for_event_or_mention"
    elif not out.get("evidence_artifact_guid"):
        out["evidence_artifact_guid"] = profile.get("ticker_guid")
    out["provenance_complete"] = _complete(out)
    return out


def load_thesis_mention_edges(root: Any) -> list[dict[str, Any]]:
    """Explicit cross-ticker mentions from thesis linked_symbols. Not ticker-text mining."""
    path = Path(root) / THESES
    if not path.is_file():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        tid = payload.get("thesis_id") or row.get("thesis_id")
        if not tid:
            continue
        latest[str(tid)] = {**payload, "_event_id": row.get("event_id"), "_occurred_at": row.get("occurred_at"), "_actor_id": row.get("actor_id")}
    edges: list[dict[str, Any]] = []
    for thesis in latest.values():
        symbols = [normalize_symbol(s) for s in (thesis.get("linked_symbols") or []) if normalize_symbol(s)]
        symbols = sorted(set(symbols))
        if len(symbols) < 2:
            continue
        observed = str(thesis.get("published_ts") or thesis.get("_occurred_at") or "")
        version = thesis.get("thesis_version") or f"{thesis.get('thesis_id')}@v{thesis.get('version')}"
        producer = thesis.get("_actor_id") or thesis.get("owner_agent") or "cio_theses"
        artifact = str(thesis.get("_event_id") or version)
        for i, src_sym in enumerate(symbols):
            for tgt_sym in symbols[i + 1:]:
                src = entity_guid("ticker", src_sym)
                tgt = entity_guid("ticker", tgt_sym)
                if not src or not tgt:
                    continue
                edge = {
                    "relationship_guid": relationship_guid(src, tgt, "MENTION"),
                    "source_entity_guid": src,
                    "target_entity_guid": tgt,
                    "source_symbol": src_sym,
                    "target_symbol": tgt_sym,
                    "relationship_type": "MENTION",
                    "relationship_class": "mention",
                    "source_type": "cio_theses",
                    "source_id": artifact,
                    "source_url": None,
                    "evidence_artifact_guid": artifact,
                    "derivation_method": "thesis.linked_symbols",
                    "observed_at": observed or None,
                    "recorded_at": observed or _now(),
                    "valid_from": observed or None,
                    "valid_to": None,
                    "confidence": 0.6,
                    "status": "CANDIDATE",
                    "producer": producer,
                    "producer_version": str(version),
                    "ticker_guid_is_not_security": True,
                }
                edge["provenance_complete"] = _complete(edge)
                edges.append(edge)
    return edges


def sourced_economic_edge(origin: dict[str, Any], econ: dict[str, Any]) -> dict[str, Any] | None:
    """Peer/customer/supplier/competitor requires explicit evidence. Shared industry is not enough."""
    kind = str(econ.get("kind") or "").lower()
    if kind not in {"peer", "competitor", "customer", "supplier"}:
        return None
    if not econ.get("evidence"):
        return None
    tgt_row = {"symbol": econ.get("symbol"), "security_guid": econ.get("security_guid"), "ticker_guid": econ.get("ticker_guid")}
    src = _entity_id(origin)
    tgt = _entity_id(tgt_row)
    if not src or not tgt:
        return None
    observed = str(econ.get("observed_at") or econ.get("as_of") or "")
    artifact = econ.get("evidence_artifact_guid") or econ.get("source_id")
    edge = {
        "relationship_guid": relationship_guid(str(src), str(tgt), kind.upper()),
        "source_entity_guid": src,
        "target_entity_guid": tgt,
        "relationship_type": kind.upper(),
        "relationship_class": kind,
        "source_type": econ.get("source_type") or "sourced_economic_evidence",
        "source_id": econ.get("source_id") or artifact,
        "source_url": econ.get("source_url"),
        "evidence_artifact_guid": artifact,
        "derivation_method": "explicit_supporting_evidence",
        "observed_at": observed or None,
        "recorded_at": _now(),
        "valid_from": observed or None,
        "valid_to": econ.get("valid_to"),
        "confidence": econ.get("confidence") if econ.get("confidence") is not None else 0.5,
        "status": econ.get("status") or "CANDIDATE",
        "producer": econ.get("producer"),
        "producer_version": econ.get("producer_version"),
        "not_from_shared_sector_alone": True,
    }
    edge["provenance_complete"] = _complete(edge)
    return edge


def universe_provenance_coverage(
    manifest: dict[str, Any],
    *,
    graph_profiles: list[dict[str, Any]] | None = None,
    mention_edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fact-edge coverage on the canonical universe. Pairwise expansion is derived, not stored."""
    securities = manifest.get("securities") or []
    complete = incomplete = disputed = expired = 0
    facts: list[dict[str, Any]] = []

    def tally(edge: dict[str, Any] | None) -> None:
        nonlocal complete, incomplete, disputed, expired
        if not edge:
            return
        facts.append(edge)
        if edge.get("status") in {"DISPUTED"}:
            disputed += 1
        if edge.get("status") in {"EXPIRED", "SUPERSEDED"}:
            expired += 1
        if edge.get("provenance_complete"):
            complete += 1
        else:
            incomplete += 1

    for rec in securities:
        if not isinstance(rec, dict):
            continue
        for field in ("industry", "sector"):
            if rec.get(field):
                src = _entity_id(rec)
                class_guid = entity_guid(field, rec.get(field))
                if not src or not class_guid:
                    continue
                observed = str(rec.get("classification_observed_at") or "")
                producer = rec.get("classification_source")
                sourced = bool(producer and observed)
                edge = {
                    "relationship_guid": relationship_guid(str(src), str(class_guid), f"CLASSIFICATION:{field}"),
                    "source_entity_guid": src,
                    "target_entity_guid": class_guid,
                    "relationship_type": "CLASSIFICATION",
                    "relationship_class": field,
                    "source_type": "symbol_profiles",
                    "source_id": producer,
                    "source_url": None,
                    "evidence_artifact_guid": _evidence_guid("symbol_profiles", field, rec.get("symbol"), producer, observed) if sourced else None,
                    "derivation_method": f"symbol_profiles.{field}",
                    "observed_at": observed or None,
                    "recorded_at": observed or None,
                    "valid_from": observed or None,
                    "valid_to": None,
                    "confidence": 0.7 if sourced else None,
                    "status": "CANDIDATE" if sourced else None,
                    "producer": producer if sourced else None,
                    "producer_version": f"observed:{observed}" if sourced else None,
                }
                edge["provenance_complete"] = _complete(edge)
                tally(edge)

    for profile in graph_profiles or []:
        if not isinstance(profile, dict):
            continue
        for raw in profile.get("relationships") or []:
            if isinstance(raw, dict):
                tally(enrich_graph_edge(raw, profile))

    for edge in mention_edges or []:
        tally(edge)

    used = complete + incomplete
    return {
        "schema": COVERAGE_SCHEMA,
        "securities_in_universe": manifest.get("canonical_universe_count"),
        "graph_profiled_securities": sum(
            1 for r in securities if "GRAPH_PROFILE" in (r.get("membership_reasons") or [])
        ),
        "identity_resolved_securities": sum(1 for r in securities if r.get("security_guid")),
        "edges_total": used,
        "fully_provenance_complete_edges": complete,
        "candidate_incomplete_edges": incomplete,
        "disputed_edges": disputed,
        "expired_superseded_edges": expired,
        "provenance_complete_ratio": round(complete / used, 4) if used else None,
        "edges_used_for_propagation": complete,
        "silent_incomplete_edges_used_for_score": False,
        "authority": AUTHORITY,
    }


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
    mention_edges: list[dict[str, Any]] | None = None,
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
        "source_type": "ticker_knowledge_profile" if origin_profile else "transferson_universe",
        "source_id": (origin_profile or {}).get("ticker_guid") or origin.get("symbol"),
    }
    scored: dict[str, dict[str, Any]] = {}
    incomplete: dict[str, dict[str, Any]] = {}
    edges_complete = 0
    edges_incomplete = 0
    edges_disputed = 0
    edges_expired = 0

    def _research_gap(rec: dict[str, Any], paths: list[str]) -> str:
        if rec.get("current_research_tier") in {"T3-COLD", "T2-INCUB"}:
            return "NO_BOUNDED_RESEARCH_COMMISSION"
        if "catalyst" in paths:
            return "CATALYST_EDGE_PRESENT_NO_BULK_RESEARCH"
        return "IMPACT_CANDIDATE_ONLY"

    def _trace(rec: dict[str, Any], edge: dict[str, Any], path: str, score: float) -> dict[str, Any]:
        return {
            "schema": TRACE_SCHEMA,
            "source_artifact": artifact,
            "source_entity": {
                "symbol": origin.get("symbol"),
                "subject_guid": identity_safe_subject(origin),
                "ticker_guid": origin.get("ticker_guid"),
            },
            "edges": [edge],
            "target_security": {
                "symbol": rec.get("symbol"),
                "subject_guid": identity_safe_subject(rec),
                "ticker_guid_is_not_security": not bool(rec.get("security_guid")),
            },
            "canonical_membership": rec.get("membership_reasons") or [],
            "impact_score": score,
            "research_gap": _research_gap(rec, [path]),
            "path": path,
        }

    def add(sym: str, path: str, edge: dict[str, Any] | None = None) -> None:
        nonlocal edges_complete, edges_incomplete, edges_disputed, edges_expired
        rec = get_symbol(manifest, sym) or {}
        if not rec or rec.get("symbol") == origin.get("symbol"):
            return
        if edge is None:
            if path in {"industry", "sector"}:
                edge = classification_edge(origin, rec, path)
            elif path == "sourced_economic":
                return
            elif path == "mention":
                return
            else:
                edge = _edge_for_path(origin_profile, path)
        if edge is None:
            return
        if edge.get("status") in {"DISPUTED"}:
            edges_disputed += 1
            return
        if edge.get("status") in {"EXPIRED", "SUPERSEDED"}:
            edges_expired += 1
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
                "why_excluded_from_score": "PROVENANCE_INCOMPLETE",
            })
            if path not in inc["paths"]:
                inc["paths"].append(path)
            inc["edges"].append(edge)
            return
        edges_complete += 1
        row = scored.setdefault(rec["symbol"], {
            "symbol": rec["symbol"],
            "subject_guid": identity_safe_subject(rec),
            "paths": [],
            "tier": rec.get("current_research_tier"),
            "membership_reasons": rec.get("membership_reasons") or [],
            "currently_held": rec.get("currently_held"),
            "score": 0.0,
            "why_included": [],
            "why_ranked": "",
            "edges": [],
            "traces": [],
            "status": "PROVENANCE_COMPLETE",
            "not_supply_chain": True,
            "research_gap": _research_gap(rec, []),
        })
        if path not in row["paths"]:
            row["paths"].append(path)
            row["why_included"].append(f"path={path};provenance_complete")
        row["score"] = round(row["score"] + _score(rec, path=path, materiality=materiality), 4)
        row["why_ranked"] = (
            f"score={row['score']};paths={','.join(row['paths'])};"
            f"tier={row.get('tier')};held={bool(row.get('currently_held'))};"
            f"identity={'resolved' if row.get('subject_guid') else 'unresolved'}"
        )
        row["research_gap"] = _research_gap(rec, row["paths"])
        if edge.get("relationship_guid") not in {e.get("relationship_guid") for e in row["edges"]}:
            row["edges"].append(edge)
            row["traces"].append(_trace(rec, edge, path, row["score"]))

    for sym in (get_related_by_industry(manifest, origin_symbol).get("related_symbols") or []):
        add(sym, "industry")
    for sym in (get_related_by_sector(manifest, origin_symbol).get("related_symbols") or []):
        add(sym, "sector")
    for sym in (get_related_by_catalyst(manifest, origin_symbol).get("related_symbols") or []):
        add(sym, "catalyst")
    origin_norm = normalize_symbol(origin.get("symbol"))
    for medge in mention_edges or []:
        if normalize_symbol(medge.get("source_symbol")) == origin_norm:
            add(str(medge.get("target_symbol")), "mention", medge)
        elif normalize_symbol(medge.get("target_symbol")) == origin_norm:
            flipped = dict(medge)
            flipped["source_symbol"], flipped["target_symbol"] = medge.get("target_symbol"), medge.get("source_symbol")
            add(str(medge.get("source_symbol")), "mention", medge)
    issuer = origin.get("issuer_guid")
    if issuer:
        for rec in manifest.get("securities") or []:
            if rec.get("issuer_guid") == issuer and rec.get("symbol") != origin.get("symbol"):
                ident_edge = _edge_for_path(origin_profile, "security")
                if ident_edge:
                    add(rec["symbol"], "security", ident_edge)
    for econ in sourced_economic or []:
        e_edge = sourced_economic_edge(origin, econ)
        if e_edge:
            add(str(econ.get("symbol")), "sourced_economic", e_edge)

    used = edges_complete + edges_incomplete
    cap = max(1, int(max_n))
    ranked_all = sorted(scored.values(), key=lambda r: (-r["score"], r["symbol"]))
    kept = ranked_all[:cap]
    excluded = [
        {
            "symbol": r["symbol"],
            "score": r["score"],
            "paths": r["paths"],
            "why_excluded": "RANK_BELOW_CUTOFF",
            "why_not_other_related": "lower_score_than_kept_set",
        }
        for r in ranked_all[cap:cap + 20]
    ]
    origin_security_trace = {
        "schema": TRACE_SCHEMA,
        "path": "security",
        "source_artifact": artifact,
        "source_entity": {
            "symbol": origin.get("symbol"),
            "subject_guid": identity_safe_subject(origin),
            "ticker_guid": origin.get("ticker_guid"),
        },
        "edges": [],
        "target_security": {
            "symbol": origin.get("symbol"),
            "subject_guid": identity_safe_subject(origin),
            "ticker_guid_is_not_security": not bool(origin.get("security_guid")),
        },
        "canonical_membership": origin.get("membership_reasons") or [],
        "impact_score": None,
        "research_gap": "ORIGIN_NOT_A_PROPAGATION_TARGET",
        "why_ranked": "originating_security",
    }
    coverage = {
        "securities_in_universe": manifest.get("canonical_universe_count"),
        "graph_profiled_securities": sum(
            1 for r in (manifest.get("securities") or [])
            if "GRAPH_PROFILE" in (r.get("membership_reasons") or [])
        ),
        "identity_resolved_securities": sum(
            1 for r in (manifest.get("securities") or []) if r.get("security_guid")
        ),
        "edges_total": used,
        "fully_provenance_complete_edges": edges_complete,
        "candidate_incomplete_edges": edges_incomplete,
        "disputed_edges": edges_disputed,
        "expired_superseded_edges": edges_expired,
        "provenance_complete_ratio": round(edges_complete / used, 4) if used else None,
        "edges_used_for_propagation": edges_complete,
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
        "origin_security_trace": origin_security_trace,
        "candidates": kept,
        "incomplete_candidates": list(incomplete.values())[:20],
        "excluded_sample": excluded,
        "related_n": len(ranked_all),
        "n": len(kept),
        "canonical_universe_count": manifest.get("canonical_universe_count"),
        "truncated": len(ranked_all) > len(kept),
        "provenance_coverage": coverage,
        "universe_provenance_coverage": universe_provenance_coverage(
            manifest, graph_profiles=graph_profiles, mention_edges=mention_edges,
        ),
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
    mentions = load_thesis_mention_edges(root)
    return impact_candidates(
        manifest,
        origin_symbol,
        evidence_class=evidence_class,
        max_n=max_n,
        materiality=materiality,
        graph_profiles=sources.get("graph_profiles"),
        mention_edges=mentions,
    )


def historical_propagation_traces(root, *, evidence_class: str = "HISTORICAL_REPLAY") -> dict[str, Any]:
    """Several real traces: security, industry, sector, catalyst, explicit mention. No bulk research."""
    from scripts.lib.transferson_universe import collect_live_sources
    sources = collect_live_sources(root=root)
    manifest = load_universe(root=root, sources=sources)
    mentions = load_thesis_mention_edges(root)
    traces: dict[str, Any] = {}
    common_kw = dict(
        evidence_class=evidence_class, max_n=8,
        graph_profiles=sources.get("graph_profiles"), mention_edges=mentions,
    )

    def pack(out: dict[str, Any], origin: str, want_path: str) -> dict[str, Any]:
        hits = [c for c in (out.get("candidates") or []) if want_path in (c.get("paths") or [])]
        incomplete = [c for c in (out.get("incomplete_candidates") or []) if want_path in (c.get("paths") or [])]
        sample = (hits or incomplete or [None])[0]
        return {
            "origin": origin,
            "path": want_path,
            "complete_hits": len(hits),
            "incomplete_hits": len(incomplete),
            "sample": {
                "symbol": (sample or {}).get("symbol"),
                "status": (sample or {}).get("status"),
                "score": (sample or {}).get("score"),
                "why_ranked": (sample or {}).get("why_ranked") or (sample or {}).get("why_excluded_from_score"),
                "trace": ((sample or {}).get("traces") or [out.get("origin_security_trace")])[0],
            } if sample else {"status": "NO_EDGE", "reason": f"no_{want_path}_edge_from_{origin}"},
            "silent_incomplete": out.get("silent_incomplete_edges_used_for_score"),
            "canonical_universe_count": out.get("canonical_universe_count"),
        }

    noc = impact_candidates(manifest, "NOC", **common_kw)
    traces["security"] = {"origin": "NOC", "path": "security", "sample": noc.get("origin_security_trace")}
    traces["industry"] = pack(noc, "NOC", "industry")
    traces["sector"] = pack(noc, "NOC", "sector")
    achv = get_symbol(manifest, "ACHV")
    traces["catalyst"] = pack(
        impact_candidates(manifest, "ACHV", **common_kw) if achv else noc,
        "ACHV" if achv else "NOC",
        "catalyst",
    )
    mention_origin = None
    for edge in mentions:
        if get_symbol(manifest, edge.get("source_symbol") or ""):
            mention_origin = edge.get("source_symbol")
            break
    if mention_origin:
        mout = impact_candidates(manifest, mention_origin, **common_kw)
        traces["mention"] = pack(mout, mention_origin, "mention")
    else:
        traces["mention"] = {
            "path": "mention",
            "sample": {"status": "NO_EDGE", "reason": "no_explicit_cross_ticker_mention_with_artifact"},
            "complete_hits": 0,
        }
    coverage = universe_provenance_coverage(
        manifest, graph_profiles=sources.get("graph_profiles"), mention_edges=mentions,
    )
    return {
        "schema": "HistoricalPropagationTraces@v1",
        "evidence_class": evidence_class,
        "traces": traces,
        "universe_provenance_coverage": coverage,
        "mention_edges_n": len(mentions),
        "auto_research_entire_universe": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }
