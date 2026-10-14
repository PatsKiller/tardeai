"""2026-10-14 SPCX incident: stop_health_check's NEAR_TRIGGER "about to fire" warnings (13:50/14:00/14:10 ET)
were classified P1_DIGEST and suppressed; the stops filled at 14:36/14:38. A stop about to fire or fired must
always interrupt, ahead of the policy router, and must not be dropped by the daily P0 budget."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import telegram_alert_router as R  # noqa: E402

BATCH = ("⚠️ STOP HEALTH — 8 alert(s)\n\n⚠️ NEAR_TRIGGER: *SPCX* (schwab_rollover_ira)\n"
         "price within 0.46% of stop $151.5 — about to fire. · if fired: −$4,566 (−9.1% vs cost $166.72)")
SINGLE = "🚨 STOP HEALTH — TRIGGERED: *SPCX* (schwab_taxable)\nstop FILLED (#1008189857145) — position may be flat; review."
CARD = ("⚠️ <b>STOP WARNING · 8 alerts</b>\n\n<b>SPCX</b> · schwab_rollover_ira · NEAR TRIGGER\n"
        "  price within 0.2% of stop $151.5 — about to fire.")
CRITICAL_CARD = "🚨 <b>CRITICAL STOP ALERT</b>\n\n<b>PL</b> · schwab_rollover_ira · TRIGGERED\n  stop FILLED (#1) — review."


def test_every_stop_firing_format_interrupts(monkeypatch):
    # Even if the policy router would digest it, the stop rule wins (it is checked first).
    for msg in (BATCH, SINGLE, CARD, CRITICAL_CARD):
        assert R.classify_alert(msg) == "P0_INTERRUPT", msg[:40]


def test_stop_firing_is_exempt_from_the_daily_budget(monkeypatch):
    monkeypatch.setattr(R, "_budget_count_today", lambda: 10_000)
    monkeypatch.setattr(R, "record_suppressed", lambda *a, **k: None)
    for msg in (BATCH, SINGLE, CARD):
        assert R._ops_exempt(msg)
        assert R.should_send_telegram(msg) is True


def test_non_firing_stop_health_is_not_promoted():
    # An ORPHANED/OVERSIZED-only report or an unrelated message is not forced to P0 by this rule.
    assert not R._STOP_FIRING_PATTERN.search("STOP HEALTH — ORPHANED: *XYZ* (schwab_taxable)\nno position for stop")
    assert not R._STOP_FIRING_PATTERN.search("Morning brief: SPCX near support, about to fire up?")
