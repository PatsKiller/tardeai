"""
Gate-D Level-0 Stabilization: Terminal wake-closure tests.

Proves that every terminal CIO run state finalizes its linked wake,
and that the dispatcher remains the sole wake-disposition owner.

All tests use temporary stores.  NO canonical store mutations.
NO provider calls. NO Telegram sends.
"""
from __future__ import annotations

import inspect
import sys
import tempfile
import uuid
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
def run_worker(run_store):
    from scripts.lib.cio_run_worker import CIORunWorker

    return CIORunWorker(
        run_store=run_store,
        health_boundary=None,
        action_ledger=None,
        notification_outbox=None,
        handoff_queue=None,
        hermes_queue=None,
        mode="shadow",
    )


def _enqueue_and_dispatch(wake_dispatcher, run_store, wake_store) -> tuple[str, str]:
    """Helper: enqueue a synthetic wake, dispatch, and create a CIO run.

    Returns (wake_job_id, run_id).  The run starts QUEUED.
    """
    wake_job_id = f"term-test-{uuid.uuid4().hex[:8]}"
    wake_payload = {
        "wake_job_id": wake_job_id,
        "trigger_type": "HEALTH_BLOCK_STARTED",
        "trigger_ref": "terminal-closure-test",
        "wake_intent": "NEW_RUN",
        "priority": "normal",
        "reason_codes": ["HEALTH_BLOCK_STARTED"],
        "required_domains": ["portfolio"],
        "idempotency_key": f"term-test-{wake_job_id}",
    }
    wake_store.enqueue(wake_payload, actor_id="test", actor_type="system")
    result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
    assert result["dispatched_count"] == 1
    run_id = result["dispatched"][0]["run_id"]
    return wake_job_id, run_id


def _start_run(run_store, run_id: str):
    """Transition QUEUED → HEALTH_CHECK so the run can reach terminal states."""
    run_store.transition(run_id, "HEALTH_CHECK", actor="test")
    assert run_store.get_run(run_id)["status"] == "HEALTH_CHECK"


# ═══════════════════════════════════════════════════════════════════════════════
# Terminal → Wake finalization
# ═══════════════════════════════════════════════════════════════════════════════


