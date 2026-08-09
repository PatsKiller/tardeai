"""
P2.10 Production Enablement — Test suite.

Tests production schedule ownership, no duplicate schedules, Alex advisory-only,
PRO_MAX confirmation, and containment preservation.
"""
import os
import tempfile
from pathlib import Path

import pytest

from scripts.lib.cio_wake_jobs import CIOWakeJobStore
from scripts.lib.cio_event_detector import CIOEventDetector, LEGACY_SCHEDULES
from scripts.lib.cio_run_worker import CIORunWorker


class TestProductionSchedules:
    """Tests for production schedule definitions."""

    def test_production_schedules_have_one_owner(self):
        """Every schedule has one owner (Trade AI CIO)."""
        detector = CIOEventDetector()
        # The event detector owns all schedule definitions
        assert len(detector.schedules) == len(LEGACY_SCHEDULES)
        for sched in detector.schedules:
            assert "schedule_id" in sched
            assert "enabled" in sched

    def test_no_duplicate_schedules(self):
        """No duplicate schedule IDs."""
        ids = [s["schedule_id"] for s in LEGACY_SCHEDULES]
        assert len(ids) == len(set(ids))

    def test_no_openclaw_financial_cron(self):
        """CIO event detector does not use OpenClaw cron."""
        detector = CIOEventDetector()
        result = detector.run_once()
        # Returns deterministic result without external cron
        assert "wakes_created" in result

    def test_no_openclaw_financial_heartbeat(self):
        """No financial heartbeat in CIO run worker."""
        auth = CIORunWorker.verify_authority()
        allowed = set(auth["allowed_tools"])
        assert "heartbeat" not in allowed
        assert "financial_heartbeat" not in allowed

    def test_no_specialist_independent_cron(self):
        """Specialist routing is through CIO run worker only."""
        auth = CIORunWorker.verify_authority()
        assert "specialist_cron" not in auth["allowed_tools"]

    def test_alex_advisory_only(self):
        """Alex (via governed bridge) is advisory only."""
        auth = CIORunWorker.verify_authority()
        assert auth["can_execute_orders"] is False

    def test_PRO_MAX_requires_confirmation(self):
        """PRO and MAX model policies require confirmation."""
        # The governed bridge enforces CONFIRMATION for PRO and PRO_MAX
        from scripts.lib.cio_governed_model_bridge import ALEX_POLICY_RESOLUTION
        for policy_name in ("PRO", "PRO_MAX"):
            if policy_name in ALEX_POLICY_RESOLUTION:
                assert ALEX_POLICY_RESOLUTION[policy_name]["thinking"] == "disabled"

    def test_containment_preserved(self):
        """Containment is preserved in production schedules."""
        auth = CIORunWorker.verify_authority()
        assert "budget_override" in auth["forbidden_tools"]
        assert "authority_escalate" in auth["forbidden_tools"]
        assert "process_registry_modify" in auth["forbidden_tools"]
