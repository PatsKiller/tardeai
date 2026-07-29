#!/usr/bin/env python3
"""Jun 25, 2026 Telegram stream fixtures — verify P1-6 routing policy."""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
os.chdir(str(PROJECT_ROOT))

# (message_snippet, expected_send, expected_level_prefix)
JUN25_CASES = [
    ("⚡ Trade AI LIVE [09:50]\n🎯 NEW GO — EHGO score=41", False, "P2"),
    ("🎯 NEW GO — ANY score=40\n🚫 Critic: BLOCK", False, "P2"),
    ("🎯 NEW GO — LOW score=12 RVOL 5x", False, "P2"),
    ("❓ Paper Proposal: GDHG\nStrategy: Sector Rotation", False, "P2"),
    ("🚨 STOP_TRIGGERED — CACI\nTrigger: stop_price", False, "P1"),
    ("🔭 Hermes watchlist alerts:\n⤴ AMD jumped", False, "P2"),
    ("⚠️ Health Agent: DEGRADED — 84/100\ndata:100", False, "P2"),
    ("🚨 Health Agent: UNHEALTHY — 60/100", False, "P1"),
    ("🔍 Investigating 5 escalation(s) via local LLM:", False, "P2"),
    ("Topic Curator: 276 entity links", False, "P2"),
    ("Incubator Promoter\nPromoted: 1 | Skipped: 14", False, "P2"),
    ("💼 PORTFOLIO INTELLIGENCE — Jun 25, 2026\nTotal: $1,243,591", False, "P1"),
    ("🚨 SIEM P1: stop_health — STOP_TRIGGERED", False, "P1"),
    ("☀️ MORNING COMMAND — Jun 25, 2026\n--- Portfolio ---", False, "P1"),
    ("Trade AI Critique: 12/15 reviewed\nConfirmed: 10", False, "P2"),
]


def test_jun25_routing_matrix():
    from telegram_alert_router import should_send_telegram, classify_alert

    for msg, expect_send, level_prefix in JUN25_CASES:
        level = classify_alert(msg)
        send = should_send_telegram(msg)
        assert level.startswith(level_prefix), f"level {level} != {level_prefix} for {msg[:40]}"
        assert send == expect_send, f"send={send} expected {expect_send} for {msg[:40]}"


def test_health_repeat_suppressed():
    from telegram_alert_router import should_send_telegram, mark_sent, _dedupe_cache, _last_health

    _dedupe_cache.clear()
    _last_health.update({"score": None, "status": None, "ts": 0.0})
    msg = "🚨 Health Agent: UNHEALTHY — 64/100\ndata:85 · execution:0"
    assert should_send_telegram(msg) is False
    mark_sent(msg)
    assert should_send_telegram(msg) is False


def test_portfolio_intelligence_dedupe():
    from telegram_alert_router import should_send_telegram, mark_sent, _dedupe_cache

    _dedupe_cache.clear()
    m1 = "💼 PORTFOLIO INTELLIGENCE — Jun 25, 2026\nTotal: $1,243,591"
    m2 = "💼 PORTFOLIO INTELLIGENCE — Jun 25, 2026\nTotal: $1,243,198"
    assert should_send_telegram(m1) is False
    mark_sent(m1)
    assert should_send_telegram(m2) is False
