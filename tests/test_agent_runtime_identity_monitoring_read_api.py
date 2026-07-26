from __future__ import annotations

from dataclasses import dataclass

import pytest

from scripts.agent_runtime.contracts import Environment
from scripts.agent_runtime.identifiers import AgentIdentity, qualified_agent_id, stable_entity_id
from scripts.agent_runtime.monitoring_events import MONITORING_EVENT_CONTRACT, MonitoringEvent
from scripts.agent_runtime.read_api import READ_API_CONTRACT, READ_ROUTES, ReadOnlyAgentRuntimeAPI


def test_namespaced_agent_and_entity_ids_are_stable():
    identity = AgentIdentity("sentinel")
    assert identity.qualified_id == "tradeai.agent.sentinel"
    first = identity.entity_id("run", ["watch_ticket_review", "input-hash"])
    second = stable_entity_id("run", "tradeai.agent.sentinel", "watch_ticket_review", "input-hash")
    assert first == second
    assert first.startswith("ta:run:")
    assert len(first.split(":")[-1]) == 32


@pytest.mark.parametrize("value", ["Sentinel", "sentinel.prod", "", "a"])
def test_invalid_short_agent_ids_are_rejected(value):
    with pytest.raises(ValueError):
        qualified_agent_id(value)


def test_monitoring_event_is_immutable_namespaced_and_secret_safe():
    event = MonitoringEvent(
        event_type="RUN_STATE_CHANGED",
        run_id="ta:run:0123456789abcdef0123456789abcdef",
        agent_id="sentinel",
        environment=Environment.SHADOW,
        sequence=1,
        status="CREATED",
        attributes={"checkpoint": "created"},
    )
    record = event.to_record()
    assert record["contract"] == MONITORING_EVENT_CONTRACT
    assert record["qualified_agent_id"] == "tradeai.agent.sentinel"
    assert record["event_id"].startswith("ta:monitor_event:")
    assert len(record["event_hash"]) == 64
    with pytest.raises(Exception):
        event.status = "COMPLETED"


def test_monitoring_event_rejects_secret_like_attributes():
    event = MonitoringEvent(
        event_type="PERSISTENCE_FAILED",
        run_id="run_x",
        agent_id="sentinel",
        environment=Environment.LAB,
        sequence=2,
        status="FAILED",
        severity="ERROR",
        attributes={"api_token": "do-not-store"},
    )
    with pytest.raises(ValueError):
        event.validate()


@dataclass
class Reader:
    def list_runs(self, *, limit, offset, agent_id=None, status=None):
        return [{"run_id": "run_1", "agent_id": "tradeai.agent.sentinel", "status": "CREATED"}]

    def get_run(self, run_id):
        return {"run_id": run_id, "status": "CREATED"}

    def list_artifacts(self, run_id):
        return [{"artifact_id": "artifact_1"}]

    def list_retrieval_evidence(self, run_id):
        return [{"ref": "kb:1"}]

    def list_tool_calls(self, run_id):
        return [{"tool_call_id": "tool_1", "decision": "DENY"}]

    def list_reviews(self, run_id):
        return [{"review_id": "review_1", "verdict": "CAUTION"}]

    def list_scores(self, run_id):
        return [{"score_id": "score_1", "value": 0.5}]

    def list_monitoring_events(self, run_id):
        return [{"event_id": "event_1", "status": "CREATED"}]


def test_read_api_exposes_only_get_routes_and_zero_mutation_authority():
    assert READ_ROUTES
    assert {route.method for route in READ_ROUTES} == {"GET"}
    operations = {route.operation for route in READ_ROUTES}
    for forbidden in {"create", "update", "delete", "cancel", "resume", "approve", "schedule", "execute"}:
        assert all(forbidden not in operation for operation in operations)

    api = ReadOnlyAgentRuntimeAPI(Reader())
    listing = api.list_runs(limit=25)
    evidence = api.get_run_evidence("run_1")
    assert listing["contract"] == READ_API_CONTRACT
    assert listing["read_only"] is True
    assert all(value is False for value in listing["authority"].values())
    assert evidence["data"]["retrieval"] == [{"ref": "kb:1"}]
    assert not any(hasattr(api, method) for method in ("create", "update", "delete", "cancel", "resume"))


def test_read_api_bounds_queries_and_rejects_secret_material():
    api = ReadOnlyAgentRuntimeAPI(Reader())
    with pytest.raises(ValueError):
        api.list_runs(limit=201)
    with pytest.raises(ValueError):
        api.get_run("")


def test_every_declared_route_maps_to_an_implemented_api_method():
    # The route table and the API surface can never drift apart (also enforced at import time).
    ReadOnlyAgentRuntimeAPI.assert_routes_are_implemented()
    api = ReadOnlyAgentRuntimeAPI(Reader())
    for route in READ_ROUTES:
        method = getattr(api, route.operation, None)
        assert callable(method), f"route {route.path} has no implemented method {route.operation}"
        result = method(limit=5) if route.operation == "list_runs" else method("run_1")
        assert result["read_only"] is True and all(v is False for v in result["authority"].values())


def test_read_api_rejects_secret_material_in_reader_rows():
    @dataclass
    class LeakyReader(Reader):
        def list_tool_calls(self, run_id):
            return [{"tool_call_id": "t1", "api_token": "leaked-value"}]

    api = ReadOnlyAgentRuntimeAPI(LeakyReader())
    with pytest.raises(ValueError):
        api.list_tool_calls("run_1")  # secret-like key must be rejected at the response boundary
