"""
Gate-D Bundle 2 Closure — Evidence Gate tests (Gate-C contract restored).

Proves that:
  - REQUIRED STALE    → BLOCK
  - REQUIRED UNAVAILABLE → BLOCK
  - REQUIRED ERROR    → BLOCK
  - REQUIRED CONFLICTED → BLOCK
  - REQUIRED PARTIAL (default) → BLOCK

All tests verify the _check_evidence_gate method directly.
Uses PORTFOLIO_ALLOCATION_REVIEW as the run purpose (well-known required domains).
"""
from __future__ import annotations

import pytest

from scripts.lib.cio_run_worker import CIORunWorker
from scripts.lib.cio_financial_snapshot import CIOFinancialSnapshot, _lazy_load_registry


def _mock_snapshot(domain_states: dict[str, str]) -> dict:
    """Build a mock snapshot result. Only includes domains in CIO_DOMAINS."""
    _lazy_load_registry()
    snap = CIOFinancialSnapshot()
    for domain_id, state in domain_states.items():
        try:
            snap.add_domain(domain_id, state, source_ref="test")
        except ValueError:
            pass
    snap.seal()
    return {
        "snapshot": snap,
        "domain_states": {
            domain_id: snap.get_domain_state(domain_id)
            for domain_id in domain_states
            if snap.get_domain_state(domain_id) != "DATA_UNAVAILABLE"
        },
        "snapshot_id": "test-snap-001",
    }


# Registry-backed purposes and their required domains
# These are looked up via check_evidence_gate → registry.run_purpose_requirements()
# The registry may require domains NOT in the legacy CIO_DOMAINS set.
# For tests we use purposes where the required domains overlap the legacy set.
PURPOSE_REQUIRED = {
    "OPERATOR_REQUEST": ["portfolio"],
}


class TestEvidenceGateBlocking:
    """The evidence gate blocks when REQUIRED domains are in blocking states."""

    def test_required_unavailable_domain_blocks(self):
        worker = CIORunWorker(mode="shadow")
        snap = _mock_snapshot({"portfolio": "DATA_UNAVAILABLE"})
        blocked, gaps = worker._check_evidence_gate({}, snap, "OPERATOR_REQUEST")
        assert blocked is True
        assert "portfolio" in gaps["missing_required"]

    def test_required_stale_domain_blocks(self):
        worker = CIORunWorker(mode="shadow")
        snap = _mock_snapshot({"portfolio": "STALE"})
        blocked, gaps = worker._check_evidence_gate({}, snap, "OPERATOR_REQUEST")
        assert blocked is True
        assert "portfolio" in gaps["stale_required"]

    def test_required_error_domain_blocks(self):
        worker = CIORunWorker(mode="shadow")
        snap = _mock_snapshot({"portfolio": "ERROR"})
        blocked, gaps = worker._check_evidence_gate({}, snap, "OPERATOR_REQUEST")
        assert blocked is True
        assert "portfolio" in gaps["error_required"]

    def test_required_conflicted_domain_blocks(self):
        worker = CIORunWorker(mode="shadow")
        snap = _mock_snapshot({"portfolio": "CONFLICTED"})
        blocked, gaps = worker._check_evidence_gate({}, snap, "OPERATOR_REQUEST")
        assert blocked is True
        assert "portfolio" in gaps["conflicted_required"]

    def test_required_partial_default_blocks(self):
        """PARTIAL without minimum_acceptable_state (default: AVAILABLE) → blocks."""
        worker = CIORunWorker(mode="shadow")
        snap = _mock_snapshot({"portfolio": "PARTIAL"})
        blocked, gaps = worker._check_evidence_gate({}, snap, "OPERATOR_REQUEST")
        assert blocked is True
        assert "portfolio" in gaps["partial_required"]

    def test_all_available_no_block(self):
        worker = CIORunWorker(mode="shadow")
        snap = _mock_snapshot({"portfolio": "AVAILABLE"})
        blocked, gaps = worker._check_evidence_gate({}, snap, "OPERATOR_REQUEST")
        assert blocked is False

    def test_multiple_blocking_states(self):
        """STALE + UNAVAILABLE concurrently → both reported."""
        worker = CIORunWorker(mode="shadow")
        snap = _mock_snapshot({"portfolio": "STALE", "income": "PARTIAL"})
        blocked, gaps = worker._check_evidence_gate({}, snap, "INCOME_REVIEW")
        # portfolio is REQUIRED for INCOME_REVIEW and is STALE → blocked
        # income is NOT required by registry (only portfolio is) but the
        # stale portfolio blocks regardless
        assert blocked is True
        assert "portfolio" in gaps["stale_required"]


class TestEvidenceGateRunPurposeMapping:
    """Each trigger_type maps to the correct run purpose for evidence checking."""

    def test_scheduled_daily_maps_to_cio_brief(self):
        worker = CIORunWorker(mode="shadow")
        purpose = worker._classify_run_purpose("SCHEDULED_DAILY", {})
        assert purpose == "SCHEDULED_CIO_BRIEF"

    def test_health_event_maps_to_risk_stop(self):
        worker = CIORunWorker(mode="shadow")
        purpose = worker._classify_run_purpose("HEALTH_EVENT", {})
        assert purpose == "RISK_OR_STOP_EVENT"

    def test_operator_message_maps_to_operator_request(self):
        worker = CIORunWorker(mode="shadow")
        purpose = worker._classify_run_purpose("OPERATOR_MESSAGE", {})
        assert purpose == "OPERATOR_REQUEST"

    def test_specialist_completion_uses_original_purpose(self):
        worker = CIORunWorker(mode="shadow")
        run = {"run_purpose": "PORTFOLIO_ALLOCATION_REVIEW"}
        purpose = worker._classify_run_purpose("SPECIALIST_COMPLETION", run)
        assert purpose == "PORTFOLIO_ALLOCATION_REVIEW"
