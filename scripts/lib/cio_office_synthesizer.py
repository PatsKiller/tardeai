"""CIO as synthesizer, not a rule router.

Deterministic scanners inform the CIO. They cannot be the CIO.
READ_ONLY_ADVISORY: think/research/disagree/theorize/recommend. No trades.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.canon_reasoning import reason_with_canon
from scripts.lib.cio_forward_program import (
    ADVISORY_INFLUENCE_PROMOTION,
    AUTHORITY,
    COGNITION_MAY_MUTATE_OFFICE_TRUTH,
    INSTITUTIONAL_COGNITION,
    MBI,
    OFFICE_TRUTH,
    gated_live_run,
    identity_roll_up,
    require_evidence_class,
)
from scripts.lib.historical_regime_lab import compare as compare_regimes
from scripts.lib.institutional_knowledge_fabric import retrieve
from scripts.lib.investment_theory_engine import competing_theories
from scripts.lib.r20_universe_propagation import impact_candidates
from scripts.lib.sector_research_desk import build_sector_theses, inherit_sector_context
from scripts.lib.transferson_universe import get_symbol, load_universe

SCHEMA = "CioOfficeCycle@v1"
RECS = (
    "BUY_ADD_CANDIDATE",
    "HOLD",
    "TRIM",
    "EXIT_CANDIDATE",
    "WATCH",
    "REENTER",
    "AVOID",
    "RESEARCH_MORE",
    "NO_EDGE",
    "THESIS_CHANGED",
    "DISAGREE_DETERMINISTIC_SETUP",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def office_truth_snapshot(rec: dict[str, Any] | None, holdings: list[str] | None = None) -> dict[str, Any]:
    """Facts the CIO may not invent or override."""
    rec = rec or {}
    return {
        "lane": OFFICE_TRUTH,
        "symbol": rec.get("symbol"),
        "identity": identity_roll_up(rec),
        "currently_held": rec.get("currently_held"),
        "membership_reasons": rec.get("membership_reasons") or [],
        "current_research_tier": rec.get("current_research_tier"),
        "held_symbols": list(holdings or []),
        "prices": None,
        "cash": None,
        "broker_state": None,
        "orders": None,
        "risk_limits": None,
        "unconfirmed": ["prices", "cash", "broker_state", "orders", "risk_limits"],
        "cognition_may_not_override": True,
    }


def _recommend(rec: dict[str, Any], theories: dict[str, Any], retrieval: dict[str, Any],
               canon: dict[str, Any], impact: dict[str, Any]) -> dict[str, Any]:
    """Synthesize. Never a single scanner rule."""
    held = bool(rec.get("currently_held"))
    identity = rec.get("identity_status") or rec.get("security_guid")
    gaps = []
    if not rec.get("catalyst_guids"):
        gaps.append("no_catalyst")
    if not identity:
        gaps.append("unresolved_identity")
    if (canon.get("catalog_available_n") or 0) == 0:
        gaps.append("canon_full_text_unavailable")
    if not (retrieval.get("hits") or []):
        gaps.append("empty_cognition")
    incomplete = impact.get("incomplete_candidates") or []
    if held and gaps:
        rec_name = "RESEARCH_MORE"
    elif not held and (impact.get("n") or 0) == 0:
        rec_name = "NO_EDGE"
    elif not held:
        rec_name = "WATCH"
    else:
        rec_name = "HOLD"
    if canon.get("disagreement_visible"):
        rec_name = "RESEARCH_MORE" if rec_name == "HOLD" else rec_name
    return {
        "recommendation": rec_name,
        "allowed_set": list(RECS),
        "advisory_only": True,
        "execution_separately_authorized": True,
        "reasons": {
            "held": held,
            "gaps": gaps,
            "theories": list((theories.get("theories") or {}).keys()),
            "canon_disagreement": canon.get("disagreement_visible"),
            "impact_n": impact.get("n"),
            "incomplete_edges": len(incomplete),
        },
        "scanner_is_not_the_cio": True,
    }


def run_office_cycle_from_manifest(
    root: Path | str,
    manifest: dict[str, Any],
    *,
    change: dict[str, Any],
    evidence_class: str,
    current_regime: dict[str, Any] | None = None,
    deterministic_setup: dict[str, Any] | None = None,
    persist: bool = True,
    max_impact: int = 8,
    graph_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("OFFICE", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SCHEMA}

    trace_id = str(uuid.uuid4())
    steps: list[dict[str, Any]] = []
    sym = str(change.get("symbol") or "")
    rec = get_symbol(manifest, sym) or {"symbol": sym}
    truth = office_truth_snapshot(rec, holdings=[r["symbol"] for r in (manifest.get("securities") or []) if r.get("currently_held")][:50])
    steps.append({"step": "office_truth", "lane": OFFICE_TRUTH, "unconfirmed": truth["unconfirmed"]})

    retrieval = retrieve(
        root, query=str(change.get("question") or f"Is {sym} attractive?"),
        symbol=sym, security_guid=rec.get("security_guid"),
    )
    steps.append({"step": "retrieve_cognition", "lane": INSTITUTIONAL_COGNITION, "used": retrieval.get("used_knowledge_ids")})

    canon = reason_with_canon(root, question=str(change.get("question") or f"Is {sym} attractive?"), symbol=sym)
    steps.append({"step": "canon", "disagreement": canon.get("disagreement_visible"), "n": len(canon.get("views") or [])})

    material = bool(rec.get("currently_held") or rec.get("watch_directive_active") or (change.get("materiality") or 0) >= 0.5)
    theories = competing_theories(
        root,
        question=str(change.get("question") or f"thesis for {sym}"),
        authoring_agent="cio_office",
        evidence_class=cls,
        affected_entities=[sym] if sym else [],
        held_or_watched=bool(rec.get("currently_held") or rec.get("watch_directive_active")),
        security_guid=rec.get("security_guid"),
        material=material,
        persist=persist,
        statements={
            "base": {
                "statement": f"Current price of {sym} already reflects known information; edge is unproven.",
                "mechanism": "no_edge_humility",
                "scope": "security",
                "canonical_framework_refs": ["malkiel_random_walk"],
                "falsification_conditions": ["A documented, leakage-aware edge appears with holdout evidence"],
            },
            "bull": {
                "statement": f"{sym} is under-discounting a durable driver.",
                "mechanism": "expected_return_driver",
                "scope": "security",
                "canonical_framework_refs": ["ilmanen_expected_returns"],
                "falsification_conditions": ["Drivers reverse or were already in the multiple"],
            },
            "bear": {
                "statement": f"{sym} is priced for a cycle that is turning against holders.",
                "mechanism": "cycle_risk",
                "scope": "security",
                "canonical_framework_refs": ["marks_most_important_thing"],
                "falsification_conditions": ["Cycle evidence improves while valuation remains conservative"],
            },
            "alternative": {
                "statement": f"The interesting opportunity linked to {sym} is outside the current watchlist.",
                "mechanism": "discovery",
                "scope": "theme",
                "canonical_framework_refs": ["lo_adaptive_markets"],
                "falsification_conditions": ["No related universe member has a sourced edge either"],
            },
        },
    )
    steps.append({"step": "competing_theories", "ok": theories.get("ok"), "roles": theories.get("roles")})

    analogues = compare_regimes(root, current_regime or {})
    steps.append({"step": "historical_regimes", "n": analogues.get("n")})

    desk = build_sector_theses(root, manifest, persist=persist, focus_symbol=sym or None)
    inherited = inherit_sector_context(manifest, sym, desk)
    steps.append({"step": "sector_desk", "inherited_n": len(inherited.get("inherited") or []), "discovered": inherited.get("discovered_related_tickers")[:8]})

    impact = impact_candidates(
        manifest, sym, evidence_class=cls, max_n=max_impact,
        graph_profiles=graph_profiles,
    ) if rec.get("symbol") else {"n": 0, "candidates": [], "incomplete_candidates": []}
    steps.append({
        "step": "universe_discovery",
        "n": impact.get("n"),
        "related_n": impact.get("related_n"),
        "beyond_holdings": True,
        "not_a_trade": True,
    })

    synthesis = _recommend(rec, theories, retrieval, canon, impact)
    if deterministic_setup and deterministic_setup.get("recommendation") and synthesis["recommendation"] != deterministic_setup.get("recommendation"):
        synthesis = dict(synthesis)
        synthesis["recommendation"] = "DISAGREE_DETERMINISTIC_SETUP"
        synthesis["deterministic_setup"] = deterministic_setup.get("recommendation")
    steps.append({"step": "cio_synthesis", "recommendation": synthesis["recommendation"]})

    influence_trace = {
        "office_truth": {k: truth[k] for k in ("symbol", "currently_held", "current_research_tier", "unconfirmed")},
        "memory_used": retrieval.get("used_knowledge_ids"),
        "canon_used": [v.get("knowledge_id") for v in (canon.get("views") or [])],
        "theories": {k: (v or {}).get("theory_id") for k, v in (theories.get("theories") or {}).items()},
        "analogues": [a.get("episode_id") for a in (analogues.get("analogues") or [])],
        "sector": [r.get("sector_thesis_id") for r in (inherited.get("inherited") or [])],
        "impact_symbols": [c.get("symbol") for c in (impact.get("candidates") or [])],
    }
    return {
        "schema": SCHEMA,
        "trace_id": trace_id,
        "as_of": _now(),
        "evidence_class": cls,
        "symbol": rec.get("symbol"),
        "office_truth": truth,
        "retrieval": retrieval,
        "canon": canon,
        "theories": theories,
        "analogues": analogues,
        "sector": inherited,
        "impact": {"n": impact.get("n"), "candidates": impact.get("candidates"), "incomplete_n": len(impact.get("incomplete_candidates") or [])},
        "synthesis": synthesis,
        "influence_trace": influence_trace,
        "steps": steps,
        "lineage": [s["step"] for s in steps],
        "scanner_is_not_the_cio": True,
        "autonomous_trading": False,
        "execution_separately_authorized": True,
        "memory_behavior_influence": MBI,
        "advisory_influence_promotion": ADVISORY_INFLUENCE_PROMOTION,
        "cognition_mutated_office_truth": COGNITION_MAY_MUTATE_OFFICE_TRUTH,
        "mutated_office_truth": False,
        "always_on_timer": False,
        "authority": AUTHORITY,
        "financial_action": False,
        "activated": False,
    }


def run_office_cycle(
    root: Path | str,
    *,
    change: dict[str, Any],
    evidence_class: str,
    current_regime: dict[str, Any] | None = None,
    deterministic_setup: dict[str, Any] | None = None,
    persist: bool = True,
    max_impact: int = 8,
) -> dict[str, Any]:
    """Live-root entry. Does not write CURRENT when persist=False."""
    from scripts.lib.transferson_universe import collect_live_sources
    sources = collect_live_sources(root=root)
    manifest = load_universe(root=root, sources=sources)
    return run_office_cycle_from_manifest(
        root, manifest, change=change, evidence_class=evidence_class,
        current_regime=current_regime, deterministic_setup=deterministic_setup,
        persist=persist, max_impact=max_impact,
        graph_profiles=sources.get("graph_profiles"),
    )


def unattended_week_capability() -> dict[str, Any]:
    """Honest answer to the final acceptance question."""
    return {
        "schema": "UnattendedWeekCapability@v1",
        "question": "If the operator disappeared for a week, would this office continue studying, updating beliefs, discovering, challenging itself, remembering, and return with a coherent briefing?",
        "answer": "NO",
        "reasons": [
            "OFFICE activation is OFF; no unattended timer is authorized",
            "R17 natural checkpoint/outcome loop remains blocked",
            "R19 has zero deterministically joinable decision-outcome holdout rows",
            "lawful canon full text is NOT_AVAILABLE; doctrine is operator-derived questions only",
            "MEMORY_BEHAVIOR_INFLUENCE remains 0; cognition is retrieved but not promoted",
            "Hermes remains a bounded challenger, not a continuously theorizing department on this branch",
        ],
        "what_is_now_executable_in_shadow": [
            "reference-brain audit with honest SOURCE_* flags",
            "shared knowledge fabric retrieval receipts",
            "canon questions without deterministic gates",
            "InvestmentTheory@v1 competing set with falsification",
            "sector thesis inheritance",
            "regime analogue comparison requiring differences",
            "CIO synthesis that can disagree with a scanner",
            "restart-stable theory/sector jsonl under a given root",
        ],
        "deterministic_incubator_role": "sensor and OFFICE_TRUTH engine under the CIO, not the CIO",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "activated": False,
    }
