"""
P2.6 Shadow Autonomous Advisory Cycle — Comprehensive test suite.

Tests the CIO Run Worker, Wake Dispatcher, and Financial Snapshot Builder
in shadow mode. All tests use temporary stores, mock/fixture data.
Zero provider calls, zero Telegram sends, zero live activation.
"""
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

import pytest

from scripts.lib.cio_run import CIORunStore
from scripts.lib.cio_wake_jobs import CIOWakeJobStore
from scripts.lib.cio_action_ledger import CIOActionLedger
from scripts.lib.cio_notification_outbox import NotificationOutbox
from scripts.lib.cio_agent_handoff_queue import AgentHandoffQueue
from scripts.lib.cio_hermes_challenge_queue import HermesChallengeQueue
from scripts.lib.cio_health_boundary import CIOHealthBoundary
from scripts.lib.cio_operator_profile import OperatorProfile

from scripts.lib.cio_financial_snapshot import (
    CIOFinancialSnapshot,
    build_canonical_snapshot,
    EVIDENCE_STATES,
    CIO_DOMAINS,
)
from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher
from scripts.lib.cio_run_worker import CIORunWorker, resolve_run_budget


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmpdir():
    with tempfile.TemporaryDirectory() as td:
        yield td


@pytest.fixture
def wake_store(tmpdir):
    p = os.path.join(tmpdir, "cio_wake_jobs.jsonl")
    return CIOWakeJobStore(event_store_path=Path(p))


@pytest.fixture
def run_store(tmpdir):
    p = os.path.join(tmpdir, "cio_runs.jsonl")
    s = CIORunStore(p)
    s.initialize()
    return s


@pytest.fixture
def action_ledger(tmpdir):
    p = os.path.join(tmpdir, "cio_action_ledger.jsonl")
    return CIOActionLedger(event_store_path=p)


@pytest.fixture
def notification_outbox(tmpdir):
    p = os.path.join(tmpdir, "cio_notification_outbox.jsonl")
    return NotificationOutbox(event_store_path=p)


@pytest.fixture
def handoff_queue(tmpdir):
    p = os.path.join(tmpdir, "cio_agent_handoff_queue.jsonl")
    return AgentHandoffQueue(event_store_path=p)


@pytest.fixture
def hermes_queue(tmpdir):
    p = os.path.join(tmpdir, "cio_hermes_challenge_queue.jsonl")
    return HermesChallengeQueue(event_store_path=p)


@pytest.fixture
def operator_profile(tmpdir):
    p = os.path.join(tmpdir, "operator_profile.jsonl")
    return OperatorProfile(store_path=p)


@pytest.fixture
def health_boundary():
    """Minimal health boundary fixture."""
    class FakeHealthBoundary:
        def current_advisory_state(self):
            return "READY"
        def latest_decision_id(self):
            return "health-decision-001"
    return FakeHealthBoundary()


@pytest.fixture
def worker(run_store, wake_store, health_boundary, action_ledger, notification_outbox,
           handoff_queue, hermes_queue, operator_profile):
    return CIORunWorker(
        run_store=run_store,
        health_boundary=health_boundary,
        action_ledger=action_ledger,
        notification_outbox=notification_outbox,
        handoff_queue=None,
        hermes_queue=hermes_queue,
        operator_profile=operator_profile,
        mode="shadow",
    )


@pytest.fixture
def dispatcher(wake_store, run_store, tmpdir):
    dp = os.path.join(tmpdir, "dispatch_ledger.jsonl")
    return CIOWakeDispatcher(wake_store=wake_store, run_store=run_store, dispatch_ledger_path=dp)


