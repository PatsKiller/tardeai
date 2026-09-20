"""The Communications Editor at telegram_transport.deliver_text: off / shadow / live.

Offline: a fake poster stands in for Telegram; registry and CIO reads are
patched; ledger and receipts are temp files.
"""
from __future__ import annotations

import json

import pytest

import scripts.lib.comms_editor as ce
import scripts.telegram_transport as tt


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMS_EDITOR_LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("COMMS_EDITOR_RECEIPTS", str(tmp_path / "receipts.jsonl"))
    monkeypatch.setattr(ce, "subjects", lambda text, resolve=None: (
        [{"symbol": "AXTI", "guid": "11111111-2222-3333-4444-555555555555"}] if "AXTI" in (text or "") else []))
    monkeypatch.setattr(ce, "default_db_query", lambda sql, params=None, fetch="all": [])
    monkeypatch.setattr(tt, "_interdicted", lambda: False)
    monkeypatch.setattr(tt, "_comms_editor", lambda: ce)
    sent = []

    def post(url, payload):
        sent.append(payload)
        return {"ok": True, "status_code": 200, "response": {"ok": True, "result": {"message_id": len(sent)}}}
    return tmp_path, sent, post


def _send(post, text="⚠️ *STOP WARNING* AXTI near stop"):
    return tt.deliver_text(token="t", chat_id="42", text=text, post=post)


def test_off_sends_the_original_unchanged(env, monkeypatch):
    tmp, sent, post = env
    monkeypatch.setenv("COMMS_EDITOR_MODE", "off")
    _send(post)
    assert sent[0]["text"] == "⚠️ *STOP WARNING* AXTI near stop"
    assert not (tmp / "receipts.jsonl").exists()


def test_shadow_sends_the_original_and_writes_a_receipt(env, monkeypatch):
    tmp, sent, post = env
    monkeypatch.setenv("COMMS_EDITOR_MODE", "shadow")
    _send(post)
    _send(post)
    assert [p["text"] for p in sent] == ["⚠️ *STOP WARNING* AXTI near stop"] * 2
    rows = [json.loads(line) for line in (tmp / "receipts.jsonl").read_text().splitlines()]
    assert len(rows) == 2 and rows[0]["mode"] == "shadow" and "text" not in rows[0]
    assert rows[0]["subjects"][0]["symbol"] == "AXTI"


def test_live_sends_html_with_links_and_guid_then_holds_the_duplicate(env, monkeypatch):
    tmp, sent, post = env
    monkeypatch.setenv("COMMS_EDITOR_MODE", "live")
    first = _send(post)
    assert first["ok"] and sent[0]["parse_mode"] == "HTML"
    assert "<b>STOP WARNING</b>" in sent[0]["text"] and "finviz.com/quote.ashx?t=AXTI" in sent[0]["text"]
    assert "🆔" in sent[0]["text"]
    second = _send(post)
    assert second["ok"] and second["suppressed"] == "duplicate" and len(sent) == 1


def test_live_holds_an_invalid_operator_product(env, monkeypatch):
    tmp, sent, post = env
    monkeypatch.setenv("COMMS_EDITOR_MODE", "live")
    out = _send(post, "[CIO DECISION] AXTI\nCompleteness: 3 of 5 · OPERATOR_PRODUCT_INVALID")
    assert out["suppressed"] == "operator_product_invalid" and sent == []


