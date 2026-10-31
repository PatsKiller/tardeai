"""Market-risk delivery policy (operator 2026-10-31, DSN-20261031-market-risk-engine P3-T1, §11 item 5).

The 2026-10-30 selloff RCA (finding 3): the only market-level warning of the week fired at 05:52 ET as a P2 and
the quiet window (22:00-07:00 ET) archived it for a digest that rendered it as ``• kind ×n``. A P2 whose
``message_class`` is ``market_risk`` is now DELIVERED inside the pre-market window named in
config/notification_intent_quiet_exemptions.json; every other P2 is still held; P1 is unchanged.
Nothing here reaches Telegram: the transport is stubbed by ``alarm_capture``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import telegram_alert as TA  # noqa: E402
import telegram_alert_router as TR  # noqa: E402

ET = ZoneInfo("America/New_York")
CONFIG = ROOT / "config" / "notification_intent_quiet_exemptions.json"


def _et(hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(2026, 10, 30, h, m, tzinfo=ET)  # a Friday


@pytest.fixture
def quiet(monkeypatch, tmp_path):
    """Durable state in tmp; the quiet window itself is the real one (22:00-07:00 ET by default)."""
    monkeypatch.delenv("TRADEAI_INCIDENT_NOTIFIER_QUIET_START", raising=False)
    monkeypatch.delenv("TRADEAI_INCIDENT_NOTIFIER_QUIET_END", raising=False)
    monkeypatch.delenv("TRADEAI_INCIDENT_NOTIFIER_TZ", raising=False)
    monkeypatch.delenv(TR.QUIET_EXEMPTIONS_ENV, raising=False)
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(tmp_path / "dedupe.jsonl"))
    monkeypatch.setattr(TR, "_intent_sent", {})
    monkeypatch.setattr(TR, "_durable_recently_sent", lambda key, ttl: False)
    return tmp_path


# ── the config is the policy ────────────────────────────────────────────────────────────────────────────────


def test_config_names_the_window_and_only_market_risk_p2():
    doc = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert doc["schema"] == TR.QUIET_EXEMPTIONS_SCHEMA
    rows = TR.load_quiet_exemptions()
    assert [r["id"] for r in rows] == ["market_risk_premarket"]
    assert rows[0]["message_classes"] == ["market_risk"] and rows[0]["priorities"] == ["P2"]
    assert rows[0]["window"] == {"start": "04:00", "end": "09:30", "tz": "America/New_York"}


def test_missing_or_malformed_config_means_no_exemption(quiet, monkeypatch, tmp_path):
    monkeypatch.setenv(TR.QUIET_EXEMPTIONS_ENV, str(tmp_path / "absent.json"))
    assert TR.load_quiet_exemptions() == []
    assert TR.route_intent("x", "P2", message_class="market_risk", now=_et("05:30"))["decision"] == "HELD_QUIET_HOURS"
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "schema": "Other@v1",
                "exemptions": [
                    {"id": "e", "message_classes": ["market_risk"], "window": {"start": "00:00", "end": "23:59"}}
                ],
            }
        )
    )
    monkeypatch.setenv(TR.QUIET_EXEMPTIONS_ENV, str(bad))
    assert TR.load_quiet_exemptions() == []


# ── the route decision ─────────────────────────────────────────────────────────────────────────────────────


def test_market_risk_p2_at_0530_et_is_delivered(quiet):
    assert TR.intent_in_quiet_hours(_et("05:30")) is True, "05:30 ET is inside the default quiet window"
    r = TR.route_intent(
        "MARKET RISK YELLOW 42/100 probe",
        "P2",
        producer="market_risk_engine",
        message_class="market_risk",
        now=_et("05:30"),
    )
    assert r["decision"] == "DELIVER" and r["deliver"] is True
    assert r["quiet_exemption"] == "market_risk_premarket"


def test_ops_info_p2_at_0530_et_is_still_held(quiet):
    r = TR.route_intent(
        "🧹 Weekly disk cleanup probe", "P2", producer="weekly_disk_cleanup", message_class="ops/info", now=_et("05:30")
    )
    assert r["decision"] == "HELD_QUIET_HOURS" and r["deliver"] is False and "quiet_exemption" not in r
    r = TR.route_intent("no class probe", "P2", now=_et("05:30"))
    assert r["decision"] == "HELD_QUIET_HOURS"


def test_market_risk_p2_outside_the_premarket_window_is_still_held(quiet):
    r = TR.route_intent("MARKET RISK YELLOW probe", "P2", message_class="market_risk", now=_et("23:15"))
    assert r["decision"] == "HELD_QUIET_HOURS", "23:15 ET is quiet and outside 04:00-09:30"
    r = TR.route_intent("MARKET RISK YELLOW probe", "P2", message_class="market_risk", now=_et("03:59"))
    assert r["decision"] == "HELD_QUIET_HOURS"
    r = TR.route_intent("MARKET RISK YELLOW probe", "P2", message_class="market_risk", now=_et("04:00"))
    assert r["decision"] == "DELIVER"


def test_market_risk_p3_is_never_exempt(quiet):
    r = TR.route_intent("MARKET RISK BLUE probe", "P3", message_class="market_risk", now=_et("05:30"))
    assert r["decision"] == "DIGEST"


def test_stop_health_p1_is_unchanged(quiet):
    r = TR.route_intent(
        "🚨 CRITICAL STOP ALERT probe",
        "P1",
        dedupe_minutes=0,
        producer="stop_health_check",
        message_class="stop_health",
        now=_et("05:30"),
    )
    assert r["decision"] == "DELIVER" and "quiet_exemption" not in r
    r = TR.route_intent(
        "🚨 CRITICAL STOP ALERT probe", "P1", dedupe_minutes=0, message_class="stop_health", now=_et("23:15")
    )
    assert r["decision"] == "DELIVER"
    # stop_health pages as a P1 intent since fix 3f91991e5 (SPCX 10-14); the text classifier is not consulted
    # for an intent and this change never touches it.


# ── end to end through send_telegram: the message_class reaches the router and the receipt says why ──────


def test_send_telegram_passes_message_class_and_receipts_the_exemption(quiet, alarm_capture, monkeypatch, tmp_path):
    monkeypatch.setenv(TR.INTENT_RECEIPTS_ENV, str(tmp_path / "intent_receipts.jsonl"))
    monkeypatch.setattr(TR, "durable_mark_sent", lambda key, meta=None: None)
    import alert_runtime_mode

    monkeypatch.setattr(alert_runtime_mode, "get_mode", lambda **k: alert_runtime_mode.MODE_OFF)
    monkeypatch.setattr(TA, "_comms_gateway_owns", lambda mc: False)
    monkeypatch.setattr(TA, "_best_effort_comms_publish", lambda *a, **k: None)
    import report_capture

    archived: list = []
    monkeypatch.setattr(
        report_capture,
        "archive_message",
        lambda message, suppressed=False, reason="", report_type=None: archived.append(report_type) or report_type,
    )
    # pin the wall clock the router sees to 05:30 ET (real decision code runs; only `now` is injected)
    real_quiet, real_exempt = TR.intent_in_quiet_hours, TR.quiet_exemption_for
    monkeypatch.setattr(TR, "intent_in_quiet_hours", lambda now=None: real_quiet(_et("05:30")))
    monkeypatch.setattr(TR, "quiet_exemption_for", lambda mc, pr, now=None: real_exempt(mc, pr, _et("05:30")))

    assert (
        TA.send_telegram(
            "MARKET RISK YELLOW 42/100 probe",
            priority="P2",
            dedupe_minutes=0,
            producer="market_risk_engine",
            message_class="market_risk",
        )
        is True
    )
    alarm_capture.assert_fired(contains="MARKET RISK YELLOW")
    assert archived == []
    rec = [json.loads(line) for line in (tmp_path / "intent_receipts.jsonl").read_text().splitlines() if line]
    assert rec[-1]["decision"] == "DELIVER" and rec[-1]["quiet_exemption"] == "market_risk_premarket"
    assert rec[-1]["delivered"] is True

    assert (
        TA.send_telegram(
            "🧹 Weekly disk cleanup probe",
            priority="P2",
            dedupe_minutes=0,
            producer="weekly_disk_cleanup",
            message_class="ops/info",
        )
        is True
    )
    assert archived == [TR.HELD_P2_REPORT_TYPE]
    assert len(alarm_capture.transport) == 1, "the ops/info P2 was held, not sent"


# ── the Communications hub knows the category ─────────────────────────────────────────────────────────────


def test_comms_hub_classifies_market_risk_cards():
    doc = yaml.safe_load((ROOT / "config" / "comms_categories.yaml").read_text(encoding="utf-8"))
    assert doc["categories"]["market_risk"]["label"] == "Market Risk"
    from comms.classify import classify as _c

    def classify(body):
        return _c(body=body)

    red = classify("🔴 RED ALERT ACTIVE — acknowledgment required · Risk 83/100")
    assert red["category"] == "market_risk" and red["priority"] == "critical" and red["actionable"] is True
    orange = classify("MARKET RISK ORANGE 63/100 · QQQ failed retest")
    assert orange["category"] == "market_risk" and orange["priority"] == "critical"
    yellow = classify("MARKET RISK YELLOW 42/100 · Semis weak")
    assert yellow["category"] == "market_risk" and yellow["priority"] == "high"
    flow = classify("📈 OPTIONS FLOW STRESS — QQQ put/call volume 3.31")
    assert flow["category"] == "market_risk" and flow["priority"] == "critical"
    stop = classify("🚨 CRITICAL STOP ALERT — probe")
    assert stop["category"] == "threat", "a per-position stop card is still a threat, not market risk"
