"""Cutover checklist: an operator-forced live n8n fire is §23.21 criterion (4) evidence (2026-10-21).

AGENTS.md §23.21 (16.0.0, PROPOSED; rebuilt from 8.0.0 / PR #1727): a lane is cutover-ready after at least one
successful live n8n run with the cron line still present under the shared lock, and "a forced live relay fire counts
when the operator forces it inside the lane's window". `scripts/n8n_cutover_checklist.py` accepted only a natural
dispatcher slot (NATURAL_CANARY) or the §23.12 weekly/monthly natural-equivalent manual fire (MANUAL_CANARY); an
operator-forced live fire had no evidence class and was silently ignored (#1727's open follow-up).

`OPERATOR_FORCED_LIVE` closes that, and only under the §23.21 / §8.1 / §23.25 bounds:
  * the n8n execution is a manual trigger (a forced fire, never a schedule slot passed off as one);
  * `forced_by` is "operator" and `operator_ref` names the operator's word or grant (an agent-forced live fire is
    not this evidence: §23.25 says an F09 lane's live proof never comes from an agent forcing a live run);
  * `window_gate_overridden` is explicitly False (§8.1: a clock-gated lane is fired in its window, never with the
    gate overridden);
  * every other correlation the canary already demands (legacy lock = live lock, cron still authoritative, current
    SHA, business-effect proof, no duplicate effects) still holds.

Hermetic: evidence is planted under tmp_path, reusing the fixture of tests/test_n8n_cutover_checklist_20261008.py.
"""

from __future__ import annotations

import pytest

from scripts import n8n_cutover_checklist as cl
from tests.test_n8n_cutover_checklist_20261008 import LANE, _acceptance, _items

FORCED = "OPERATOR_FORCED_LIVE"


def _forced(tmp_path, **overrides):
    """The shared fixture with its one manual live canary re-labelled as an operator-forced live fire."""
    packet = _acceptance(tmp_path)
    obs = packet["lanes"][LANE]["runs"][2]
    assert obs["evidence_class"] == "MANUAL_CANARY" and obs["ledger_run"]["mode"] == "live"
    obs.update(
        {
            "evidence_class": FORCED,
            "forced_by": "operator",
            "operator_ref": 'operator 2026-10-21 in session: "push live now"',
            "window_gate_overridden": False,
        }
    )
    for key, value in overrides.items():
        if value is None:
            obs.pop(key, None)
        else:
            obs[key] = value
    return packet


def test_operator_forced_live_fire_is_accepted_as_canary_evidence(tmp_path):
    items = _items(tmp_path, _forced(tmp_path))
    assert items["canary"]["done"], items["canary"]["evidence"]
    assert f"{FORCED}=1" in items["canary"]["evidence"]


def test_evidence_class_is_declared():
    assert FORCED in cl.EVIDENCE_CLASSES
    assert FORCED in (cl.__doc__ or "")


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"forced_by": "agent"}, "operator"),
        ({"forced_by": None}, "operator"),
        ({"operator_ref": ""}, "operator"),
        ({"operator_ref": None}, "operator"),
        ({"window_gate_overridden": True}, "window"),
        ({"window_gate_overridden": None}, "window"),
        ({"legacy_authoritative": False}, "legacy authority"),
    ],
)
def test_forced_live_fire_without_operator_attribution_or_inside_bounds_is_refused(tmp_path, overrides, reason):
    items = _items(tmp_path, _forced(tmp_path, **overrides))
    assert not items["canary"]["done"]
    assert reason in items["canary"]["evidence"], items["canary"]["evidence"]


def test_forced_fire_cannot_pose_as_a_schedule_slot(tmp_path):
    packet = _forced(tmp_path)
    packet["lanes"][LANE]["runs"][2]["n8n_execution"]["trigger_kind"] = "schedule"
    items = _items(tmp_path, packet)
    assert not items["canary"]["done"]
    assert "DRIFT" in items["canary"]["evidence"]


def test_forced_dry_run_is_not_live_evidence(tmp_path):
    packet = _forced(tmp_path)
    obs = packet["lanes"][LANE]["runs"][0]
    obs.update(
        {"evidence_class": FORCED, "forced_by": "operator", "operator_ref": "x", "window_gate_overridden": False}
    )
    obs["n8n_execution"]["trigger_kind"] = "manual"
    items = _items(tmp_path, packet)
    assert "evidence class/mode mismatch" in items["canary"]["evidence"]
    assert not items["canary"]["done"]


def test_natural_and_manual_canaries_keep_their_meaning(tmp_path):
    # The unchanged fixture (MANUAL_CANARY) still ticks the canary; the new class widens nothing else.
    items = _items(tmp_path, _acceptance(tmp_path))
    assert items["canary"]["done"] and f"{FORCED}=0" in items["canary"]["evidence"]
