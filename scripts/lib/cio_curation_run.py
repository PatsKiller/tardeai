"""CurationRun@v1 — governed LLM curation lineage without fake progress.

A MATERIAL HermesCurationSummary version is created only for accepted material
cognitive change. Rejected/failed runs stay in audit history and never become
current belief. Challenger results stay separate. Corrected evidence supersedes
without deleting history.

Never persist private chain-of-thought. MEMORY_BEHAVIOR_INFLUENCE=0.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.cio_intelligence_fabric import FORBIDDEN_TRUTH_KEYS, _strip_truth
from scripts.lib.hermes_curation_summary import KIND_BASELINE, KIND_MATERIAL, build_summary
from scripts.lib.security_identity import normalize_symbol

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CurationRun@v1"
PATH = "data/cio/curation_runs.jsonl"
CHALLENGER_PATH = "data/cio/curation_challenger_runs.jsonl"
THESIS_LINK_PATH = "data/cio/curation_thesis_links.jsonl"

LLM_STATES = (
    "NO_NEW_INFO",
    "FREE_RESOLVED",
    "LLM_ELIGIBLE",
    "CONFLICT_REVIEW_ELIGIBLE",
    "DEEP_REVIEW_ELIGIBLE",
)
COT_KEYS = (
    "chain_of_thought",
    "cot",
    "reasoning_content",
    "private_reasoning",
    "thinking",
    "hidden_reasoning",
)
LADDER = (
    "DETERMINISTIC",
    "FAST",
    "FAST_THINK",
    "CHALLENGER",
    "PRO",
    "PRO_THINK",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


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


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_UN)


def strip_private_reasoning(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    for key in COT_KEYS:
        out.pop(key, None)
    return _strip_truth(out)


def model_ladder(*, contradiction: bool = False, deep_review: bool = False, challenger: bool = False, material_evidence: bool = False) -> str:
    """PRO is never bulk default."""
    if not material_evidence and not contradiction and not deep_review:
        return "DETERMINISTIC"
    if deep_review:
        return "PRO_THINK" if contradiction else "PRO"
    if challenger:
        return "CHALLENGER"
    if contradiction:
        return "FAST_THINK"
    return "FAST"


def curation_dedupe_key(
    *,
    security_guid: str | None,
    prior_curation_version: int | None,
    evidence_delta_hash: str,
    prompt_version: str,
    task_type: str,
) -> str:
    return _sha({
        "security_guid": security_guid,
        "prior_curation_version": int(prior_curation_version or 0),
        "evidence_delta_hash": evidence_delta_hash,
        "prompt_version": prompt_version,
        "task_type": task_type,
    })[:32]


def llm_eligibility(*, free_first: dict[str, Any] | None = None, contradiction: bool = False, deep_review: bool = False) -> str:
    if deep_review:
        return "DEEP_REVIEW_ELIGIBLE"
    if contradiction:
        return "CONFLICT_REVIEW_ELIGIBLE"
    if not free_first:
        return "NO_NEW_INFO"
    if free_first.get("unresolved"):
        return "LLM_ELIGIBLE"
    if free_first.get("resolved") and free_first.get("new_evidence"):
        return "FREE_RESOLVED"
    return "NO_NEW_INFO"


def critique_before_memory(run: dict[str, Any]) -> dict[str, Any]:
    """No LLM JSON enters durable memory merely because it parsed."""
    checks = {
        "schema_valid": bool(run.get("schema_valid")),
        "evidence_refs": bool(run.get("input_evidence_refs")),
        "source_freshness": str(run.get("freshness") or run.get("source_freshness") or "").upper() in {"FRESH", "OK", ""},
        "contradiction_check": run.get("contradiction_checked", True) is True,
        "critique": str(run.get("critique_verdict") or "").upper() in {"ACCEPT", "ACCEPTED", "PASS"},
        "provenance": bool(run.get("process_id") and run.get("executed_policy") and run.get("model_id")),
        "secret_scan": not any(k in json.dumps(run, default=str).lower() for k in ("api_key", "password", "2fa", "bearer ")),
        "authority_scan": not any(k in run for k in FORBIDDEN_TRUTH_KEYS),
    }
    accepted = all(checks.values()) and bool(run.get("accepted"))
    return {
        "schema": "CurationCritique@v1",
        "checks": checks,
        "may_admit": accepted,
        "rejected_reason": None if accepted else [k for k, v in checks.items() if not v] or ["not_accepted"],
        "current_belief": False if not accepted else True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def build_curation_run(
    *,
    security_guid: str | None,
    symbol: str,
    task_type: str,
    prior_curation_id: str | None,
    prior_curation_version: int | None,
    evidence_delta_hash: str,
    input_evidence_refs: list[str],
    prompt_version: str,
    process_id: str,
    requested_policy: str,
    executed_policy: str,
    model_id: str,
    latency_ms: int = 0,
    estimated_cost: float = 0.0,
    schema_valid: bool = True,
    critique_verdict: str = "ACCEPT",
    classification: str = "NO_NEW_INFO",
    confidence: str = "medium",
    accepted: bool = False,
    material_change: bool = False,
    result: dict[str, Any] | None = None,
    retry: bool = False,
    freshness: str = "FRESH",
) -> dict[str, Any]:
    result = strip_private_reasoning(result or {})
    key = curation_dedupe_key(
        security_guid=security_guid,
        prior_curation_version=prior_curation_version,
        evidence_delta_hash=evidence_delta_hash,
        prompt_version=prompt_version,
        task_type=task_type,
    )
    run = {
        "schema": SCHEMA,
        "curation_run_id": key if not retry else f"{key}:retry",
        "dedupe_key": key,
        "security_guid": security_guid,
        "symbol": normalize_symbol(symbol),
        "task_type": task_type,
        "prior_curation_id": prior_curation_id,
        "prior_curation_version": prior_curation_version,
        "evidence_delta_hash": evidence_delta_hash,
        "input_evidence_refs": list(input_evidence_refs),
        "prompt_version": prompt_version,
        "process_id": process_id,
        "requested_policy": requested_policy,
        "executed_policy": executed_policy,
        "model_id": model_id,
        "started_at": _now(),
        "completed_at": _now(),
        "latency_ms": int(latency_ms),
        "estimated_cost": float(estimated_cost),
        "schema_valid": bool(schema_valid),
        "critique_verdict": critique_verdict,
        "result_hash": _sha(result),
        "classification": classification,
        "confidence": confidence,
        "accepted": bool(accepted),
        "acceptance_reason": "CRITIQUE_PASS" if accepted else "CRITIQUE_HOLD",
        "material_change": bool(material_change and accepted),
        "new_curation_id": None,
        "new_curation_version": None,
        "freshness": freshness,
        "contradiction_checked": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "private_reasoning_persisted": False,
    }
    return strip_private_reasoning(run)


def persist_curation_run(root: Path | str, run: dict[str, Any], *, retry: bool = False) -> dict[str, Any]:
    path = Path(root) / PATH
    key = run.get("dedupe_key")
    if not retry:
        for row in _jsonl(path):
            if row.get("dedupe_key") == key:
                return {"wrote": False, "reason": "DEDUPE", "run": row, "duplicate": True}
    clean = strip_private_reasoning(run)
    critique = critique_before_memory(clean)
    clean["critique"] = critique
    if not critique["may_admit"]:
        clean["accepted"] = False
        clean["material_change"] = False
        clean["new_curation_id"] = None
        clean["new_curation_version"] = None
        clean["current_belief"] = False
        clean["retained_in_audit"] = True
    _append(path, clean)
    return {"wrote": True, "run": clean, "duplicate": False, "may_admit": critique["may_admit"]}


def apply_material_version(
    *,
    run: dict[str, Any],
    previous: dict[str, Any] | None,
    support_guids: list[str],
    counter_guids: list[str] | None = None,
    what_changed: str,
) -> dict[str, Any]:
    """NO_NEW_INFO must not create fake progress. Rejected runs are not current belief."""
    material = bool(run.get("accepted") and run.get("material_change"))
    summary = build_summary(
        security_guid=run.get("security_guid"),
        issuer_guid=(previous or {}).get("issuer_guid"),
        listing_guid=(previous or {}).get("listing_guid"),
        symbol=run.get("symbol") or "",
        evidence_watermark=run.get("evidence_delta_hash") or "",
        previous=previous,
        support_guids=support_guids,
        counter_guids=list(counter_guids or []),
        catalyst_guids=list((previous or {}).get("current_catalyst_guids") or []),
        calendar_guids=list((previous or {}).get("calendar_event_guids") or []),
        sector_guid=(previous or {}).get("sector_guid"),
        industry_guid=(previous or {}).get("industry_guid"),
        theme_guids=list((previous or {}).get("theme_guids") or []),
        peer_guids=list((previous or {}).get("peer_guids") or []),
        open_gap_ids=list((previous or {}).get("open_research_gap_ids") or []),
        contradictions=list((previous or {}).get("unresolved_contradictions") or []),
        freshness_summary=str(run.get("freshness") or "FRESH"),
        source_mix={"curation_run": 1},
        source_sha=run.get("result_hash") or "",
        what_changed=what_changed if material else "NO_NEW_INFO",
        next_review="ON_MATERIAL_EVIDENCE_CHANGE",
        material=material,
        conclusion=str(run.get("classification") or "NO_NEW_INFO"),
    )
    run = dict(run)
    if material:
        run["new_curation_id"] = summary["curation_id"]
        run["new_curation_version"] = summary["version"]
        run["kind"] = KIND_MATERIAL
    else:
        run["new_curation_id"] = None if not previous else previous.get("curation_id")
        run["new_curation_version"] = None if not previous else previous.get("version")
        run["kind"] = KIND_BASELINE if not previous else previous.get("kind")
        run["fake_progress"] = False
    run["summary"] = summary
    run["current_belief"] = bool(material or (previous and not run.get("accepted") is False))
    if not run.get("accepted"):
        run["current_belief"] = False
        run["retained_in_audit"] = True
    return run


def link_thesis_candidate(root: Path | str, *, run: dict[str, Any], thesis_id: str, thesis_version: int, evidence_refs: list[str]) -> dict[str, Any]:
    """Link; do not rewrite history."""
    if not run.get("accepted") or not run.get("material_change"):
        return {"linked": False, "reason": "NO_MATERIAL_ACCEPTED_CURATION", "history_rewritten": False}
    row = {
        "schema": "CurationThesisLink@v1",
        "curation_run_id": run.get("curation_run_id"),
        "curation_id": run.get("new_curation_id"),
        "curation_version": run.get("new_curation_version"),
        "symbol_thesis_id": thesis_id,
        "symbol_thesis_version": int(thesis_version),
        "evidence_refs": list(evidence_refs),
        "history_rewritten": False,
        "created_at": _now(),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }
    _append(Path(root) / THESIS_LINK_PATH, row)
    return {"linked": True, "link": row, "history_rewritten": False}


def persist_challenger(root: Path | str, run: dict[str, Any], *, parent_run_id: str) -> dict[str, Any]:
    row = strip_private_reasoning(dict(run))
    row["schema"] = "ChallengerCurationRun@v1"
    row["parent_run_id"] = parent_run_id
    row["flattened_into_parent"] = False
    _append(Path(root) / CHALLENGER_PATH, row)
    return row


def cognition_timeline(root: Path | str, *, security_guid: str | None, symbol: str | None = None) -> dict[str, Any]:
    runs = []
    for row in _jsonl(Path(root) / PATH):
        if security_guid and row.get("security_guid") == security_guid:
            runs.append(row)
        elif not security_guid and symbol and row.get("symbol") == normalize_symbol(symbol):
            runs.append(row)
    current = next((r for r in reversed(runs) if r.get("accepted") and r.get("material_change")), None)
    if current is None:
        current = next((r for r in reversed(runs) if r.get("kind") == KIND_BASELINE or r.get("new_curation_version") == 0), None)
    rejected = [r for r in runs if not r.get("accepted")]
    return {
        "schema": "CognitionTimeline@v1",
        "security_guid": security_guid,
        "runs": [
            {
                "curation_run_id": r.get("curation_run_id"),
                "accepted": r.get("accepted"),
                "material_change": r.get("material_change"),
                "version": r.get("new_curation_version"),
                "model_id": r.get("model_id"),
                "critique_verdict": r.get("critique_verdict"),
                "classification": r.get("classification"),
                "current_belief": bool(current and r.get("curation_run_id") == current.get("curation_run_id")),
            }
            for r in runs
        ],
        "current": None if not current else {
            "curation_run_id": current.get("curation_run_id"),
            "version": current.get("new_curation_version"),
            "curation_id": current.get("new_curation_id"),
        },
        "rejected_retained": len(rejected),
        "rejected_is_current_belief": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def supersede(prior: dict[str, Any], successor: dict[str, Any]) -> dict[str, Any]:
    """Corrected evidence supersedes rather than deletes prior cognition."""
    return {
        "schema": "CognitionSupersession@v1",
        "prior_id": prior.get("curation_run_id") or prior.get("curation_id"),
        "successor_id": successor.get("curation_run_id") or successor.get("curation_id"),
        "prior_deleted": False,
        "prior_current_belief": False,
        "successor_current_belief": bool(successor.get("accepted")),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }
