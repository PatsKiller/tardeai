"""R11 interactive same-brain attention answers + human-readable notify."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lib.cio_advisory_message import assert_not_json_dump, render_advisory_message
from scripts.lib.cio_advisory_notify import deliver_prepared, prepare_advisory_notification
from scripts.lib.cio_converse_core import process_operator_message
from scripts.lib.cio_office_cycle import run_office_cycle
from scripts.lib.cio_operator_attention import answer_attention_query, looks_like_attention_query
from tests.r11_office_fixtures import NOW, office, policy, portfolio

pytestmark = pytest.mark.tier0


def test_why_nothing_no_material() -> None:
    ans = answer_attention_query(
        "Why haven't you told me anything today?",
        office=office(portfolio_state=portfolio(cash_pct=10.0)),
    )
    assert ans["hallucinated"] is False
    assert ans["reason"] in {"NO_MATERIAL_CHANGE", "CASH_WITHIN_POLICY"}
    low = ans["text"].lower()
    assert "not inventing" in low or "nothing material" in low or "invented" in low or "no_material_change" in low


def test_why_nothing_policy_gap() -> None:
    ans = answer_attention_query(
        "Why haven't you told me anything today?",
        office=office(policy=policy(confirmed=False)),
    )
    assert ans["reason"] in {"MATERIAL_SITUATION", "POLICY_GAP"} or "HEADLINE" in ans["text"]
    assert ans["hallucinated"] is False


def test_what_should_i_pay_attention_to_uses_same_scan() -> None:
    assert looks_like_attention_query("What should I be paying attention to?")
    ans = answer_attention_query(
        "What should I be paying attention to?",
        office=office(),
        envelope={"schema": "CIOContextEnvelope@v2"},
    )
    assert ans["same_brain"] is True
    assert ans["envelope_present"] is True
    assert "HEADLINE" in ans["text"] or "WHAT TO PAY ATTENTION" in ans["text"]
    assert_not_json_dump(ans["text"])


def test_converse_routes_attention(tmp_path: Path) -> None:
    out = process_operator_message(
        channel="telegram",
        chat_id="1",
        message_id="m-attn-1",
        text="Why haven't you told me anything today?",
        allowlist={"1"},
        converse_on=True,
        dry_run=True,
        dedup_path=tmp_path / "dedup.jsonl",
        msg_map_path=tmp_path / "map.jsonl",
        rate_path=tmp_path / "rate.jsonl",
    )
    assert out["handled"] is True
    assert out["kind"] == "attention"
    assert out["same_brain"] is True


def test_human_readable_not_json_dump(tmp_path: Path) -> None:
    result = run_office_cycle(office(), root=tmp_path, evaluated_at=NOW)
    assert_not_json_dump(result["message"])
    assert "HEADLINE" in result["message"]
    assert "WHY NOW" in result["message"]
    assert "READ_ONLY_ADVISORY" in result["message"]
    prepared = prepare_advisory_notification(result["primary_situation"], message=result["message"])
    receipt = deliver_prepared(prepared)
    assert receipt["sender_attribution"] == "alex_cio"
    assert receipt["trace_id"]
    assert receipt["situation_id"] == result["primary_situation"]["situation_id"]
