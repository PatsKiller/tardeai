"""R22 — Governed institutional CIO loop contract.

Continuous questions, not autonomous trading. Activation default OFF.
Consumes the same canonical identity/universe/graph/outcome fabric.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI, gated_live_run, require_evidence_class

SCHEMA = "InstitutionalCioLoop@v1"
QUESTIONS = (
    "what_changed",
    "which_entities_affected",
    "what_we_already_know",
    "what_is_contradicted",
    "what_is_stale",
    "what_to_research",
    "what_changed_in_the_thesis",
    "operator_attention",
    "what_happened_after_prior_decisions",
    "what_we_are_learning",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def cio_loop_cycle(
    *,
    evidence_class: str,
    answers: dict[str, Any] | None = None,
    impact: dict[str, Any] | None = None,
    calibration: dict[str, Any] | None = None,
    learning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("R22", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SCHEMA}
    filled = dict(answers or {})
    slots = {q: filled.get(q) for q in QUESTIONS}
    return {
        "schema": SCHEMA,
        "evidence_class": cls,
        "as_of": _now(),
        "questions": QUESTIONS,
        "slots": slots,
        "impact_candidate_set": impact,
        "calibration_ref": (calibration or {}).get("schema"),
        "learning_stage": (learning or {}).get("stage"),
        "autonomous_trading": False,
        "execution_separately_authorized": True,
        "canonical_contract": "TransfersonUniverseManifest@v1",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "activated": False,
    }


def run_cycle(
    *,
    root: Path | str,
    change: dict[str, Any],
    evidence_class: str,
    max_impact: int = 12,
) -> dict[str, Any]:
    """Callable orchestration: change → identity → materiality → prior → graph → gap → free-first inspect → synthesis.

    Does not dispatch paid LLM. Does not write broker/policy. Does not mutate CURRENT graph
    (free-first inspect is read-only).
    """
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("R22", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SCHEMA}
    from scripts.lib.cio_institutional_learning import similar_setup
    from scripts.lib.free_first_refresh import load_profiles
    from scripts.lib.r20_universe_propagation import impact_candidates
    from scripts.lib.ticker_knowledge_graph import retrieve_context
    from scripts.lib.transferson_universe import collect_live_sources, get_identity_lineage, get_symbol, load_universe

    trace_id = str(uuid.uuid4())
    steps: list[dict[str, Any]] = []
    sources = collect_live_sources(root=root)
    manifest = load_universe(root=root, sources=sources)
    steps.append({"step": "change", "input": change, "canonical_universe_count": manifest.get("canonical_universe_count")})
    sym = str(change.get("symbol") or "")
    ident = get_identity_lineage(manifest, sym)
    steps.append({"step": "identity", "identity_status": ident.get("identity_status"), "security_guid": ident.get("security_guid")})
    rec = get_symbol(manifest, sym) or {}
    material = bool(rec.get("currently_held") or rec.get("active_proposal") or rec.get("watch_directive_active") or (change.get("materiality") or 0) >= 0.5)
    steps.append({"step": "materiality", "material": material, "tier": rec.get("current_research_tier"), "reasons": rec.get("membership_reasons")})
    prior = similar_setup(current={"recommendation": change.get("recommendation") or rec.get("current_research_tier")}, history=[], limit=5)
    steps.append({"step": "prior_cognition", "matches": prior.get("matches")})
    impact = impact_candidates(
        manifest, sym, evidence_class=cls, max_n=max_impact, materiality=float(change.get("materiality") or 0.6),
        graph_profiles=sources.get("graph_profiles"),
    )
    steps.append({"step": "graph_impact", "n": impact.get("n"), "related_n": impact.get("related_n")})
    gap = {
        "no_graph_profile": "GRAPH_PROFILE" not in (rec.get("membership_reasons") or []),
        "unresolved_identity": ident.get("identity_status") == "UNRESOLVED_WITH_REASON",
        "no_catalyst": not rec.get("catalyst_guids"),
    }
    steps.append({"step": "gap", "gap": gap})
    profiles = [p for p in load_profiles(root) if str(p.get("symbol") or "").upper() == str(sym).upper()]
    ctx = retrieve_context(root, sym, limit=40) if profiles else {"linear": [], "lateral": [], "vertical": [], "macro": [], "calendar": []}
    art_n = sum(len(ctx.get(k) or []) for k in ("linear", "lateral", "vertical", "macro", "calendar"))
    steps.append({
        "step": "free_first_inspect",
        "profiled": bool(profiles),
        "artifact_n": art_n,
        "wrote": False,
        "paid_dispatch": False,
        "searx": False,
    })
    synthesis = {
        "symbol": sym,
        "material": material,
        "identity_status": ident.get("identity_status"),
        "impact_n": impact.get("n"),
        "gaps": [k for k, v in gap.items() if v],
        "operator_attention": material and any(gap.values()),
        "investment_recommendation": None,
    }
    steps.append({"step": "advisory_synthesis", "synthesis": synthesis})
    return {
        "schema": SCHEMA,
        "evidence_class": cls,
        "trace_id": trace_id,
        "as_of": _now(),
        "steps": steps,
        "lineage": [s["step"] for s in steps],
        "impact": impact,
        "synthesis": synthesis,
        "autonomous_trading": False,
        "execution_separately_authorized": True,
        "financial_action": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "activated": False,
    }
