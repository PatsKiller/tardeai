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
