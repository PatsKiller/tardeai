"""ANCHOR: SCHEDULER_PRESENCE_LQ318_20261107 — a declared scheduler is not missing because the matcher looked elsewhere.

`/v3/health` lane-registry read 36 ORPHANED on 2026-11-07T21:55Z. Twelve were rows whose cron line
the n8n cutover retired (a registry declaration belongs to the lead, not to this module). Ten more
were the monitor asking the wrong question, in three shapes measured on the live registry:

* **systemd `match` ignored.** `scheduler.expression` is the operator-facing label
  ("tradeai-health-tick.timer (*:0/5)") and `scheduler.match` is the unit, or the reverse
  (`tmp-hygiene-apply`: expression is the unit, match is the script). The old code compared only
  `expression` to the unit name, so six live timers read ORPHANED — telling the operator to fix a
  scheduler that was running.
* **`<unit> step <id>`.** A health-tick step is not a unit; its scheduler is the timer and its
  membership is `config/health_tick_steps.json`. Asking for a unit by the step's name failed by
  construction.
* **a list `match`.** An off-peak line plus its plain twin carry two markers; `str(match)` is a
  Python repr that matches no crontab line (`find_undeclared` was taught this on 2026-11-07; the
  presence check was not).
* **`kind: none`.** Three ACTIVE rows declare that an operator action triggers them. A declared
  absence was being read as an absence that was not declared.

Every test is a pair: the shape that must read present, and a control that must still read absent,
so the fix cannot pass by returning True everywhere.

COVERS: scripts/lib/lane_registry.py::_scheduler_present
COVERS: scripts/lib/lane_registry.py::_health_tick_step_declared
COVERS: scripts/lib/lane_registry.py::evaluate_lane

Hermetic: synthetic rows, a synthetic `found` map, and a step config written under tmp_path. No
database, no systemd, no crontab, no host state.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts.lib import lane_registry as LR

NOW = datetime(2026, 11, 7, 22, 0, tzinfo=timezone.utc)
TIMER = "tradeai-health-tick.timer"
TIMER_LINE = f"{TIMER} 2026-11-01 00:00:00 UTC"


def _found(cron=(), timers=(), units=()):
    return {
        "cron": [{"expression": line} for line in cron],
        "systemd": [{"expression": unit, "enabled_state": "enabled"} for unit in timers],
        "systemd_services": [{"expression": unit, "enabled_state": "enabled"} for unit in units],
    }


def _row(lane_id="lane", kind="systemd", expression="", match=None, cadence_h=1.0):
    sched = {"kind": kind, "expression": expression}
    if match is not None:
        sched["match"] = match
    return {
        "lane_id": lane_id,
        "state": "ACTIVE",
        "scheduler": sched,
        "expected_cadence_hours": cadence_h,
        "output_signal": {"kind": "none"},
    }


# --------------------------------------------------------------------------- systemd: the unit is in either field


def test_systemd_label_expression_with_the_unit_in_match_is_present():
    """The live shape: expression carries the label, match carries the unit."""
    row = _row(expression=f"{TIMER} (*:0/5)", match=TIMER)
    assert LR._scheduler_present(row, _found(timers=[TIMER]), now=NOW) is True


def test_systemd_unit_expression_with_a_script_match_is_present():
    """`tmp-hygiene-apply`: the reverse shape, so testing only one field orphans this row."""
    row = _row(expression="tradeai-tmp-hygiene-apply.service", match="scripts/tmp_hygiene_auto.py --apply")
    assert LR._scheduler_present(row, _found(units=["tradeai-tmp-hygiene-apply.service"]), now=NOW) is True


def test_systemd_unit_absent_from_both_fields_is_absent():
    """Control: the widened matcher must not declare every systemd row present."""
    row = _row(expression="wt/livefix-cc-deepseek-4-lq318-retired.timer", match="scripts/gone.py")
    assert LR._scheduler_present(row, _found(timers=[TIMER]), now=NOW) is False


# --------------------------------------------------------------------------- health-tick steps


@pytest.fixture()
def step_config(tmp_path, monkeypatch):
    """`_health_tick_step_declared` resolves against the module ROOT, so point it at tmp_path."""
    (tmp_path / "config").mkdir()
    path = tmp_path / "config" / "health_tick_steps.json"
    path.write_text(json.dumps({"steps": [{"step_id": "premarket-delivery-deadman", "cadence_minutes": 15}]}))
    monkeypatch.setattr(LR, "ROOT", tmp_path)
    return path


def test_health_tick_step_is_present_when_the_timer_and_the_step_both_exist(step_config):
    row = _row("premarket-delivery-deadman", expression=f"{TIMER} step premarket-delivery-deadman")
    assert LR._scheduler_present(row, _found(timers=[TIMER]), now=NOW) is True


def test_health_tick_step_is_absent_when_the_step_was_deleted(step_config):
    """Control: the step's own membership is still a question — a deleted step is a real orphan."""
    row = _row("removed-step", expression=f"{TIMER} step removed-step")
    assert LR._scheduler_present(row, _found(timers=[TIMER]), now=NOW) is False


