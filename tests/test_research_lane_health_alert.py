"""Alert-state unwrap + per-lane hints. Dedup must survive a 15-min timer."""
from __future__ import annotations

import json
import time

import research_lane_health as hl


def test_unwrap_heals_nested_lanes_wrapper():
    nested = {"as_of": "t0", "lanes": {"as_of": "t1", "lanes": {
        "deepseek": {"last_alert": 111, "ok": False},
        "overnight-deep": {"last_alert": 222, "ok": False},
    }}}
    m = hl.unwrap_lane_map(nested)
    assert m["deepseek"]["last_alert"] == 111
    assert m["overnight-deep"]["last_alert"] == 222
    assert "as_of" not in m


def test_unwrap_flat_map_passthrough():
    m = hl.unwrap_lane_map({
        "as_of": "t",
        "lanes": {"deepseek": {"last_alert": 9}},
        "schema": "x",
    })
    assert m == {"deepseek": {"last_alert": 9}}


def test_fix_hint_is_not_stale_import():
    h = hl.fix_hint({"lane": "deepseek", "firing": ["error_streak:50>=5"]})
    assert "lib.llm_lane" not in h or "already" in h.lower()
    assert "COST_CONFIGURATION_INVALID" in h
    o = hl.fix_hint({"lane": "overnight-deep", "firing": ["zero_non_error_24h"]})
    assert "ChatGPT" in o and "gemma" in o
    d = hl.fix_hint({"lane": "drive-sync", "firing": ["exit_code:1", "zero_uploaded_with_failures:1230"]})
    assert "404" in d


def test_alert_dedup_does_not_send_twice(tmp_path, monkeypatch):
    path = tmp_path / "health.json"
    monkeypatch.setattr(hl, "STATUS_PATH", path)
    monkeypatch.setattr(hl, "ALERT_DEDUP_SEC", 6 * 3600)
    sent = []
    monkeypatch.setattr(hl, "_deliver_telegram", lambda msg: sent.append(msg))

    report = {
        "as_of": "now",
        "ok": False,
        "lanes": [
            {"lane": "deepseek", "ok": False, "firing": ["error_streak:50>=5"],
             "error_streak": 50, "non_error_24h": 1, "attempts_24h": 275},
        ],
    }
    n1 = hl._alert(report)
    n2 = hl._alert(report)
    assert n1 == 1
    assert n2 == 0
    assert len(sent) == 1
    assert "COST_CONFIGURATION_INVALID" in sent[0]
    assert "lib.llm_lane" not in sent[0] or "already" in sent[0]
    raw = json.loads(path.read_text())
    assert raw["lanes"]["deepseek"]["last_alert"] > 0
    assert "as_of" not in raw.get("lanes", {})
    assert time.time() - int(raw["lanes"]["deepseek"]["last_alert"]) < 5
    assert "deepseek (watched)" in sent[0]


def test_raw_store_health_classifies_digest_not_interrupt():
    """D3 2026-09-16: this heartbeat is machine telemetry, never a phone page.

    It fired ~40x/day to the DM because the producer bypassed the router. When
    it DOES go through the router, the header must classify DIGEST (P1), not
    INTERRUPT (P0). Mutate this by making the header read like capital-at-risk
    and confirm the assert goes red.
    """
    from telegram_alert_router import classify_alert, should_send_telegram
    msg = (
        "⚠️ *Research lane RAW-store health*\n"
        "Reads RAW stores (research rows **including** `[ERROR]…`, Drive "
        "last-result JSON, CURRENT vs SOURCE_COMMIT). Silence is not health.\n\n"
        "Firing:\n"
        "  • deepseek: budget_throttled:5/70  streak=0  ok_24h=0 attempts_24h=70\n"
        "  • chatgpt: error_rate_24h:77.8>=15  streak=0  ok_24h=0 attempts_24h=9\n"
    )
    assert classify_alert(msg) == "P1_DIGEST"
    assert should_send_telegram(msg) is False


def test_deliver_telegram_does_not_bypass_router(monkeypatch):
    """The producer must hand off to the classifier, not page the phone.

    bypass_router=True was the whole bug: it skipped classify_alert() and sent
    this non-actionable heartbeat straight to the DM ~40x/day. Mutate this by
    flipping the producer back to bypass_router=True and the captured kwarg
    goes red.
    """
    import telegram_alert as _ta
    captured = {}

    def _fake_send(msg, bypass_router=True, **kw):
        captured["bypass_router"] = bypass_router
        return True

    monkeypatch.setattr(_ta, "send_telegram", _fake_send, raising=True)
    hl._deliver_telegram("⚠️ *Research lane RAW-store health*")
    assert captured.get("bypass_router") is False


def test_alert_suppressed_to_digest_not_transported(alarm_capture, tmp_path, monkeypatch):
    """End-to-end: a firing lane lands in the router's digest, not the transport.

    Proves the full path — _alert -> _deliver_telegram -> send_telegram(bypass_router=False)
    -> router classify P1_DIGEST -> archived — with nothing reaching the phone.
    Mutate by restoring bypass_router=True and alarm_capture.transport fills (red).
    """
    monkeypatch.setattr(hl, "STATUS_PATH", tmp_path / "health.json")
    monkeypatch.setattr(hl, "ALERT_DEDUP_SEC", 6 * 3600)
    report = {
        "as_of": "now",
        "ok": False,
        "lanes": [
            {"lane": "deepseek", "ok": False, "firing": ["budget_throttled:5/70"],
             "error_streak": 0, "non_error_24h": 0, "attempts_24h": 70},
        ],
    }
    n = hl._alert(report)
    assert n == 1
    assert not alarm_capture.transport, (
        "RAW-store health must not page the phone; it should route to digest. "
        f"{len(alarm_capture.transport)} message(s) reached the transport."
    )
    assert any("RAW-store health" in s for s in alarm_capture.suppressed), (
        "expected the heartbeat in the router's suppressed/digest set, got "
        f"{alarm_capture.suppressed[:2]}"
    )


def test_alert_exit_zero_when_alarms_found(monkeypatch, tmp_path):
    """systemd failed must mean CHECK crashed, not 'found problems'."""
    monkeypatch.setattr(hl, "STATUS_PATH", tmp_path / "h.json")
    monkeypatch.setattr(hl, "_deliver_telegram", lambda msg: None)
    report = {
        "as_of": "now",
        "ok": False,
        "lanes": [
            {"lane": "deepseek", "ok": True, "firing": [], "error_streak": 0,
             "non_error_24h": 545, "attempts_24h": 545},
            {"lane": "overnight-deep", "ok": False, "firing": ["zero_non_error_24h"],
             "error_streak": 0, "non_error_24h": 0, "attempts_24h": 0},
        ],
    }
    rc = hl._alert(report)
    assert rc in (0, 1)  # 1 would be sent-count; check main()
    monkeypatch.setattr(hl, "collect_report", lambda: report)
    import sys
    monkeypatch.setattr(sys, "argv", ["research_lane_health.py", "--alert"])
    assert hl.main() == 0
