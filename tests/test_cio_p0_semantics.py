"""P0-1 / P0-2 CIO semantics — standing vs current action, REJECT challenge.

No network. Dispositions are monkeypatched. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_alex_telegram import classify_actionability, format_cio_message, rejected_unchanged
from scripts.lib.cio_material_scan import _canonical_decisions, select_publications
from scripts.lib.cio_telegram_converse import (
    format_decision_thread_reply,
    persist_operator_challenge,
)

DID = "dec_5866156741de9046"
STAPLE = "income / staple / it is working"


def _stale_trim(**over):
    base = {
        "decision_id": DID,
        "symbol": "SCHD",
        "action": "TRIM",
        "stance": "Trim",
        "stance_code": "TRIM",
        "why_now": "Advisory TRIM — SCHD concentration above single-name fire.",
        "recommended_delta_usd": -44334.57,
        "delta_usd": -44334.57,
        "act_now": False,
        "action_label": "STALE_REFRESH_REQUIRED",
        "decision_input_digest": "",
        "decision_evidence_digest": "",
        "risk": "concentration fire",
        "counter_thesis": "Income sleeve may tolerate concentration.",
        "what_changes_call": "Weight falls under fire or marks refresh.",
    }
    base.update(over)
    return base


def test_01_standing_trim_stale_current_action_wait_revalidate():
    cls = classify_actionability(_stale_trim())
    assert cls["standing_recommendation"] == "TRIM"
    assert cls["current_action"] in {"WAIT", "REVALIDATE"}
    assert cls["act_now"] is False
    assert cls["actionability"] == "STALE_REFRESH_REQUIRED"

    rows = _canonical_decisions({"position_decisions": [_stale_trim()]})
    assert rows
    got = rows[0]
    assert got["standing_recommendation"] == "TRIM"
    assert got["current_action"] in {"WAIT", "REVALIDATE"}
    assert got["act_now"] is False
    assert got["action"] == "TRIM"


def test_02_format_cio_message_no_bare_my_call_when_not_act_now():
    body = format_cio_message(_stale_trim())
    assert "STANDING VIEW" in body
    assert "CURRENT ACTION" in body
    assert "TRIM" in body
    assert "SCHD" in body
    assert "ACT_NOW=false" in body
    assert "concentration" in body.lower() or "fire" in body.lower()
    assert "MY CALL" not in body
    lines = body.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "MY CALL":
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            assert not nxt.upper().startswith("TRIM"), nxt

    rejected = format_cio_message(_stale_trim(
        operator_disposition="REJECT",
        operator_note="keep the income sleeve",
    ))
    assert "STANDING VIEW" in rejected
    assert "TRIM" in rejected
    assert "OPERATOR" in rejected
    assert "REJECT recorded" in rejected
    assert "keep the income sleeve" in rejected


def test_03_reject_persist_exact_free_text_in_thread_reply(tmp_path, monkeypatch):
    note = "i rejected as its making money and a staple anchor to account right now"
    body = format_decision_thread_reply(
        decision_id=DID,
        operator_text=note,
        thread={
            "decision_id": DID,
            "symbol": "SCHD",
            "stance": "Trim",
            "standing_recommendation": "TRIM",
            "disposition": "REJECT",
            "why_now": "Advisory TRIM — SCHD concentration above fire.",
            "action_label": "STALE_REFRESH_REQUIRED",
            "act_now": False,
        },
    )
    assert note in body
    assert "REJECT" in body
    assert f"Decision: {DID}" in body

    from scripts.lib import cio_production_case as cs
    monkeypatch.setattr(cs, "DEFAULT_PATH", tmp_path / "cases.jsonl")
    rec = persist_operator_challenge(DID, note, "REJECT")
    assert rec["ok"] is True
    assert rec["note"] == note
    raw = (tmp_path / "cases.jsonl").read_text(encoding="utf-8")
    assert note in raw
    assert rec["operator_challenge_status"] == "OPEN"
    assert rec["challenge_review"] == "DATA_UNAVAILABLE"


def test_04_rejected_unchanged_excluded_from_select_publications(monkeypatch):
    trim = _stale_trim()
    cash = {
        "decision_id": "dec_cash_1",
        "symbol": "CASH",
        "action": "HOLD_CASH",
        "decision_input_digest": "",
        "decision_evidence_digest": "",
    }

    def _disp():
        return {
            "dispositions": {
                DID: {
                    "disposition": "reject",
                    "decision_input_digest": "",
                    "decision_evidence_digest": "",
                    "note": "keep it",
                }
            }
        }

    monkeypatch.setattr("scripts.api_v3_cio.get_decision_dispositions", _disp)
    assert rejected_unchanged(trim) is True
    got = select_publications([cash, trim], max_publish=3)
    ids = [g["decision_id"] for g in got]
    assert DID not in ids
    assert "dec_cash_1" in ids

    changed = dict(trim, decision_evidence_digest="new_evidence_hash")
    assert rejected_unchanged(changed) is False
    got2 = select_publications([changed], max_publish=3)
    assert [g["decision_id"] for g in got2] == [DID]


def test_06_operator_note_not_hardcoded_staple_unless_actual_note():
    own = "I disagree with the recommended size; keep the sleeve."
    body = format_decision_thread_reply(
        decision_id=DID,
        operator_text=own,
        thread={
            "decision_id": DID,
            "symbol": "SCHD",
            "stance": "TRIM",
            "disposition": "REJECT",
            "why_now": "Advisory TRIM — SCHD concentration above fire.",
            "act_now": False,
        },
    )
    assert own in body
    assert STAPLE not in body.lower()

    allowed = format_decision_thread_reply(
        decision_id=DID,
        operator_text=STAPLE,
        thread={
            "decision_id": DID,
            "symbol": "SCHD",
            "stance": "TRIM",
            "disposition": "REJECT",
            "why_now": "Advisory TRIM — SCHD concentration above fire.",
        },
    )
    assert STAPLE in allowed.lower()


def test_24_reply_formatter_includes_decision_id():
    body = format_decision_thread_reply(
        decision_id=DID,
        operator_text="noted",
        thread={"decision_id": DID, "symbol": "SCHD", "stance": "TRIM"},
    )
    assert f"Decision: {DID}" in body
    assert DID.startswith("dec_")
