"""Operations posture read API tests."""
from __future__ import annotations

from pathlib import Path

from agent_runtime.operations import operations_payload
from agent_runtime.read_http import AGENT_RUNTIME_OPERATIONS_PATH, dispatch

ROOT = Path(__file__).resolve().parents[1]


class _FakeReader:
    def list_runs(self, *, limit, offset, agent_id=None, status=None):
        if agent_id == "sentinel":
            return [{"run_id": "run_x", "started_at": "2026-07-31T03:00:00+00:00", "status": "COMPLETED"}]
        return []


def test_operations_payload_no_secrets():
    payload = operations_payload(ROOT, reader=_FakeReader())
    assert payload["read_only"] is True
    assert payload["contract"] == "agent-runtime-operations-v1"
    assert len(payload["agents"]) >= 16
    body = str(payload)
    assert "postgresql://" not in body
    sentinel = next(a for a in payload["agents"] if a["agent_id"] == "sentinel")
    assert sentinel["last_dispatch_outcome"] == "COMPLETED"
    assert "tradeai-agent-runtime@sentinel.timer" in sentinel["timer_unit"]
    assert sentinel["schedule_mode"] == "EVENT_DRIVEN"
    assert "15m" not in sentinel["designed_schedule"]
    assert sentinel["autonomy"]["per_run_operator_approval_required"] is False
    assert sentinel["autonomy"]["execution"] == "MANUAL_DISPATCH_ONLY"
    assert sentinel["autonomy"]["capability"] == "BOUNDED_AUTONOMOUS_SHADOW"
    assert sentinel["autonomy"]["event_queue_state"] in {"NOT_VERIFIED", "READY"}
    assert "source_state" in sentinel
    assert sentinel["summary"]
    assert sentinel["triggers"]
    broker = next(a for a in payload["agents"] if a["agent_id"] == "broker_cloud_oversight")
    assert broker["schedule_mode"] == "NOT_RUNNABLE"
    assert broker["timer_state"] == "NOT_APPLICABLE"
    assert broker["autonomy"]["execution"] == "OBSERVABILITY_ONLY"
    assert payload["health_monitor"]["state"] in {"NOT_INSTALLED", "STALE", "HEALTHY", "DEGRADED", "INVALID"}


def test_operations_http_get():
    status, body = dispatch(None, "GET", AGENT_RUNTIME_OPERATIONS_PATH)
    assert status == 200
    assert body["contract"] == "agent-runtime-operations-v1"


def test_operations_http_post_rejected():
    status, body = dispatch(None, "POST", AGENT_RUNTIME_OPERATIONS_PATH)
    assert status == 405
    assert body["read_only"] is True
