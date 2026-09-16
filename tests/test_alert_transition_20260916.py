"""Step 1 of the monitor consolidation: an alert has to survive.

Measured 2026-09-16, before this change: **7,830 `alert_events` rows, 100%
`lifecycle_state='active'`, 0 with a `telegram_message_id`**, and seven scheduled
monitors each re-implementing "suppress if the fingerprint is unchanged" — so a
permanently broken condition alerted exactly once and was then silent forever.
`check_expected_services` was suppressing a FAILED path unit since 00:13;
`check_data_source_health` had been sitting on finnhub's 401 for fifty-one days.

These are the four properties that were missing, exercised through a real
monitor rather than against the library in isolation.
"""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
# appended, not prepended: scripts/lib shadows same-named top-level scripts
sys.path.append(str(ROOT / "scripts" / "lib"))

import alert_transition as AT  # noqa: E402
import check_expected_services as ces  # noqa: E402

# No COVERS: the send_telegram site this drives is already declared by
# tests/test_expected_services_20260913.py, and claiming it twice would inflate
# the firing-coverage number without testing anything new.
COVERS = []


class _Captured:
    """Stands in for telegram_alert, including the id the transport returns."""

    def __init__(self):
        self.sent = []

    def send_telegram(self, message, **kwargs):
        self.sent.append(message)
        return True

    def last_message_id(self):
        return "4242"


@pytest.fixture
def wired(monkeypatch, tmp_path):
    cap = _Captured()
    mod = types.ModuleType("telegram_alert")
    mod.send_telegram = cap.send_telegram
    mod.last_message_id = cap.last_message_id
    monkeypatch.setitem(sys.modules, "telegram_alert", mod)
    monkeypatch.setattr(ces, "STATE_PATH", tmp_path / "state.json")
    return cap


class _Writer:
    """Records what would have reached alert_events. Nothing touches the database."""

    def __init__(self):
        self.saved = []
        self.resolved = []

    def save_alert_event(self, **kw):
        self.saved.append(kw)
        return 1000 + len(self.saved)

    def resolve_alert_events(self, **kw):
        self.resolved.append(kw)
        return 3


@pytest.fixture
def writer(monkeypatch):
    w = _Writer()
    # conftest turns the real writer off for the whole suite; this test is the
    # one that wants to watch it, against a fake.
    monkeypatch.setenv("TRADEAI_ALERT_EVENT_DB", "1")
    monkeypatch.setattr(AT, "_writer", lambda: w)
    return w


OFF = [{"name": "tradeai-hermes-cio-worker.path", "status": "FAILED"}]
WORSE = OFF + [{"name": "tradeai-cio-telegram.service", "status": "DISABLED"}]


def _age_last_notification(path, key, minutes):
    """Move the last notification back in time so the heartbeat clock elapses."""
    doc = json.loads(Path(path).read_text())
    when = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    doc["conditions"][key]["last_notify_at"] = when.isoformat()
    Path(path).write_text(json.dumps(doc))


# ── the interval is not a new number ─────────────────────────────────────────


def test_the_heartbeat_interval_is_the_one_operations_already_specifies():
    """OPERATIONS.md:71-75 declares 360 for the health agent's throttle."""
    assert AT.MIN_REALERT_MINUTES == 360
    doc = (ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
    assert "min_realert_minutes" in doc and "360" in doc


# ── the defect ───────────────────────────────────────────────────────────────


def test_a_permanently_broken_condition_is_heard_from_again(wired):
    """THE defect: it alerted once and then never again, however long it stayed broken."""
    ces._alert(OFF)
    assert len(wired.sent) == 1

    ces._alert(OFF)
    assert len(wired.sent) == 1, "inside the window it must stay quiet"

    _age_last_notification(ces.STATE_PATH, ces.CONDITION_KEY, AT.MIN_REALERT_MINUTES + 1)
    ces._alert(OFF)
    assert len(wired.sent) == 2, "past the heartbeat window it must speak again"
    assert "tradeai-hermes-cio-worker.path" in wired.sent[1]


def test_an_escalation_breaks_through_the_window_at_once(wired):
    """A second unit going down is new information, not a repeat."""
    ces._alert(OFF)
    ces._alert(WORSE)
    assert len(wired.sent) == 2
    assert "tradeai-cio-telegram.service" in wired.sent[1]
    assert "NEW since the last run" in wired.sent[1]


# ── the alert is recorded where it can be acknowledged ───────────────────────


def test_the_transition_is_recorded_with_its_telegram_message_id(wired, writer):
    """The id existed at the transport and was discarded one frame later."""
    ces._alert(OFF)

    assert len(writer.saved) == 1, "a transition must write exactly one row"
    row = writer.saved[0]
    assert row["telegram_message_id"] == "4242"
    assert row["alert_type"] == AT.TYPE_SYSTEM_HEALTH
    assert row["source_script"] == "check_expected_services.py"
    assert row["parsed_payload"]["condition_key"] == ces.CONDITION_KEY
    assert row["parsed_payload"]["transition"] == "new"


def test_a_suppressed_run_writes_no_row(wired, writer):
    """One row per transition, not one per run, or the store fills with noise."""
    ces._alert(OFF)
    ces._alert(OFF)
    assert len(writer.saved) == 1


def test_recovery_resolves_instead_of_only_printing_a_tick(wired, writer):
    """Every one of the seven computed a recovery branch and emitted it as prose."""
    ces._alert(OFF)
    ces._alert([])

    assert writer.resolved, "a recovered condition must advance lifecycle_state"
    assert writer.resolved[0]["condition_key"] == ces.CONDITION_KEY
    assert writer.resolved[0]["source_script"] == "check_expected_services.py"
    assert writer.saved[-1]["parsed_payload"]["transition"] == "recovered"


# ── the finding is never lost ────────────────────────────────────────────────


def test_a_failed_send_does_not_consume_the_transition(monkeypatch, tmp_path, writer):
    """Advancing state before the transport is confirmed loses the alert entirely:
    the next run reads it as already told and says nothing."""
    boom = types.ModuleType("telegram_alert")

    def _boom(message, **kwargs):
        raise RuntimeError("transport down")

    boom.send_telegram = _boom
    monkeypatch.setitem(sys.modules, "telegram_alert", boom)
    monkeypatch.setattr(ces, "STATE_PATH", tmp_path / "s.json")

    ces._alert(OFF)
    assert writer.saved == [], "nothing was delivered, so nothing may be recorded"

    cap = _Captured()
    working = types.ModuleType("telegram_alert")
    working.send_telegram = cap.send_telegram
    working.last_message_id = cap.last_message_id
    monkeypatch.setitem(sys.modules, "telegram_alert", working)

    ces._alert(OFF)
    assert len(cap.sent) == 1, "the finding survived the failed send"


# ── negative control ─────────────────────────────────────────────────────────


def test_a_healthy_condition_that_was_never_bad_says_nothing(wired, writer):
    """An all-clear with nothing open is not news, and must not page."""
    ces._alert([])
    assert wired.sent == []
    assert writer.saved == []
