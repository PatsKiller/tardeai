"""Freeform Alex agent grounded in Trade-AI — regress P0 meta + reentry paths."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_operator_desk_loop import (
    analyze_operator_intent,
    gather_tradeai_evidence,
    handle_operator_desk_question,
)


def test_meta_still_not_freeform(monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    intent = analyze_operator_intent("alex what llm you using")
    assert intent.get("intent") == "meta_system"
    out = handle_operator_desk_question("alex what llm you using", chat_id="1", message_id="m1")
    text = out.get("text") or ""
    assert "deepseek" in text.lower() or "flash" in text.lower()
    assert "READY TO REVIEW" not in text
    assert out.get("reply_source") == "runtime_meta"


def test_freeform_jepi_ask_answers(monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setenv("CIO_OPERATOR_FREEFORM_FLASH", "0")  # deterministic failsoft
    monkeypatch.setenv("CIO_OPERATOR_FREEFORM_QUEUE", "0")
    intent = analyze_operator_intent("alex explain why JEPI fits my book")
    assert intent.get("intent") == "freeform"
    assert "JEPI" in (intent.get("symbols") or [])
    out = handle_operator_desk_question(
        "alex explain why JEPI fits my book",
        chat_id="1",
        message_id="m2",
    )
    text = out.get("text") or ""
    assert out.get("kind") == "answered"
    assert out.get("intent", {}).get("intent") == "freeform"
    assert len(text) > 40
    assert "READ_ONLY" in text
    assert "defensive_observe" not in text.lower()
    assert "READY TO REVIEW" not in text
    # Failsoft path when flash off
    assert out.get("reply_source") in ("freeform_failsoft", "freeform_flash")


def test_reentry_still_desk_path(monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setenv("CIO_REENTRY_FLASH", "0")
    intent = analyze_operator_intent(
        "what can i reenter now support resistance 50day"
    )
    assert intent.get("intent") == "reentry"
    assert "reentry_ready" in (intent.get("needs") or [])
    out = handle_operator_desk_question(
        "what can i reenter now support resistance 50day",
        chat_id="1",
        message_id="m3",
    )
    assert out.get("kind") in ("answered", "deferred")
    if out.get("kind") == "answered":
        text = out.get("text") or ""
        assert "S0 OPERATOR" not in text
        # Live desk may include READY — that's correct for reentry path
        assert out.get("reply_source") != "freeform_flash"


def test_gather_freeform_no_reentry_card(monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    intent = {
        "ok": True,
        "intent": "freeform",
        "symbols": ["JEPI"],
        "needs": [],
    }
    ev = gather_tradeai_evidence(intent)
    assert ev.get("complete") is True
    assert "reentry_card" not in (ev.get("available") or {})
    assert "freeform_context" in (ev.get("available") or {})
