"""Operator desk loop: Flash intent → Trade-AI evidence → answer or defer.

P0: meta_system must never dump re-entry READY/NEAR cards.
"""
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
    format_meta_system_reply,
    load_runtime_llm_facts,
)


def test_intent_reentry_heuristic():
    intent = analyze_operator_intent(
        "alex what can i reenter now and whats the support and resistance 50day etc"
    )
    assert intent.get("ok")
    assert "reentry_ready" in intent.get("needs") or intent.get("intent") == "reentry"
    assert "reentry_levels" in intent.get("needs")


def test_intent_meta_llm_ask_no_reentry_default(monkeypatch):
    """P0: 'what llm you using' must be meta_system — never reentry_ready/portfolio."""
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    intent = analyze_operator_intent("alex what llm you using")
    assert intent.get("ok")
    assert intent.get("intent") == "meta_system"
    needs = intent.get("needs") or []
    assert "reentry_ready" not in needs
    assert "portfolio" not in needs
    assert "runtime_llm" in needs or "runtime_status" in needs


def test_intent_unclear_not_reentry_dump(monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    intent = analyze_operator_intent("alex hello there")
    assert intent.get("intent") == "unclear"
    assert intent.get("needs") == []


def test_handle_llm_ask_no_reentry_dump(monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setenv("CIO_REENTRY_FLASH", "0")
    out = handle_operator_desk_question(
        "alex what llm you using",
        chat_id="1",
        message_id="2",
    )
    text = (out.get("text") or "")
    assert out.get("kind") == "answered"
    assert out.get("intent", {}).get("intent") == "meta_system"
    low = text.lower()
    assert "flash" in low or "deepseek" in low
    assert "ready to review" not in low
    assert "dhx" not in low
    assert "mogu" not in low
    assert "defensive_observe" not in low
    assert "S0 OPERATOR" not in text
    assert "READ_ONLY" in text


def test_meta_facts_mention_flash():
    facts = load_runtime_llm_facts()
    reply = format_meta_system_reply(facts)
    assert "deepseek-v4-flash" in reply
    assert "READ_ONLY_ADVISORY" in reply
    assert "READY TO REVIEW" not in reply


def test_gather_meta_skips_reentry_card(monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    intent = {
        "ok": True,
        "intent": "meta_system",
        "symbols": [],
        "needs": ["runtime_llm", "runtime_status"],
    }
    ev = gather_tradeai_evidence(intent)
    assert ev.get("complete") is True
    assert ev.get("available", {}).get("meta_card")
    assert "reentry_card" not in (ev.get("available") or {})


def test_gather_answers_when_desk_present():
    intent = {
        "ok": True,
        "intent": "reentry",
        "symbols": [],
        "needs": ["reentry_ready", "reentry_levels"],
    }
    ev = gather_tradeai_evidence(intent)
    if ev.get("available", {}).get("reentry_card"):
        assert ev.get("complete") is True
        assert (
            "READY" in ev["available"]["reentry_card"]
            or "re-entry" in ev["available"]["reentry_card"].lower()
        )


def test_handle_does_not_emit_s0_wallpaper(monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setenv("CIO_REENTRY_FLASH", "0")
    out = handle_operator_desk_question(
        "what can i reenter now support resistance 50day",
        chat_id="1",
        message_id="2",
    )
    text = out.get("text") or ""
    assert "defensive_observe" not in text.lower() or "acknowledge and monitor" not in text.lower()
    assert "S0 OPERATOR" not in text
    assert out.get("kind") in ("answered", "deferred")
    if out.get("kind") == "answered":
        assert "READ_ONLY" in text


def test_gather_portfolio_need_no_reentry(monkeypatch):
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    intent = analyze_operator_intent("alex what's my portfolio cash")
    assert "cash" in intent.get("needs") or "portfolio" in intent.get("needs")
    assert "reentry_ready" not in (intent.get("needs") or [])
    ev = gather_tradeai_evidence(intent)
    assert "reentry_card" not in (ev.get("available") or {})
