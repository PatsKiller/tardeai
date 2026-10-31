"""A comms-critical POSITION alert that the legacy router digests by classification is sent as a deduped P1 intent.

2026-10-31 audit: cron senders run with the comms gateway OFF, so the legacy router decides. In 48 h it digested 13
messages the comms classifier rated critical, including the 10-30 11:07 ET position-sync "[holdings-change] …
protective-stop band recheck recommended" alerts. The independent review of the first version showed it also paged
health-repeat and telemetry messages and a self-reversing holdings flap 5/5; this version is narrow (config), never
overrides health-repeat or rate/budget suppression, sends a P1 intent (exact-body dedupe + receipt) and pages a
subject at most once per window. Fixtures only: synthetic symbols, transport stubbed, temp state, no network or DB.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import telegram_alert as ta  # noqa: E402
import telegram_alert_router as router  # noqa: E402

FLAP_CLOSE = "[holdings-change] SYMA closed 1000→0 sh — protective-stop band recheck recommended"
FLAP_OPEN = "[holdings-change] SYMA opened 0→1000 sh — protective-stop band recheck recommended"
OTHER_NAME = "[holdings-change] SYMB resized 900→1200 sh — protective-stop band recheck recommended"
HEALTH = "Health Agent: DEGRADED — 41/100 protective-stop coverage gap"
REAPER = "Process reaper: 2 orphaned workers cleaned up"
SWEEP = "stop_health sweep complete: 27 checked, 0 issues"


@pytest.fixture
def transport(monkeypatch, tmp_path):
    sent: list[str] = []
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(tmp_path / "dedupe.jsonl"))
    monkeypatch.setenv("TRADEAI_INTENT_RECEIPTS_PATH", str(tmp_path / "receipts.jsonl"))
    monkeypatch.setattr(router, "_intent_sent", {})
    monkeypatch.setattr(ta, "_token", lambda: "synthetic")
    monkeypatch.setattr(ta, "_chat_ids", lambda: ["1"])
    monkeypatch.setattr(ta, "_raw_send_telegram_result", lambda m, t, **kw: sent.append(m) or {"ok": True})
    monkeypatch.setattr(router, "_record_budget_send", lambda: None, raising=False)
    import report_capture

    monkeypatch.setattr(report_capture, "archive_message", lambda *a, **k: None)
    return sent


def _receipts(tmp_path):
    p = tmp_path / "receipts.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_stop_recheck_is_paged_once_as_a_receipted_p1_intent(transport, tmp_path):
    assert sum(bool(ta._legacy_send(FLAP_CLOSE, False)) for _ in range(5)) == 1
    assert transport == [FLAP_CLOSE]
    r = _receipts(tmp_path)
    assert r[0]["priority"] == "P1" and r[0]["producer"] == "legacy_critical_override" and r[0]["delivered"] is True


def test_self_reversing_flap_pages_the_subject_once_per_window(transport):
    assert ta._legacy_send(FLAP_CLOSE, False) is True
    assert ta._legacy_send(FLAP_OPEN, False) is False  # same SYMA inside subject_window_minutes
    assert ta._legacy_send(OTHER_NAME, False) is True  # a different name is its own subject
    assert transport == [FLAP_CLOSE, OTHER_NAME]


@pytest.mark.parametrize("message", [HEALTH, REAPER, SWEEP])
def test_health_and_telemetry_are_never_overridden(transport, message):
    assert sum(bool(ta._legacy_send(message, False)) for _ in range(5)) == 0
    assert transport == []


def test_rate_limited_or_budget_suppression_is_not_overridden(monkeypatch, transport):
    monkeypatch.setattr(router, "should_send_telegram", lambda m: False)
    monkeypatch.setattr(router, "classify_alert", lambda m: "P0_INTERRUPT")
    assert ta._legacy_send(FLAP_CLOSE, False) is False
    assert transport == []


def test_comms_classifier_really_rates_the_fixture_critical():
    from scripts.lib.comms.classify import classify

    c = classify(body=FLAP_CLOSE)
    assert c["priority"] == "critical" and c["rule_id"] == "stop_health"


def test_classifier_failure_is_sent_as_receipted_intent_and_keeps_the_hold(monkeypatch, transport, tmp_path):
    import scripts.lib.comms.classify as c

    def boom(**kw):
        raise RuntimeError("config unreadable")

    monkeypatch.setattr(c, "classify", boom)
    assert ta._legacy_send(FLAP_CLOSE, False) is False  # the original message keeps the router's hold
    assert len(transport) == 1 and "COMMS CLASSIFIER DOWN" in transport[0]
    assert any(r["producer"] == "legacy_critical_override" and r["priority"] == "P2" for r in _receipts(tmp_path))


def test_disabled_config_restores_the_router(monkeypatch, transport, tmp_path):
    cfg = json.loads(Path(ta._OVERRIDE_CONFIG).read_text())
    cfg["enabled"] = False
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(cfg))
    monkeypatch.setattr(ta, "_OVERRIDE_CONFIG", str(p))
    assert ta._legacy_send(FLAP_CLOSE, False) is False
    assert transport == []
