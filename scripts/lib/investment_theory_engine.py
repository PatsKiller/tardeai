"""InvestmentTheory@v1 — a theory is not a fact and not a trade.

Competing theories are mandatory on material questions.
Never silently overwrite. Discovery may exist with no held/watched name.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.cio_forward_program import AUTHORITY, MBI, gated_live_run, require_evidence_class

SCHEMA = "InvestmentTheory@v1"
SET_SCHEMA = "CompetingTheorySet@v1"
PATH = "data/cio/office/investment_theories.jsonl"
STATUSES = (
    "PROPOSED",
    "UNDER_RESEARCH",
    "SUPPORTED",
    "CONTESTED",
    "INVALIDATED",
    "SUPERSEDED",
)
SCOPES = ("security", "industry", "sector", "macro", "portfolio", "theme")
REQUIRED_SET = ("base", "bull", "bear", "alternative")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _load(root: Path) -> list[dict[str, Any]]:
    path = root / PATH
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


def _append(root: Path, row: dict[str, Any]) -> None:
    path = root / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def propose_theory(
    root: Path | str,
    *,
    statement: str,
    mechanism: str,
    scope: str,
    authoring_agent: str,
    evidence_class: str,
    expected_consequences: list[str] | None = None,
    affected_entities: list[str] | None = None,
    supporting_evidence: list[str] | None = None,
    contradictory_evidence: list[str] | None = None,
    canonical_framework_refs: list[str] | None = None,
    historical_analogues: list[str] | None = None,
    assumptions: list[str] | None = None,
    falsification_conditions: list[str] | None = None,
    expected_horizon: str | None = None,
    confidence: float | None = None,
    unresolved_questions: list[str] | None = None,
    research_requests: list[str] | None = None,
    security_guid: str | None = None,
    held_or_watched: bool = False,
    persist: bool = True,
) -> dict[str, Any]:
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("OFFICE", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SCHEMA}
    if scope not in SCOPES:
        return {"ok": False, "reason": "unknown_scope", "schema": SCHEMA, "authority": AUTHORITY}
    if not falsification_conditions:
        return {"ok": False, "reason": "falsification_required", "schema": SCHEMA, "authority": AUTHORITY}
    payload = {
        "statement": statement,
        "mechanism": mechanism,
        "scope": scope,
        "affected_entities": list(affected_entities or []),
        "falsification_conditions": list(falsification_conditions),
    }
    tid = "thy_" + _sha(payload)[:20]
    row = {
        "schema": SCHEMA,
        "theory_id": tid,
        "created_at": _now(),
        "authoring_agent": authoring_agent,
        "scope": scope,
        "statement": statement,
        "mechanism": mechanism,
        "expected_consequences": list(expected_consequences or []),
        "affected_entities": list(affected_entities or []),
        "supporting_evidence": list(supporting_evidence or []),
        "contradictory_evidence": list(contradictory_evidence or []),
        "canonical_framework_refs": list(canonical_framework_refs or []),
        "historical_analogues": list(historical_analogues or []),
        "assumptions": list(assumptions or []),
        "falsification_conditions": list(falsification_conditions),
        "expected_horizon": expected_horizon,
        "confidence": confidence,
        "unresolved_questions": list(unresolved_questions or []),
        "research_requests": list(research_requests or []),
        "version": 1,
        "status": "PROPOSED",
        "security_guid": security_guid,
        "discovery_outside_watchlist": not held_or_watched,
        "not_a_fact": True,
        "not_a_trade": True,
        "financial_action": False,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "evidence_class": cls,
    }
    if persist:
        _append(Path(root), row)
    return {"ok": True, "theory": row, "persisted": persist}


def transition(root: Path | str, theory_id: str, new_status: str, *, reason: str) -> dict[str, Any]:
    if new_status not in STATUSES:
        return {"ok": False, "reason": "unknown_status"}
    rows = _load(Path(root))
    current = None
    for row in reversed(rows):
        if row.get("theory_id") == theory_id:
            current = row
            break
    if not current:
        return {"ok": False, "reason": "theory_not_found"}
    nxt = dict(current)
    nxt["status"] = new_status
    nxt["version"] = int(current.get("version") or 1) + 1
    nxt["supersedes_version"] = current.get("version")
    nxt["transition_reason"] = reason
    nxt["transitioned_at"] = _now()
    nxt["prior_status"] = current.get("status")
    _append(Path(root), nxt)
    return {"ok": True, "theory": nxt, "silently_overwritten": False}


def competing_theories(
    root: Path | str,
    *,
    question: str,
    authoring_agent: str,
    evidence_class: str,
    statements: dict[str, dict[str, Any]],
    affected_entities: list[str] | None = None,
    held_or_watched: bool = False,
    security_guid: str | None = None,
    material: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    """Require base/bull/bear/alternative when evidence permits."""
    cls = require_evidence_class(evidence_class)
    gate = gated_live_run("OFFICE", evidence_class=cls)
    if not gate["ok"]:
        return {**gate, "schema": SET_SCHEMA}
    missing = [k for k in REQUIRED_SET if k not in statements]
    if material and missing:
        return {
            "ok": False,
            "schema": SET_SCHEMA,
            "reason": "competing_theories_required",
            "missing": missing,
            "authority": AUTHORITY,
        }
    created = {}
    for role in REQUIRED_SET:
        spec = statements[role]
        out = propose_theory(
            root,
            statement=str(spec.get("statement") or ""),
            mechanism=str(spec.get("mechanism") or role),
            scope=str(spec.get("scope") or "security"),
            authoring_agent=authoring_agent,
            evidence_class=cls,
            expected_consequences=spec.get("expected_consequences"),
            affected_entities=affected_entities or spec.get("affected_entities"),
            supporting_evidence=spec.get("supporting_evidence"),
            contradictory_evidence=spec.get("contradictory_evidence"),
            canonical_framework_refs=spec.get("canonical_framework_refs"),
            historical_analogues=spec.get("historical_analogues"),
            assumptions=spec.get("assumptions"),
            falsification_conditions=spec.get("falsification_conditions") or [f"{role} would be wrong if opposite evidence appears"],
            expected_horizon=spec.get("expected_horizon"),
            confidence=spec.get("confidence"),
            unresolved_questions=spec.get("unresolved_questions"),
            research_requests=spec.get("research_requests"),
            security_guid=security_guid,
            held_or_watched=held_or_watched,
            persist=persist,
        )
        if not out.get("ok"):
            return out
        created[role] = out["theory"]
    return {
        "ok": True,
        "schema": SET_SCHEMA,
        "question": question,
        "theories": created,
        "roles": list(REQUIRED_SET),
        "not_a_trade": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def list_theories(root: Path | str) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in _load(Path(root)):
        tid = row.get("theory_id")
        if tid:
            latest[str(tid)] = row
    return list(latest.values())
