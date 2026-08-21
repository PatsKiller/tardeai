"""IIC Telegram inline feedback keyboard + signed-action apply path."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_action_links import (
    ACTIONS,
    MUTATING,
    apply_signed_disposition,
    mint_action_token,
    reject_lan_url,
    verify_action_token,
)
from scripts.lib.cio_notification_outbox import NotificationOutbox
from scripts.lib.cio_product_reassessment import _enqueue_material_product_outbox
from scripts.lib.cio_telegram_keyboard import build_intelligence_inline_keyboard


def _card(symbol: str = "UBER") -> dict:
    return {
        "symbol": symbol,
        "object_id": f"sio_{symbol}_reentry_added_NEAR",
        "headline": f"{symbol} · Added To Reentry Watch",
        "card_schema": "InvestmentIntelligenceCard@v1",
    }


def test_intelligence_keyboard_labels_and_https():
    kb = build_intelligence_inline_keyboard(_card(), key=b"unit-iic-key")
    labels = [c["text"] for r in kb["inline_keyboard"] for c in r]
    assert labels == [
        "Agree", "Disagree",
        "Interested", "Defer",
        "Need data", "Dismiss",
        "OPEN CIO", "Thesis",
    ]
    urls = [c["url"] for r in kb["inline_keyboard"] for c in r]
    assert all(u.startswith("https://") for u in urls)
    assert all(not reject_lan_url(u) for u in urls)
    assert any("/action/agree" in u for u in urls)
    assert any("/action/need_data" in u for u in urls)
    assert any("tab=research" in u and "UBER" in u for u in urls)
    assert kb["authority"] == "READ_ONLY_ADVISORY"
    assert kb["decision_id"].startswith("sio_UBER_")


def test_new_actions_in_actions_frozenset():
    for a in ("agree", "disagree", "interested", "need_data", "dismiss"):
        assert a in ACTIONS
        assert a in MUTATING


def test_signed_iic_token_roundtrip():
    did = "sio_UBER_reentry_added_NEAR"
    tok = mint_action_token(
        decision_id=did,
        action="agree",
        decision_input_digest="iic:UBER",
        decision_evidence_digest="InvestmentIntelligenceCard@v1",
        key=b"k",
    )
    vr = verify_action_token(tok, expected_action="agree", expected_decision_id=did, key=b"k")
    assert vr["ok"] is True
    assert vr["payload"]["decision_input_digest"] == "iic:UBER"


def test_apply_signed_agree_appends_feedback(tmp_path, monkeypatch):
    import scripts.lib.cio_operator_ticker_feedback as fb

    monkeypatch.setattr(fb, "feedback_path", lambda root=None: tmp_path / "otf.jsonl")
    # Avoid NEED_DATA side effects in other tests; agree has none.
    payload = {
        "decision_id": "sio_ANET_opportunity_added_1",
        "action": "agree",
        "decision_input_digest": "iic:ANET",
        "decision_evidence_digest": "InvestmentIntelligenceCard@v1",
    }
    result = apply_signed_disposition(payload)
    assert result.get("ok") is True
    assert result.get("intent") == "AGREE"
    assert result.get("symbol") == "ANET"
    assert (tmp_path / "otf.jsonl").exists()
    line = (tmp_path / "otf.jsonl").read_text(encoding="utf-8")
    assert "ANET" in line
    assert "AGREE" in line
    assert "telegram" in line


def test_apply_failsoft_without_feedback_module(monkeypatch):
    # sys.modules[name] = None → import raises (fail-soft path).
    monkeypatch.setitem(sys.modules, "scripts.lib.cio_operator_ticker_feedback", None)
    result = apply_signed_disposition({
        "decision_id": "sio_CSCO_reentry_upgrade_NEAR",
        "action": "disagree",
        "decision_input_digest": "iic:CSCO",
    })
    assert result.get("ok") is False
    assert result.get("error") == "feedback_module_unavailable"


def test_enqueue_attaches_reply_markup(tmp_path, monkeypatch):
    monkeypatch.setenv("CIO_ACTION_LINK_KEY", "unit-enqueue-key")
    outbox = NotificationOutbox(event_store_path=tmp_path / "outbox.jsonl")
    product = {
        "product_id": "prod_iic_kb_1",
        "trigger": "RESEARCH_COMPLETED",
        "reentry_book": {
            "names": [{
                "symbol": "UBER",
                "status": "NEAR",
                "current_price": 70.0,
                "what_happened_since": "Support hold after pullback.",
            }]
        },
    }
    changed = {
        "material": True,
        "as_of": "2026-08-21T12:00:00+00:00",
        "items": [
            {"kind": "reentry_added", "symbol": "UBER", "to": "NEAR", "material": True},
        ],
    }
    res = _enqueue_material_product_outbox(
        product, changed, {"symbol": "SPCX"}, root=tmp_path, outbox=outbox, max_cards=1,
    )
    assert res.get("outbox_enqueued") is True
    assert res.get("cards_enqueued") == 1
    notif = outbox.get_notification(res["outbox_notification_id"])
    assert notif is not None
    markup = notif.get("reply_markup")
    assert isinstance(markup, dict)
    labels = [c["text"] for r in (markup.get("inline_keyboard") or []) for c in r]
    assert "Agree" in labels
    assert "Need data" in labels
    assert "OPEN CIO" in labels
