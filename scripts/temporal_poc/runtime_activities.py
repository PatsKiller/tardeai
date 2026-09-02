"""Real Temporal Activities for the localhost-only NOC due-diligence POC."""
from __future__ import annotations

import asyncio
import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from temporalio import activity
from temporalio.exceptions import ApplicationError

from scripts.lib.agent_decision_payload import build_decision_payload
from scripts.lib.cio_theses import CIOThesisStore
from scripts.lib.symbol_thesis_publish import publish_symbol_thesis
from scripts.lib.symbol_thesis_review import reconcile_symbol_thesis
from scripts.temporal_poc.contracts import AUTHORITY, HARD_POLICY_ERRORS
from scripts.temporal_poc.noc_shadow import NOCShadowWorkflow, fixture_evidence_refs
from scripts.temporal_poc.runtime_store import RuntimeStore, digest

NON_RETRYABLE_POC_ERRORS = {*HARD_POLICY_ERRORS, "MALFORMED_RESEARCH"}


@contextmanager
def _domain_lock(root: Path) -> Iterator[None]:
    path = root / "domain.lock"
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class RuntimeActivities:
    """Activity implementations whose side effects are all isolated and idempotent."""

    def __init__(self, build_id: str):
        self.build_id = build_id

    async def _start(self, stage: str, value: dict[str, Any]) -> tuple[RuntimeStore, str]:
        info = activity.info()
        store = RuntimeStore(value["root"])
        store.record_attempt(value["workflow_id"], stage, info.attempt, self.build_id)
        delay = float(value.get("stage_delay_seconds") or 0)
        if delay:
            await asyncio.sleep(delay)
        await self._fault(store, stage, value, "before")
        return store, f"{value['workflow_id']}:{stage}"

    async def _fault(
        self,
        store: RuntimeStore,
        stage: str,
        value: dict[str, Any],
        boundary: str,
    ) -> None:
        fault = value.get("fault") or {}
        if fault.get("stage") != stage or fault.get("boundary", "before") != boundary:
            return
        info = activity.info()
        fault_type = str(fault.get("type") or "HTTP_500")
        if fault.get("mode") == "pause":
            key = f"{stage}:{boundary}"
            if store.reserve_fault_once(value["workflow_id"], key):
                store.marker(
                    value["workflow_id"],
                    key,
                    {"attempt": info.attempt, "worker_build_id": self.build_id},
                )
                while True:
                    activity.heartbeat({"stage": stage, "boundary": boundary})
                    await asyncio.sleep(0.2)
            return
        failures = int(fault.get("failures") or 1)
        if info.attempt <= failures:
            raise ApplicationError(
                f"injected {fault_type} at {stage}:{boundary}",
                type=fault_type,
                non_retryable=fault_type in NON_RETRYABLE_POC_ERRORS,
            )

    def _result(self, value: dict[str, Any], **fields: Any) -> dict[str, Any]:
        return {**fields, "worker_build_id": self.build_id, "authority": AUTHORITY}

    @activity.defn(name="load_standing_thesis")
    async def load_standing_thesis(self, value: dict[str, Any]) -> dict[str, Any]:
        store, key = await self._start("load_standing_thesis", value)
        if cached := store.cached_result(key):
            return cached
        root = Path(value["root"])
        thesis_store = CIOThesisStore(
            event_path=root / "theses.jsonl", projection_path=root / "theses_projection.json"
        )
        with _domain_lock(root):
            current = thesis_store.get_current("symbol_noc")
            if current is None:
                current = publish_symbol_thesis(
                    "NOC",
                    summary=(
                        "NOC is held for strategic defense exposure; backlog quality and program "
                        "execution must be reassessed as new governed evidence arrives."
                    ),
                    stance="hold",
                    portfolio_role="DEFENSIVE_GROWTH",
                    why_owned_or_watched="Strategic defense exposure.",
                    research_gaps=["Validate backlog quality and program execution."],
                    store=thesis_store,
                    notify=False,
                    actor_id="temporal_runtime_poc_fixture",
                )
        result = self._result(
            value,
            thesis_id="symbol_noc",
            thesis_version=current["thesis_version"],
        )
        return store.save_result(key, result)

    @activity.defn(name="retrieve_supporting_rag")
    async def retrieve_supporting_rag(self, value: dict[str, Any]) -> dict[str, Any]:
        store, key = await self._start("retrieve_supporting_rag", value)
        if cached := store.cached_result(key):
            return cached
        await self._fault(store, "retrieve_supporting_rag", value, "during")
        items = NOCShadowWorkflow.fixture()["supporting"]
        artifact_ref = "rag_supporting_" + digest(items)[:20]
        store.put_artifact(artifact_ref, {"items": items})
        return store.save_result(key, self._result(value, artifact_ref=artifact_ref, item_count=len(items)))

    @activity.defn(name="retrieve_contradictory_rag")
    async def retrieve_contradictory_rag(self, value: dict[str, Any]) -> dict[str, Any]:
        store, key = await self._start("retrieve_contradictory_rag", value)
        if cached := store.cached_result(key):
            return cached
        items = NOCShadowWorkflow.fixture()["contradictory"]
        artifact_ref = "rag_contradictory_" + digest(items)[:20]
        store.put_artifact(artifact_ref, {"items": items})
        return store.save_result(key, self._result(value, artifact_ref=artifact_ref, item_count=len(items)))

    @activity.defn(name="acquire_research")
    async def acquire_research(self, value: dict[str, Any]) -> dict[str, Any]:
        store, key = await self._start("acquire_research", value)
        if cached := store.cached_result(key):
            return cached
        fixture = NOCShadowWorkflow.fixture()
        research = dict(fixture["research"])
        request_id = "provider_" + digest(
            [fixture["research_gap_id"], research["source_refs"]]
        )[:20]
        response, _ = store.provider_response(request_id, research)
        research_ref = "research_" + digest(response)[:20]
        store.put_artifact(research_ref, response)
        await self._fault(store, "acquire_research", value, "after_provider")
        result = self._result(
            value,
            research_id=response["research_id"],
            research_ref=research_ref,
            provider_request_id=request_id,
        )
        return store.save_result(key, result)

    @activity.defn(name="classify_delta")
    async def classify_delta(self, value: dict[str, Any]) -> dict[str, Any]:
        store, key = await self._start("classify_delta", value)
        if cached := store.cached_result(key):
            return cached
        fixture = NOCShadowWorkflow.fixture()
        evidence_hash = digest(
            [
                fixture["research"]["research_id"],
                fixture["supporting"],
                fixture["contradictory"],
                fixture["research"]["source_refs"],
            ]
        )
        classification = (
            "NO_NEW_INFO"
            if store.accepted_evidence(value["symbol"]) == evidence_hash
            else "STRENGTHENS"
        )
        delta_id = "delta_" + digest([value["symbol"], evidence_hash, classification])[:20]
        delta = {
            "schema": "ResearchThesisDelta@v1",
            "delta_id": delta_id,
            "symbol": value["symbol"],
            "standing_thesis_version": value["standing_thesis_version"],
            "classification": classification,
            "evidence_hash": evidence_hash,
            "supporting_evidence_ids": [row["evidence_id"] for row in fixture["supporting"]],
            "contradictory_evidence_ids": [row["evidence_id"] for row in fixture["contradictory"]],
            "research_ref": "research_" + digest(fixture["research"])[:20],
            "authority": AUTHORITY,
        }
        store.put_artifact(delta_id, delta)
        return store.save_result(
            key,
            self._result(value, delta_id=delta_id, classification=classification, evidence_hash=evidence_hash),
        )

    @activity.defn(name="reconcile_thesis")
    async def reconcile_thesis(self, value: dict[str, Any]) -> dict[str, Any]:
        store, key = await self._start("reconcile_thesis", value)
        if cached := store.cached_result(key):
            return cached
        root = Path(value["root"])
        delta = store.artifact(value["delta_id"])
        thesis_store = CIOThesisStore(
            event_path=root / "theses.jsonl", projection_path=root / "theses_projection.json"
        )
        with _domain_lock(root):
            if value["classification"] == "NO_NEW_INFO":
                reconcile_result = reconcile_symbol_thesis(
                    value["symbol"],
                    trigger="temporal_runtime_poc_replay",
                    evidence=NOCShadowWorkflow.fixture()["research"],
                    root=root,
                    store=thesis_store,
                    publish=False,
                    notify=False,
                    actor_id="temporal_runtime_poc",
                )
            else:
                reconcile_result = reconcile_symbol_thesis(
                    value["symbol"],
                    trigger="temporal_runtime_poc_research_completion",
                    evidence=NOCShadowWorkflow.fixture()["research"],
                    root=root,
                    store=thesis_store,
                    publish=True,
                    notify=False,
                    actor_id="temporal_runtime_poc",
                )
            current = thesis_store.get_current("symbol_noc") or {}
        await self._fault(store, "reconcile_thesis", value, "after_domain_write")
        store.accept_evidence(value["symbol"], delta["evidence_hash"])
        result = self._result(
            value,
            delta_id=value["delta_id"],
            classification=value["classification"],
            thesis_version=current.get("thesis_version"),
            version_published=bool(reconcile_result.get("version_published")),
            thesis_version_count=len(thesis_store.list_versions("symbol_noc", limit=200)),
        )
        return store.save_result(key, result)

    @activity.defn(name="build_decision_payload")
    async def build_decision_payload(self, value: dict[str, Any]) -> dict[str, Any]:
        store, key = await self._start("build_decision_payload", value)
        if cached := store.cached_result(key):
            return cached
        if value["classification"] == "NO_NEW_INFO":
            return store.save_result(
                key,
                self._result(value, emitted=False, suppression="NO_NEW_INFO", decision_id=None),
            )
        decision_id = "dec_" + digest(
            [value["symbol"], value["delta_id"], value["thesis_version"]]
        )[:12]
        payload = build_decision_payload(
            decision_id=decision_id,
            wake_id="wake_noc_temporal_runtime_poc",
            trace_id=value["workflow_id"],
            symbol=value["symbol"],
            surface="advisory",
            current_action="HOLD",
            confidence=0.68,
            decision_origin="FRESH_RESEARCH",
            inputs_digest="ctx_" + digest(value["delta_id"])[:16],
            evidence_refs=fixture_evidence_refs(),
            gates_evaluated=[{"gate": "THESIS_DECISION", "result": "NO_INDEPENDENT_PROMOTION"}],
            extra={
                "thesis_version": value["thesis_version"],
                "research_delta": value["classification"],
            },
        )
        created = store.insert_unique("decisions", "decision_id", decision_id, payload)
        if created:
            store.increment("decision_writes")
        return store.save_result(
            key,
            self._result(value, emitted=created, decision_id=decision_id, duplicate=not created),
        )

    @activity.defn(name="evaluate_notification")
    async def evaluate_notification(self, value: dict[str, Any]) -> dict[str, Any]:
        store, key = await self._start("evaluate_notification", value)
        if cached := store.cached_result(key):
            return cached
        send = bool(value["decision_emitted"] and value.get("decision_id"))
        identity = "notify_" + digest(value["decision_id"])[:16] if send else None
        return store.save_result(
            key,
            self._result(value, send=send, notification_identity=identity, reason="MATERIAL_DECISION" if send else "UNCHANGED_REPLAY"),
        )

    @activity.defn(name="enqueue_notification")
    async def enqueue_notification(self, value: dict[str, Any]) -> dict[str, Any]:
        store, key = await self._start("enqueue_notification", value)
        if cached := store.cached_result(key):
            return cached
        if not value["send"]:
            return store.save_result(
                key,
                self._result(value, enqueued=False, suppression="UNCHANGED_REPLAY", notification_identity=None),
            )
        created = store.insert_unique(
            "notification_outbox",
            "notification_identity",
            value["notification_identity"],
            {
                "decision_id": value["decision_id"],
                "delivery": "SHADOW_ONLY_NO_TELEGRAM_SEND",
                "authority": AUTHORITY,
            },
        )
        if created:
            store.increment("notification_writes")
        return store.save_result(
            key,
            self._result(
                value,
                enqueued=created,
                duplicate=not created,
                notification_identity=value["notification_identity"],
            ),
        )

    def all(self) -> list[Any]:
        return [
            self.load_standing_thesis,
            self.retrieve_supporting_rag,
            self.retrieve_contradictory_rag,
            self.acquire_research,
            self.classify_delta,
            self.reconcile_thesis,
            self.build_decision_payload,
            self.evaluate_notification,
            self.enqueue_notification,
        ]
