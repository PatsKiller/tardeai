"""Tests for the Health Agent Telegram alert throttle (_alert_suppressed).

Covers the 2026-07-04 incidents:
- duplicate-scheduler pairs (cron :00/:30 + systemd timer :03/:33) — an identical
  snapshot minutes after an alert must be suppressed;
- evening status flapping (DEGRADED 67/68 <-> UNHEALTHY 59/60 as one check
  oscillated) — flipping back to a recently-alerted status at a similar score
  must NOT re-arm the throttle, while a genuine deterioration still alerts.
"""
import importlib
import json
import sys
import os
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

import health_agent  # noqa: E402

POLICY = {"alert": {"min_realert_minutes": 360, "realert_on_score_drop": 5,
                    "flap_suppress_minutes": 120}}


def _snap(status, score):
    return {"status": status, "overall_score": score}


def _setup(tmp_path):
    health_agent.ALERT_STATE = tmp_path / "alert_state.json"
    return health_agent.ALERT_STATE


def _age_state(state_file, minutes):
    """Rewind every timestamp in the persisted state by `minutes`."""
    st = json.loads(state_file.read_text())
    past = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    st["at"] = past
    for v in (st.get("recent") or {}).values():
        v["at"] = past
    state_file.write_text(json.dumps(st))


def test_first_alert_sends(tmp_path):
    _setup(tmp_path)
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is False


def test_duplicate_scheduler_pair_suppressed(tmp_path):
    """The 14:00 + 14:03 pair: identical status/score minutes later must not re-page."""
    _setup(tmp_path)
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is False
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is True


def test_new_status_alerts(tmp_path):
    _setup(tmp_path)
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is False
    assert health_agent._alert_suppressed(POLICY, _snap("unhealthy", 59)) is False


def test_flap_back_suppressed(tmp_path):
    """DEGRADED->UNHEALTHY->DEGRADED oscillation: the flip back is a flap, not news."""
    _setup(tmp_path)
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is False
    assert health_agent._alert_suppressed(POLICY, _snap("unhealthy", 59)) is False
    # flip back to a status alerted minutes ago at the same score -> suppressed
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is True
    # and the next flip to unhealthy at the same score is also a flap
    assert health_agent._alert_suppressed(POLICY, _snap("unhealthy", 60)) is True


def test_real_drop_during_flap_alerts(tmp_path):
    _setup(tmp_path)
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is False
    assert health_agent._alert_suppressed(POLICY, _snap("unhealthy", 59)) is False
    # unhealthy again but materially worse than the last unhealthy alert -> page
    assert health_agent._alert_suppressed(POLICY, _snap("unhealthy", 50)) is False


def test_heartbeat_realerts(tmp_path):
    state_file = _setup(tmp_path)
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is False
    _age_state(state_file, 361)
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is False


def test_flap_window_expiry_realerts_on_change(tmp_path):
    """After flap_suppress_minutes, a status change is treated as news again."""
    state_file = _setup(tmp_path)
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is False
    assert health_agent._alert_suppressed(POLICY, _snap("unhealthy", 59)) is False
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is True
    _age_state(state_file, 121)
    # the degraded alert is now >120min old: a change back to degraded is news again
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is False


def test_legacy_state_without_recent_map(tmp_path):
    """State written by the pre-flap-guard throttle (no 'recent' key) still works."""
    state_file = _setup(tmp_path)
    state_file.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(),
                                      "status": "degraded", "score": 67}))
    assert health_agent._alert_suppressed(POLICY, _snap("degraded", 67)) is True
    assert health_agent._alert_suppressed(POLICY, _snap("unhealthy", 59)) is False
