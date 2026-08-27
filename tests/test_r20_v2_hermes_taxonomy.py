"""R20 V2 Lane C — Hermes runtime taxonomy.

Oneshot / event-driven architecture is valid. Empty queue + no daemon is
EXPECTED_IDLE, never FAILED / BROKEN. READ_ONLY_ADVISORY only.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.hermes_runtime_status import (  # noqa: E402
    AUTHORITY,
    DISABLED,
    EVENT_DRIVEN_IDLE,
    EXPECTED_IDLE,
    FAILED,
    ON_DEMAND_READY,
    ON_DEMAND_RUNNING,
    QUEUE_ACTIVE,
    QUEUE_WAITING,
    SCHEDULED,
    STATES,
    UNKNOWN,
    DEGRADED,
    classify,
)

pytestmark = pytest.mark.tier0

REQUIRED_KEYS = {"mode", "state", "pending", "reason", "authority"}


def _assert_envelope(result: dict) -> None:
    assert REQUIRED_KEYS.issubset(result)
    assert result["authority"] == AUTHORITY == "READ_ONLY_ADVISORY"
    assert result["state"] in STATES
    assert "BROKEN" not in result.values()
    assert result.get("memory_behavior_influence", 0) == 0


def test_idle_oneshot_is_expected_idle() -> None:
    result = classify(architecture="oneshot", pending=0, worker_running=False)
    _assert_envelope(result)
    assert result["state"] == EXPECTED_IDLE
    assert result["mode"] == "ON_DEMAND"
    assert result["pending"] == 0
    assert result["state"] not in {FAILED, "BROKEN"}


def test_classify_default_kwargs_are_idle_oneshot() -> None:
    result = classify()
    _assert_envelope(result)
    assert result["state"] == EXPECTED_IDLE
    assert result["pending"] == 0


def test_pending_without_worker_is_queue_waiting() -> None:
    result = classify(architecture="oneshot", pending=3, worker_running=False)
    _assert_envelope(result)
    assert result["state"] == QUEUE_WAITING
    assert result["pending"] == 3
    assert result["state"] != FAILED


def test_explicit_error_is_failed() -> None:
    result = classify(
        architecture="oneshot",
        pending=0,
        worker_running=False,
        error="backend timeout",
    )
    _assert_envelope(result)
    assert result["state"] == FAILED
    assert "timeout" in result["reason"]


def test_failed_only_on_explicit_error_not_empty_queue() -> None:
    idle = classify(pending=0, worker_running=False, error=None)
    assert idle["state"] == EXPECTED_IDLE
    no_error = classify(pending=0, worker_running=False, error=False)
    assert no_error["state"] == EXPECTED_IDLE
    empty_error = classify(pending=0, worker_running=False, error="")
    assert empty_error["state"] == EXPECTED_IDLE


def test_disabled_when_enabled_false() -> None:
    result = classify(enabled=False, pending=4, worker_running=True, error="ignored")
    _assert_envelope(result)
    assert result["state"] == DISABLED
    assert result["pending"] == 4


def test_worker_running_oneshot_drain_is_on_demand_running() -> None:
    result = classify(
        architecture="oneshot",
        pending=2,
        worker_running=True,
        drain=True,
    )
    _assert_envelope(result)
    assert result["state"] == ON_DEMAND_RUNNING
    assert result["mode"] == "ON_DEMAND"
    assert result["pending"] == 2


def test_worker_running_with_pending_queue_is_queue_active() -> None:
    result = classify(architecture="queue", pending=5, worker_running=True)
    _assert_envelope(result)
    assert result["state"] == QUEUE_ACTIVE
    assert result["pending"] == 5


def test_event_driven_idle() -> None:
    result = classify(architecture="event_driven", pending=0, worker_running=False)
    _assert_envelope(result)
    assert result["state"] == EVENT_DRIVEN_IDLE
    assert result["mode"] == "EVENT_DRIVEN"


def test_scheduled_waiting() -> None:
    result = classify(architecture="scheduled", pending=0, worker_running=False)
    _assert_envelope(result)
    assert result["state"] == SCHEDULED
    assert result["mode"] == "SCHEDULED"


def test_on_demand_ready() -> None:
    result = classify(
        architecture="oneshot",
        pending=0,
        worker_running=False,
        ready=True,
    )
    _assert_envelope(result)
    assert result["state"] == ON_DEMAND_READY


def test_degraded_without_error() -> None:
    result = classify(architecture="oneshot", pending=0, worker_running=False, degraded=True)
    _assert_envelope(result)
    assert result["state"] == DEGRADED
    assert result["state"] != FAILED


def test_unknown_architecture() -> None:
    result = classify(architecture="unknown")
    _assert_envelope(result)
    assert result["state"] == UNKNOWN


def test_no_daemon_is_not_broken() -> None:
    result = classify(
        architecture="oneshot",
        pending=0,
        worker_running=False,
        no_daemon=True,
    )
    _assert_envelope(result)
    assert result["state"] == EXPECTED_IDLE
    assert result["state"] not in {FAILED, "BROKEN"}
    assert "BROKEN" not in result["reason"]
    assert all(value != "BROKEN" for value in result.values())


def test_empty_queue_is_not_unhealthy() -> None:
    result = classify(pending=0, worker_running=False, architecture="oneshot")
    assert result["state"] == EXPECTED_IDLE
    assert result["state"] not in {FAILED, DEGRADED, "BROKEN"}


def test_all_contract_states_are_reachable() -> None:
    samples = {
        ON_DEMAND_READY: classify(architecture="oneshot", ready=True),
        ON_DEMAND_RUNNING: classify(architecture="oneshot", worker_running=True, drain=True),
        EVENT_DRIVEN_IDLE: classify(architecture="event_driven"),
        QUEUE_WAITING: classify(pending=1, worker_running=False),
        QUEUE_ACTIVE: classify(architecture="queue", pending=1, worker_running=True),
        SCHEDULED: classify(architecture="scheduled"),
        EXPECTED_IDLE: classify(architecture="oneshot", pending=0, worker_running=False),
        DEGRADED: classify(degraded=True),
        FAILED: classify(error="boom"),
        DISABLED: classify(enabled=False),
        UNKNOWN: classify(architecture="unknown"),
    }
    assert set(samples) == set(STATES)
    for state, result in samples.items():
        assert result["state"] == state


def test_authority_is_read_only_advisory() -> None:
    src = (ROOT / "scripts/lib/hermes_runtime_status.py").read_text(encoding="utf-8")
    assert "READ_ONLY_ADVISORY" in src
    lowered = src.lower()
    assert "place_order" not in lowered
    assert "modify_order" not in lowered
    assert "telegram send" not in lowered
    result = classify()
    assert result["authority"] == "READ_ONLY_ADVISORY"
