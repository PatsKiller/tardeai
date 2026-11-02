"""A transient apply-time evidence capture must not abort a whole standing pass (2026-11-02).

The standing path re-captures the complete evidence set before EVERY removal. Measured on this host: one
capture in forty raised ``evidence_opaque_processes`` — a short-lived process whose cwd/fds the kernel hides
and whose ancestry cannot be read. With no retry, that single event ended the pass at
``evidence_recheck_unavailable`` and re-held every item not yet removed; it is why two consecutive 13- and
16-item runs both stopped early.

The retry never weakens the guard: a failed attempt is retried, and if it keeps failing the apply still
refuses — now naming the check instead of the opaque ``evidence_recheck_unavailable`` alone.
"""
from __future__ import annotations

from datetime import datetime, timezone

from scripts import disk_hygiene as DH
from scripts.lib import disk_hygiene_retention as SR

NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def _evidence(*, opaque: bool = False, incomplete: str | None = None) -> dict:
    processes = [{"pid": "1234", "opaque": True, "uid": 0, "own_uid": False, "comm": "hidden"}] if opaque else []
    values = {
        "cron": "",
        "units": [],
        "processes": processes,
        "pointers": [],
        "prs": [],
        "coordination": {"references": [], "live_claims": [], "live_worklogs": []},
    }
    doc = {
        "schema": SR.SCHEMA,
        "offline": False,
        "sources": {
            key: {"complete": True, "captured_at": NOW.isoformat(), "data": val, "sha256": SR.digest(val)}
            for key, val in values.items()
        },
    }
    if incomplete:
        doc["sources"][incomplete]["complete"] = False
        doc["sources"][incomplete]["reason"] = incomplete + "_unavailable"
    return doc


def test_a_clean_capture_is_used_on_the_first_attempt(monkeypatch):
    calls = []
    monkeypatch.setattr(DH, "collect_standing_evidence", lambda *a, **k: calls.append("capture") or _evidence())

    ctx, reason = DH.revalidate_evidence({}, NOW, sleep=calls.append)

    assert reason is None and ctx is not None
    assert calls == ["capture"], "a clean capture must never sleep or re-capture"


def test_a_transient_opaque_process_is_retried_and_the_pass_continues(monkeypatch):
    """The exact 2026-11-02 failure: one opaque capture, gone on the next attempt."""
    sequence = [_evidence(opaque=True), _evidence()]
    sleeps = []
    monkeypatch.setattr(DH, "collect_standing_evidence", lambda *a, **k: sequence.pop(0))

    ctx, reason = DH.revalidate_evidence({}, NOW, sleep=sleeps.append)

    assert reason is None, "a transient opaque process must not end the pass"
    assert ctx is not None
    assert sleeps == [DH.EVIDENCE_RECHECK_DELAY_S], "one bounded retry, after the configured delay"
    assert sequence == [], "the second capture was used"


def test_an_opaque_process_that_persists_still_refuses_and_is_named(monkeypatch):
    monkeypatch.setattr(DH, "collect_standing_evidence", lambda *a, **k: _evidence(opaque=True))
    sleeps = []

    ctx, reason = DH.revalidate_evidence({}, NOW, sleep=sleeps.append)

    assert ctx is None, "absence is never proven by an opaque capture"
    assert reason == "evidence_opaque_processes", "the refusing check must be named, not swallowed"
    assert len(sleeps) == DH.EVIDENCE_RECHECK_ATTEMPTS - 1


def test_an_incomplete_source_is_retried_then_named(monkeypatch):
    monkeypatch.setattr(DH, "collect_standing_evidence", lambda *a, **k: _evidence(incomplete="prs"))

    ctx, reason = DH.revalidate_evidence({}, NOW, sleep=lambda _s: None)

    assert ctx is None
    assert reason == "evidence_incomplete:prs"


def test_the_attempt_count_is_bounded(monkeypatch):
    seen = []

    def capture(*_a, **_k):
        seen.append(1)
        return _evidence(opaque=True)

    monkeypatch.setattr(DH, "collect_standing_evidence", capture)
    DH.revalidate_evidence({}, NOW, attempts=2, sleep=lambda _s: None)

    assert len(seen) == 2, "the retry is bounded; it must not loop"


def test_the_apply_report_carries_a_refusal_detail_field():
    """The receipt must be able to say which check refused (§0 rule 8)."""
    import inspect

    source = inspect.getsource(DH.apply)
    assert '"refusal_detail"' in source
