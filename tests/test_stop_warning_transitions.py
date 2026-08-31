"""A stop warning notifies on transitions, not on every evaluation.

AES #825 produced 40 STOP_WARNING alerts over four trading days -- 83% of every
row in open_trade_alerts -- because `already_alerted` keys on
(trade_id, alert_type) with a 30-minute window against a 3-minute evaluation
cadence. That is a repeat-every-30-minutes instruction, not a dedupe window.

Three acknowledgement mechanisms existed and this producer read none: stop_snooze
and stop_decisions HOLD_OVERRIDE, both honoured by portfolio_stops.py, and
open_trade_alerts.acknowledged, never written in 864 rows. The operator's own
Hold button wrote to a table nobody consulted.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ("scripts", "scripts/lib"):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

from alert_condition_state import observe  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return tmp_path / "conditions.json"


def test_an_unchanged_condition_does_not_renotify(store):
    """The regression. 40 evaluations in-band must produce one notification."""
    notifies = sum(
        bool(observe("stop_warning:825", "warn_band", alertable=True, path=store).get("notify"))
        for _ in range(40)
    )
    assert notifies == 1, f"expected 1 notification across 40 evaluations, got {notifies}"


def test_the_old_behaviour_would_have_sent_many(store):
    """Guard the guard: prove the 30-minute key really does repeat.

    Without this the test above would pass against a producer that never
    notifies at all, which is a different defect.
    """
    sends, last = 0, -999
    for i in range(40):
        minute = i * 3
        if minute - last >= 30:
            sends += 1
            last = minute
    assert sends > 1, "the old dedupe no longer reproduces the repeat"


def test_recovery_notifies_once(store):
    observe("stop_warning:825", "warn_band", alertable=True, path=store)
    for _ in range(10):
        observe("stop_warning:825", "warn_band", alertable=True, path=store)
    r = observe("stop_warning:825", "clear", alertable=False, path=store)
    assert r.get("notify"), "leaving the band must notify once"
    again = observe("stop_warning:825", "clear", alertable=False, path=store)
    assert not again.get("notify"), "a cleared condition must not renotify"


def test_reentering_the_band_notifies_again(store):
    observe("stop_warning:825", "warn_band", alertable=True, path=store)
    observe("stop_warning:825", "clear", alertable=False, path=store)
    r = observe("stop_warning:825", "warn_band", alertable=True, path=store)
    assert r.get("notify"), "re-entry is a real transition and must notify"


def test_the_producer_reads_the_acknowledgement_stores():
    """The three mechanisms that existed and were never consulted."""
    src = (ROOT / "scripts" / "open_trade_monitor.py").read_text(encoding="utf-8")
    assert "stop_snooze" in src
    assert "HOLD_OVERRIDE" in src
    assert "acknowledged" in src


def test_the_durable_row_is_still_written_when_the_alert_is_suppressed():
    """Record and notification are different concerns.

    Suppressing the interrupt must not suppress the audit row -- the history is
    the only evidence of what the monitor saw.
    """
    src = (ROOT / "scripts" / "open_trade_monitor.py").read_text(encoding="utf-8")
    warn = src.split("elif price <= entry - 0.50 * stop_dist:", 1)[1]
    insert_at = warn.index("insert_alert(")
    gate_at = warn.index("_stop_warning_notify_decision(")
    assert insert_at < gate_at, "the durable row must be written before the notify gate"