def test_health_tick_step_is_absent_when_the_timer_is_gone(step_config):
    """Control: a step whose unit is not running has no scheduler, whatever the config says."""
    row = _row("premarket-delivery-deadman", expression=f"{TIMER} step premarket-delivery-deadman")
    assert LR._scheduler_present(row, _found(timers=[]), now=NOW) is False


def test_a_step_row_with_an_unreadable_config_does_not_invent_an_orphan(tmp_path, monkeypatch):
    """Fail-open on the config read, like every other single missing source in these checkers.

    The timer is the scheduler; a step deleted from the config goes stale through its own output
    signal, so an unreadable file is not evidence that anything was orphaned.
    """
    monkeypatch.setattr(LR, "ROOT", tmp_path)
    row = _row("premarket-delivery-deadman", expression=f"{TIMER} step premarket-delivery-deadman")
    assert LR._scheduler_present(row, _found(timers=[TIMER]), now=NOW) is True


# --------------------------------------------------------------------------- cron: match may be a list


def _cron_row(match, lane_id="research-intelligence-queue"):
    return _row(lane_id, kind="cron", expression="45 16 * * 1-5", match=match)


LINES = [
    "45 16 * * 1-5 cd $PROJ && flock -n /tmp/q.lock $PY scripts/q.py --drain",
    "40 2 * * * cd $PROJ && bash wrap.sh --official -- flock -n /tmp/q.lock $PY scripts/q.py --drain",
]


def test_cron_list_match_is_present_when_any_item_hits():
    row = _cron_row(["&& flock -n /tmp/q.lock $PY scripts/q.py", "--official -- flock -n /tmp/q.lock $PY scripts/q.py"])
    assert LR._scheduler_present(row, _found(cron=LINES), now=NOW) is True


def test_cron_list_match_is_absent_when_no_item_hits():
    """Control: a repr never matched a line, and a marker that matches nothing still must not."""
    row = _cron_row(["scripts/not_in_any_line.py", "scripts/also_absent.py"])
    assert LR._scheduler_present(row, _found(cron=LINES), now=NOW) is False


# --------------------------------------------------------------------------- kind: none (on-demand)


def test_on_demand_row_is_present():
    """advisory-desk-run-now and friends: nothing schedules them, so nothing can orphan them."""
    row = _row("advisory-desk-run-now", kind="none", expression="on-demand: operator POST /api/v2/advisory/run")
    assert LR._scheduler_present(row, _found(), now=NOW) is True


def test_kind_none_without_an_on_demand_expression_is_still_absent():
    """Control: `kind: none` on its own is not an assertion that a trigger exists."""
    row = _row("mystery", kind="none", expression="")
    assert LR._scheduler_present(row, _found(), now=NOW) is False


# --------------------------------------------------------------------------- the verdict, not just the boolean


@pytest.mark.parametrize(
    "row, found",
    [
        (_row("label-row", expression=f"{TIMER} (*:0/5)", match=TIMER), _found(timers=[TIMER])),
        (_row("on-demand", kind="none", expression="on-demand: operator run"), _found()),
        (_cron_row(["scripts/q.py"]), _found(cron=LINES)),
    ],
)
def test_evaluate_lane_no_longer_calls_these_rows_orphaned(tmp_path, row, found):
    """`output_signal.kind == none` grades UNVERIFIABLE, never LIVE — a clean discriminator."""
    verdict = LR.evaluate_lane(row, now=NOW, found=found, root=tmp_path)["verdict"]
    assert verdict != LR.ORPHANED
    assert verdict == LR.UNVERIFIABLE


def test_evaluate_lane_still_orphans_a_row_whose_scheduler_is_really_gone(tmp_path):
    """Control: ORPHANED must remain reachable, or the monitor has been silenced rather than fixed."""
    row = _row("gone", expression="wt/livefix-cc-deepseek-4-lq318-retired.timer")
    assert LR.evaluate_lane(row, now=NOW, found=_found(), root=tmp_path)["verdict"] == LR.ORPHANED
