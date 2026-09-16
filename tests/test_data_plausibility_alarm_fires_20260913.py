"""C1 firing test — the plausibility alarm actually fires, and says something useful.

An alarm nobody has watched fire is indistinguishable from no alarm. This injects
the condition and asserts on the message body, the escalation, and the silence.

The escalation assertions are the important ones. `telegram_alert_router` routes
on the literal word CRITICAL, so that word is the difference between an interrupt
and a message that sits in a 4-hourly digest. Measured during this campaign:
send_telegram returned True for a real alert and True meant "suppressed into the
P1 digest" -- accepted by the platform is not received by the operator. So a NEW
violation must carry the word and a known-open one must not, or the alarm is
either useless or wallpaper.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import data_plausibility_monitor as dpm  # noqa: E402

# Declares to the C1 gate that this file's send_telegram sites have a firing test.
COVERS = ["scripts/data_plausibility_monitor.py"]


class _Captured:
    """Stands in for telegram_alert, recording what would have been sent."""

    def __init__(self, accept=True):
        self.sent = []
        self.accept = accept

    def send_telegram(self, message, **kwargs):
        self.sent.append({"message": message, "kwargs": kwargs})
        return self.accept


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """Redirect state to tmp and capture egress. Never touches the real bot."""
    cap = _Captured()
    module = type(sys)("telegram_alert")
    module.send_telegram = cap.send_telegram
    monkeypatch.setitem(sys.modules, "telegram_alert", module)
    monkeypatch.setattr(dpm, "STATE_PATH", tmp_path / "state.json")
    return cap


def _violation(table, column, violations=5, total=100, detail="rule=range"):
    return {
        "table": table,
        "column": column,
        "severity": "BLOCK",
        "status": "VIOLATION",
        "violations": violations,
        "total": total,
        "detail": detail,
        "samples": ["-99.7"],
    }


def test_alarm_fires_and_names_the_column_and_the_counts(wired):
    bad = _violation("analyst_consensus_history", "recom_score", 130155, 132894)
    dpm._alert([bad], [bad])

    assert len(wired.sent) == 1, "a BLOCK violation must reach the operator"
    body = wired.sent[0]["message"]
    assert "analyst_consensus_history.recom_score" in body
    assert "130,155" in body and "132,894" in body
    assert "97.9%" in body


def test_a_new_violation_escalates_to_an_interrupt(wired):
    """A new violation must actually route P0, not merely sound urgent.

    This test used to assert the word "CRITICAL" was in the body. That was
    wrong: telegram_alert_router consults operator_alert_policy_v2 FIRST and
    returns on its verdict, so the prose never reached _P0_PATTERNS. The alert
    said CRITICAL and sat in the 4-hourly digest anyway. Assert the routing.
    """
    bad = _violation("indicator_confluence_cache", "stop_price", 17, 1817)
    dpm._alert([bad], [bad])

    body = wired.sent[0]["message"]
    assert "[DATA_INTEGRITY]" in body, "the sentinel is what routes this, not the wording"
    assert "NEW since the last run" in body

    sys.path.insert(0, str(Path(dpm.PROJECT_ROOT) / "scripts"))
    from telegram_alert_router import classify_alert

    assert classify_alert(body) == "P0_INTERRUPT"


def test_a_known_open_violation_does_not_escalate(wired, tmp_path):
    """Already-reported debt must not interrupt, or the alarm becomes wallpaper.

    Primed by a real first run at a different count, so the "already reported"
    state is the one the shared state machine actually keeps.
    """
    first = _violation("trade_ai_scans", "catalyst_confidence", 900, 5311)
    dpm._alert([first], [first])
    wired.sent.clear()

    bad = _violation("trade_ai_scans", "catalyst_confidence", 915, 5311)
    dpm._alert([bad], [bad])

    body = wired.sent[0]["message"]
    assert "CRITICAL" not in body, "a known-open violation must not interrupt"
    assert "trade_ai_scans.catalyst_confidence" in body
    assert "NEW since the last run" not in body, "the column was already reported"


def test_a_changed_count_is_news_and_re_alerts(wired):
    """A violation going from 8 rows to 900 is not 'unchanged'."""
    dpm._alert([_violation("symbol_profiles", "ytd_return_pct", 8, 2945)],
               [_violation("symbol_profiles", "ytd_return_pct", 8, 2945)])
    wired.sent.clear()
    worse = _violation("symbol_profiles", "ytd_return_pct", 900, 2945)
    dpm._alert([worse], [worse])
    assert len(wired.sent) == 1, "a materially changed count must speak"


def test_an_unchanged_picture_stays_silent(wired):
    """Same columns, same counts: say nothing rather than train the reader to ignore."""
    bad = _violation("symbol_profiles", "ytd_return_pct", 266, 2945)
    dpm._alert([bad], [bad])
    wired.sent.clear()

    dpm._alert([bad], [bad])

    assert wired.sent == [], "an identical run must not re-alert"


def test_recovery_is_reported_once(wired):
    """Going clean is news exactly once."""
    bad = _violation("symbol_profiles", "ytd_return_pct", 266, 2945)
    dpm._alert([bad], [bad])
    wired.sent.clear()

    dpm._alert([], [])

    assert len(wired.sent) == 1
    assert "✅" in wired.sent[0]["message"]

    # And the next clean run is silent.
    dpm._alert([], [])
    assert len(wired.sent) == 1


def test_state_is_recorded_so_the_next_run_can_compare(wired):
    """The finding set is kept — now as the shared machine's condition state."""
    bad = _violation("proposal_agent_reviews", "confidence", 12, 4479)
    dpm._alert([bad], [bad])

    doc = json.loads(dpm.STATE_PATH.read_text())
    condition = doc["conditions"][dpm.CONDITION_KEY]
    assert json.loads(condition["state"]) == {"proposal_agent_reviews.confidence": 12}
    assert condition["alertable"] is True


def test_a_send_failure_never_masks_the_finding(monkeypatch, tmp_path, capsys):
    """An alerting fault must not swallow what it was carrying."""
    module = type(sys)("telegram_alert")

    def _boom(message, **kwargs):
        raise RuntimeError("telegram unreachable")

    module.send_telegram = _boom
    monkeypatch.setitem(sys.modules, "telegram_alert", module)
    monkeypatch.setattr(dpm, "STATE_PATH", tmp_path / "state.json")

    bad = _violation("proposal_execution_readiness", "spread_pct", 9, 17205)
    dpm._alert([bad], [bad])  # must not raise

    err = capsys.readouterr().err
    assert "FAILED to send" in err
    assert "still stand" in err
    # State must NOT advance on a failed send, or the finding is lost silently.
    assert not dpm.STATE_PATH.exists()
