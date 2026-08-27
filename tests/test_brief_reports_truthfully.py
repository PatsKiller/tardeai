"""Two lines in logs/aegis_brief.log were false. Both are the same defect class:
a path reporting success it did not have.

    column "run_type" does not exist        -- a live SQL error, swallowed
    [telegram] Suppressed (P2_DASHBOARD_ONLY)
      Telegram: sent                        -- printed directly underneath

Every morning since the code was written.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SRC = (ROOT / "scripts/aegis_morning_brief_delivery.py").read_text(encoding="utf-8")


# ── the SQL ────────────────────────────────────────────────────────────────

def test_the_query_uses_columns_pipeline_runs_actually_has():
    """Verified against the live schema: pipeline_runs has run_label and
    pipeline_key; it has neither run_type nor script_name."""
    assert "run_type" not in SRC or "no `run_type`" in SRC, "run_type is not a column"
    assert not re.search(r"COUNT\(CASE WHEN run_type=", SRC)
    assert "run_label LIKE 'retry%'" in SRC
    assert not re.search(r"SELECT DISTINCT script_name FROM", SRC)
    assert "pipeline_key AS script_name" in SRC


def test_a_failed_health_query_is_reported_not_blanked():
    """Returning '' made a broken column indistinguishable from a healthy quiet
    night -- the brief looked complete with no pipeline line at all."""
    i = SRC.index("def _get_pipeline_health_for_brief")
    block = SRC[i:SRC.index("\ndef ", i + 10)]
    assert "except Exception as e:" in block
    assert "status unavailable" in block
    assert "pipeline health unavailable" in block


# ── accepted is not delivered ──────────────────────────────────────────────

def _outcome(monkeypatch, result):
    import telegram_alert
    import aegis_morning_brief_delivery as mod
    monkeypatch.setattr(telegram_alert, "publish_operator_message",
                        lambda *a, **k: result, raising=False)
    return mod.send_telegram_brief({"sections": [], "next_actions": []}, "s")


def test_a_suppressed_message_is_not_reported_as_sent(monkeypatch):
    """The incident: accepted=True, delivered=False, routed to the dashboard."""
    out = _outcome(monkeypatch, {"accepted": True, "delivered": False,
                                 "queued": False, "route_mode": "P2_DASHBOARD_ONLY"})
    assert out["delivered"] is False
    assert "sent" not in out["outcome"] or "not sent" in out["outcome"]
    assert "P2_DASHBOARD_ONLY" in out["outcome"]


def test_a_real_delivery_still_says_delivered(monkeypatch):
    out = _outcome(monkeypatch, {"accepted": True, "delivered": True,
                                 "route_mode": "P0_INTERRUPT"})
    assert out["outcome"] == "delivered"
    assert out["delivered"] is True


def test_a_digested_message_is_neither_sent_nor_failed(monkeypatch):
    """Returning False for a correctly digested event is what caused the retry
    storm this routing exists to stop -- so it must not read as failure."""
    out = _outcome(monkeypatch, {"accepted": True, "delivered": False,
                                 "queued": True, "route_mode": "P1_DIGEST"})
    assert "queued" in out["outcome"]
    assert "failed" not in out["outcome"]


def test_a_genuine_failure_still_says_failed(monkeypatch):
    out = _outcome(monkeypatch, {"accepted": False, "delivered": False,
                                 "reason": "token_missing"})
    assert out["outcome"].startswith("failed")
    assert "token_missing" in out["outcome"]
