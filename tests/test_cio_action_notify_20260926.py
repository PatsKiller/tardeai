"""CIO Desk messages: material actions only, readable, once per window (operator 2026-09-26).

The chat showed "CIO Advisory Action cio-action-f0b9... / CIO run <uuid> produced action <id>"
once per action per run; "RE_ENTER TDG" was re-created 91 times in a week.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import cio_action_notify as n  # noqa: E402

POLICY = n.load_policy()


def _a(title, **kw):
    return {"cio_action_id": f"cio-action-{abs(hash(title)) % 10**12}", "title": title, **kw}


def test_material_verbs_page_status_and_temperament_do_not():
    assert n.is_material(_a("AVOID NUAI"), POLICY)
    assert n.is_material(_a("RE_ENTER TDG"), POLICY)
    assert n.is_material(_a("Recommendation 1", action_type="HOLD"), POLICY)
    assert not n.is_material(_a("CIO Run x — No recommendations", action_type="STATUS"), POLICY)
    assert not n.is_material(_a("Market temperament — RISK ON TREND", operator_decision_required=True), POLICY)


def test_same_advice_pages_once_per_window(tmp_path):
    st = tmp_path / "state.json"
    first = n.select_new([_a("RE_ENTER TDG"), _a("AVOID NUAI")], POLICY, now=1000.0, state_path=st)
    again = n.select_new([_a("RE_ENTER TDG"), _a("AVOID NUAI")], POLICY, now=2000.0, state_path=st)
    later = n.select_new([_a("RE_ENTER TDG")], POLICY, now=1000.0 + 8 * 86400, state_path=st)
    assert len(first) == 2 and again == [] and len(later) == 1


def test_message_is_readable_and_carries_no_ids():
    msg = n.render([_a("AVOID NUAI", evidence_refs=["book:avoid:NUAI"], operator_decision_required=True),
                    _a("RE_ENTER TDG", recommended_action="Re-enter on a pullback to the plan zone")], POLICY)
    assert msg["subject"] == "CIO: 2 new recommendations · 1 need your decision"
    assert "• AVOID NUAI — basis: book:avoid:NUAI" in msg["body"]
    assert "• RE_ENTER TDG — Re-enter on a pullback" in msg["body"]
    assert "cio-action-" not in msg["body"] and "cio-action-" not in msg["subject"]
    assert n.render([], POLICY) is None


def test_policy_is_config():
    import json
    cfg = json.loads((ROOT / "config" / "cio_notification_policy.json").read_text(encoding="utf-8"))
    assert cfg["repeat_suppress_days"] > 0 and "RE_ENTER" in cfg["material_title_verbs"]
