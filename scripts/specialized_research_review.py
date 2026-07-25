#!/usr/bin/env python3
"""Bounded independent critics for specialized research due-diligence packets.

Supports proposal, Defense, sector, industry and Watch research packets. Critics
receive the exact immutable deterministic packet and a curated evidence subset.
They may identify contradictions, missing/stale evidence or methodology risk;
they may never change deterministic state, create mechanics, grant admission,
activate a recommendation, write proposal state or invoke paid/execution lanes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

REVIEW_CONTRACT = "specialized-research-independent-review-v1"
VERDICTS = {"PASS", "CAUTION", "REJECT"}
ARRAY_KEYS = (
    "contradictions", "missing_evidence", "stale_sources",
    "methodology_objections", "questions", "evidence_citations",
)

_SYSTEM = (
    "You are an independent adversarial reviewer of a deterministic specialized "
    "research packet. The deterministic state, source ledger, arithmetic and "
    "downstream authority are sovereign. You never create or repair data, entry, "
    "stop, target, size, allocation, sector state, industry mapping, recommendation "
    "or proposal mechanics. You never convert BLOCKED or REVIEW_REQUIRED into "
    "permission. Use only the packet. Reply with STRICT JSON exactly: "
    '{"verdict":"PASS|CAUTION|REJECT","summary":"<=60 words",'
    '"contradictions":[],"missing_evidence":[],"stale_sources":[],'
    '"methodology_objections":[],"questions":[],"evidence_citations":[]}'
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_review_packet(diligence: dict, *, evidence: dict | None = None) -> dict:
    """Curate a minimum-sufficient immutable packet for every provider family."""
    return {
        "contract": REVIEW_CONTRACT,
        "due_diligence_contract": diligence.get("contract_version"),
        "domain": diligence.get("domain"),
        "subject": diligence.get("subject"),
        "packet_hash": diligence.get("packet_hash"),
        "deterministic_state": diligence.get("deterministic_state"),
        "hard_failures": diligence.get("hard_failures") or [],
        "warnings": diligence.get("warnings") or [],
        "checks": diligence.get("checks") or [],
        "source_ledger": diligence.get("sources") or [],
        "coverage": diligence.get("coverage") or {},
        "downstream": diligence.get("downstream") or {},
        "curated_evidence": evidence if evidence is not None else diligence.get("evidence") or {},
        "authority": {
            "deterministic_state_is_sovereign": True,
            "critic_may_create_or_repair_evidence": False,
            "critic_may_create_or_repair_mechanics": False,
            "critic_may_activate_recommendation": False,
            "critic_may_write_proposal_state": False,
            "critic_may_call_paid_lane": False,
            "critic_may_execute": False,
        },
        "excluded_anchoring_inputs": [
            "other critic verdicts", "CIO conclusion", "Street recommendation",
            "Hermes rank", "social popularity", "operator desired outcome",
        ],
    }


def _prompt(packet: dict) -> str:
    return (
        "Review this exact specialized research packet adversarially. Cite packet "
        "field paths in evidence_citations. A deterministic block is not appealable.\n\n"
        + json.dumps(packet, indent=1, default=str)
    )


def _parse(raw: str) -> dict | None:
    text = str(raw or "").strip()
    if "```" in text:
        text = text.split("```", 1)[1].lstrip("json").strip()
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        parsed = json.loads(text[start:end])
    except Exception:
        return None
    if str(parsed.get("verdict") or "").upper() not in VERDICTS:
        return None
    if not isinstance(parsed.get("summary"), str):
        return None
    for key in ARRAY_KEYS:
        if not isinstance(parsed.get(key), list):
            return None
    parsed["verdict"] = str(parsed["verdict"]).upper()
    parsed["summary"] = parsed["summary"][:500]
    return parsed


def _base(lane: str, family: str, packet: dict) -> dict:
    return {
        "contract": REVIEW_CONTRACT,
        "lane": lane,
        "provider_family": family,
        "model": None,
        "verdict": "UNAVAILABLE",
        "packet_hash_reviewed": packet.get("packet_hash"),
        "reviewed_at": _now(),
        "summary": "",
        "contradictions": [],
        "missing_evidence": [],
        "stale_sources": [],
        "methodology_objections": [],
        "questions": [],
        "evidence_citations": [],
        "may_override": False,
    }


def _finish(base: dict, parsed: dict | None, error: str | None = None) -> dict:
    if parsed is None:
        base["error"] = error or "unparseable strict-schema response"
        return base
    for key in ("verdict", "summary", *ARRAY_KEYS):
        base[key] = parsed[key]
    return base


def run_local(diligence: dict, *, evidence: dict | None = None) -> dict:
    packet = build_review_packet(diligence, evidence=evidence)
    base = _base("local", "LOCAL_OLLAMA", packet)
    if not (diligence.get("model_oversight") or {}).get("allowed"):
        base["error"] = "deterministic packet does not permit model oversight"
        return base
    import local_llm
    result = local_llm.generate_local_only(_prompt(packet), system=_SYSTEM)
    if not result.get("ok"):
        base["error"] = result.get("error") or "local lane unavailable"
        return base
    base["model"] = result.get("model")
    return _finish(base, _parse(result.get("text")), "local model returned non-schema text")


def run_oauth(lane: str, diligence: dict, *, evidence: dict | None = None) -> dict:
    if lane not in {"grok", "chatgpt"}:
        raise ValueError("OAuth lane must be grok or chatgpt")
    packet = build_review_packet(diligence, evidence=evidence)
    family = {"grok": "XAI", "chatgpt": "OPENAI"}[lane]
    base = _base(lane, family, packet)
    if not (diligence.get("model_oversight") or {}).get("allowed"):
        base["error"] = "deterministic packet does not permit model oversight"
        return base
    import llm_lane
    try:
        if not llm_lane.available(lane):
            base["error"] = f"{lane} OAuth lane unavailable"
            return base
        raw = llm_lane.generate(_SYSTEM + "\n\n" + _prompt(packet), lane=lane, timeout=150)
        text = raw.get("text") if isinstance(raw, dict) else str(raw)
        base["model"] = raw.get("model") if isinstance(raw, dict) else lane
        return _finish(base, _parse(text), f"{lane} returned non-schema text")
    except Exception as exc:
        base["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return base


def run_free_reviews(
    diligence: dict,
    *,
    evidence: dict | None = None,
    lanes: tuple[str, ...] = ("local", "grok", "chatgpt"),
) -> dict:
    """Run only requested free lanes. BLOCKED packets make zero provider calls."""
    reviews = {}
    if not (diligence.get("model_oversight") or {}).get("allowed"):
        return {
            "_meta": {
                "completed": 0,
                "independent_families": 0,
                "consensus_possible": False,
                "skipped": "deterministic packet blocks model oversight",
                "paid_lane_called": False,
                "reviewed_at": _now(),
            }
        }
    if "local" in lanes:
        reviews["local"] = run_local(diligence, evidence=evidence)
    if "grok" in lanes:
        reviews["grok"] = run_oauth("grok", diligence, evidence=evidence)
    if "chatgpt" in lanes:
        reviews["chatgpt"] = run_oauth("chatgpt", diligence, evidence=evidence)
    completed = [review for review in reviews.values()
                 if review.get("verdict") != "UNAVAILABLE"]
    families = {review.get("provider_family") for review in completed
                if review.get("provider_family")}
    reviews["_meta"] = {
        "completed": len(completed),
        "independent_families": len(families),
        "consensus_possible": len(families) >= 2,
        "single_lane": len(completed) == 1,
        "paid_lane_called": False,
        "reviewed_at": _now(),
    }
    return reviews
