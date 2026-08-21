"""Suppress legacy raw CIO product dumps; HTML parse_mode opt-in."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.cio_notification_delivery import (
    RealTelegramAdapter,
    is_raw_product_dump_body,
)
from scripts.lib.cio_notification_outbox import NotificationOutbox
from scripts.lib.cio_product_reassessment import _enqueue_material_product_outbox


def test_is_raw_product_dump_body_prefix():
    assert is_raw_product_dump_body(
        "Material CIO product change · BOOK\n\n- reentry_added UBER"
    )
    assert is_raw_product_dump_body("… Material CIO product change · X …")


def test_is_raw_product_dump_body_two_bullets():
    dump = (
        "Some header\n"
        "- reentry_added UBER → NEAR\n"
        "- opportunity_added ANET → 1\n"
    )
    assert is_raw_product_dump_body(dump) is True


def test_is_raw_product_dump_body_one_bullet_false():
    assert is_raw_product_dump_body("- reentry_added UBER → NEAR\n") is False


def test_is_raw_product_dump_body_html_card_false():
    card = (
        "⚪ <b>CIO book update</b>\n"
        "Causality: <code>SPCX</code> · RESEARCH_COMPLETED\n"
        "Attribution: <code>BOOK</code>\n"
        "No single-ticker material rows to card.\n"
        "READ_ONLY_ADVISORY"
    )
    assert is_raw_product_dump_body(card) is False
    assert is_raw_product_dump_body("") is False
    assert is_raw_product_dump_body("Why now\nThesis\nTechnical setup") is False


def test_adapter_suppresses_raw_dump(monkeypatch):
    adapter = RealTelegramAdapter(bot_token="t", chat_id="1")
    sent = []

    def boom(*a, **k):
        sent.append((a, k))
        raise AssertionError("send_cio_message must not be called for raw dumps")

    monkeypatch.setattr(
        "scripts.lib.cio_telegram_transport.send_cio_message", boom, raising=False
    )
    # Also patch the late import path used inside send()
    import scripts.lib.cio_telegram_transport as tg

    monkeypatch.setattr(tg, "send_cio_message", boom)
    monkeypatch.setattr(tg, "network_interdicted", lambda: False)

    body = (
        "Material CIO product change · BOOK\n"
        "- reentry_added UBER → NEAR\n"
        "- opportunity_added ANET → 1\n"
    )
    res = adapter.send(
        {
            "notification_id": "ntf_raw_1",
            "subject": "CIO material change · BOOK",
            "body": body,
        }
    )
    assert res.get("delivered") is False
    assert res.get("error") == "SUPPRESSED_RAW_PRODUCT_DUMP"
    assert sent == []


def test_adapter_passes_html_parse_mode(monkeypatch):
    adapter = RealTelegramAdapter(bot_token="t", chat_id="1")
    seen = {}

    def fake_send(body, **kwargs):
        seen["body"] = body
        seen.update(kwargs)
        return {"delivered": True, "message_ids": [42]}

    import scripts.lib.cio_telegram_transport as tg

    monkeypatch.setattr(tg, "send_cio_message", fake_send)
    monkeypatch.setattr(tg, "network_interdicted", lambda: False)

    res = adapter.send(
        {
            "notification_id": "ntf_html_1",
            "subject": "CIO book update · BOOK",
            "body": "⚪ <b>CIO book update</b>\nREAD_ONLY_ADVISORY",
            "parse_mode": "HTML",
        }
    )
    assert res.get("delivered") is True
    assert seen.get("parse_mode") == "HTML"


def test_adapter_ignores_unsupported_parse_mode(monkeypatch):
    adapter = RealTelegramAdapter(bot_token="t", chat_id="1")
    seen = {}

    def fake_send(body, **kwargs):
        seen.update(kwargs)
        return {"delivered": True, "message_ids": [1]}

    import scripts.lib.cio_telegram_transport as tg

    monkeypatch.setattr(tg, "send_cio_message", fake_send)
    monkeypatch.setattr(tg, "network_interdicted", lambda: False)

    res = adapter.send(
        {
            "notification_id": "ntf_md_1",
            "body": "plain advisory",
            "parse_mode": "Markdown",
        }
    )
    assert res.get("delivered") is True
    assert seen.get("parse_mode") is None


def test_enqueue_book_fallback_html_subject(tmp_path: Path):
    """Temperament-only / no-ticker material → muted HTML book digest."""
    outbox = NotificationOutbox(event_store_path=tmp_path / "outbox.jsonl")
    product = {
        "product_id": "prod_book_1",
        "trigger": "RESEARCH_COMPLETED",
        "reentry_book": {"names": []},
    }
    changed = {
        "material": True,
        "as_of": "2026-08-21T00:00:00+00:00",
        # No symbol → cards_for_product_change returns []
        "items": [{"kind": "temperament_changed", "material": True}],
    }
    res = _enqueue_material_product_outbox(
        product, changed, {"symbol": "SPCX"}, root=tmp_path, outbox=outbox
    )
    assert res.get("outbox_enqueued") is True
    assert res.get("cards_enqueued") == 0
    assert res.get("attribution_symbol") == "BOOK"
    notif = outbox.get_notification(res["outbox_notification_id"])
    assert notif is not None
    assert notif.get("subject") == "CIO book update · BOOK"
    assert notif.get("parse_mode") == "HTML"
    body = notif.get("body") or ""
    assert "<b>CIO book update</b>" in body
    assert "CIO material change" not in (notif.get("subject") or "")
    assert "*CIO" not in body
    assert is_raw_product_dump_body(body) is False


def test_enqueue_card_sets_html_parse_mode(tmp_path: Path):
    outbox = NotificationOutbox(event_store_path=tmp_path / "outbox.jsonl")
    product = {
        "product_id": "prod_iic_html",
        "trigger": "RESEARCH_COMPLETED",
        "reentry_book": {
            "names": [{
                "symbol": "UBER",
                "status": "NEAR",
                "current_price": 70.0,
                "what_happened_since": "Support hold.",
            }]
        },
    }
    changed = {
        "material": True,
        "as_of": "2026-08-21T00:00:00+00:00",
        "items": [
            {"kind": "reentry_added", "symbol": "UBER", "to": "NEAR", "material": True},
        ],
    }
    res = _enqueue_material_product_outbox(
        product, changed, {"symbol": "SPCX"}, root=tmp_path, outbox=outbox, max_cards=1,
    )
    assert res.get("outbox_enqueued") is True
    notif = outbox.get_notification(res["outbox_notification_id"])
    assert notif is not None
    assert notif.get("parse_mode") == "HTML"
    assert is_raw_product_dump_body(notif.get("body") or "") is False
