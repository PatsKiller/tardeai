"""One Institutional Knowledge Fabric for Hermes, CIO, Advisory, specialists.

Knowledge attaches to durable identity and provenance, not ticker strings alone.
Survives restart by reading durable jsonl/json under a root. Does not invent
book full text. Does not mutate OFFICE_TRUTH.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.lib.cio_forward_program import (
    AUTHORITY,
    INSTITUTIONAL_COGNITION,
    MBI,
    OFFICE_TRUTH,
    identity_roll_up,
)
from scripts.lib.cio_institutional_learning import identity_safe_subject
from scripts.lib.reference_brain_audit import _doctrine
from scripts.lib.research_governance.mechanics.references import REFERENCES

SCHEMA = "InstitutionalKnowledgeHit@v1"
RECEIPT = "KnowledgeRetrievalReceipt@v1"
KNOWLEDGE_CLASSES = (
    "canonical_framework",
    "primary_research",
    "operator_derived_doctrine",
    "internal_strategy",
    "security_research",
    "sector_research",
    "investment_thesis",
    "rejected_thesis",
    "contradiction",
    "decision",
    "measured_outcome",
    "lesson",
    "operator_feedback",
    "prior_theory",
    "invalidated_theory",
    "historical_episode",
)

THESES = "data/cio/cio_theses.jsonl"
OBS = "data/cio/outcome_observations.jsonl"
THEORIES = "data/cio/office/investment_theories.jsonl"
SECTORS = "data/cio/office/sector_theses.jsonl"
EPISODES = "data/cio/office/historical_episodes.jsonl"
MEMORY = "data/cio/aif_memory.json"
STRATEGIES = "config/strategies"


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


def _hit(*, kid: str, kclass: str, statement: str, provenance: dict[str, Any],
         identity: dict[str, Any] | None = None, source_id: str | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "knowledge_id": kid,
        "knowledge_class": kclass,
        "statement": statement,
        "source_id": source_id,
        "identity": identity or {"ticker_guid_is_not_security": True},
        "provenance": provenance,
        "lane": INSTITUTIONAL_COGNITION,
        "not_office_truth": True,
        "authority": AUTHORITY,
    }


def retrieve(
    root: Path | str,
    *,
    query: str,
    symbol: str | None = None,
    security_guid: str | None = None,
    knowledge_classes: list[str] | None = None,
    limit: int = 24,
) -> dict[str, Any]:
    """Retrieve from the shared durable corpus. Records what was actually used."""
    root_p = Path(root)
    want = set(knowledge_classes or KNOWLEDGE_CLASSES)
    q = (query or "").lower()
    sym = (symbol or "").upper()
    hits: list[dict[str, Any]] = []

    if "operator_derived_doctrine" in want or "canonical_framework" in want:
        for item in _doctrine():
            blob = f"{item.get('prompt')} {item.get('source_id')} {item.get('doctrine_id')}".lower()
            if q and q not in blob and not any(u in q for u in (item.get("use") or [])):
                if "attract" not in q and "valu" not in q and "challeng" not in q:
                    continue
            hits.append(_hit(
                kid=str(item.get("doctrine_id")),
                kclass="operator_derived_doctrine",
                statement=str(item.get("prompt")),
                source_id=item.get("source_id"),
                provenance={
                    "path": "config/operator_derived_doctrine.json",
                    "not_full_text": True,
                    "role": item.get("role"),
                },
            ))

    if "canonical_framework" in want or "primary_research" in want:
        for row in REFERENCES:
            blob = f"{row.get('mechanic')} {row.get('formula')}".lower()
            if q and q not in blob and "valid" not in q and "risk" not in q:
                continue
            hits.append(_hit(
                kid=str(row.get("mechanic")),
                kclass="canonical_framework",
                statement=str(row.get("formula")),
                source_id=(row.get("source_ids") or [None])[0],
                provenance={
                    "path": row.get("implementation_file"),
                    "source_status": row.get("source_status"),
                    "not_full_text": True,
                },
            ))

    if "internal_strategy" in want:
        sdir = root_p / STRATEGIES
        if sdir.is_dir():
            for path in sorted(sdir.glob("*.yaml"))[:20]:
                if q and q not in path.name.lower():
                    continue
                hits.append(_hit(
                    kid=path.stem,
                    kclass="internal_strategy",
                    statement=f"strategy specification {path.name}",
                    provenance={"path": str(path.relative_to(root_p) if root_p in path.parents else path)},
                ))

    if "investment_thesis" in want or "rejected_thesis" in want:
        latest: dict[str, dict[str, Any]] = {}
        for ev in _jsonl(root_p / THESES):
            payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
            tid = payload.get("thesis_id") or ev.get("thesis_id")
            if tid:
                latest[str(tid)] = {**payload, "_event_id": ev.get("event_id")}
        for tid, th in latest.items():
            linked = [str(s).upper() for s in (th.get("linked_symbols") or []) if s]
            if sym and th.get("symbol") != symbol and sym not in linked and tid != "desk":
                continue
            status = str(th.get("status") or th.get("stance") or "")
            kclass = "rejected_thesis" if status.upper() in {"REJECTED", "INVALIDATED", "EXITED"} else "investment_thesis"
            if kclass not in want:
                continue
            ident = identity_roll_up({
                "security_guid": th.get("security_guid"),
                "symbol": th.get("symbol") or (linked[0] if linked else None),
            })
            hits.append(_hit(
                kid=str(th.get("thesis_version") or tid),
                kclass=kclass,
                statement=str(th.get("summary") or th.get("stance") or tid)[:400],
                identity=ident,
                provenance={"store": THESES, "event_id": th.get("_event_id"), "thesis_id": tid},
            ))

    if "prior_theory" in want or "invalidated_theory" in want:
        for th in _jsonl(root_p / THEORIES):
            st = str(th.get("status") or "")
            kclass = "invalidated_theory" if st in {"INVALIDATED", "SUPERSEDED"} else "prior_theory"
            if kclass not in want:
                continue
            if sym and sym not in {str(x).upper() for x in (th.get("affected_entities") or [])}:
                if security_guid and security_guid != th.get("security_guid"):
                    continue
            hits.append(_hit(
                kid=str(th.get("theory_id")),
                kclass=kclass,
                statement=str(th.get("statement") or ""),
                identity=identity_roll_up(th),
                provenance={"store": THEORIES, "version": th.get("version"), "status": st},
            ))

    if "measured_outcome" in want:
        for obs in _jsonl(root_p / OBS):
            if security_guid and identity_safe_subject(obs) not in {None, security_guid}:
                continue
            hits.append(_hit(
                kid=str(obs.get("outcome_id")),
                kclass="measured_outcome",
                statement=f"outcome {obs.get('outcome_id')} horizon={obs.get('horizon')}",
                identity=identity_roll_up(obs),
                provenance={"store": OBS, "decision_id": obs.get("decision_id")},
            ))

    if "operator_feedback" in want:
        mem_path = root_p / MEMORY
        if mem_path.is_file():
            try:
                mem = json.loads(mem_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                mem = {}
            for rec in (mem.get("records") or []) if isinstance(mem, dict) else []:
                if rec.get("memory_type") not in {"OPERATOR_EXPLICIT_PREFERENCE", "PROCEDURAL_HINT", "RESEARCH_REFERENCE"}:
                    continue
                symbols = [str(s).upper() for s in (rec.get("symbols") or [])]
                content = str(rec.get("content") or "")
                if sym and sym not in symbols and (q and q not in content.lower()):
                    if rec.get("memory_type") != "OPERATOR_EXPLICIT_PREFERENCE":
                        continue
                hits.append(_hit(
                    kid=str(rec.get("memory_id")),
                    kclass="operator_feedback" if rec.get("memory_type") == "OPERATOR_EXPLICIT_PREFERENCE" else "security_research",
                    statement=content[:400],
                    provenance={
                        "store": MEMORY,
                        "memory_type": rec.get("memory_type"),
                        "status": rec.get("status"),
                    },
                ))

    if "historical_episode" in want:
        for ep in _jsonl(root_p / EPISODES):
            hits.append(_hit(
                kid=str(ep.get("episode_id")),
                kclass="historical_episode",
                statement=str(ep.get("statement") or ep.get("label") or ""),
                provenance={"store": EPISODES},
            ))

    if "sector_research" in want:
        for row in _jsonl(root_p / SECTORS):
            hits.append(_hit(
                kid=str(row.get("sector_thesis_id") or row.get("sector")),
                kclass="sector_research",
                statement=str(row.get("current_theory") or row.get("sector") or ""),
                provenance={"store": SECTORS},
            ))

    # Do not let doctrine fill the entire window and hide operator feedback / theses.
    by_class: dict[str, list[dict[str, Any]]] = {}
    for hit in hits:
        by_class.setdefault(str(hit.get("knowledge_class")), []).append(hit)
    clipped: list[dict[str, Any]] = []
    cap = max(1, int(limit))
    per = max(1, cap // max(1, len(by_class)))
    for rows in by_class.values():
        for hit in rows[:per]:
            if len(clipped) < cap:
                clipped.append(hit)
    for hit in hits:
        if len(clipped) >= cap:
            break
        if hit["knowledge_id"] not in {c["knowledge_id"] for c in clipped}:
            clipped.append(hit)
    return {
        "schema": RECEIPT,
        "query": query,
        "symbol": symbol,
        "security_guid": security_guid,
        "knowledge_classes_requested": sorted(want),
        "n": len(clipped),
        "hits": clipped,
        "used_knowledge_ids": [h["knowledge_id"] for h in clipped],
        "office_truth_lane": OFFICE_TRUTH,
        "cognition_lane": INSTITUTIONAL_COGNITION,
        "memory_behavior_influence": MBI,
        "mutated_office_truth": False,
        "authority": AUTHORITY,
        "financial_action": False,
    }
