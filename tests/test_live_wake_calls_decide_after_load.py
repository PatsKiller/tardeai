"""PR #810's contract must run on the SCHEDULED wake, not only under --dry-run.

Cause (2026-09-01): decide_after_load — the function #810 shipped and tested —
had exactly one non-report call site, inside dry_run_record_consult(), reached
only via `if args.dry_run:`. The installed cron is

    */5 * * * * cd .../CURRENT && .../python scripts/cio_wake_dispatch_entrypoint.py

with NO flag, so args.dry_run is False and the deeper load-then-decide never ran
on a scheduled wake. The `record_consult:` telemetry that fired every 5 minutes
came from the shallower cio_wake_subject.decide, which is what made the node look
wired. The PR written to close the filing-cabinet defect reproduced it.
"""
import inspect
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

dispatcher = pytest.importorskip("scripts.lib.cio_wake_dispatcher")
subject = pytest.importorskip("scripts.lib.cio_wake_subject")


def _poll_source() -> str:
    return inspect.getsource(dispatcher.CIOWakeDispatcher.poll_and_dispatch)


def test_the_live_dispatch_path_calls_decide_after_load():
    """The load-order guarantee: it must be CALLED in poll_and_dispatch itself.

    Asserting the bare symbol is not enough — the import line alone satisfies it.
    A mutation that deleted the call but kept the import passed this test until
    it checked for an invocation, which is the whole point of mutation-testing a
    guard rather than trusting that it reads correctly.
    """
    src = _poll_source()
    assert re.search(r"_decide_after_load\s*\(", src), (
        "poll_and_dispatch imports decide_after_load but never INVOKES it — the "
        "live wake path still only runs the shallower subject consult"
    )
    assert "research_decision" in src, "the preflight result must be recorded"


def test_it_is_not_gated_behind_a_dry_run_flag():
    """The whole defect was a flag the cron does not pass."""
    src = _poll_source()
    assert "dry_run" not in src, (
        "the live dispatch path references dry_run; #810's contract must not be "
        "reachable only under a flag the installed cron omits"
    )


def test_preflight_runs_after_the_cadence_gate_not_before():
    """A deferred subject must cost nothing: skip first, preflight second.

    If the preflight ran before the cadence check, a record that says 'not due'
    would still pay for a research decision every cycle.
    """
    src = _poll_source()
    skip_at = src.find("_SKIP_CADENCE")
    call_at = src.find("_decide_after_load(")
    assert skip_at != -1 and call_at != -1
    assert skip_at < call_at, "preflight must come AFTER the cadence skip gate"


def test_preflight_failure_is_named_never_bare():
    """AGENTS.md §7: a swallowed alarm is how 24 days of outage stayed invisible."""
    src = _poll_source()
    seg = src[src.find("_decide_after_load("):]
    assert "except Exception as exc" in seg
    assert "research preflight failed" in seg, "a preflight failure must log"
    assert "except:" not in seg and "except Exception:\n" not in seg


# ── the evidence line must show whether it ran ───────────────────────────────

def test_summarise_counts_the_preflight():
    rows = [
        {"verdict": "PROCEED", "subject_resolved": True, "record_found": True,
         "research_decision": "research", "research_decide_called": True,
         "research_record_loaded": True},
        {"verdict": "PROCEED", "subject_resolved": True, "record_found": True,
         "research_decision": "skip", "research_decide_called": False,
         "research_record_loaded": True},
        {"verdict": "NO_SUBJECT"},
    ]
    out = subject.summarise(rows)
    assert out["research_preflight_called"] == 2
    assert out["research_decide_called"] == 1
    assert out["research_record_loaded"] == 2
    assert out["research_errors"] == 0


def test_summarise_counts_preflight_errors_separately():
    """An error must not read as a successful preflight."""
    out = subject.summarise([{"verdict": "PROCEED", "research_decision": "error"}])
    assert out["research_preflight_called"] == 1
    assert out["research_errors"] == 1
    assert out["research_decide_called"] == 0


def test_zero_when_nothing_ran():
    """The counters must not manufacture activity from an empty cycle."""
    out = subject.summarise([{"verdict": "NO_SUBJECT"}])
    assert out["research_preflight_called"] == 0
    assert out["research_decide_called"] == 0
    assert out["research_errors"] == 0


def test_decide_after_load_writes_nothing():
    """It is READ-ONLY. Wiring it into the claim path must add no store write."""
    pre = pytest.importorskip("scripts.lib.cio_research_preflight")
    src = inspect.getsource(pre.decide_after_load)
    for writer in ("upsert(", "persist_instrument_record", "write_text(", "json.dump("):
        assert writer not in src, f"decide_after_load performs a write: {writer}"
