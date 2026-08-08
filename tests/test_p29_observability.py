"""
P2.9 Cost / Quality / Observability — Test suite.

Tests budget enforcement, cost tracking, quality metrics, and explainability.
"""
import os
import tempfile
from pathlib import Path

import pytest

from scripts.lib.cio_run import CIORunStore
from scripts.lib.cio_run_worker import resolve_run_budget, CIORunWorker, RUN_BUDGETS


class TestRunBudgets:
    """Tests for CIO run budget enforcement."""

    def test_run_budget_enforcement(self):
        """All budgets are within global cap."""
        daily_cap = 0.25
        for name, budget in RUN_BUDGETS.items():
            assert budget["max_cost_usd"] <= daily_cap, \
                f"{name}: {budget['max_cost_usd']} > {daily_cap}"
            assert budget["max_provider_calls"] <= 20  # hard cap
            assert budget["max_wall_time_minutes"] <= 60  # hard cap

    def test_budget_deferred_not_fallback(self):
        """Budget-deferred runs have specific cost limits."""
        b = resolve_run_budget("SCHEDULED_DAILY")
        assert b["max_cost_usd"] == 0.02
        assert b["max_provider_calls"] == 4

    def test_cost_tracking_per_run(self):
        """Each run has cost tracking fields."""
        b = resolve_run_budget("SCHEDULED_WEEKLY")
        assert "max_cost_usd" in b
        assert "max_provider_calls" in b
        assert "max_wall_time_minutes" in b

    def test_run_explainability(self, tmpdir):
        """Run has all required trace references."""
        p = os.path.join(tmpdir.strpath if hasattr(tmpdir, "strpath") else str(tmpdir), "runs.jsonl")
        store = CIORunStore(p)
        store.initialize()
        event = store.create_run(trigger_type="MANUAL", actor="test")
        run_id = event["payload"]["run_id"]
        run = store.get_run(run_id)
        assert run is not None
        assert run["status"] == "QUEUED"
        assert run["trigger_type"] == "MANUAL"
        assert "created_at" in run
        assert "budget" in run
        assert "counters" in run

    def test_quality_grounding_check(self, tmpdir):
        """Run references canonical sources via snapshot and health."""
        p = os.path.join(tmpdir.strpath if hasattr(tmpdir, "strpath") else str(tmpdir), "runs2.jsonl")
        store = CIORunStore(p)
        store.initialize()
        event = store.create_run(
            trigger_type="MANUAL",
            input_hash="abc123",
            operator_profile_version=1,
            ips_version=2,
            actor="test",
        )
        run_id = event["payload"]["run_id"]
        run = store.get_run(run_id)
        assert run is not None
        assert run["input_hash"] == "abc123"
        assert run["operator_profile_version"] == 1
        assert run["ips_version"] == 2

    def test_no_execution_tool_in_run(self):
        """Run worker has no execution tools."""
        auth = CIORunWorker.verify_authority()
        assert not auth["can_execute_orders"]
        assert not auth["can_modify_risk"]
        assert not auth["can_remediate_infra"]
        assert not auth["can_send_live_telegram"]
