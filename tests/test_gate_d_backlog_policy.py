"""
Gate-D Level-0 Stabilization: Backlog policy tests.

Proves the deterministic CIOWakeBacklogPolicy correctly classifies and
disposes of accumulated PENDING wakes before the dispatcher activates.

All tests use temporary stores. NO canonical store mutations.
NO provider calls. NO Telegram sends.
"""
from __future__ import annotations

import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def wake_store(temp_dir):
    from scripts.lib.cio_wake_jobs import CIOWakeJobStore

    store_path = temp_dir / "cio_wake_jobs.jsonl"
    return CIOWakeJobStore(event_store_path=store_path)


@pytest.fixture
def run_store(temp_dir):
    from scripts.lib.cio_run import CIORunStore

    store_path = temp_dir / "cio_runs.jsonl"
    store = CIORunStore(store_path=str(store_path))
    store.initialize()
    return store


@pytest.fixture
def wake_dispatcher(wake_store, run_store, temp_dir):
    from scripts.lib.cio_wake_dispatcher import CIOWakeDispatcher

    ledger = temp_dir / "cio_wake_dispatches.jsonl"
    return CIOWakeDispatcher(
        wake_store=wake_store,
        run_store=run_store,
        dispatch_ledger_path=str(ledger),
    )


@pytest.fixture
def backlog_policy():
    from scripts.lib.cio_wake_backlog_policy import CIOWakeBacklogPolicy

    return CIOWakeBacklogPolicy()


def _enqueue_wake(wake_store, wake_job_id, trigger_type="SCHEDULE_DUE",
                  created_at=None, wake_intent="NEW_RUN"):
    """Helper: enqueue a single wake with optional created_at override."""
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    wake_payload = {
        "wake_job_id": wake_job_id,
        "trigger_type": trigger_type,
        "trigger_ref": f"ref-{wake_job_id}",
        "wake_intent": wake_intent,
        "priority": "normal",
        "reason_codes": [trigger_type],
        "required_domains": ["portfolio"],
        "idempotency_key": f"bl-test-{wake_job_id}",
        "created_at": created_at,
        "due_at": created_at,
    }
    wake_store.enqueue(wake_payload, actor_id="test", actor_type="system")
    return wake_job_id