class TestTerminalRunFinalizesWake:
    """Prove every terminal run status finalizes its linked wake."""

    def test_blocked_run_finalizes_linked_wake(
        self, wake_dispatcher, run_store, wake_store
    ):
        """BLOCKED run → wake reaches terminal disposition."""
        wake_job_id, run_id = _enqueue_and_dispatch(
            wake_dispatcher, run_store, wake_store
        )
        wake_dispatcher.mark_in_flight(wake_job_id)

        # QUEUED → HEALTH_CHECK → BLOCKED (valid per STATE_TRANSITIONS)
        _start_run(run_store, run_id)
        run_store.block(run_id, "EVIDENCE_GAP:missing:portfolio", actor="test")
        assert run_store.get_run(run_id)["status"] == "BLOCKED"

        ok = wake_dispatcher.on_run_completed(wake_job_id, run_id, "BLOCKED")
        assert ok is True

        wake = wake_store.get_wake_job(wake_job_id)
        assert wake["current_status"] != "IN_FLIGHT"
        assert wake["current_status"] == "COMPLETED"

    def test_failed_run_finalizes_linked_wake(
        self, wake_dispatcher, run_store, wake_store
    ):
        """FAILED run → wake reaches terminal disposition."""
        wake_job_id, run_id = _enqueue_and_dispatch(
            wake_dispatcher, run_store, wake_store
        )
        wake_dispatcher.mark_in_flight(wake_job_id)

        _start_run(run_store, run_id)
        run_store.fail(run_id, "simulated failure", actor="test")
        assert run_store.get_run(run_id)["status"] == "FAILED"

        ok = wake_dispatcher.on_run_completed(wake_job_id, run_id, "FAILED")
        assert ok is True
        assert wake_store.get_wake_job(wake_job_id)["current_status"] == "COMPLETED"

    def test_cancelled_run_finalizes_linked_wake(
        self, wake_dispatcher, run_store, wake_store
    ):
        """CANCELLED run → wake reaches terminal disposition."""
        wake_job_id, run_id = _enqueue_and_dispatch(
            wake_dispatcher, run_store, wake_store
        )
        wake_dispatcher.mark_in_flight(wake_job_id)

        run_store.cancel(run_id, actor="test")
        assert run_store.get_run(run_id)["status"] == "CANCELLED"

        ok = wake_dispatcher.on_run_completed(wake_job_id, run_id, "CANCELLED")
        assert ok is True
        assert wake_store.get_wake_job(wake_job_id)["current_status"] == "COMPLETED"

    def test_completed_run_finalizes_linked_wake(
        self, wake_dispatcher, run_store, wake_store
    ):
        """COMPLETED run → wake reaches terminal disposition."""
        wake_job_id, run_id = _enqueue_and_dispatch(
            wake_dispatcher, run_store, wake_store
        )
        wake_dispatcher.mark_in_flight(wake_job_id)

        # Walk the state machine: QUEUED → HEALTH_CHECK → EVIDENCE_BUILD
        # → CIO_SYNTHESIS → COMPLETED
        run_store.transition(run_id, "HEALTH_CHECK", actor="test")
        run_store.transition(run_id, "EVIDENCE_BUILD", actor="test")
        run_store.transition(run_id, "CIO_SYNTHESIS", actor="test")
        run_store.complete(run_id, cio_artifact_id="art-001", actor="test")
        assert run_store.get_run(run_id)["status"] == "COMPLETED"

        ok = wake_dispatcher.on_run_completed(wake_job_id, run_id, "COMPLETED")
        assert ok is True
        assert wake_store.get_wake_job(wake_job_id)["current_status"] == "COMPLETED"

    def test_expired_run_finalizes_linked_wake(
        self, wake_dispatcher, run_store, wake_store
    ):
        """EXPIRED run → wake reaches terminal disposition."""
        wake_job_id, run_id = _enqueue_and_dispatch(
            wake_dispatcher, run_store, wake_store
        )
        wake_dispatcher.mark_in_flight(wake_job_id)

        # QUEUED → EXPIRED is a valid terminal transition.
        run_store.transition(run_id, "EXPIRED", actor="test")
        assert run_store.get_run(run_id)["status"] == "EXPIRED"

        ok = wake_dispatcher.on_run_completed(wake_job_id, run_id, "EXPIRED")
        assert ok is True
        assert wake_store.get_wake_job(wake_job_id)["current_status"] == "COMPLETED"

    def test_non_terminal_does_not_finalize_wake(
        self, wake_dispatcher, run_store, wake_store
    ):
        """Non-terminal run states (QUEUED, HEALTH_CHECK) must NOT
        finalize the linked wake."""
        wake_job_id, run_id = _enqueue_and_dispatch(
            wake_dispatcher, run_store, wake_store
        )
        wake_dispatcher.mark_in_flight(wake_job_id)

        # QUEUED is non-terminal
        ok = wake_dispatcher.on_run_completed(wake_job_id, run_id, "QUEUED")
        assert ok is False
        assert wake_store.get_wake_job(wake_job_id)["current_status"] == "IN_FLIGHT"

        # HEALTH_CHECK is also non-terminal
        _start_run(run_store, run_id)
        ok = wake_dispatcher.on_run_completed(wake_job_id, run_id, "HEALTH_CHECK")
        assert ok is False
        assert wake_store.get_wake_job(wake_job_id)["current_status"] == "IN_FLIGHT"

    def test_unknown_terminal_string_is_rejected(
        self, wake_dispatcher, run_store, wake_store
    ):
        """Arbitrary strings that aren't canonical terminal states are rejected."""
        wake_job_id, run_id = _enqueue_and_dispatch(
            wake_dispatcher, run_store, wake_store
        )
        wake_dispatcher.mark_in_flight(wake_job_id)

        ok = wake_dispatcher.on_run_completed(
            wake_job_id, run_id, "RANDOM_GARBAGE"
        )
        assert ok is False


# ═══════════════════════════════════════════════════════════════════════════════
# Terminal wake not reclaimed
# ═══════════════════════════════════════════════════════════════════════════════


class TestTerminalWakeNotReclaimed:
    """Prove that once a wake is finalized, it cannot be re-dispatched."""

    def test_terminal_wake_not_reclaimed_by_dispatcher(
        self, wake_dispatcher, run_store, wake_store
    ):
        """After on_run_completed, the wake is terminal.
        A second poll_and_dispatch() must not reclaim it."""
        wake_job_id, run_id = _enqueue_and_dispatch(
            wake_dispatcher, run_store, wake_store
        )
        wake_dispatcher.mark_in_flight(wake_job_id)

        _start_run(run_store, run_id)
        run_store.block(run_id, "EVIDENCE_GAP", actor="test")
        wake_dispatcher.on_run_completed(wake_job_id, run_id, "BLOCKED")

        # Second dispatch pass — terminal wake must not appear
        result2 = wake_dispatcher.poll_and_dispatch(max_dispatches=5)
        dispatched_ids = {d["wake_job_id"] for d in result2["dispatched"]}
        assert wake_job_id not in dispatched_ids

    def test_terminal_wake_second_dispatch_noop(
        self, wake_dispatcher, run_store, wake_store
    ):
        """Two consecutive on_run_completed calls for the same wake
        are idempotent — neither crashes nor creates duplicate events."""
        wake_job_id, run_id = _enqueue_and_dispatch(
            wake_dispatcher, run_store, wake_store
        )
        wake_dispatcher.mark_in_flight(wake_job_id)

        _start_run(run_store, run_id)
        run_store.block(run_id, "EVIDENCE_GAP", actor="test")

        ok1 = wake_dispatcher.on_run_completed(wake_job_id, run_id, "BLOCKED")
        assert ok1 is True

        # Second call must not raise — idempotent
        ok2 = wake_dispatcher.on_run_completed(wake_job_id, run_id, "BLOCKED")
        assert ok2 in (True, False)


