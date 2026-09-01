"""The P1 digest sender — the tier's missing delivery.

A P1_DIGEST verdict archives a message to telegram_outbox and returns False.
Those rows are readable in the v3 Reports portal but nothing pushed them, so
"digest" meant "archived to a pull surface nobody was watching". 4,387 rows since
2026-07-02 against 1,707 delivered.

COVERS is not claimed for this file: it has no send_telegram call site of its own
outside deliver(), which these tests do exercise, so it is listed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["scripts/p1_digest_sender.py"]

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _rows(n=3, start_id=100):
    return [(start_id + i, NOW - timedelta(hours=1), "siem_p1",
             f"🚨 SIEM P1: pipeline {i}", "body") for i in range(n)]


@pytest.fixture
def sender(tmp_path, monkeypatch):
    monkeypatch.setenv("P1_DIGEST_STATE", str(tmp_path / "wm.json"))
    for m in list(sys.modules):
        if m == "p1_digest_sender":
            del sys.modules[m]
    import p1_digest_sender as P
    monkeypatch.setattr(P, "STATE", tmp_path / "wm.json", raising=True)
    return P


# ── rendering ────────────────────────────────────────────────────────────────
def test_digest_aggregates_by_cause_with_counts(sender):
    text = sender.render({"rows": _rows(13), "since_hours": 24, "watermark": 0})
    assert "×13" in text, text
    assert "13 suppressed messages" in text


def test_nothing_suppressed_renders_nothing(sender):
    assert sender.render({"rows": [], "since_hours": 24, "watermark": 0}) == ""


def test_many_kinds_are_folded_with_a_stated_remainder(sender):
    rows = [(i, NOW, f"kind_{i}", f"t{i}", "b") for i in range(40)]
    text = sender.render({"rows": rows, "since_hours": 24, "watermark": 0})
    assert "more kinds" in text, "a truncated list must say how many it folded"


# ── the safety property: the watermark ───────────────────────────────────────
def test_watermark_advances_only_after_a_confirmed_send(sender, monkeypatch):
    monkeypatch.setattr(sender, "collect",
                        lambda since_hours=24, query=None: {"rows": _rows(3), "since_hours": 24, "watermark": 0})
    monkeypatch.setattr(sender, "deliver", lambda text: True)
    monkeypatch.setattr(sys, "argv", ["p1", "--send"])
    assert sender.main() == 0
    assert json.loads(sender.STATE.read_text())["last_id"] == 102


def test_a_failed_delivery_does_not_advance_the_watermark(sender, monkeypatch):
    """Advancing first would silently drop the batch — the failure mode at issue."""
    monkeypatch.setattr(sender, "collect",
                        lambda since_hours=24, query=None: {"rows": _rows(3), "since_hours": 24, "watermark": 0})
    monkeypatch.setattr(sender, "deliver", lambda text: False)
    monkeypatch.setattr(sys, "argv", ["p1", "--send"])
    assert sender.main() == 1
    assert not sender.STATE.exists(), "watermark written despite a failed delivery"


def test_dry_run_sends_nothing_and_does_not_advance(sender, monkeypatch, alarm_capture):
    monkeypatch.setattr(sender, "collect",
                        lambda since_hours=24, query=None: {"rows": _rows(3), "since_hours": 24, "watermark": 0})
    monkeypatch.setattr(sys, "argv", ["p1"])
    assert sender.main() == 0
    assert not alarm_capture.fired
    assert not sender.STATE.exists()


# ── delivery must not be swallowed by the mechanism it drains ────────────────
def test_delivery_reaches_the_transport(sender, alarm_capture):
    assert sender.deliver("📋 P1 digest — probe") is True
    alarm_capture.assert_fired(contains="P1 digest")


def test_delivery_survives_a_router_that_refuses_everything(sender, alarm_capture, monkeypatch):
    """A digest OF suppressed messages, if routed, is suppressed in turn.

    That is not hypothetical: it is the same classification that swallowed its
    contents. This asserts the bypass is load-bearing.
    """
    try:
        import telegram_alert_router as TR
        monkeypatch.setattr(TR, "should_send_telegram", lambda *a, **k: False, raising=True)
    except Exception:
        pytest.skip("router unavailable")
    sender.deliver("📋 P1 digest — must survive the router")
    alarm_capture.assert_fired(contains="must survive")


# ── the backlog hazard ───────────────────────────────────────────────────────
def test_collect_is_bounded_by_time_not_only_by_watermark(sender):
    """A first run with watermark 0 must not page 4,387 rows.

    The query is bounded by BOTH id and sent_at, so a fresh state file yields the
    recent window rather than the entire archive.
    """
    seen = {}

    def fake_query(sql, params=None):
        seen["sql"] = sql
        seen["params"] = params
        return []

    sender.collect(since_hours=6, query=fake_query)
    assert "sent_at >" in seen["sql"], seen["sql"]
    assert "id > " in seen["sql"], seen["sql"]
    assert len(seen["params"]) == 2
