"""R-04 (2026-09-15): a research lane that recovers stops firing in the health agent."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import research_lane_health as rlh  # noqa: E402

STALE = {
    "current-pin": {"lane": "current-pin", "ok": False, "firing": ["tree_diff:1"], "as_of": "2026-09-08T22:15:36+00:00",
                    "last_alert": 1788905741, "signature": "current-pin|tree_diff:1", "since": 1788905741},
    "cio-hermes-queue": {"lane": "cio-hermes-queue", "ok": False, "firing": ["failure_rate_24h:15/37"],
                         "last_alert": 1789484979, "signature": "cio-hermes-queue|failure_rate_24h:15/37"},
}


def test_a_lane_evaluated_ok_is_recorded_ok():
    report = {"as_of": "2026-09-15T16:10:00+00:00", "lanes": [{"lane": "current-pin", "ok": True},
                                                            {"lane": "cio-hermes-queue", "ok": False}]}
    state = rlh.reconcile_recovered(STALE, report)
    assert state["current-pin"]["ok"] is True and state["current-pin"]["firing"] == []
    assert state["current-pin"]["last_alert"] == 1788905741
    assert state["cio-hermes-queue"]["ok"] is False  # still firing: untouched here


def test_unchanged_firing_lane_carries_the_current_row_not_the_old_one(monkeypatch, tmp_path):
    """The suppressed row must still carry today's evidence.

    The lane is primed by a real first alert, because the suppression decision
    now lives in the shared state machine rather than in this file's lane map —
    and _deliver_telegram is stubbed so the check never reaches the network.
    """
    monkeypatch.setattr(rlh, "STATUS_PATH", tmp_path / "research_lane_health.json")
    sent = []
    monkeypatch.setattr(rlh, "_deliver_telegram", lambda msg: sent.append(msg))

    old = {"lane": "drive-sync", "ok": False, "firing": ["exit_code:1"], "exit_code": 1,
           "finished_utc": "2026-09-15T12:07:00+00:00"}
    rlh._alert({"as_of": "2026-09-15T12:08:12+00:00", "lanes": [old]})
    assert len(sent) == 1, "the first observation of a firing lane speaks"

    row = {"lane": "drive-sync", "ok": False, "firing": ["exit_code:1"], "exit_code": 1,
           "finished_utc": "2026-09-15T15:06:35+00:00"}
    rlh._alert({"as_of": "2026-09-15T16:10:00+00:00", "lanes": [row]})
    assert len(sent) == 1, "an unchanged lane stays quiet inside its window"

    saved = rlh._load_lane_map()["drive-sync"]
    assert saved["finished_utc"] == "2026-09-15T15:06:35+00:00" and saved["suppressed"] is True


def test_health_agent_ignores_lanes_that_are_not_false():
    src = (ROOT / "scripts" / "health_agent.py").read_text()
    assert 'row.get("ok") is not False' in src
