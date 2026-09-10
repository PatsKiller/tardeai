"""Fixture-backed NOC workflow runner for Temporal architecture due diligence.

This is deliberately not a scheduler or production worker. It exercises the same
idempotency boundaries a Temporal Activity retry would cross while writing only to
an explicitly supplied temporary directory.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from scripts.lib.agent_decision_payload import build_decision_payload
from scripts.lib.cio_theses import CIOThesisStore
from scripts.lib.symbol_thesis_publish import publish_symbol_thesis
from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis
from scripts.temporal_poc.contracts import AUTHORITY, MEMORY_BEHAVIOR_INFLUENCE, WORKFLOW_STAGES


class InjectedCrash(RuntimeError):
    """Test-only worker termination at a named activity boundary."""


def _digest(value: Any) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


class ShadowLedger:
    """Persistent idempotency and workflow journal in an isolated directory."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.path = self.root / "temporal_poc_ledger.json"
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {
            "schema": "TemporalPOCShadowLedger@v1",
            "authority": AUTHORITY,
            "memory_behavior_influence": MEMORY_BEHAVIOR_INFLUENCE,
            "activities": {},
            "workflows": {},
            "provider_responses": {},
            "decisions": {},
            "accepted_evidence": {},
            "counters": {"provider_calls": 0, "decision_writes": 0},
            "injected_boundaries": [],
        }

    def save(self) -> None:
        _atomic_json(self.path, self.data)

    def activity(
        self,
        key: str,
        fn: Callable[[], dict[str, Any]],
        *,
        crash_after: str | None = None,
    ) -> dict[str, Any]:
        rec = self.data["activities"].get(key)
        if rec and rec.get("status") == "COMPLETED":
            rec["cache_hits"] = int(rec.get("cache_hits") or 0) + 1
            self.save()
            return dict(rec["result"])
        attempts = int((rec or {}).get("attempts") or 0) + 1
        self.data["activities"][key] = {"status": "STARTED", "attempts": attempts}
        self.save()
        result = fn()
        if crash_after and crash_after not in self.data["injected_boundaries"]:
            self.data["injected_boundaries"].append(crash_after)
            self.save()
            raise InjectedCrash(crash_after)
        self.data["activities"][key] = {
            "status": "COMPLETED",
            "attempts": attempts,
            "result": result,
        }
        self.save()
        return dict(result)


