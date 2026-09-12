"""A failed health check must not record that a health check happened.

CL-61, second half. `_check_health()` wrote a `health_checked` receipt whether
or not the boundary produced a decision, substituting a freshly minted
`health-<uuid>` when `decision_id` was None. Because
`CIOHealthBoundary.current_advisory_state()` did not exist, that was EVERY run:
the run store recorded a health decision that was never made, and `blocked`
stayed False so nothing was ever gated.

These tests drive `_check_health` directly against a bare object, which is what
the real CIOHealthBoundary looked like to this code before the fix.
"""

from __future__ import annotations

import pytest

from scripts.lib.cio_run_worker import CIORunWorker


class _RecordingRunStore:
    def __init__(self):
        self.receipts = []

    def health_checked(self, run_id, decision_id, actor=None):
        self.receipts.append({"run_id": run_id, "decision_id": decision_id, "actor": actor})


def _worker(boundary, store):
    w = CIORunWorker.__new__(CIORunWorker)   # bypass __init__; only these are used
    w.health_boundary = boundary
    w.run_store = store
    w._run_id = "run-test-001"
    return w


class _BoundaryWithoutTheMethod:
    """Exactly what CIOHealthBoundary was before the fix."""


class _WorkingBoundary:
    def __init__(self, state="READY"):
        self._state = state

    def current_advisory_state(self, required_domains=None):
        self.seen_domains = list(required_domains or [])
        return self._state

    def latest_decision_id(self):
        return "health-decision-real"


def test_failed_check_writes_no_receipt():
    """NEGATIVE CONTROL: before the fix this wrote a minted-id receipt."""
    store = _RecordingRunStore()
    out = _worker(_BoundaryWithoutTheMethod(), store)._check_health()
    assert out["check_failed"] is True
    assert store.receipts == [], (
        "a health check that raised must not leave a receipt claiming a "
        "decision was made"
    )


def test_failed_check_does_not_claim_a_known_state():
    out = _worker(_BoundaryWithoutTheMethod(), _RecordingRunStore())._check_health()
    assert out["state"] == "UNKNOWN"
    assert out["decision_id"] is None


def test_successful_check_writes_the_real_decision_id():
    store = _RecordingRunStore()
    out = _worker(_WorkingBoundary(), store)._check_health()
    assert out["check_failed"] is False
    assert out["state"] == "READY"
    assert len(store.receipts) == 1
    assert store.receipts[0]["decision_id"] == "health-decision-real"


def test_blocked_state_blocks():
    out = _worker(_WorkingBoundary("BLOCKED"), _RecordingRunStore())._check_health()
    assert out["blocked"] is True


@pytest.mark.parametrize("state", ["READY", "DEGRADED", "UNKNOWN"])
def test_non_blocked_states_do_not_block(state):
    out = _worker(_WorkingBoundary(state), _RecordingRunStore())._check_health()
    assert out["blocked"] is False


def test_declared_domains_reach_the_boundary():
    """The worker must pass the run's own required_domains, not an empty list."""
    b = _WorkingBoundary()
    _worker(b, _RecordingRunStore())._check_health(required_domains=["portfolio"])
    assert b.seen_domains == ["portfolio"]


def test_legacy_boundary_without_the_parameter_still_works():
    """The fakes in test_p26_shadow_autonomy take no arguments. An older
    duck-type must not be misread as a health failure."""
    class _Legacy:
        def current_advisory_state(self):
            return "DEGRADED"

        def latest_decision_id(self):
            return "legacy-001"

    store = _RecordingRunStore()
    out = _worker(_Legacy(), store)._check_health()
    assert out["check_failed"] is False
    assert out["state"] == "DEGRADED"
    assert store.receipts[0]["decision_id"] == "legacy-001"
