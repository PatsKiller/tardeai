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