class NOCShadowWorkflow:
    """Synchronous runner over Activity-shaped functions and durable fixture state."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.ledger = ShadowLedger(self.root)
        self.store = CIOThesisStore(
            event_path=self.root / "theses.jsonl",
            projection_path=self.root / "theses_projection.json",
        )

    @staticmethod
    def fixture() -> dict[str, Any]:
        research = {
            "research_id": "research_noc_temporal_poc_v1",
            "symbol": "NOC",
            "summary": (
                "NOC remains a durable defense holding supported by funded backlog, while program "
                "execution and valuation remain explicit counterweights requiring continued review."
            ),
            "stance": "hold",
            "portfolio_role": "DEFENSIVE_GROWTH",
            "why_owned_or_watched": "Funded defense backlog and strategic mission exposure.",
            "evidence_for": ["ev_noc_backlog", "ev_noc_budget"],
            "counter_evidence": ["ev_noc_execution"],
            "invalidation_conditions": ["Material funded-backlog contraction or repeated program losses."],
            "research_gaps": ["Validate margin durability at the next reported quarter."],
            "what_changes_my_mind": ["A sustained deterioration in funded backlog and program margins."],
            "source_refs": ["fixture:sec_backlog", "fixture:program_execution"],
            "provider": "DETERMINISTIC_FIXTURE",
            "paid_provider": False,
        }
        return {
            "symbol": "NOC",
            "research_gap_id": "gap_noc_temporal_poc_v1",
            "supporting": [
                {"evidence_id": "ev_noc_backlog", "polarity": "SUPPORTING", "source": "fixture:sec_backlog"},
                {"evidence_id": "ev_noc_budget", "polarity": "SUPPORTING", "source": "fixture:budget"},
            ],
            "contradictory": [
                {"evidence_id": "ev_noc_execution", "polarity": "CONTRADICTORY", "source": "fixture:filing"}
            ],
            "research": research,
        }

    def _ensure_standing_thesis(self) -> None:
        if self.store.get_current("symbol_noc"):
            return
        publish_symbol_thesis(
            "NOC",
            summary=(
                "NOC is held for strategic defense exposure; backlog quality and program execution "
                "must be reassessed as new governed evidence arrives."
            ),
            stance="hold",
            portfolio_role="DEFENSIVE_GROWTH",
            why_owned_or_watched="Strategic defense exposure.",
            research_gaps=["Validate backlog quality and program execution."],
            store=self.store,
            notify=False,
            actor_id="temporal_poc_fixture",
        )

    def _provider_activity(self, fixture: dict[str, Any]) -> dict[str, Any]:
        request_id = "provider_" + _digest(
            [fixture["research_gap_id"], fixture["research"]["source_refs"]]
        )[:20]
        existing = self.ledger.data["provider_responses"].get(request_id)
        if existing:
            return dict(existing)
        response = dict(fixture["research"])
        response["provider_request_id"] = request_id
        self.ledger.data["provider_responses"][request_id] = response
        self.ledger.data["counters"]["provider_calls"] += 1
        self.ledger.save()
        return response

    def _reconcile_activity(
        self,
        fixture: dict[str, Any],
        delta: dict[str, Any],
        *,
        crash_after_domain_write: bool,
    ) -> dict[str, Any]:
        evidence = dict(fixture["research"])
        result = reconcile_symbol_thesis(
            "NOC",
            trigger="temporal_poc_research_completion",
            evidence=evidence,
            root=self.root,
            store=self.store,
            publish=delta["classification"] != "NO_NEW_INFO",
            notify=False,
            actor_id="temporal_poc",
        )
        boundary = "reconcile_after_domain_write"
        if crash_after_domain_write and boundary not in self.ledger.data["injected_boundaries"]:
            self.ledger.data["injected_boundaries"].append(boundary)
            self.ledger.save()
            raise InjectedCrash(boundary)
        self.ledger.data["accepted_evidence"]["NOC"] = delta["evidence_hash"]
        self.ledger.save()
        return result

    def _decision_activity(self, delta: dict[str, Any], thesis: dict[str, Any]) -> dict[str, Any]:
        if delta["classification"] == "NO_NEW_INFO":
            return {"emitted": False, "suppression": "NO_NEW_INFO", "authority": AUTHORITY}
        decision_id = "dec_" + _digest(["NOC", delta["evidence_hash"], thesis["thesis_version"]])[:12]
        existing = self.ledger.data["decisions"].get(decision_id)
        if existing:
            return {"emitted": False, "suppression": "IDENTICAL_DECISION", "payload": existing}
        payload = build_decision_payload(
            decision_id=decision_id,
            wake_id="wake_noc_temporal_poc",
            trace_id="trace_noc_temporal_poc",
            symbol="NOC",
            surface="advisory",
            current_action="HOLD",
            confidence=0.68,
            decision_origin="FRESH_RESEARCH",
            inputs_digest="ctx_" + delta["evidence_hash"][:16],
            evidence_refs=fixture_evidence_refs(),
            gates_evaluated=[{"gate": "THESIS_DECISION", "result": "NO_INDEPENDENT_PROMOTION"}],
            extra={"thesis_version": thesis["thesis_version"], "research_delta": delta["classification"]},
        )
        self.ledger.data["decisions"][decision_id] = payload
        self.ledger.data["counters"]["decision_writes"] += 1
        self.ledger.save()
        return {"emitted": True, "payload": payload}

    def run(
        self,
        *,
        run_id: str,
        crash_after_provider: bool = False,
        crash_after_reconcile_write: bool = False,
    ) -> dict[str, Any]:
        fixture = self.fixture()
        self._ensure_standing_thesis()
        prefix = f"{run_id}:"

        standing = self.ledger.activity(
            prefix + "load_standing_thesis",
            lambda: self.store.get_current("symbol_noc") or {},
        )
        supporting = self.ledger.activity(
            prefix + "retrieve_supporting_rag", lambda: {"items": fixture["supporting"]}
        )
        contradictory = self.ledger.activity(
            prefix + "retrieve_contradictory_rag", lambda: {"items": fixture["contradictory"]}
        )
        research = self.ledger.activity(
            prefix + "acquire_research",
            lambda: self._provider_activity(fixture),
            crash_after="provider_after_response" if crash_after_provider else None,
        )
        evidence_hash = _digest(
            [research["research_id"], supporting["items"], contradictory["items"], research["source_refs"]]
        )
        delta = self.ledger.activity(
            prefix + "classify_delta",
            lambda: {
                "schema": "ResearchThesisDelta@v1",
                "symbol": "NOC",
                "standing_thesis_id": "symbol_noc",
                "standing_thesis_version": standing.get("thesis_version"),
                "classification": (
                    "NO_NEW_INFO"
                    if self.ledger.data["accepted_evidence"].get("NOC") == evidence_hash
                    else "STRENGTHENS"
                ),
                "evidence_hash": evidence_hash,
                "supporting_evidence_ids": [r["evidence_id"] for r in supporting["items"]],
                "contradictory_evidence_ids": [r["evidence_id"] for r in contradictory["items"]],
                "authority": AUTHORITY,
            },
        )
        reconciliation = self.ledger.activity(
            prefix + "reconcile_thesis",
            lambda: self._reconcile_activity(
                fixture, delta, crash_after_domain_write=crash_after_reconcile_write
            ),
        )
        thesis = self.store.get_current("symbol_noc") or {}
        decision = self.ledger.activity(
            prefix + "build_decision_payload", lambda: self._decision_activity(delta, thesis)
        )
        result = {
            "workflow": "AutonomousResearchToCIOWorkflow",
            "run_id": run_id,
            "symbol": "NOC",
            "stages": list(WORKFLOW_STAGES),
            "delta": delta,
            "reconciliation": reconciliation,
            "thesis_version": thesis.get("thesis_version"),
            "decision": decision,
            "provider_calls": self.ledger.data["counters"]["provider_calls"],
            "decision_writes": self.ledger.data["counters"]["decision_writes"],
            "thesis_version_count": len(self.store.list_versions("symbol_noc", limit=200)),
            "authority": AUTHORITY,
            "financial_writes": 0,
        }
        self.ledger.data["workflows"][run_id] = result
        self.ledger.save()
        return result


def fixture_evidence_refs() -> list[str]:
    return ["ev_noc_backlog", "ev_noc_budget", "ev_noc_execution"]