def test_live_rewrites_go_to_watch_when_cio_says_research_more(env, monkeypatch):
    """2026-09-20 C2: NEW GO + CIO RESEARCH_MORE soft-rewrites to WATCH and delivers.

    Pre-C2 this path held with ``suppressed=cio_disagreement``. Hard-bear CIO
    (AVOID) still holds — see ``test_live_holds_cio_disagreement_go_vs_avoid``.
    """
    tmp, sent, post = env
    monkeypatch.setenv("COMMS_EDITOR_MODE", "live")
    monkeypatch.setattr(ce, "subjects", lambda text, resolve=None: (
        [{"symbol": "ELMT", "guid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}] if "ELMT" in (text or "") else []))
    monkeypatch.setattr(
        ce, "default_db_query",
        lambda sql, params=None, fetch="all": [
            {"symbol": "ELMT", "action": "RESEARCH_MORE", "created_at": "2026-09-13T17:08:00-04:00"}
        ],
    )
    out = _send(post, "🎯 *NEW GO* — *ELMT* score=44 RVOL 165.3x")
    assert out["ok"] and not out.get("suppressed") and sent
    body = sent[0]["text"].upper()
    assert "WATCH" in body
    assert "NEW GO" not in body.replace("WATCH", "")
    assert "RESEARCH_MORE" in body or "CIO ELMT" in body


def test_live_holds_cio_disagreement_go_vs_avoid(env, monkeypatch):
    """Hard-bear CIO: GO vs AVOID stays held at the transport (no soft rewrite)."""
    tmp, sent, post = env
    monkeypatch.setenv("COMMS_EDITOR_MODE", "live")
    monkeypatch.setattr(ce, "subjects", lambda text, resolve=None: (
        [{"symbol": "ELMT", "guid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}] if "ELMT" in (text or "") else []))
    monkeypatch.setattr(
        ce, "default_db_query",
        lambda sql, params=None, fetch="all": [
            {"symbol": "ELMT", "action": "AVOID", "created_at": "2026-09-13T17:08:00-04:00"}
        ],
    )
    out = _send(post, "🎯 *NEW GO* — *ELMT* score=44 RVOL 165.3x")
    assert out["ok"] and out.get("suppressed") == "cio_disagreement" and sent == []


def test_live_delivers_a_multi_decision_digest_with_invalid_markers(env, monkeypatch):
    """A fresh-day morning brief is a digest, not a standalone invalid product.

    2026-09-16 07:30 ET: the bare substring hold suppressed two of the three
    morning-brief chunks, so the operator got only the tail. A digest with many
    ``[CIO DECISION]`` blocks must ship even when it reports ``OPERATOR_PRODUCT_INVALID``.
    """
    tmp, sent, post = env
    monkeypatch.setenv("COMMS_EDITOR_MODE", "live")
    body = (
        "☀️ MORNING CIO BRIEF\n\n"
        "[CIO DECISION] AXTI\nDecision: AVOID\n"
        "Completeness: 3 of 5 fields unpopulated · OPERATOR_PRODUCT_INVALID\n\n"
        "[CIO DECISION] IRDM\nDecision: TRIM\n"
        "Completeness: 3 of 5 fields unpopulated · OPERATOR_PRODUCT_INVALID\n\n"
        "Re-entry book A: 2 names"
    )
    out = _send(post, body)
    assert out["ok"] and not out.get("suppressed")
    assert sent, "the daily digest must be delivered, not held"


def test_editor_failure_never_blocks_the_send(env, monkeypatch):
    tmp, sent, post = env
    monkeypatch.setenv("COMMS_EDITOR_MODE", "live")

    def boom(*a, **k):
        raise RuntimeError("editor down")
    monkeypatch.setattr(ce, "edit", boom)
    out = _send(post)
    assert out["ok"] and sent[0]["text"] == "⚠️ *STOP WARNING* AXTI near stop"


def test_failed_send_is_not_recorded_so_a_retry_is_not_held(env, monkeypatch):
    tmp, sent, post = env
    monkeypatch.setenv("COMMS_EDITOR_MODE", "live")
    calls = []

    def failing(url, payload):
        calls.append(payload)
        return {"ok": False, "status_code": 500, "response": {"ok": False}}
    tt.deliver_text(token="t", chat_id="42", text="AXTI plain", post=failing)
    retry = tt.deliver_text(token="t", chat_id="42", text="AXTI plain", post=post)
    assert retry["ok"] and not retry.get("suppressed") and len(sent) == 1