# ═══════════════════════════════════════════════════════════════════════════════
# Backlog Policy Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBacklogPolicy:
    """Core backlog policy classification and disposition tests."""

    def test_fresh_wake_dispatches(self, backlog_policy, wake_store):
        """A fresh PENDING wake within all windows classifies as DISPATCH."""
        wake_job_id = f"fresh-{uuid.uuid4().hex[:8]}"
        _enqueue_wake(wake_store, wake_job_id, trigger_type="SCHEDULE_DUE")

        wake = wake_store.get_wake_job(wake_job_id)
        classification = backlog_policy.classify(wake)
        assert classification == "DISPATCH"

    def test_expired_wake_does_not_dispatch(self, backlog_policy, wake_store):
        """A wake past its effective window classifies as EXPIRE."""
        wake_job_id = f"expired-{uuid.uuid4().hex[:8]}"
        past_time = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        _enqueue_wake(wake_store, wake_job_id, trigger_type="SCHEDULE_DUE",
                      created_at=past_time)

        wake = wake_store.get_wake_job(wake_job_id)
        classification = backlog_policy.classify(wake)
        assert classification == "EXPIRE"

    def test_expired_wake_not_in_dispatch_list(self, backlog_policy, wake_store, run_store):
        """apply() must not include expired wakes in the dispatch list."""
        wake_job_id = f"exp-nd-{uuid.uuid4().hex[:8]}"
        past_time = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        _enqueue_wake(wake_store, wake_job_id, trigger_type="SCHEDULE_DUE",
                      created_at=past_time)

        result = backlog_policy.apply(wake_store, run_store=run_store)
        dispatched_ids = {d["wake_job_id"] for d in result["dispatched"]}
        assert wake_job_id not in dispatched_ids
        assert result["expired_count"] >= 1

    def test_superseded_wake_does_not_dispatch(self, backlog_policy, wake_store):
        """With two SCHEDULE_DUE wakes, the older one is CANCEL_AS_SUPERSEDED."""
        older_id = f"older-{uuid.uuid4().hex[:8]}"
        newer_id = f"newer-{uuid.uuid4().hex[:8]}"

        older_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        newer_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        _enqueue_wake(wake_store, older_id, trigger_type="SCHEDULE_DUE",
                      created_at=older_time)
        _enqueue_wake(wake_store, newer_id, trigger_type="SCHEDULE_DUE",
                      created_at=newer_time)

        all_pending = wake_store.list_wakes(status="PENDING", limit=50)
        older_wake = wake_store.get_wake_job(older_id)
        classification = backlog_policy.classify(older_wake,
                                                  all_pending_wakes=all_pending)
        assert classification == "CANCEL_AS_SUPERSEDED"

        newer_wake = wake_store.get_wake_job(newer_id)
        classification_newer = backlog_policy.classify(newer_wake,
                                                        all_pending_wakes=all_pending)
        assert classification_newer == "DISPATCH"

    def test_already_satisfied_wake_does_not_dispatch(
        self, backlog_policy, wake_store, run_store
    ):
        """A PENDING wake whose linked run is terminal is ALREADY_SATISFIED.

        This scenario arises when lease recovery releases a previously-dispatched
        wake back to PENDING while the linked run has already completed.
        """
        # Create a run directly and transition it through valid states to COMPLETED
        event = run_store.create_run(
            trigger_type="HEALTH_EVENT",
            trigger_ref="already-satisfied-test",
            actor="test",
        )
        run_id = event["payload"]["run_id"]
        run_store.transition(run_id, "HEALTH_CHECK", actor="test")
        run_store.transition(run_id, "EVIDENCE_BUILD", actor="test")
        run_store.transition(run_id, "CIO_SYNTHESIS", actor="test")
        run_store.complete(run_id, cio_artifact_id="art-001", actor="test")
        assert run_store.get_run(run_id)["status"] == "COMPLETED"

        # Construct a PENDING wake dict that has a linked_run_id pointing to
        # the terminal run. This matches the state after lease recovery
        # releases a previously-dispatched wake.
        wake_job_id = f"sat-{uuid.uuid4().hex[:8]}"
        wake_dict = {
            "wake_job_id": wake_job_id,
            "trigger_type": "HEALTH_BLOCK_STARTED",
            "current_status": "PENDING",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "linked_run_id": run_id,
            "wake_intent": "NEW_RUN",
            "priority": "normal",
            "reason_codes": ["HEALTH_BLOCK_STARTED"],
            "required_domains": ["portfolio"],
        }

        classification = backlog_policy.classify(
            wake_dict, all_pending_wakes=[wake_dict], run_store=run_store
        )
        assert classification == "ALREADY_SATISFIED"

    def test_bounded_backlog_lookback(self, backlog_policy, wake_store):
        """A wake older than MAX_BACKLOG_AGE_HOURS (24h) classifies as EXPIRE."""
        wake_job_id = f"oldcut-{uuid.uuid4().hex[:8]}"
        ancient_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        _enqueue_wake(wake_store, wake_job_id, trigger_type="HANDOFF_COMPLETED",
                      created_at=ancient_time)

        wake = wake_store.get_wake_job(wake_job_id)
        classification = backlog_policy.classify(wake)
        assert classification == "EXPIRE"

    def test_backlog_disposition_has_reason_code(
        self, backlog_policy, wake_store, run_store
    ):
        """Expired and cancelled wakes record reason codes in their events."""
        # Expired wake
        exp_id = f"reason-exp-{uuid.uuid4().hex[:8]}"
        past_time = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        _enqueue_wake(wake_store, exp_id, trigger_type="SCHEDULE_DUE",
                      created_at=past_time)

        result = backlog_policy.apply(wake_store, run_store=run_store)
        assert result["expired_count"] >= 1

        # Verify the expired wake has a reason in its events
        events = wake_store.list_events(exp_id)
        expired_events = [e for e in events if e["event_type"] == "CIO_WAKE_EXPIRED"]
        assert len(expired_events) >= 1
        assert "reason" in expired_events[0]["payload"]
        assert "BACKLOG_EXPIRED" in expired_events[0]["payload"]["reason"]

    def test_dispatcher_remains_sole_wake_claimant(
        self, backlog_policy, wake_store, run_store
    ):
        """Backlog policy never claims wakes — only the dispatcher does."""
        wake_job_id = f"claimant-{uuid.uuid4().hex[:8]}"
        _enqueue_wake(wake_store, wake_job_id, trigger_type="ACTION_FOLLOWUP_DUE")

        result = backlog_policy.apply(wake_store, run_store=run_store)

        # The DISPATCH wake should be in the dispatch list
        dispatched_ids = {d["wake_job_id"] for d in result["dispatched"]}
        assert wake_job_id in dispatched_ids

        # But the wake should still be PENDING (policy doesn't claim)
        wake = wake_store.get_wake_job(wake_job_id)
        assert wake["current_status"] == "PENDING"

        # Verify no CIO_WAKE_CLAIMED event exists for this wake
        events = wake_store.list_events(wake_job_id)
        claimed_events = [e for e in events if e["event_type"] == "CIO_WAKE_CLAIMED"]
        assert len(claimed_events) == 0

    def test_direct_worker_path_not_used(self, backlog_policy):
        """Backlog policy has no dependency on CIORunWorker."""
        import inspect
        source = inspect.getsource(backlog_policy.__class__)
        assert "CIORunWorker" not in source
        assert "cio_run_worker" not in source

    def test_terminal_wake_not_replayed(self, backlog_policy, wake_store, run_store):
        """After backlog disposition, terminal wakes are not re-processed."""
        exp_id = f"noreplay-{uuid.uuid4().hex[:8]}"
        past_time = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        _enqueue_wake(wake_store, exp_id, trigger_type="SCHEDULE_DUE",
                      created_at=past_time)

        # First apply: should expire the wake
        result1 = backlog_policy.apply(wake_store, run_store=run_store)
        assert result1["expired_count"] >= 1

        # Second apply: should NOT re-process the terminal wake
        result2 = backlog_policy.apply(wake_store, run_store=run_store)
        assert result2["expired_count"] == 0
        assert result2["dispatched_count"] == 0

    def test_historical_wakes_not_deleted(self, backlog_policy, wake_store, run_store):
        """Wake events persist in the event store — nothing is deleted."""
        wake_job_id = f"persist-{uuid.uuid4().hex[:8]}"
        past_time = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        _enqueue_wake(wake_store, wake_job_id, trigger_type="SCHEDULE_DUE",
                      created_at=past_time)

        events_before = len(wake_store.list_events(wake_job_id))
        assert events_before >= 1  # at least CIO_WAKE_ENQUEUED

        backlog_policy.apply(wake_store, run_store=run_store)

        # Events should have increased (expiration event added), not decreased
        events_after = len(wake_store.list_events(wake_job_id))
        assert events_after >= events_before
        assert events_after > events_before  # new event was appended

    def test_multiple_old_wakes_are_classified_separately(
        self, backlog_policy, wake_store
    ):
        """Multiple old wakes each get their own independent classification."""
        ids = []
        for i in range(3):
            wid = f"multi-{i}-{uuid.uuid4().hex[:6]}"
            past_time = (datetime.now(timezone.utc) - timedelta(hours=6 + i)).isoformat()
            _enqueue_wake(wake_store, wid, trigger_type="HEALTH_BLOCK_STARTED",
                          created_at=past_time)
            ids.append(wid)

        all_pending = wake_store.list_wakes(status="PENDING", limit=50)
        classifications = {}
        for wid in ids:
            wake = wake_store.get_wake_job(wid)
            classifications[wid] = backlog_policy.classify(
                wake, all_pending_wakes=all_pending
            )

        # All three should be EXPIRE (all past 2-hour health window)
        for wid in ids:
            assert classifications[wid] == "EXPIRE", \
                f"Wake {wid} classified as {classifications[wid]}, expected EXPIRE"

    def test_schedule_singleton_latest_dispatches_only(
        self, backlog_policy, wake_store
    ):
        """With multiple SCHEDULE_DUE wakes, only the latest dispatches;
        older ones are superseded."""
        ids = []
        for i in range(3):
            wid = f"sched-{i}-{uuid.uuid4().hex[:6]}"
            past_time = (datetime.now(timezone.utc) - timedelta(hours=i)).isoformat()
            _enqueue_wake(wake_store, wid, trigger_type="SCHEDULE_DUE",
                          created_at=past_time)
            ids.append(wid)

        all_pending = wake_store.list_wakes(status="PENDING", limit=50)

        # Oldest (i=0, 0 hours ago) should be CANCEL_AS_SUPERSEDED
        # Middle (i=1, 1 hour ago) should be CANCEL_AS_SUPERSEDED
        # Newest (i=2, 2 hours ago ... wait, this is wrong)

        # Actually: i=0 → now - 0h, i=1 → now - 1h, i=2 → now - 2h
        # So ids[0] is newest, ids[2] is oldest
        # Newest should DISPATCH, older ones CANCEL_AS_SUPERSEDED

        for idx, wid in enumerate(ids):
            wake = wake_store.get_wake_job(wid)
            classification = backlog_policy.classify(
                wake, all_pending_wakes=all_pending
            )
            if idx == 0:  # newest
                assert classification == "DISPATCH", \
                    f"Newest wake {wid} should DISPATCH, got {classification}"
            else:  # older
                assert classification == "CANCEL_AS_SUPERSEDED", \
                    f"Older wake {wid} should be superseded, got {classification}"


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: backlog policy + dispatcher
# ═══════════════════════════════════════════════════════════════════════════════


