"""R19 additive historical identity/join projection.

Does not rewrite original jsonl rows. Joins are explicit:
DETERMINISTICALLY_JOINABLE | CANDIDATE_JOIN | UNRESOLVED_WITH_REASON.
Ticker matching is never deterministic. Prompt-eval quality is never a
market OutcomeObservation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI
from scripts.lib.cio_institutional_learning import identity_safe_subject
from scripts.lib.ticker_knowledge_graph import entity_guid

SCHEMA = "DecisionJoinProjection@v1"
OBS = "data/cio/outcome_observations.jsonl"
CK = "data/cio/outcome_checkpoints.jsonl"
PERF = "data/cio/model_task_performance.jsonl"
LINEAGE = "data/cio/intelligence_lineages.jsonl"
EVALS = "data/cio/cio_prompt_evals.jsonl"
PLANS = "data/cio/cio_plans.jsonl"
THESES = "data/cio/cio_theses.jsonl"
DISPOSITIONS = "data/cio/decision_dispositions.jsonl"

CHAIN_OBJECTS = (
    "Decision",
    "DecisionIdentity",
    "SecurityIdentity",
    "ThesisVersion",
    "ResearchContext",
    "ExperimentRegistration",
    "OutcomeCheckpoint",
    "OutcomeObservation",
    "EvaluationWindow",
)


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


def _obj(kind: str, *, status: str, reason: str | None = None, **fields: Any) -> dict[str, Any]:
    out = {"object": kind, "status": status, **fields}
    if reason:
        out["reason"] = reason
    return out


def _unresolved(kind: str, reason: str) -> dict[str, Any]:
    return _obj(kind, status="UNRESOLVED_WITH_REASON", reason=reason)


def _chain(**fields: Any) -> dict[str, Any]:
    decision_id = fields.get("decision_id")
    security_guid = fields.get("security_guid")
    ticker_alias = fields.get("ticker_alias")
    thesis_version_id = fields.get("thesis_version_id")
    decision_timestamp = fields.get("decision_timestamp")
    objects = {
        "Decision": _obj(
            "Decision",
            status="PRESENT" if decision_id else "UNRESOLVED_WITH_REASON",
            reason=None if decision_id else "missing_decision_id",
            decision_id=decision_id,
            decision_timestamp=decision_timestamp,
            recommendation=fields.get("recommendation"),
        ) if decision_id else _unresolved("Decision", "missing_decision_id"),
        "DecisionIdentity": _obj(
            "DecisionIdentity",
            status="PRESENT" if decision_id else "UNRESOLVED_WITH_REASON",
            reason=None if decision_id else "missing_decision_id",
            decision_id=decision_id,
        ) if decision_id else _unresolved("DecisionIdentity", "missing_decision_id"),
        "SecurityIdentity": _obj(
            "SecurityIdentity",
            status="PRESENT" if security_guid else "UNRESOLVED_WITH_REASON",
            reason=None if security_guid else "ticker_alias_is_not_security_guid",
            security_guid=security_guid,
            ticker_alias=ticker_alias,
            ticker_guid_is_not_security=True,
        ) if security_guid else _unresolved(
            "SecurityIdentity",
            "no_security_guid_ticker_alias_only" if ticker_alias else "no_security_guid",
        ),
        "ThesisVersion": _obj(
            "ThesisVersion",
            status="PRESENT" if thesis_version_id else "UNRESOLVED_WITH_REASON",
            reason=None if thesis_version_id else "no_thesis_version_on_record",
            thesis_version_id=thesis_version_id,
        ) if thesis_version_id else _unresolved("ThesisVersion", "no_thesis_version_on_record"),
        "ResearchContext": _obj(
            "ResearchContext",
            status="PRESENT" if fields.get("research_watermark") else "UNRESOLVED_WITH_REASON",
            reason=None if fields.get("research_watermark") else "no_research_watermark",
            research_watermark=fields.get("research_watermark"),
            catalyst_guids=fields.get("catalyst_guids") or [],
            sector=fields.get("sector"),
            industry=fields.get("industry"),
            sector_guid=entity_guid("sector", fields.get("sector")) if fields.get("sector") else None,
            industry_guid=entity_guid("industry", fields.get("industry")) if fields.get("industry") else None,
        ) if fields.get("research_watermark") or fields.get("sector") or fields.get("industry") or fields.get("catalyst_guids")
        else _unresolved("ResearchContext", "no_research_context"),
        "ExperimentRegistration": _obj(
            "ExperimentRegistration",
            status="PRESENT" if fields.get("hypothesis_id") else "UNRESOLVED_WITH_REASON",
            reason=None if fields.get("hypothesis_id") else "not_preregistered",
            hypothesis_id=fields.get("hypothesis_id"),
            preregistration_timestamp=fields.get("preregistration_timestamp"),
        ) if fields.get("hypothesis_id") else _unresolved("ExperimentRegistration", "not_preregistered"),
        "OutcomeCheckpoint": _obj(
            "OutcomeCheckpoint",
            status="PRESENT" if fields.get("checkpoint_id") else "UNRESOLVED_WITH_REASON",
            reason=None if fields.get("checkpoint_id") else "no_checkpoint",
            checkpoint_id=fields.get("checkpoint_id"),
        ) if fields.get("checkpoint_id") else _unresolved("OutcomeCheckpoint", "no_checkpoint"),
        "OutcomeObservation": _obj(
            "OutcomeObservation",
            status="PRESENT" if fields.get("outcome_id") else "UNRESOLVED_WITH_REASON",
            reason=None if fields.get("outcome_id") else "no_outcome_observation",
            outcome_id=fields.get("outcome_id"),
        ) if fields.get("outcome_id") else _unresolved("OutcomeObservation", "no_outcome_observation"),
        "EvaluationWindow": _obj(
            "EvaluationWindow",
            status="PRESENT" if fields.get("holdout_window") or fields.get("evaluation_horizon") else "UNRESOLVED_WITH_REASON",
            reason=None if (fields.get("holdout_window") or fields.get("evaluation_horizon")) else "no_holdout_or_horizon",
            training_window=fields.get("training_window"),
            holdout_window=fields.get("holdout_window"),
            evaluation_horizon=fields.get("evaluation_horizon"),
        ) if fields.get("holdout_window") or fields.get("evaluation_horizon") or fields.get("training_window")
        else _unresolved("EvaluationWindow", "no_holdout_or_horizon"),
    }
    scored = bool(
        fields.get("join_class") == "DETERMINISTICALLY_JOINABLE"
        and fields.get("outcome_id")
        and fields.get("checkpoint_id")
        and decision_id
        and security_guid
    )
    return {
        "decision_id": decision_id,
        "security_guid": security_guid,
        "ticker_alias": ticker_alias,
        "thesis_version_id": thesis_version_id,
        "decision_timestamp": decision_timestamp,
        "research_watermark": fields.get("research_watermark"),
        "catalyst_guids": fields.get("catalyst_guids") or [],
        "sector": fields.get("sector"),
        "industry": fields.get("industry"),
        "sector_guid": objects["ResearchContext"].get("sector_guid"),
        "industry_guid": objects["ResearchContext"].get("industry_guid"),
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
        "chain_complete_for_scored_learning": scored,
        "objects": objects,
        "objective_score": fields.get("objective_score"),
        "recommendation": fields.get("recommendation"),
    }


def _reconstruct_plans(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Replay PLAN_CREATED then non-empty PLAN_UPDATED fields. Additive; originals untouched."""
    plans: dict[str, dict[str, Any]] = {}
    for ev in events:
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        pid = payload.get("plan_id") or ev.get("plan_id")
        if not pid:
            continue
        cur = plans.setdefault(str(pid), {"plan_id": str(pid), "_events": 0})
        cur["_events"] += 1
        et = str(ev.get("event_type") or "")
        if et == "PLAN_CREATED" or not cur.get("created_ts"):
            for key, val in payload.items():
                if key not in cur or cur.get(key) in (None, [], {}, ""):
                    cur[key] = val
            cur["_created_event_id"] = ev.get("event_id")
            cur["_created_occurred_at"] = ev.get("occurred_at")
        else:
            for key, val in payload.items():
                if val not in (None, [], {}, ""):
                    cur[key] = val
    return plans


