"""MEM-CONTAIN review B2: a cold (SWR UNKNOWN) or refused /api/v2/risk read never crashes the stop-alert assembler;
it is an explicit UNKNOWN that the Telegram stopinfo reply and the stop alert name as "risk data unavailable", never
"no position". Synthetic symbols and payloads; every send is a recorder."""
import time

import pytest

from scripts.lib import shared_get_swr as swr


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SWR_SLOT_DIR", raising=False)
    monkeypatch.setattr(swr, "cgroup_memory", lambda: (None, None))
    swr.clear()
    yield
    deadline = time.time() + 5
    while swr.running_builds() and time.time() < deadline:
        time.sleep(0.01)
    swr.clear()


def _cold_risk_body(monkeypatch):
    import api_v2

    class R:
        def risk_payload(self, db_query=None):
            time.sleep(0.5)
            return {"positions": []}
    monkeypatch.setattr(api_v2, "_cio_truth_readers", lambda: R())
    body = api_v2._risk_payload_cached()
    assert body["status"] == "UNKNOWN" and body["positions"] is None  # the served cold shape
    return body


def test_cold_risk_is_unknown_not_a_crash(monkeypatch):
    import stop_alert_assembler as saa

    body = _cold_risk_body(monkeypatch)
    monkeypatch.setattr(saa, "_api_get", lambda p: {"ok": True, "data": body} if p == "/api/v2/risk" else {})
    out = saa.assemble_stop_alert_data("SYNTH")
    assert out["status"] == "UNKNOWN" and out["symbol"] == "SYNTH"
    assert "still building" in out["reason"]


def test_refused_risk_read_is_unknown(monkeypatch):
    import stop_alert_assembler as saa

    monkeypatch.setattr(saa, "_api_get", lambda p: {})  # _api_get's own failure shape (timeout, refused, 5xx)
    out = saa.assemble_stop_alert_data("SYNTH")
    assert out["status"] == "UNKNOWN" and "unavailable" in out["reason"]


def test_ready_risk_without_the_position_is_still_none(monkeypatch):
    import stop_alert_assembler as saa

    monkeypatch.setattr(saa, "_api_get", lambda p: {"ok": True, "data": {"positions": [{"symbol": "OTHER"}]}}
                        if p == "/api/v2/risk" else {})
    assert saa.assemble_stop_alert_data("SYNTH") is None


def test_telegram_stopinfo_replies_risk_unavailable(monkeypatch):
    import stop_alert_assembler as saa
    import telegram_callback_handler as tch

    body = _cold_risk_body(monkeypatch)
    monkeypatch.setattr(saa, "_api_get", lambda p: {"ok": True, "data": body} if p == "/api/v2/risk" else {})
    replies, answers = [], []
    monkeypatch.setattr(tch, "_allowed_chat_ids", lambda: ["1001"])
    monkeypatch.setattr(tch, "send_reply", lambda chat, mid, text: replies.append(text))
    monkeypatch.setattr(tch, "answer_callback", lambda cb_id, text, show_alert=False: answers.append(text))
    tch.handle_callback_query({"id": "cb1", "data": "stopinfo:SYNTH", "from": {"id": 1001, "first_name": "op"},
                               "message": {"chat": {"id": 1001}, "message_id": 7}})
    assert len(replies) == 1 and "SYNTH" in replies[0] and "risk data unavailable" in replies[0]
    assert "still building" in replies[0]
    assert answers


def test_stop_alert_names_unknown_risk_in_its_one_existing_send(monkeypatch):
    import proposal_alerter as pa
    import stop_alert_assembler as saa
    import telegram_alert

    body = _cold_risk_body(monkeypatch)
    monkeypatch.setattr(saa, "_api_get", lambda p: {"ok": True, "data": body} if p == "/api/v2/risk" else {})
    sent = []
    monkeypatch.setattr(telegram_alert, "send_telegram", lambda msg, **k: sent.append(msg))
    monkeypatch.setattr(pa, "_shadow_publish", lambda *a, **k: None)
    pa.send_stop_alert("SYNTH")
    assert len(sent) == 1 and "SYNTH" in sent[0] and "risk data unavailable" in sent[0]
