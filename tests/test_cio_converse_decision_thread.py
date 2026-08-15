"""In-thread reply to a CIO NOW card must keep the same decision_id."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_telegram_converse import parse_ids_from_text, format_decision_thread_reply
from scripts.lib.cio_converse_core import process_operator_message

CARD = """Alex · CIO NOW

WHAT CHANGED
Advisory TRIM — SCHD Freshness=STALE_REFRESH_REQUIRED; not ACT NOW.

MY CALL
TRIM SCHD  $-44,335

Decision: dec_5866156741de9046
"""


def test_parse_decision_id_from_cio_card():
    got = parse_ids_from_text(CARD)
    assert got["decision_id"] == "dec_5866156741de9046"
    assert got["plan_id"] is None


def test_parse_still_finds_plan_footer():
    got = parse_ids_from_text("`plan_bf9d724376cc` · thesis `desk@v5`")
    assert got["plan_id"] == "plan_bf9d724376cc"


def test_format_reject_thread_does_not_open_s0():
    body = format_decision_thread_reply(
        decision_id="dec_5866156741de9046",
        operator_text="i rejected as its making money and a staple anchor to account right now",
        thread={
            "decision_id": "dec_5866156741de9046",
            "symbol": "SCHD",
            "stance": "Trim",
            "disposition": "reject",
            "why_now": "Advisory TRIM — SCHD concentration above fire.",
            "action_label": "STALE_REFRESH_REQUIRED",
            "act_now": False,
        },
    )
    assert "dec_5866156741de9046" in body
    assert "REJECT" in body
    assert "staple" in body.lower() or "making money" in body.lower()
    assert "S0" in body  # we explicitly say we will not open a new S0
    assert "plan_bf9" not in body
    assert "choose ack" not in body.lower()


def test_process_reply_to_card_is_decision_thread():
    out = process_operator_message(
        channel="telegram",
        chat_id="1",
        message_id="999010",
        text="i rejected as its making money and a staple anchor to account right now",
        reply_to_message_id="35",
        reply_to_text=CARD,
        allowlist={"1"},
        converse_on=True,
        dry_run=True,
    )
    assert out["handled"] is True
    assert out["kind"] == "decision_thread"
    assert out["decision_id"] == "dec_5866156741de9046"
    assert out.get("plan_id") is None
    preview = out.get("reply_preview") or ""
    assert "dec_5866156741de9046" in preview
    assert "S0 OPERATOR CONVERSE" not in preview
    assert "desk@v5" not in preview
