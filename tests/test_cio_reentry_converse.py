"""Re-entry purchase queries must get a short factual reply — not S0 template."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_telegram_converse import (
    format_reentry_purchase_reply,
    looks_like_reentry_purchase_query,
)
from scripts.lib.cio_converse_core import process_operator_message


SAMPLE_ROWS = [
    {
        "symbol": "DHX",
        "held": False,
        "price": 4.1,
        "entry_low": 3.8,
        "entry_high": 4.2,
        "intel": {"state": "READY TO REVIEW"},
        "advisory": {"action": "Tactical Re-Entry / Buy Limit"},
    },
    {
        "symbol": "MOGU",
        "held": False,
        "price": 1.945,
        "entry_low": 1.88,
        "entry_high": 2.08,
        "intel": {"state": "READY TO REVIEW"},
        "advisory": {"action": "Tactical Re-Entry / Buy Limit"},
    },
    {
        "symbol": "ANET",
        "held": False,
        "price": 183.69,
        "entry_low": 174.5,
        "entry_high": 179.5,
        "intel": {"state": "NEAR ENTRY"},
        "advisory": {"action": "Prepare Re-Entry / Watch Limit"},
    },
    {
        "symbol": "FATN",
        "held": False,
        "price": 6.19,
        "entry_low": 5.6,
        "entry_high": 6.1,
        "intel": {"state": "NEAR ENTRY"},
    },
]


def test_intent_detects_operator_reentry_question():
    assert looks_like_reentry_purchase_query(
        "alex any holdings on rentry ready for purchase"
    )
    assert looks_like_reentry_purchase_query(
        "Any re-entry names ready to buy?"
    )
    assert looks_like_reentry_purchase_query("what's ready for purchase on reentry")
    assert not looks_like_reentry_purchase_query("/cio reentry")
    assert not looks_like_reentry_purchase_query("how is SCHD concentration")


def test_format_lists_ready_and_near():
    text = format_reentry_purchase_reply(
        desk_rows=SAMPLE_ROWS,
        computed_at="2026-08-20T22:45:30+00:00",
        near_limit=8,
    )
    assert "READY TO REVIEW" in text
    assert "*DHX*" in text
    assert "*MOGU*" in text
    assert "NEAR ENTRY" in text
    assert "`ANET`" in text
    assert "READ_ONLY" in text
    assert "S0" not in text
    assert "defensive_observe" not in text


def test_process_operator_message_reentry_skips_s0_plan(tmp_path):
    sent: list[str] = []

    def send_fn(chat_id, body, reply_to=None):
        sent.append(body)
        return {"ok": True, "message_id": "99"}

    out = process_operator_message(
        channel="telegram",
        chat_id="111",
        message_id="msg-reentry-1",
        text="alex any holdings on rentry ready for purchase",
        allowlist={"111"},
        converse_on=True,
        dry_run=False,
        send_fn=send_fn,
        dedup_path=tmp_path / "dedup.jsonl",
        msg_map_path=tmp_path / "msgmap.jsonl",
        rate_path=tmp_path / "rate.jsonl",
    )
    assert out.get("handled") is True
    assert out.get("kind") == "reentry_facts"
    assert sent, "expected a Telegram reply"
    body = sent[0]
    assert "READY TO REVIEW" in body or "re-entry desk artifact" in body.lower()
    assert "S0 OPERATOR" not in body
    assert "Acknowledge and monitor" not in body
