"""R19 additive historical identity/join projection.

Does not rewrite original jsonl rows. Joins are explicit:
DETERMINISTICALLY_JOINABLE | CANDIDATE_JOIN | UNRESOLVED_WITH_REASON.
Ticker matching is never deterministic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI
from scripts.lib.cio_institutional_learning import identity_safe_subject

SCHEMA = "DecisionJoinProjection@v1"
OBS = "data/cio/outcome_observations.jsonl"
CK = "data/cio/outcome_checkpoints.jsonl"
PERF = "data/cio/model_task_performance.jsonl"
LINEAGE = "data/cio/intelligence_lineages.jsonl"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _chain(**fields: Any) -> dict[str, Any]:
    return {
        "decision_id": fields.get("decision_id"),
        "security_guid": fields.get("security_guid"),
        "ticker_alias": fields.get("ticker_alias"),
        "thesis_version_id": fields.get("thesis_version_id"),
        "decision_timestamp": fields.get("decision_timestamp"),
        "research_watermark": fields.get("research_watermark"),
        "catalyst_guids": fields.get("catalyst_guids") or [],
        "sector": fields.get("sector"),
        "industry": fields.get("industry"),
        "hypothesis_id": fields.get("hypothesis_id"),
        "preregistration_timestamp": fields.get("preregistration_timestamp"),
        "training_window": fields.get("training_window"),
        "holdout_window": fields.get("holdout_window"),
        "evaluation_horizon": fields.get("evaluation_horizon"),
        "outcome_id": fields.get("outcome_id"),
        "checkpoint_id": fields.get("checkpoint_id"),
        "model_prompt_code_version": fields.get("model_prompt_code_version"),
        "evidence_class": fields.get("evidence_class"),
        "join_class": fields.get("join_class"),
        "join_reason": fields.get("join_reason"),
        "join_provenance": fields.get("join_provenance") or [],
        "ticker_guid_is_not_security": True,
    }


def project_joins(root: Path | str) -> dict[str, Any]:
    """Additive projection. Original files are not mutated."""
    root_p = Path(root)
    observations = _jsonl(root_p / OBS)
    checkpoints = _jsonl(root_p / CK)
    performance = _jsonl(root_p / PERF)
    lineages = _jsonl(root_p / LINEAGE)
    ck_by_dec = {r.get("decision_id"): r for r in checkpoints if r.get("decision_id")}
    rows = []
    reasons: dict[str, int] = {}

    def add(row: dict[str, Any]) -> None:
        rows.append(row)
        reasons[row["join_class"]] = reasons.get(row["join_class"], 0) + 1
        if row["join_class"] == "UNRESOLVED_WITH_REASON":
            reasons[row["join_reason"]] = reasons.get(row["join_reason"], 0) + 1

    for obs in observations:
        did = obs.get("decision_id")
        ck = ck_by_dec.get(did)
        sg = identity_safe_subject(obs) or (identity_safe_subject(ck) if ck else None)
        if ck and did and sg:
            add(_chain(
                decision_id=did,
                security_guid=sg,
                outcome_id=obs.get("outcome_id"),
                checkpoint_id=ck.get("checkpoint_id"),
                decision_timestamp=(ck.get("original_decision_state") or {}).get("as_of") or obs.get("source_as_of"),
                evaluation_horizon=obs.get("horizon") or ck.get("horizon"),
                model_prompt_code_version=ck.get("runtime_source_sha"),
                evidence_class="HISTORICAL_REPLAY",
                join_class="DETERMINISTICALLY_JOINABLE",
                join_reason="exact_decision_id_and_security_guid",
                join_provenance=[{"method": "exact_decision_id", "left": OBS, "right": CK, "key": did}],
            ))
        elif ck and did:
            add(_chain(
                decision_id=did,
                outcome_id=obs.get("outcome_id"),
                checkpoint_id=ck.get("checkpoint_id"),
                decision_timestamp=(ck.get("original_decision_state") or {}).get("as_of") or obs.get("source_as_of"),
                evidence_class="HISTORICAL_REPLAY",
                join_class="UNRESOLVED_WITH_REASON",
                join_reason="deterministic_id_join_but_no_security_guid",
                join_provenance=[{"method": "exact_decision_id", "left": OBS, "right": CK, "key": did, "security_guid": None}],
            ))
        else:
            add(_chain(
                decision_id=did,
                outcome_id=obs.get("outcome_id"),
                security_guid=sg,
                decision_timestamp=obs.get("source_as_of") or obs.get("observed_at"),
                evaluation_horizon=obs.get("horizon"),
                evidence_class="HISTORICAL_REPLAY",
                join_class="UNRESOLVED_WITH_REASON",
                join_reason="observation_decision_id_not_in_checkpoints",
                join_provenance=[{"method": "decision_id_lookup", "left": OBS, "right": CK, "key": did, "hit": False}],
            ))

    for ck in checkpoints:
        did = ck.get("decision_id")
        if any(r.get("checkpoint_id") == ck.get("checkpoint_id") for r in rows):
            continue
        sg = identity_safe_subject(ck)
        add(_chain(
            decision_id=did,
            checkpoint_id=ck.get("checkpoint_id"),
            security_guid=sg,
            ticker_alias=(ck.get("original_decision_state") or {}).get("symbol"),
            decision_timestamp=(ck.get("original_decision_state") or {}).get("as_of"),
            evaluation_horizon=ck.get("horizon"),
            model_prompt_code_version=ck.get("runtime_source_sha"),
            evidence_class="HISTORICAL_REPLAY",
            join_class="UNRESOLVED_WITH_REASON" if not sg else "UNRESOLVED_WITH_REASON",
            join_reason="checkpoint_without_matching_observation" if not sg else "checkpoint_without_matching_observation",
            join_provenance=[{"method": "checkpoint_orphan", "store": CK, "key": did}],
        ))

    for perf in performance:
        pid = "|".join((str(perf.get("process_id") or ""), str(perf.get("recorded_at") or ""), str(perf.get("model_id") or "")))
        rec = _chain(
            decision_id=pid,
            decision_timestamp=perf.get("recorded_at"),
            model_prompt_code_version=perf.get("prompt_version"),
            evidence_class=perf.get("evidence_class") or "GOLDEN_SHADOW",
            join_class="DETERMINISTICALLY_JOINABLE",
            join_reason="self_identified_performance_event",
            join_provenance=[{"method": "process_id+recorded_at+model_id", "store": PERF, "key": pid}],
        )
        rec["objective_score"] = perf.get("objective_score")
        add(rec)

    for lin in lineages:
        add(_chain(
            decision_id=lin.get("lineage_id"),
            ticker_alias=lin.get("symbol"),
            research_watermark=str(lin.get("research_result_ids") or []),
            decision_timestamp=lin.get("at"),
            evidence_class="HISTORICAL_REPLAY",
            join_class="CANDIDATE_JOIN",
            join_reason="ticker_alias_only_no_security_guid",
            join_provenance=[{"method": "symbol_alias", "store": LINEAGE, "forbidden_for_scored_learning": True}],
        ))

    det = [r for r in rows if r["join_class"] == "DETERMINISTICALLY_JOINABLE"]
    cand = [r for r in rows if r["join_class"] == "CANDIDATE_JOIN"]
    unres = [r for r in rows if r["join_class"] == "UNRESOLVED_WITH_REASON"]
    scored_ok = [r for r in det if r.get("security_guid") or r.get("join_reason") == "self_identified_performance_event"]
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "originals_rewritten": False,
        "counts": {
            "DETERMINISTICALLY_JOINABLE": len(det),
            "CANDIDATE_JOIN": len(cand),
            "UNRESOLVED_WITH_REASON": len(unres),
            "scored_learning_eligible": len(scored_ok),
        },
        "unresolved_reasons": {k: v for k, v in reasons.items() if k not in {"DETERMINISTICALLY_JOINABLE", "CANDIDATE_JOIN", "UNRESOLVED_WITH_REASON"}},
        "candidate_joins_forbidden_for_scored_learning": True,
        "rows": rows,
    }