class TestBacklogDispatcherIntegration:
    """Verify that applying backlog policy BEFORE poll_and_dispatch()
    does not break the dispatcher's behavior."""

    def test_backlog_then_dispatch_works(self, backlog_policy, wake_dispatcher,
                                          wake_store, run_store):
        """Apply backlog policy with a mix of expired+valid wakes, then
        dispatch the valid ones."""
        # Create an expired wake
        exp_id = f"int-exp-{uuid.uuid4().hex[:8]}"
        past = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        _enqueue_wake(wake_store, exp_id, trigger_type="SCHEDULE_DUE",
                      created_at=past)

        # Create a fresh wake
        fresh_id = f"int-fresh-{uuid.uuid4().hex[:8]}"
        _enqueue_wake(wake_store, fresh_id, trigger_type="HEALTH_BLOCK_STARTED")

        # Apply backlog policy first
        bl_result = backlog_policy.apply(wake_store, run_store=run_store)
        assert bl_result["expired_count"] >= 1
        assert bl_result["dispatched_count"] >= 1

        # The fresh wake should still be PENDING and ready for dispatch
        wake = wake_store.get_wake_job(fresh_id)
        assert wake["current_status"] == "PENDING"

        # Dispatcher can now claim and dispatch the valid wake
        disp_result = wake_dispatcher.poll_and_dispatch(max_dispatches=5)
        assert disp_result["dispatched_count"] >= 1
        dispatched_ids = {d["wake_job_id"] for d in disp_result["dispatched"]}
        assert fresh_id in dispatched_ids

    def test_backlog_is_prefilter_not_replacement(
        self, backlog_policy, wake_dispatcher, wake_store, run_store
    ):
        """The backlog policy is a pre-filter, not a replacement for the
        dispatcher. It does not create runs or operate on DISPATCHED wakes."""
        wake_job_id = f"prefilt-{uuid.uuid4().hex[:8]}"
        _enqueue_wake(wake_store, wake_job_id, trigger_type="ACTION_FOLLOWUP_DUE")

        # Apply backlog: the wake should be classified DISPATCH
        result = backlog_policy.apply(wake_store, run_store=run_store)
        assert result["dispatched_count"] >= 1

        # After backlog, wake is still PENDING
        wake = wake_store.get_wake_job(wake_job_id)
        assert wake["current_status"] == "PENDING"

        # Verify no CIO run was created for this wake by the backlog policy
        runs = run_store.list_runs(limit=50)
        wake_linked_runs = [r for r in runs
                            if r.get("trigger_ref") == wake_job_id]
        assert len(wake_linked_runs) == 0

        # Dispatcher creates the run
        disp_result = wake_dispatcher.poll_and_dispatch(max_dispatches=5)
        assert disp_result["dispatched_count"] >= 1

        # Now a run should exist
        runs_after = run_store.list_runs(limit=50)
        wake_linked_runs_after = [r for r in runs_after
                                   if r.get("trigger_ref") == wake_job_id]
        assert len(wake_linked_runs_after) >= 1

    def test_backlog_policy_preserves_event_integrity(
        self, backlog_policy, wake_dispatcher, wake_store, run_store
    ):
        """Event store integrity is maintained after backlog + dispatch."""
        # Create several wakes including old ones
        past = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        _enqueue_wake(wake_store, f"ei-old-{uuid.uuid4().hex[:8]}",
                      trigger_type="SCHEDULE_DUE", created_at=past)
        _enqueue_wake(wake_store, f"ei-fresh-{uuid.uuid4().hex[:8]}",
                      trigger_type="HEALTH_BLOCK_STARTED")

        # Apply backlog policy
        backlog_policy.apply(wake_store, run_store=run_store)

        # Verify store integrity after backlog events
        integrity = wake_store.verify_integrity()
        assert integrity["valid"] is True, \
            f"Wake store integrity broken: {integrity}"

        # Dispatch
        wake_dispatcher.poll_and_dispatch(max_dispatches=5)

        # Verify store integrity after dispatch
        integrity2 = wake_store.verify_integrity()
        assert integrity2["valid"] is True, \
            f"Wake store integrity broken after dispatch: {integrity2}"

        # Run store integrity
        run_ok, run_msg = run_store.verify_integrity()
        assert run_ok is True, f"Run store integrity broken: {run_msg}"


