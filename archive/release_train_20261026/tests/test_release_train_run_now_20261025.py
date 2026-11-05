"""Hermetic tests for Ops Controls Run now bridge (scripts/lib/release_train_run_now.py).

AGENTS 22.0.0 is ACTIVE: policy_gate on the live AGENTS.md is ACTIVE. Phrase, market-hours,
and lifecycle chamber math are pure. No broker, no live controller mutation. A PROPOSED fixture
still refuses POLICY_NOT_ACTIVE.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.lib import release_train_run_now as RN
from scripts.lib import release_train_view as RV
from scripts.lib.ops_controls_core import OpsError

TZ = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]


def test_kind_and_policy_constants():
    assert RN.KIND == "release_train.run_now"
    assert RN.POLICY_REQUIRED == "22.0.0"
    assert RN.POLICY_ANCHOR == "release_train.run_now"


def test_run_now_phrase_shape():
    assert RN.run_now_phrase(7, "1800") == "RUN NOW EPOCH 7 WINDOW 1800"
    assert RN.run_now_phrase(None, "0000") == "RUN NOW EPOCH 0 WINDOW 0000"


@pytest.mark.parametrize(
    "when,expected",
    [
        (datetime(2026, 10, 23, 10, 0, tzinfo=TZ), True),   # Fri 10:00 ET
        (datetime(2026, 10, 23, 9, 29, tzinfo=TZ), False),  # before open
        (datetime(2026, 10, 23, 16, 0, tzinfo=TZ), False),  # at close
        (datetime(2026, 10, 24, 12, 0, tzinfo=TZ), False),  # Saturday
        (datetime(2026, 10, 25, 20, 0, tzinfo=TZ), False),  # Sunday evening
    ],
)
def test_market_hours_open(when, expected):
    assert RN.market_hours_open(when) is expected


def test_policy_gate_on_live_agents_is_retired_by_25_0_0():
    """AGENTS.md 25.0.0 removed the release train (operator 2026-10-27): the 22.0.0 row reads RETIRED and the
    ``release_train.run_now`` anchor is gone, so the Run now gate fails closed on the live file."""
    st = RN.policy_gate(ROOT / "AGENTS.md")
    assert st["state"] != "ACTIVE"
    with pytest.raises(OpsError) as ei:
        RN.require_policy_active(ROOT / "AGENTS.md")
    assert ei.value.code == "POLICY_NOT_ACTIVE"


def test_policy_gate_refuses_proposed_fixture(tmp_path):
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "# AGENTS.md\n\n| 21.0.0 | 2026-10-25 | ACTIVE | MAJOR | prior |\n"
        "| 22.0.0 | 2026-10-25 | PROPOSED | MAJOR | run now |\n"
        "release_train.run_now\n",
        encoding="utf-8",
    )
    st = RN.policy_gate(agents)
    assert st["state"] != "ACTIVE"
    with pytest.raises(OpsError) as ei:
        RN.require_policy_active(agents)
    assert ei.value.code == "POLICY_NOT_ACTIVE"


def test_readiness_blocks_while_controller_build_only(monkeypatch, tmp_path):
    """readiness never mutates; BUILD_ONLY still refuses even when policy is ACTIVE."""
    monkeypatch.setattr(RN, "TRAIN_CONTROLLER_STATUS", "BUILD_ONLY")
    monkeypatch.setattr(RN, "forced_canary_policy", lambda: {
        "operator_forced_off_window": True, "slots": ["1800"],
    })
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# AGENTS.md\n\n| 22.0.0 | 2026-10-25 | ACTIVE | MAJOR | run now |\nrelease_train.run_now\n",
                      encoding="utf-8")  # the 22.0.0-ACTIVE shape; the live file retired it in 25.0.0
    out = RN.readiness(agents_path=agents, now=datetime(2026, 10, 25, 20, 0, tzinfo=TZ))
    assert out["kind"] == RN.KIND
    assert out["allowed"] is False
    assert out["block_reason"]
    assert "POLICY_NOT_ACTIVE" not in out["block_reason"]
    assert out["phrase_example"].startswith("RUN NOW EPOCH")


def test_lifecycle_chambers_from_by_state():
    by = {"submitted": 2, "ready": 1, "held": 3, "integrating": 1, "released": 4, "cancelled": 1}
    life = RV.lifecycle_from_by_state(by)
    assert life["total"] == 12
    assert life["chambers"]["intake"]["count"] == 2
    assert life["chambers"]["gated"]["count"] == 4  # ready+held
    assert life["chambers"]["release"]["count"] == 4
    assert life["chambers"]["closed"]["count"] == 1


def test_lifecycle_none_when_store_missing():
    life = RV.lifecycle_from_by_state(None)
    assert life["chambers"] is None and life["total"] is None


def test_ops_controls_registers_run_now_kind():
    from scripts.lib import ops_controls_core as C

    assert "release_train.run_now" in C.KINDS
    spec = C.KINDS["release_train.run_now"]
    assert spec.direction == C.RISKY
    assert spec.executor == C.EXEC_APPLIER
    assert spec.tab == "jobs"


def test_sudo_always_fresh_includes_run_now():
    from scripts.lib import ops_controls_sudo as S

    assert "release_train.run_now" in S.ALWAYS_FRESH_KINDS