def _latest_theses(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for ev in events:
        payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
        tid = payload.get("thesis_id") or ev.get("thesis_id")
        if not tid:
            continue
        latest[str(tid)] = {
            **payload,
            "_event_id": ev.get("event_id"),
            "_occurred_at": ev.get("occurred_at"),
            "_actor_id": ev.get("actor_id"),
        }
    return latest


def project_joins(root: Path | str) -> dict[str, Any]:
    """Additive projection. Original files are not mutated."""
    root_p = Path(root)
    observations = _jsonl(root_p / OBS)
    checkpoints = _jsonl(root_p / CK)
    performance = _jsonl(root_p / PERF)
    lineages = _jsonl(root_p / LINEAGE)
    evals = _jsonl(root_p / EVALS)
    plan_events = _jsonl(root_p / PLANS)
    thesis_events = _jsonl(root_p / THESES)
    dispositions = _jsonl(root_p / DISPOSITIONS)
    plans = _reconstruct_plans(plan_events)
    theses = _latest_theses(thesis_events)
    ck_by_dec = {r.get("decision_id"): r for r in checkpoints if r.get("decision_id")}
    rows: list[dict[str, Any]] = []
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
                recommendation=(ck.get("original_decision_state") or {}).get("recommendation"),
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
            recommendation=(ck.get("original_decision_state") or {}).get("recommendation"),
            evidence_class="HISTORICAL_REPLAY",
            join_class="UNRESOLVED_WITH_REASON",
            join_reason="checkpoint_without_matching_observation",
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
            objective_score=perf.get("objective_score"),
        )
        rec["chain_complete_for_scored_learning"] = False
        rec["not_a_decision_outcome_pair"] = True
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

    for disp in dispositions:
        did = disp.get("decision_id")
        add(_chain(
            decision_id=did,
            ticker_alias=disp.get("symbol"),
            decision_timestamp=disp.get("occurred_at"),
            recommendation=disp.get("action"),
            evidence_class="HISTORICAL_REPLAY",
            join_class="CANDIDATE_JOIN",
            join_reason="disposition_ticker_alias_only_no_outcome",
            join_provenance=[{"method": "exact_decision_id", "store": DISPOSITIONS, "key": did, "forbidden_for_scored_learning": True}],
        ))

    eval_by_plan: dict[str, list[dict[str, Any]]] = {}
    for ev in evals:
        pid = ev.get("plan_id")
        if pid:
            eval_by_plan.setdefault(str(pid), []).append(ev)

    for pid, plan in plans.items():
        evs = eval_by_plan.get(pid) or []
        symbols = plan.get("symbols") if isinstance(plan.get("symbols"), list) else []
        ticker = str(symbols[0]).upper() if symbols else None
        thesis_id = None
        for ev in evs:
            if ev.get("thesis_version"):
                thesis_id = ev.get("thesis_version")
                break
        if not thesis_id:
            thesis_id = plan.get("thesis_version")
        watermark = plan.get("evidence_refs") or plan.get("hermes_research_id")
        if evs:
            for ev in evs:
                add(_chain(
                    decision_id=pid,
                    ticker_alias=ticker,
                    thesis_version_id=ev.get("thesis_version") or thesis_id,
                    decision_timestamp=plan.get("created_ts") or plan.get("_created_occurred_at"),
                    research_watermark=str(watermark or ev.get("prompt_version") or ""),
                    model_prompt_code_version=ev.get("prompt_version"),
                    recommendation=plan.get("recommendation"),
                    evidence_class="HISTORICAL_REPLAY",
                    join_class="CANDIDATE_JOIN",
                    join_reason="exact_plan_id_prompt_eval_not_outcome_observation",
                    join_provenance=[{
                        "method": "exact_plan_id",
                        "left": PLANS,
                        "right": EVALS,
                        "key": pid,
                        "forbidden_for_scored_learning": True,
                        "note": "prompt quality is not a market OutcomeObservation",
                    }],
                    objective_score=(ev.get("quality") or {}).get("total") if isinstance(ev.get("quality"), dict) else None,
                ))
        else:
            add(_chain(
                decision_id=pid,
                ticker_alias=ticker,
                thesis_version_id=thesis_id,
                decision_timestamp=plan.get("created_ts") or plan.get("_created_occurred_at"),
                research_watermark=str(watermark or ""),
                recommendation=plan.get("recommendation"),
                evidence_class="HISTORICAL_REPLAY",
                join_class="CANDIDATE_JOIN",
                join_reason="plan_without_prompt_eval_or_outcome",
                join_provenance=[{"method": "plan_id", "store": PLANS, "key": pid, "eval_hit": False}],
            ))

    unmatched_evals = [e for e in evals if e.get("plan_id") and str(e.get("plan_id")) not in plans]
    for ev in unmatched_evals:
        add(_chain(
            decision_id=ev.get("plan_id"),
            thesis_version_id=ev.get("thesis_version"),
            decision_timestamp=ev.get("ts"),
            model_prompt_code_version=ev.get("prompt_version"),
            evidence_class="HISTORICAL_REPLAY",
            join_class="UNRESOLVED_WITH_REASON",
            join_reason="prompt_eval_plan_id_not_in_plan_store",
            join_provenance=[{"method": "plan_id_lookup", "left": EVALS, "right": PLANS, "key": ev.get("plan_id"), "hit": False}],
        ))

    for thesis in theses.values():
        linked_plans = thesis.get("linked_plan_ids") or []
        if linked_plans:
            continue
        add(_chain(
            decision_id=None,
            ticker_alias=(thesis.get("linked_symbols") or [None])[0] if thesis.get("linked_symbols") else thesis.get("symbol"),
            thesis_version_id=thesis.get("thesis_version") or (
                f"{thesis.get('thesis_id')}@v{thesis.get('version')}" if thesis.get("thesis_id") and thesis.get("version") is not None else None
            ),
            decision_timestamp=thesis.get("published_ts") or thesis.get("_occurred_at"),
            research_watermark=str(thesis.get("evidence_for") or thesis.get("evidence_refs") or thesis.get("_event_id") or ""),
            evidence_class="HISTORICAL_REPLAY",
            join_class="CANDIDATE_JOIN",
            join_reason="thesis_version_without_linked_decision",
            join_provenance=[{"method": "thesis_id+version", "store": THESES, "key": thesis.get("thesis_id"), "forbidden_for_scored_learning": True}],
        ))

    det = [r for r in rows if r["join_class"] == "DETERMINISTICALLY_JOINABLE"]
    cand = [r for r in rows if r["join_class"] == "CANDIDATE_JOIN"]
    unres = [r for r in rows if r["join_class"] == "UNRESOLVED_WITH_REASON"]
    scored_ok = [r for r in det if r.get("chain_complete_for_scored_learning")]
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "originals_rewritten": False,
        "chain_objects": list(CHAIN_OBJECTS),
        "counts": {
            "DETERMINISTICALLY_JOINABLE": len(det),
            "CANDIDATE_JOIN": len(cand),
            "UNRESOLVED": len(unres),
            "UNRESOLVED_WITH_REASON": len(unres),
            "scored_learning_eligible": len(scored_ok),
            "decision_outcome_pairs": len(scored_ok),
        },
        "unresolved_reasons": {
            k: v for k, v in reasons.items()
            if k not in {"DETERMINISTICALLY_JOINABLE", "CANDIDATE_JOIN", "UNRESOLVED_WITH_REASON"}
        },
        "candidate_joins_forbidden_for_scored_learning": True,
        "rows": rows,
    }