# ═══════════════════════════════════════════════════════════════════════════════
# Smoke: policy results structure
# ═══════════════════════════════════════════════════════════════════════════════


class TestBacklogResultStructure:
    """Verify the apply() return dict has correct shape."""

    def test_result_has_required_keys(self, backlog_policy, wake_store, run_store):
        """apply() returns a dict with all expected keys."""
        result = backlog_policy.apply(wake_store, run_store=run_store)
        for key in ("dispatched", "expired", "superseded", "satisfied",
                     "dispatched_count", "expired_count",
                     "superseded_count", "satisfied_count"):
            assert key in result, f"Missing key '{key}' in result"

    def test_counts_match_list_lengths(self, backlog_policy, wake_store, run_store):
        """Count integers match the lengths of their corresponding lists."""
        # Create an expired wake to get non-zero counts
        past = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        _enqueue_wake(wake_store, f"cnt-{uuid.uuid4().hex[:8]}",
                      trigger_type="SCHEDULE_DUE", created_at=past)
        _enqueue_wake(wake_store, f"cnt2-{uuid.uuid4().hex[:8]}",
                      trigger_type="ACTION_FOLLOWUP_DUE")

        result = backlog_policy.apply(wake_store, run_store=run_store)
        assert result["dispatched_count"] == len(result["dispatched"])
        assert result["expired_count"] == len(result["expired"])
        assert result["superseded_count"] == len(result["superseded"])
        assert result["satisfied_count"] == len(result["satisfied"])
