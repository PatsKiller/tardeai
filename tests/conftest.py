"""Shared pytest hooks — block live side effects during unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# These four predate the pytest suite: they are standalone SCRIPTS whose entire
# body — including live database writes to trade_approvals and
# schwab_round_trips — runs at module import and then calls sys.exit(). pytest
# executes module bodies during COLLECTION, so importing any one of them raised
# SystemExit inside the collector and aborted the run with INTERNALERROR before
# a single test executed. `pytest tests/` was therefore collecting zero tests.
#
# CI never caught this because every workflow names its files explicitly
# (options-lifecycle-ci.yml:59) and none of them names these four — so CI stayed
# green while the full-suite command was completely broken.
#
# Ignored rather than converted: they exercise real broker approval and canary
# paths against a live database, which is a deliberate choice for a manually-run
# script and the wrong thing to have pytest trigger on collection. Run them
# directly: `.venv/bin/python tests/test_canary_gate.py`.
# (found 2026-07-20 while wiring the decision-packet suite)
def pytest_configure(config) -> None:
    config.addinivalue_line("markers", "tier0: R11 fast unit + contracts (<5 min)")
    config.addinivalue_line("markers", "tier1: R11 integration fixtures (<15 min)")


collect_ignore = [
    "test_broker_scaffold.py",
    "test_canary_exclusion.py",
    "test_canary_gate.py",
    "test_two_channel_approval.py",
]


@pytest.fixture(autouse=True)
def _block_options_monitor_live_telegram(monkeypatch):
    """Reconcile/orphan tests call real alert dispatch; never ping the operator bot."""
    from lib.options_pipeline import paper_position_alerts as ppa

    monkeypatch.setattr(ppa, "send_telegram", lambda _message: False)


@pytest.fixture(autouse=True)
def _block_all_telegram_http(monkeypatch):
    """Phase 1: hard-interdict telegram_transport.send_message for entire suite.

    No unit test may open api.telegram.org. Returns a structured blocked result.
    """
    def _blocked(**kwargs):
        return {
            "ok": False,
            "status_code": 0,
            "response": {"ok": False, "description": "PYTEST_INTERDICTED"},
            "interdicted": True,
        }

    try:
        import telegram_transport as tt
        monkeypatch.setattr(tt, "send_message", _blocked)
    except Exception:
        pass
    try:
        import scripts.telegram_transport as tt2  # type: ignore
        monkeypatch.setattr(tt2, "send_message", _blocked)
    except Exception:
        pass

@pytest.fixture(autouse=True)
def _block_alert_outbox_production_writes(monkeypatch):
    """Keep the alert outbox off the PRODUCTION database during unit tests.

    Found 2026-07-29. `tests/test_telegram_notification_normalization.py` calls
    publish_event() directly with no DB isolation, and alert_outbox._db() opens a
    connection to the live trade_ai database. Those writes used to fail — the
    outbox targeted a first-draft schema that no longer existed, so the calls
    raised and nothing landed. Repairing publish_event() turned a
    failing-and-harmless test into a passing-and-POLLUTING one: a single suite run
    wrote 3 incidents, 6 occurrences, 2 deliveries and a digest row into
    production alert tables.

    Returning None routes publish_event() to its designed in-memory path, which is
    what these tests actually assert against. Tests that genuinely need a database
    (test_alert_delivery_recording_db.py, test_alert_occurrence_persistence_db.py)
    monkeypatch _db themselves to an ISOLATED DSN and refuse any DSN naming
    trade_ai, so they override this and stay safe.
    """
    try:
        import alert_outbox
    except Exception:
        return
    monkeypatch.setattr(alert_outbox, "_db", lambda: None)


# ── C1 alarm-firing capture ──────────────────────────────────────────────────
# An alarm that has never been observed firing is indistinguishable from no alarm.
# Capture happens at the REAL transport boundary, telegram_transport.send_message,
# which telegram_alert binds at module level. Capturing at send_telegram itself
# would prove only that a function was called; capturing here proves the message
# reached the transport it claims to use, having survived the router. Nothing is
# sent -- the stub never touches the network.
from dataclasses import dataclass, field  # noqa: E402


@dataclass
class Captured:
    transport: list[dict] = field(default_factory=list)
    suppressed: list[str] = field(default_factory=list)

    @property
    def fired(self) -> bool:
        return bool(self.transport)

    def text(self) -> str:
        return "\n".join(m.get("text", "") for m in self.transport)

    def assert_fired(self, contains: str | None = None) -> None:
        assert self.transport, (
            "alarm did not reach the transport. "
            + (f"router suppressed {len(self.suppressed)}: {self.suppressed[:2]}"
               if self.suppressed else "nothing was produced at all")
        )
        if contains is not None:
            assert contains.lower() in self.text().lower(), (
                f"alarm fired but the message does not mention {contains!r}: "
                f"{self.text()[:200]!r}"
            )


@pytest.fixture
def alarm_capture(monkeypatch):
    """Capture outbound Telegram at the transport boundary. Sends nothing."""
    import telegram_alert as TA

    cap = Captured()

    def _fake_send_message(token=None, chat_id=None, text="", **kw):
        cap.transport.append({"chat_id": chat_id, "text": text})
        return {"ok": True, "status_code": 200}

    # Bound into telegram_alert's namespace by `from telegram_transport import ...`,
    # so patching the source module alone would not intercept it.
    monkeypatch.setattr(TA, "send_message", _fake_send_message, raising=True)
    monkeypatch.setattr(TA, "_token", lambda: "test-token", raising=False)
    monkeypatch.setattr(TA, "_chat_ids", lambda: ["test-chat"], raising=False)

    # Record router suppression instead of letting it silently swallow.
    try:
        import telegram_alert_router as TR

        real_should = TR.should_send_telegram

        def _record(msg, *a, **k):
            allowed = True
            try:
                allowed = bool(real_should(msg, *a, **k))
            except Exception:
                allowed = True
            if not allowed:
                cap.suppressed.append(msg[:120])
            return allowed

        monkeypatch.setattr(TR, "should_send_telegram", _record, raising=True)
        monkeypatch.setattr(TR, "mark_sent", lambda *a, **k: None, raising=False)
    except Exception:
        pass

    return cap
