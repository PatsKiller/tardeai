"""Operator desk loop: Flash intent → Trade-AI evidence → answer or defer."""
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


def test_intent_reentry_heuristic():
    intent = analyze_operator_intent(
        "alex what can i reenter now and whats the support and resistance 50day etc"
    )
    assert intent.get("ok")
    assert "reentry_ready" in intent.get("needs") or intent.get("intent") == "reentry"
    assert "reentry_levels" in intent.get("needs")


def test_gather_answers_when_desk_present():
    intent = {
        "ok": True,
        "intent": "reentry",
        "symbols": [],
        "needs": ["reentry_ready", "reentry_levels"],
    }
    ev = gather_tradeai_evidence(intent)
    # Live desk may or may not exist in CI — if present, must be complete
    if ev.get("available", {}).get("reentry_card"):
        assert ev.get("complete") is True
        assert "READY" in ev["available"]["reentry_card"] or "re-entry" in ev["available"]["reentry_card"].lower()


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
