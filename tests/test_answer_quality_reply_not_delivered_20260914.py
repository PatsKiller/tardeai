"""A reply the desk wrote but Telegram never accepted is a finding. Offline.

2026-09-14 13:47 ET: the 4,571-character AXTI answer was refused (400) twice. Its conversation-turn row carried
message_id NULL, the poller logged "replied", and every text rule of the answer-quality monitor passed it,
because the text was fine. The operator had no answer.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_operator_answer_quality as q  # noqa: E402

COVERS = ["scripts/check_operator_answer_quality.py"]


def test_the_rule_is_declared_and_explained():
    assert "REPLY_NOT_DELIVERED" in q.RULES and "REPLY_NOT_DELIVERED" in q._WHAT_WILL_BE_DONE


def test_a_written_reply_without_a_telegram_message_id_is_a_finding():
    turns = [
        {"message_id": "51807", "ts": "2026-09-14T17:47:45+00:00", "question": "Axti goes up and down between 5% and 15%",
         "reply": "Key: …" * 900},
        {"message_id": "51746", "ts": "2026-09-14T13:12:38+00:00", "question": "HPE", "reply": "HPE answer"},
        {"message_id": "51700", "ts": "2026-09-14T12:00:00+00:00", "question": "no reply yet", "reply": None},
    ]
    out = q.replies_not_delivered(turns, {"51807": False, "51746": True, "51700": False})
    assert [r["message_id"] for r in out] == ["51807"] and out[0]["reply_chars"] > 4096


def test_an_unknown_delivery_state_is_not_a_finding():
    turns = [{"message_id": "1", "ts": "t", "question": "q", "reply": "answer"}]
    assert q.replies_not_delivered(turns, {}) == []


def test_the_alert_names_the_undelivered_answer():
    report = {"finding_count": 1, "findings": {r: [] for r in q.RULES}}
    report["findings"]["REPLY_NOT_DELIVERED"] = [{"message_id": "51807", "ts": "t", "question": "Axti goes up and down",
                                                  "reply_chars": 4571}]
    text = q.format_alert(report, {})
    assert "[REPLY_NOT_DELIVERED]" in text and "4571-character answer written, never delivered" in text
