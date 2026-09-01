"""C1 batch 4 — the naked-position alarm, and the digest closing the loop.

Since the P1 digest sender exists, a routed message has two honest outcomes: it
pages (P0_INTERRUPT) or it is delivered later in the digest (P1_DIGEST). Before
that, P1_DIGEST meant archived and never pushed. These tests pin which outcome
each alarm actually gets, rather than assuming the router agrees with the words in
the message body.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["scripts/alpaca_stop_manager.py:454"]

NAKED = ("🛑 NAKED paper position ABCD: OCO convert interrupted (OCO_REPLACING) and NO stop "
         "exists at the broker. Run alpaca_stop_manager.py --repair-oco --apply to re-place.")


# ── the naked-position alarm must PAGE, not digest ───────────────────────────
def test_naked_position_alarm_reaches_the_transport(alarm_capture):
    """A position with no stop at the broker is money at risk. It must page.

    The call site is routed (no bypass) and wrapped in `except Exception: pass`, so
    whether the operator hears it is entirely the router's decision. This asserts
    the router classifies it as an interrupt and it actually leaves.
    """
    from telegram_alert import send_telegram
    send_telegram(NAKED)
    alarm_capture.assert_fired(contains="NAKED")


def test_naked_position_is_classified_as_an_interrupt_not_a_digest():
    """Pins the classification itself, so a router edit cannot quietly demote it."""
    from telegram_alert_router import classify_alert
    assert classify_alert(NAKED) == "P0_INTERRUPT", classify_alert(NAKED)


# ── a body saying CRITICAL is not necessarily treated as one ─────────────────
def test_pipeline_watchdog_critical_is_digested_not_paged_FINDING():
    """FINDING. "CRITICAL: <script> failed 3x" classifies P1_DIGEST.

    It is now DELIVERED -- the digest sender exists -- but it arrives up to four
    hours later rather than interrupting. Whether a repeated pipeline failure
    should page is a router-classification decision affecting every producer, so it
    is reported here rather than changed.

    Pinned so the current behaviour is a stated fact, not an assumption.
    """
    from telegram_alert_router import classify_alert
    assert classify_alert("CRITICAL: some_script.py failed 3x") == "P1_DIGEST"


# ── the loop: a suppressed message must be picked up by the digest ───────────
def test_the_digest_collects_a_suppressed_message(alarm_capture):
    """End of the chain. A P1_DIGEST message is archived; the digest must find it.

    Before the sender existed this row was written and never read by anything that
    pushes. This asserts collect() would pick up exactly such a row and render it.
    """
    import p1_digest_sender as P

    now = datetime.now(timezone.utc)
    row = (99999, now - timedelta(minutes=5), "health_agent",
           "⚠️ Health Agent: DEGRADED — 70/100", "body")

    captured = {}

    def fake_query(sql, params=None):
        captured["sql"] = sql
        return [row]

    collected = P.collect(since_hours=4, query=fake_query)
    assert "reports_archive" in captured["sql"], captured["sql"]
    text = P.render(collected)
    # The kind is escaped in the rendered digest (health\_agent), because embedded
    # text is neutralised before it is sent. Assert against the shared escaper
    # rather than a raw literal -- an assertion that hard-codes the unescaped form
    # is asserting the bug that shipped before it.
    from telegram_transport import escape_markdown
    assert escape_markdown("health_agent") in text, text
    assert "×1" in text, text


def test_the_digest_itself_pages(alarm_capture):
    """The digest must not be digested. It bypasses, so it reaches the transport."""
    import p1_digest_sender as P
    assert P.deliver("📋 P1 digest — loop closure probe") is True
    alarm_capture.assert_fired(contains="loop closure")
