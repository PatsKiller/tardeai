"""R17 coverage closures: sector/industry/catalyst/market/risk/news/specialists.

Bounded propagation. Shared industry text does not wake the universe.
No execution authority.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.cio_intelligence_fabric import AUTHORITY, MBI, process_observation
from scripts.lib.cio_institutional_learning import identity_safe_subject
from scripts.lib.ticker_knowledge_graph import entity_guid
from scripts.lib.transferson_universe import get_related_by_industry, get_related_by_sector, get_symbol

SCHEMA_BOUNDED = "BoundedProducerImpact@v1"
EXPOSURE_ROLES = {"T0-HOLD", "T0-PROP", "T1-WATCH"}


def bounded_graph_wake(
    manifest: dict[str, Any],
    *,
    origin_symbol: str | None,
    kind: str,
    material: bool,
    max_n: int = 12,
) -> dict[str, Any]:
    """Sector/industry event → exposed names only. Membership is not impact."""
    if not material or not origin_symbol:
        return {
            "schema": SCHEMA_BOUNDED,
            "kind": kind,
            "wake": [],
            "rejected_reason": "NON_MATERIAL_OR_NO_ORIGIN",
            "inferred_from_shared_industry_text": False,
            "authority": AUTHORITY,
        }
    origin = get_symbol(manifest, origin_symbol) or {}
    if kind == "sector":
        related = get_related_by_sector(manifest, origin_symbol).get("related_symbols") or []
    elif kind == "industry":
        related = get_related_by_industry(manifest, origin_symbol).get("related_symbols") or []
    else:
        related = []
    wake, skipped = [], []
    for sym in related:
        rec = get_symbol(manifest, sym) or {}
        exposed = bool(rec.get("currently_held") or rec.get("watch_directive_active") or rec.get("active_proposal"))
        tier = rec.get("current_research_tier")
        if exposed or tier in EXPOSURE_ROLES:
            wake.append({
                "symbol": rec.get("symbol"),
                "subject_guid": identity_safe_subject(rec),
                "tier": tier,
                "reason": "exposed_or_active_thesis",
            })
        else:
            skipped.append({"symbol": rec.get("symbol"), "reason": "membership_without_exposure"})
        if len(wake) >= max_n:
            break
    return {
        "schema": SCHEMA_BOUNDED,
        "kind": kind,
        "origin": origin.get("symbol"),
        "class_entity_guid": entity_guid(kind, origin.get(kind)) if origin.get(kind) else None,
        "wake": wake,
        "skipped_sample": skipped[:20],
        "inferred_from_shared_industry_text": False,
        "not_indiscriminate": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def catalyst_trace(*, source: str, catalyst_guid: str, security: dict[str, Any],
                   cognition_ref: str | None, research_ref: str | None,
                   decision_id: str | None, outcome_id: str | None) -> dict[str, Any]:
    return {
        "schema": "CatalystTrace@v1",
        "source": source,
        "catalyst_guid": catalyst_guid,
        "target_security": {
            "symbol": security.get("symbol"),
            "subject_guid": identity_safe_subject(security),
            "ticker_guid_is_not_security": not bool(identity_safe_subject(security)),
        },
        "cognition_ref": cognition_ref,
        "research_ref": research_ref,
        "decision_id": decision_id,
        "outcome_id": outcome_id,
        "gui_visible": True,
        "outcome_linked": bool(outcome_id or decision_id),
        "authority": AUTHORITY,
        "financial_action": False,
    }


def market_context_bound(*, regime: dict[str, Any] | None, held: list[str],
                         thesis_symbols: list[str], material: bool) -> dict[str, Any]:
    """Macro/rates/vol/seasonality influence context, not a universe wake."""
    eligible = sorted(set(held) | set(thesis_symbols))
    return {
        "schema": "MarketContextPropagation@v1",
        "regime": regime or {},
        "eligible_symbols": eligible[:40],
        "wake_entire_universe": False,
        "material": material,
        "research_gap_only_if_material_and_exposed": True,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def envelope_extras(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """ContextEnvelope projections for previously unwired producers."""
    src = payload or {}
    return {
        "schema": "R17EnvelopeExtras@v1",
        "STOP_ADVISORY": src.get("stop_advisory") or {"status": "OK", "execution": False},
        "WATCH_REENTRY": src.get("watch_reentry") or {"status": "OK"},
        "RISK": src.get("risk") or {"status": "OK", "execution": False},
        "SECTOR": src.get("sector") or {"status": "OK"},
        "INDUSTRY": src.get("industry") or {"status": "OK"},
        "CATALYSTS": src.get("catalysts") or {"status": "OK"},
        "NEWS": src.get("news") or {"status": "OK", "not_truth": True},
        "SEC_PRIMARY": src.get("sec_primary") or {"status": "OK", "not_truth": True},
        "RAG": src.get("rag") or {"status": "OK", "not_truth": True},
        "SPECIALISTS": src.get("specialists") or {
            "maria": {"disagreement_preserved": True},
            "steph": {"disagreement_preserved": True},
            "guardian": {"disagreement_preserved": True},
            "ledger": {"disagreement_preserved": True},
        },
        "gui_is_projection": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def event_research_path(materiality: str) -> dict[str, Any]:
    steps = ["MATERIAL_CHANGE", "ResearchGap", "FREE_FIRST_PENDING", "TickerResearchState", "HERMES", "RAG", "STRUCTURED", "SEARXNG_RESIDUAL"]
    if materiality != "MATERIAL_CHANGE":
        return {"ok": False, "status": "NO_EVENT", "steps": steps, "fired": False}
    return {
        "ok": True,
        "status": "PATH_ARMED",
        "steps": steps,
        "searx_residual_only": True,
        "paid_dispatch": False,
        "authority": AUTHORITY,
    }


def process_sector_observation(root, observation: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    """Reuse fabric process_observation. No second bus."""
    observation = dict(observation)
    observation.setdefault("source_domain", "sector_rotation")
    observation.setdefault("entity_type", "sector")
    return process_observation(root, observation, **kwargs)