# ═══════════════════════════════════════════════════════════════════════════════
# Worker does NOT finalize the wake directly
# ═══════════════════════════════════════════════════════════════════════════════


class TestWorkerDoesNotFinalizeWake:
    """CIORunWorker is a run executor — it must not own wake disposition."""

    def test_worker_has_no_wake_reference(self, run_worker):
        """CIORunWorker constructor accepts no wake_store parameter."""
        sig = inspect.signature(run_worker.__class__.__init__)
        params = list(sig.parameters.keys())[1:]  # skip self
        assert "wake_store" not in params
        assert "wake_dispatcher" not in params

    def test_worker_has_no_wake_completion_method(self, run_worker):
        """CIORunWorker has no method to complete or finalize a wake."""
        wake_methods = [a for a in dir(run_worker) if "wake" in a.lower()]
        assert not wake_methods, (
            f"CIORunWorker must not own wake methods, but found: {wake_methods}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Dispatcher remains sole terminal-disposition owner
# ═══════════════════════════════════════════════════════════════════════════════


class TestDispatcherRemainsTerminalDispositionOwner:
    """CIOWakeDispatcher is the sole owner of wake terminal disposition."""

    def test_dispatcher_has_exclusive_completion(self, wake_dispatcher):
        """Only the CIOWakeDispatcher has on_run_completed()."""
        assert hasattr(wake_dispatcher, "on_run_completed")
        assert callable(wake_dispatcher.on_run_completed)

    def test_wake_store_records_dispatcher_completion(
        self, wake_dispatcher, run_store, wake_store
    ):
        """on_run_completed() writes the completion event with the
        linked CIO run reference."""
        wake_job_id, run_id = _enqueue_and_dispatch(
            wake_dispatcher, run_store, wake_store
        )
        wake_dispatcher.mark_in_flight(wake_job_id)

        _start_run(run_store, run_id)
        run_store.block(run_id, "EVIDENCE_GAP", actor="test")

        ok = wake_dispatcher.on_run_completed(wake_job_id, run_id, "BLOCKED")
        assert ok is True

        wake = wake_store.get_wake_job(wake_job_id)
        assert wake["current_status"] == "COMPLETED"
        assert wake.get("linked_run_id") == run_id

        completion = wake.get("completion_details", {})
        assert completion.get("cio_run_id") == run_id
        assert completion.get("run_status") == "BLOCKED"


# ═══════════════════════════════════════════════════════════════════════════════
# Canonical TERMINAL_STATUSES integrity
# ═══════════════════════════════════════════════════════════════════════════════


class TestCanonicalTerminalStatuses:
    """The canonical TERMINAL_STATUSES set covers every dead-end run state."""

    def test_all_terminal_states_present(self):
        """COMPLETED, BLOCKED, FAILED, CANCELLED, EXPIRED are all terminal."""
        from scripts.lib.cio_run import TERMINAL_STATUSES

        expected = {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED", "EXPIRED"}
        assert TERMINAL_STATUSES == expected

    def test_on_run_completed_uses_canonical(self, wake_dispatcher):
        """on_run_completed() references the shared TERMINAL_STATUSES."""
        source = inspect.getsource(wake_dispatcher.on_run_completed)
        assert "TERMINAL_STATUSES" in source


# ═══════════════════════════════════════════════════════════════════════════════
# Wake intent → run creation (non-RESUME intents create runs)
# ═══════════════════════════════════════════════════════════════════════════════


class TestWakeIntentRunCreation:
    """Any wake_intent other than RESUME_RUN must create a CIO run."""

    def test_explicit_new_run_creates_run(
        self, wake_store, run_store, wake_dispatcher
    ):
        """wake_intent=NEW_RUN creates a new run."""
        wake_job_id = _enqueue_wake(wake_store, wake_intent="NEW_RUN")
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 1
        assert result["dispatched"][0]["run_id"] is not None

    def test_run_purpose_intent_creates_run(
        self, wake_store, run_store, wake_dispatcher
    ):
        """wake_intent=SCHEDULED_CIO_BRIEF creates a new run."""
        wake_job_id = _enqueue_wake(wake_store, wake_intent="SCHEDULED_CIO_BRIEF")
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 1
        run_id = result["dispatched"][0]["run_id"]
        assert run_id is not None
        assert run_id != ""

    def test_health_event_intent_creates_run(
        self, wake_store, run_store, wake_dispatcher
    ):
        """wake_intent=HEALTH_EVENT creates a new run."""
        wake_job_id = _enqueue_wake(wake_store, wake_intent="HEALTH_EVENT")
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 1
        assert result["dispatched"][0]["run_id"] is not None

    def test_resume_run_does_not_create_run(
        self, wake_store, run_store, wake_dispatcher
    ):
        """wake_intent=RESUME_RUN without target is skipped."""
        wake_job_id = _enqueue_wake(wake_store, wake_intent="RESUME_RUN")
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 0

    def test_resume_with_target_resumes(
        self, wake_store, run_store, wake_dispatcher
    ):
        """wake_intent=RESUME_RUN with valid target_run_id dispatches."""
        wake_job_id = _enqueue_wake(wake_store, wake_intent="NEW_RUN")
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        run_id = result["dispatched"][0]["run_id"]
        assert run_id is not None

        resume_id = _enqueue_wake(
            wake_store, wake_intent="RESUME_RUN", target_run_id=run_id
        )
        result2 = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result2["dispatched_count"] == 1
        assert result2["dispatched"][0]["run_id"] == run_id


def _enqueue_wake(wake_store, wake_intent="NEW_RUN", target_run_id=None):
    """Helper: enqueue a PENDING wake via the wake store."""
    import uuid
    wake_id = f"test-wake-{uuid.uuid4().hex[:12]}"
    payload = {
        "wake_job_id": wake_id,
        "trigger_type": "SCHEDULE_DUE",
        "trigger_ref": "test-fixture",
        "idempotency_key": wake_id,
        "wake_intent": wake_intent,
        "target_run_id": target_run_id,
        "required_domains": [],
        "priority": "normal",
    }
    wake_store.enqueue(payload, actor_id="test-fixture")
    return wake_id


# ═══════════════════════════════════════════════════════════════════════════════
# Wake-intent normalization — fail-closed for unknown intents
# ═══════════════════════════════════════════════════════════════════════════════


class TestWakeIntentNormalization:
    """Wake intent must use explicit normalization map; unknown intents fail closed."""

    def test_new_run_creates_run(self, wake_store, run_store, wake_dispatcher):
        """NEW_RUN creates exactly one run."""
        wake_job_id = _enqueue_wake(wake_store, wake_intent="NEW_RUN")
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 1
        assert result["dispatched"][0]["run_id"] is not None

    def test_known_legacy_intent_normalizes_to_new_run(
        self, wake_store, run_store, wake_dispatcher
    ):
        """SCHEDULED_CIO_BRIEF normalizes to NEW_RUN and creates a run."""
        wake_job_id = _enqueue_wake(wake_store, wake_intent="SCHEDULED_CIO_BRIEF")
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 1
        assert result["dispatched"][0]["run_id"] is not None

    def test_health_event_intent_normalizes(
        self, wake_store, run_store, wake_dispatcher
    ):
        """HEALTH_EVENT normalizes to NEW_RUN."""
        wake_job_id = _enqueue_wake(wake_store, wake_intent="HEALTH_EVENT")
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 1

    def test_unknown_wake_intent_does_not_create_run(
        self, wake_store, run_store, wake_dispatcher
    ):
        """Unknown wake_intent is rejected — no run created."""
        wake_job_id = _enqueue_wake(wake_store, wake_intent="EXECUTE_TRADE")
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 0
        assert len(result["errors"]) > 0 or len(result["skipped"]) > 0

    def test_malformed_wake_intent_does_not_create_run(
        self, wake_store, run_store, wake_dispatcher
    ):
        """Malformed intent (empty string) does not create a run."""
        wake_job_id = _enqueue_wake(wake_store, wake_intent="")
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result["dispatched_count"] == 0

    def test_resume_run_never_creates_second_run(
        self, wake_store, run_store, wake_dispatcher
    ):
        """RESUME_RUN with valid target does not create a second run."""
        # Create a run first
        wake_job_id = _enqueue_wake(wake_store, wake_intent="NEW_RUN")
        result = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        run_id = result["dispatched"][0]["run_id"]

        # Resume should link to the same run_id, not create a new one
        resume_id = _enqueue_wake(
            wake_store, wake_intent="RESUME_RUN", target_run_id=run_id
        )
        result2 = wake_dispatcher.poll_and_dispatch(max_dispatches=1)
        assert result2["dispatched_count"] == 1
        assert result2["dispatched"][0]["run_id"] == run_id
        # The wake_job_id should be the resume wake, not the original
        assert result2["dispatched"][0]["wake_job_id"] == resume_id
