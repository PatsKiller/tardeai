"""C1 batch 5, final — the digest-delivered tail.

Nine sites across aegis_overnight, api_v2 and system_health_agent. Every one of
their message bodies classifies P1_DIGEST: none pages, all are archived and
delivered by the digest sender within four hours. Before that sender existed, all
nine were silent.

COVERAGE IS CLAIMED FOR EXACTLY ONE SITE. system_health_agent._send_alert is
directly callable, so its full chain is observed: suppressed -> archived with
reason P1_DIGEST -> collected by the digest. The other eight live inside main(),
handle() and run_health_check(), orchestrators these tests cannot drive, so their
ROUTING is pinned and their coverage is not claimed. Pinning a routing verdict is
weaker than observing an alarm fire, and calling it coverage would be the
overstatement this gate exists to prevent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["scripts/system_health_agent.py:478"]

# The exact body shapes the nine sites emit.
BODIES = {
    "aegis:watchlist_health": "*Watchlist Health — 3 broken*",
    "aegis:reentry_signal": "*Re-entry Signal: ABCD*\nprice 10",
    "aegis:headline": "Overnight Summary (3 items)",
    "api:journal_reminder": "*Trade Journal Reminder*\n\n*4 unannotated*",
    "api:ri_promoted": "📌 RI staged idea promoted: ABCD → active",
    "api:escalated_to_alex": "⭐ *ABCD* escalated to Alex from watchlist",
    "health:agent_staleness": "⚠️ AGENT STALENESS\nresearch-lane stale 9h",
    "health:pipeline_health": "🔴 PIPELINE HEALTH\nscreener 0 rows",
}


@pytest.mark.parametrize("name,body", sorted(BODIES.items()))
def test_every_tail_alarm_has_a_known_delivery_path(name, body):
    """No alarm may have an UNKNOWN fate. Each is paged or digested, and stated.

    This is the weaker claim: it pins routing, not firing. It still forecloses the
    condition that hid the 24-day outage -- a message whose delivery nobody had
    established either way.
    """
    from telegram_alert_router import classify_alert
    verdict = classify_alert(body)
    assert verdict in ("P0_INTERRUPT", "P1_DIGEST"), (
        f"{name} classifies {verdict}: neither paged nor digested, so it reaches "
        "nobody. P2_DASHBOARD_ONLY and P3_LOG_ONLY are not delivery."
    )


def test_a_suppressed_alarm_is_archived_for_the_digest(monkeypatch):
    """The link the whole digest depends on.

    If a P1_DIGEST suppression did not archive, the digest would have nothing to
    read and 'delivered later' would be false.
    """
    import telegram_alert as TA
    import report_capture as RC

    calls = []
    monkeypatch.setattr(RC, "archive_message",
                        lambda msg, suppressed=False, reason="": calls.append((suppressed, reason)),
                        raising=True)
    monkeypatch.setattr(TA, "_token", lambda: "t", raising=False)
    monkeypatch.setattr(TA, "_chat_ids", lambda: ["c"], raising=False)
    monkeypatch.setattr(TA, "_enabled", lambda: True, raising=False)
    monkeypatch.setattr(TA, "send_message", lambda **k: {"ok": True}, raising=True)

    TA._legacy_send(BODIES["health:agent_staleness"], False)
    assert calls == [(True, "P1_DIGEST")], calls


# ── the one site this batch actually covers ──────────────────────────────────
def test_health_send_alert_is_archived_end_to_end(alarm_capture, monkeypatch):
    """system_health_agent._send_alert: driven, and its fate observed.

    It does not page -- its contract says "NEVER bypass" -- so the observation is
    that it is suppressed AND archived under P1_DIGEST, which is what makes the
    digest deliver it. Both halves are asserted: silence at the transport is only
    acceptable because the archive step is proven.
    """
    import report_capture as RC
    import system_health_agent as SHA

    calls = []
    monkeypatch.setattr(RC, "archive_message",
                        lambda msg, suppressed=False, reason="": calls.append((suppressed, reason)),
                        raising=True)

    SHA._send_alert(BODIES["health:pipeline_health"])
    assert not alarm_capture.fired, "unexpectedly paged; update the contract and COVERS"
    assert calls == [(True, "P1_DIGEST")], (
        f"not archived, so the digest can never deliver it: {calls}"
    )