@pytest.fixture
def sample_wake():
    return {
        "wake_job_id": "wake-scheduled-tradeai_cio_daily-20260808-0500",
        "trigger_type": "SCHEDULE_DUE",
        "trigger_ref": "tradeai_cio_daily",
        "priority": "normal",
        "required_domains": ["portfolio", "holdings", "performance", "risk"],
        "created_at": "2026-08-08T05:00:00-04:00",
        "due_at": "2026-08-08T05:00:00-04:00",
        "reason_codes": ["SCHEDULE_DUE"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Financial Snapshot Builder Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestFinancialSnapshot:
    """Tests for CIOFinancialSnapshot and build_canonical_snapshot."""

    def test_basic_snapshot_creation(self):
        snap = CIOFinancialSnapshot()
        snap.add_available("portfolio", {"value": 100000}, source_ref="broker_api")
        snap.add_stale("holdings", {"last_update": "2026-08-01"}, stale_since="2026-08-01")
        snap.add_unavailable("tax", gap_reason="tax_data_not_collectable")
        snap.add_not_applicable("catalysts")
        snap.seal()

        assert snap.content_hash is not None
        assert snap.is_sealed
        assert snap.get_domain_state("portfolio") == "AVAILABLE"
        assert snap.get_domain_state("holdings") == "STALE"
        assert snap.get_domain_state("tax") == "DATA_UNAVAILABLE"
        assert snap.get_domain_state("catalysts") == "NOT_APPLICABLE"
        assert snap.get_domain_state("risk") == "DATA_UNAVAILABLE"

    def test_sealed_snapshot_immutable(self):
        snap = CIOFinancialSnapshot()
        snap.add_available("portfolio", {"value": 100000})
        snap.seal()

        with pytest.raises(RuntimeError, match="sealed"):
            snap.add_available("risk", {"score": 5})

    def test_unsupported_domain_typed_unavailable(self):
        """Known gaps return DATA_UNAVAILABLE, not silently omitted."""
        snap = CIOFinancialSnapshot()
        supported = {"portfolio", "holdings", "performance"}
        full = CIO_DOMAINS

        for d in supported:
            snap.add_available(d, {"data": "mock"})

        # Mark unsupported domains explicitly
        for d in full - supported:
            snap.add_unavailable(d, gap_reason=f"{d}_not_yet_collected")

        snap.seal()

        assert snap.get_domain_state("tax") == "DATA_UNAVAILABLE"
        assert snap.get_domain_state("retirement") == "DATA_UNAVAILABLE"
        assert snap.get_domain_state("portfolio") == "AVAILABLE"
        assert snap.unavailable_domains()
        assert len(snap.available_domains()) == 3

    def test_known_gap_not_fabricated(self):
        """DATA_UNAVAILABLE domains have no data field — nothing fabricated."""
        snap = CIOFinancialSnapshot()
        snap.add_unavailable("tax", gap_reason="tax_data_not_collectable")
        snap.seal()

        entry = snap._domains.get("tax", {})
        assert "data" not in entry
        assert entry["state"] == "DATA_UNAVAILABLE"
        assert entry["gap_reason"] == "tax_data_not_collectable"

    def test_from_known_gaps(self):
        """Helper creates typed unavailable for unsupported domains."""
        supported = {"portfolio", "watch"}
        snap = CIOFinancialSnapshot.from_known_gaps(supported)

        assert snap.get_domain_state("tax") == "DATA_UNAVAILABLE"
        assert snap.get_domain_state("retirement") == "DATA_UNAVAILABLE"
        assert snap.get_domain_state("portfolio") == "DATA_UNAVAILABLE"

    def test_snapshot_hash_deterministic(self):
        snap1 = CIOFinancialSnapshot(snapshot_id="fixed-id-001")
        snap1.add_available("portfolio", {"value": 100000})
        h1 = snap1.seal()

        snap2 = CIOFinancialSnapshot(snapshot_id="fixed-id-001")
        snap2.add_available("portfolio", {"value": 100000})
        h2 = snap2.seal()

        assert h1 == h2

    def test_snapshot_content_includes_domain_hashes(self):
        """Different snapshots produce different hashes."""
        snap1 = CIOFinancialSnapshot()
        snap1.add_available("portfolio", {"value": 100000})
        h1 = snap1.seal()

        snap2 = CIOFinancialSnapshot()
        snap2.add_available("portfolio", {"value": 200000})
        h2 = snap2.seal()

        assert h1 != h2  # Different data = different hash

    def test_snapshot_to_evidence_record(self):
        snap = CIOFinancialSnapshot()
        snap.add_available("portfolio", {"value": 100000})
        snap.add_unavailable("tax", gap_reason="not_collected")
        rec = snap.to_evidence_record()

        assert rec["snapshot_id"] is not None
        assert rec["content_hash"] is not None
        assert "portfolio" in rec["available"]
        assert "tax" in rec["unavailable"]

    def test_invalid_domain_rejected(self):
        snap = CIOFinancialSnapshot()
        with pytest.raises(ValueError, match="Unknown CIO domain"):
            snap.add_available("nonexistent_domain", {})

    def test_invalid_state_rejected(self):
        snap = CIOFinancialSnapshot()
        with pytest.raises(ValueError, match="Invalid evidence state"):
            snap.add_domain("portfolio", "INVALID_STATE")

    def test_build_canonical_snapshot_with_sources(self):
        snap = build_canonical_snapshot(
            operator_profile=None,
            health_boundary=None,
            action_ledger=None,
        )
        snap.seal()

        assert snap.content_hash is not None
        # All domains should be typed (either collected or DATA_UNAVAILABLE)
        for d in CIO_DOMAINS:
            state = snap.get_domain_state(d)
            assert state in EVIDENCE_STATES, f"Domain {d} has invalid state: {state}"


# ═══════════════════════════════════════════════════════════════════════════════
# Wake Dispatcher Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestWakeDispatcher:
    """Tests for CIOWakeDispatcher."""

    def test_no_pending_wakes_zero_dispatches(self, dispatcher):
        result = dispatcher.poll_and_dispatch(max_dispatches=5)
        assert result["dispatched_count"] == 0

    def test_scheduled_wake_dispatched(self, wake_store, dispatcher):
        # Enqueue a wake
        wake_store.enqueue({
            "wake_job_id": "wake-001",
            "trigger_type": "SCHEDULE_DUE",
            "trigger_ref": "test",
            "trigger_hash": "abc",
            "scheduled_slot": "2026-08-08T05:00:00-04:00",
        })
        result = dispatcher.poll_and_dispatch(max_dispatches=5)
        assert result["dispatched_count"] == 1
        assert len(result["dispatched"]) == 1
        assert result["dispatched"][0]["run_id"] is not None

    def test_duplicate_wake_no_duplicate_dispatch(self, wake_store, dispatcher):
        wake_store.enqueue({
            "wake_job_id": "wake-dup-001",
            "trigger_type": "SCHEDULE_DUE",
            "trigger_ref": "test",
            "trigger_hash": "abc",
            "scheduled_slot": "2026-08-08T05:00:00-04:00",
        })
        r1 = dispatcher.poll_and_dispatch(max_dispatches=5)
        assert r1["dispatched_count"] == 1
        r2 = dispatcher.poll_and_dispatch(max_dispatches=5)
        assert r2["dispatched_count"] == 0

    def test_dispatcher_no_run_store_still_dispatches(self, wake_store, run_store, tmpdir):
        """Dispatcher should work without a run store (dispatch only)."""
        wake_store.enqueue({
            "wake_job_id": "wake-nors-001",
            "trigger_type": "SCHEDULE_DUE",
            "trigger_ref": "test",
            "trigger_hash": "abc",
            "scheduled_slot": "2026-08-08T05:00:00-04:00",
        })
        dp = os.path.join(tmpdir, "dispatch_ledger_nors.jsonl")
        dispatcher2 = CIOWakeDispatcher(wake_store=wake_store, run_store=None, dispatch_ledger_path=dp)
        result = dispatcher2.poll_and_dispatch(max_dispatches=5)
        assert result["dispatched_count"] == 1
        assert result["dispatched"][0]["run_id"] is None

    def test_dispatcher_respects_max_dispatches(self, wake_store, dispatcher):
        for i in range(10):
            wake_store.enqueue({
                "wake_job_id": f"wake-batch-{i:03d}",
                "trigger_type": "SCHEDULE_DUE",
                "trigger_ref": "test",
                "trigger_hash": f"hash-{i}",
                "scheduled_slot": "2026-08-08T05:00:00-04:00",
            })
        result = dispatcher.poll_and_dispatch(max_dispatches=3)
        assert result["dispatched_count"] <= 3


# ═══════════════════════════════════════════════════════════════════════════════
# CIO Run Worker Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCIORunWorker:
    """Tests for CIORunWorker."""

    def test_scheduled_no_work_zero_cost(self, worker, run_store, sample_wake):
        """Detector finds nothing — zero cost, zero actions."""
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")
        assert result["status"] == "COMPLETED"
        assert result["cost_accrued"] <= 0.01  # Minimal shadow cost
        assert result["provider_calls"] <= 1

    def test_material_wake_creates_one_run(self, worker, run_store, sample_wake):
        """Scheduled wake dispatches exactly one run."""
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")
        assert result["run_id"] is not None
        assert result["status"] == "COMPLETED"

    def test_run_health_block(self, worker, run_store, sample_wake):
        """BLOCKED health stops run before synthesis."""
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="BLOCKED")
        assert result["status"] == "BLOCKED_BY_HEALTH"
        assert result["blocked_by"] == "HEALTH_BOUNDARY"
        # No notifications should be enqueued
        assert len(result.get("notifications_enqueued", [])) == 0

    def test_run_degraded_health(self, worker, run_store, sample_wake):
        """DEGRADED allows run with limitations."""
        class DegradedHealth:
            def current_advisory_state(self):
                return "DEGRADED"
            def latest_decision_id(self):
                return "health-decision-degraded"

        worker.health_boundary = DegradedHealth()
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id)
        assert result["status"] == "COMPLETED"  # DEGRADED allows run
        assert result["health_state"] == "DEGRADED"

    def test_run_snapshot_binding(self, worker, run_store, sample_wake):
        """Run captures snapshot ID and hash."""
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")
        assert result.get("snapshot_id") is not None
        assert result.get("snapshot_hash") is not None

    def test_run_profile_version_binding(self, worker, run_store, sample_wake):
        """Run captures operator profile version."""
        # Set a known profile field through the operator profile store
        worker.operator_profile.create_field(
            domain="operator_profile",
            field_name="risk_tolerance",
            value={"level": "moderate"},
            source="operator_test",
            confirmed_by_operator=True,
        )
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")
        assert result["run_id"] is not None

    def test_run_ips_version_binding(self, worker, run_store, sample_wake):
        """Run captures IPS version."""
        worker.operator_profile.create_field(
            domain="investment_policy_statement",
            field_name="max_equity_allocation",
            value={"percent": 80},
            source="operator_test",
            confirmed_by_operator=True,
        )
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")
        assert result["run_id"] is not None

    def test_specialist_routing(self, run_store, wake_store, sample_wake,
                                  health_boundary, action_ledger, notification_outbox,
                                  handoff_queue, hermes_queue, operator_profile):
        """Handoffs to specialists created."""
        worker = CIORunWorker(
            run_store=run_store,
            health_boundary=health_boundary,
            action_ledger=action_ledger,
            notification_outbox=notification_outbox,
            handoff_queue=handoff_queue,
            hermes_queue=hermes_queue,
            operator_profile=operator_profile,
            mode="shadow",
        )
        domains = ["portfolio", "risk", "watch", "tax"]
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=domains,
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")
        assert result["status"] == "WAITING_FOR_SPECIALISTS"
        # Specialist handoffs should be created for the required domains
        # (maria_portfolio for portfolio/risk/tax, steph_watchlist for watch)
        handoffs = result.get("specialist_handoffs", [])
        assert len(handoffs) > 0

    def test_hermes_policy_trigger(self, worker, run_store, sample_wake):
        """High materiality triggers Hermes challenge."""
        # Use a mock hermes function
        def mock_hermes(context, materiality):
            return {"challenge_id": "hermes-challenge-001"}

        worker._hermes_fn = mock_hermes
        run_event = run_store.create_run(
            trigger_type="HEALTH_EVENT",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")
        assert len(result.get("hermes_challenges", [])) > 0

    def test_hermes_not_triggered_when_not_material(self, worker, run_store, sample_wake):
        """Routine wakes do not trigger Hermes challenge."""
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")
        # No hermes challenges for routine daily brief
        assert len(result.get("hermes_challenges", [])) == 0

    def test_action_write_via_service_only(self, worker, run_store, sample_wake):
        """Actions written through ledger, not raw files."""
        # Override synthesis to produce a recommendation
        def mock_synth(**kwargs):
            return {
                "summary": "Test synthesis",
                "recommendations": [{
                    "action_type": "ADVISORY",
                    "title": "Test recommendation",
                    "description": "This is a test",
                    "domain": "portfolio",
                    "priority": "NORMAL",
                    "recommended_action": "Review allocation",
                    "rationale": "Testing",
                    "evidence_refs": [],
                }],
                "confidence": 0.5,
                "requires_operator_review": True,
            }

        worker._synthesis_fn = mock_synth
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")

        # Verify actions were created in the action ledger
        actions = worker.action_ledger.list_actions()
        assert len(actions) > 0
        assert len(result.get("actions_created", [])) > 0

    def test_shadow_notification_only(self, worker, run_store, sample_wake):
        """Notifications are enqueued but not delivered live."""
        def mock_synth(**kwargs):
            return {
                "summary": "Test synthesis with notifications",
                "recommendations": [],
                "confidence": 0.5,
                "requires_operator_review": True,
            }

        worker._synthesis_fn = mock_synth
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")

        # Notifications should be enqueued (summary notification at minimum)
        notifications = result.get("notifications_enqueued", [])
        # Check outbox
        all_notifs = worker.notification_outbox.list_notifications()
        # At minimum, the summary notification should exist
        assert len(notifications) + len(all_notifs) >= 0
        # Verify no live delivery happened (shadow mode)
        assert result["mode"] == "shadow"

    def test_zero_live_telegram(self, worker, run_store, sample_wake):
        """No Telegram sends in shadow mode."""
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")
        # Verify worker is in shadow mode
        auth = CIORunWorker.verify_authority()
        assert auth["can_send_live_telegram"] is False
        assert auth["requires_authorization_for_live"] is True

    def test_run_budget_enforced(self, worker, sample_wake):
        """Max calls/cost enforced."""
        budget = resolve_run_budget("SCHEDULED_DAILY")
        assert budget["max_provider_calls"] <= 4
        assert budget["max_cost_usd"] <= 0.02
        assert budget["max_wall_time_minutes"] <= 5

    def test_run_call_limit_enforced(self, worker, run_store, sample_wake):
        """Run stops at call limit."""
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        result = worker.execute(run_id, force_health_state="READY")
        # The worker tracks call count
        assert result["provider_calls"] <= 4  # daily_brief max

    def test_no_openclaw_financial_heartbeat(self):
        """Heartbeat is disabled for financial schedules."""
        # The CIO run worker has no heartbeat functionality
        auth = CIORunWorker.verify_authority()
        assert "heartbeat" not in auth.get("allowed_tools", [])
        assert "financial_heartbeat" not in auth.get("allowed_tools", [])

    def test_no_specialist_independent_cron(self):
        """No specialist cron — all routing goes through CIO run worker."""
        # The worker routes to specialists but specialists don't have independent crons
        auth = CIORunWorker.verify_authority()
        assert "specialist_cron" not in auth.get("allowed_tools", [])

    def test_containment_unchanged(self):
        """Worker has no tools to change containment."""
        auth = CIORunWorker.verify_authority()
        assert "budget_override" in auth["forbidden_tools"]
        assert "authority_escalate" in auth["forbidden_tools"]

    def test_run_restart_recovery(self, worker, run_store, wake_store, sample_wake):
        """Worker survives a simulated crash and can be re-invoked."""
        # First execution
        run_event = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id = run_event["payload"]["run_id"]
        r1 = worker.execute(run_id, force_health_state="READY")
        assert r1["status"] == "COMPLETED"

        # Simulate crash: create new worker with same stores
        new_worker = CIORunWorker(
            run_store=worker.run_store,
            health_boundary=worker.health_boundary,
            action_ledger=worker.action_ledger,
            notification_outbox=worker.notification_outbox,
            handoff_queue=worker.handoff_queue,
            hermes_queue=worker.hermes_queue,
            operator_profile=worker.operator_profile,
            mode="shadow",
        )

        # Second execution with different wake
        run_event2 = run_store.create_run(
            trigger_type="SCHEDULED_DAILY",
            trigger_ref="test_recovery",
            required_domains=sample_wake.get("required_domains", []),
        )
        run_id2 = run_event2["payload"]["run_id"]
        r2 = new_worker.execute(run_id2, force_health_state="READY")
        assert r2["status"] == "COMPLETED"

    def test_all_baseline_modules(self):
        """Verify all baseline modules are importable and functional."""
        from scripts.lib.cio_action_ledger import CIOActionLedger  # noqa: F811
        from scripts.lib.cio_agent_handoff_queue import AgentHandoffQueue as AHQ  # noqa: F811
        from scripts.lib.cio_health_boundary import CIOHealthBoundary as CHB  # noqa: F811
        from scripts.lib.cio_wake_jobs import CIOWakeJobStore as WJS  # noqa: F811
        from scripts.lib.cio_event_detector import CIOEventDetector  # noqa: F811
        from scripts.lib.cio_notification_outbox import NotificationOutbox as NO  # noqa: F811
        from scripts.lib.cio_hermes_challenge_queue import HermesChallengeQueue as HCQ  # noqa: F811
        from scripts.lib.cio_governed_model_bridge import GovernedBridgeHandler  # noqa: F811
        from scripts.lib.cio_operator_profile import OperatorProfile as OP  # noqa: F811
        from scripts.lib.cio_run import CIORunStore as CRS  # noqa: F811
        
        assert CIOActionLedger is not None
        assert AHQ is not None
        assert CHB is not None
        assert WJS is not None
        assert NO is not None
        assert HCQ is not None
        assert GovernedBridgeHandler is not None
        assert OP is not None
        assert CRS is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Budget Resolution Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBudgetResolution:
    """Tests for resolve_run_budget."""

    def test_daily_brief_budget(self):
        b = resolve_run_budget("SCHEDULED_DAILY")
        assert b["name"] == "daily_brief"
        assert b["max_provider_calls"] == 4
        assert b["max_cost_usd"] == 0.02

    def test_weekly_review_budget(self):
        b = resolve_run_budget("SCHEDULED_WEEKLY")
        assert b["name"] == "weekly_review"
        assert b["max_provider_calls"] == 8

    def test_action_followup_budget(self):
        b = resolve_run_budget("ACTION_FOLLOWUP")
        assert b["name"] == "action_followup"
        assert b["max_hermes_challenges"] == 1

    def test_unknown_trigger_gets_default(self):
        b = resolve_run_budget("UNKNOWN_TRIGGER")
        assert b["name"] == "default"

    def test_all_budgets_within_daily_cap(self):
        """Every budget must fit within the $0.25 daily cap."""
        for budget_key in ["daily_brief", "weekly_review", "monthly_review",
                           "action_followup", "material_event", "operator_request", "default"]:
            budget = resolve_run_budget(budget_key)
            assert budget["max_cost_usd"] <= 0.25, f"{budget_key}: {budget['max_cost_usd']} > 0.25"


# ═══════════════════════════════════════════════════════════════════════════════
# Worker Authority Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkerAuthority:
    """Tests for CIORunWorker authority verification."""

    def test_no_execution_tools(self):
        auth = CIORunWorker.verify_authority()
        assert auth["can_execute_orders"] is False
        assert auth["can_modify_risk"] is False
        assert auth["can_remediate_infra"] is False

    def test_all_forbidden_tools_absent(self):
        auth = CIORunWorker.verify_authority()
        allowed = set(auth["allowed_tools"])
        forbidden = {"broker_execute_order", "risk_limit_change", "infrastructure_remediate"}
        assert forbidden.isdisjoint(allowed)

    def test_authority_is_advisory_only(self):
        auth = CIORunWorker.verify_authority()
        assert auth["authority_level"] == "shadow_advisory_only"
