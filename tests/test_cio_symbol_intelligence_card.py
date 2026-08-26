"""Investment Intelligence Card — product notify narrative (Phase A)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.lib.cio_notification_outbox import NotificationOutbox
from scripts.lib.cio_product_reassessment import _notify, _enqueue_material_product_outbox
from scripts.lib.cio_symbol_intelligence import (
    assemble_symbol_intelligence,
    render_telegram_card,
    cards_for_product_change,
)


def _desk(symbol: str, *, price: float = 72.5, stop: float = 68.0) -> dict:
    return {
        "symbol": symbol,
        "price": price,
        "price_source": "finviz",
        "price_as_of": datetime.now(timezone.utc).isoformat(),
        "entry_low": 68.0,
        "entry_high": 74.0,
        "stop": stop,
        "rsi": 52.0,
        "intel": {"state": "NEAR ENTRY"},
    }


def test_render_uber_near_no_raw_dump(monkeypatch):
    monkeypatch.setattr("scripts.lib.cio_symbol_intelligence._desk_row", lambda *a, **k: _desk("UBER"))
    obj = assemble_symbol_intelligence(
        "UBER",
        change_item={
            "kind": "reentry_added",
            "symbol": "UBER",
            "to": "NEAR",
            "material": True,
        },
        product={
            "trigger": "RESEARCH_COMPLETED",
            "reentry_book": {
                "names": [{
                    "symbol": "UBER",
                    "status": "NEAR",
                    "current_price": 72.5,
                    "what_happened_since": "Pullback toward prior support while ride-share demand intact.",
                    "setup": "Zone 68–74; desk NEAR",
                }]
            },
        },
        parent={"symbol": "SPCX"},
    )
    body = render_telegram_card(obj)
    assert "UBER" in body
    assert "Added to Reentry" in body or "Reentry" in body
    assert "<b>Do this</b>" in body or "Do this" in body
    assert "<b>Why now</b>" in body or "Why now" in body
    assert "<b>Thesis</b>" in body or "Thesis" in body
    assert "<b>Levels</b>" in body or "Levels" in body
    assert "🟠" in body  # reentry_added → WARM
    assert "*Why now*" not in body
    assert "*Thesis*" not in body
    assert "Causality" in body
    assert "SPCX" in body
    assert "Provenance" in body
    assert "FRESH_RESEARCH" in body or "Fresh research" in body
    assert "reentry_added UBER" not in body
    assert "symbol=BOOK" not in body
    assert "READ_ONLY_ADVISORY" in body


def test_cards_one_per_ticker(monkeypatch):
    monkeypatch.setattr("scripts.lib.cio_symbol_intelligence._desk_row", lambda sym, **k: _desk(sym))
    changed = {
        "material": True,
        "items": [
            {"kind": "reentry_added", "symbol": "UBER", "to": "NEAR", "material": True},
            {"kind": "opportunity_added", "symbol": "ANET", "to": 1, "material": True},
            {"kind": "reentry_added", "symbol": "UBER", "to": "NEAR", "material": True},  # dup
        ],
    }
    cards = cards_for_product_change(
        {"trigger": "RESEARCH_COMPLETED", "reentry_book": {"names": []}},
        changed,
        {"symbol": "SPCX"},
        max_cards=3,
    )
    syms = [c["symbol"] for c in cards]
    assert syms == ["UBER", "ANET"]


def test_enqueue_per_ticker_intelligence_body(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("scripts.lib.cio_symbol_intelligence._desk_row", lambda sym, **k: _desk(sym, price=70.0))
    outbox = NotificationOutbox(event_store_path=tmp_path / "outbox.jsonl")
    product = {
        "product_id": "prod_iic_1",
        "trigger": "MARKET_DATA_CHANGED",
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
        "as_of": "2026-08-21T00:00:00+00:00",
        "items": [
            {"kind": "reentry_added", "symbol": "UBER", "to": "NEAR", "material": True},
            {"kind": "opportunity_added", "symbol": "ANET", "to": 1, "material": True},
        ],
    }
    res = _enqueue_material_product_outbox(
        product, changed, {"symbol": "SPCX"}, root=tmp_path, outbox=outbox, max_cards=3,
    )
    assert res.get("outbox_enqueued") is True
    assert res.get("cards_enqueued") == 2
    assert res.get("attribution_symbol") == "UBER"
    text = (tmp_path / "outbox.jsonl").read_text(encoding="utf-8")
    assert "Why now" in text
    assert "Causality" in text
    assert "reentry_added UBER → NEAR" not in text
    assert "symbol=BOOK" not in text
    # Soft: IIC outbox notes opt into HTML parse_mode for Telegram bold/code.
    assert '"parse_mode": "HTML"' in text or '"parse_mode":"HTML"' in text


def test_research_completion_does_not_enqueue_unrelated_book_churn(tmp_path: Path):
    outbox = NotificationOutbox(event_store_path=tmp_path / "outbox.jsonl")
    res = _enqueue_material_product_outbox(
        {
            "product_id": "prod_cross_symbol",
            "trigger": "RESEARCH_COMPLETED",
            "reentry_book": {"names": []},
        },
        {
            "material": True,
            "items": [
                {"kind": "opportunity_added", "symbol": "FCNTX", "to": 20, "material": True},
                {"kind": "reentry_removed", "symbol": "JTAI", "from": "NEAR", "material": True},
            ],
        },
        {"symbol": "SCHD"},
        root=tmp_path,
        outbox=outbox,
    )
    assert res["outbox_enqueued"] is False
    assert res["outbox_skip_reason"] == "unrelated_rebuild_churn"


def test_notify_still_enqueues(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "scripts.lib.cio_symbol_intelligence._desk_row",
        lambda sym, **k: {
            **_desk(sym, price=50.0, stop=48.0),
            "entry_low": 49.0,
            "entry_high": 51.0,
        },
    )
    outbox = NotificationOutbox(event_store_path=tmp_path / "outbox.jsonl")
    product = {
        "product_id": "prod_material_1",
        "decision_id": "dec_material_1",
        "trigger": "RESEARCH_COMPLETED",
        "action_book": {},
        "reentry_book": {"names": [{"symbol": "CSCO", "status": "NEAR", "current_price": 50, "stop": 48}]},
    }
    changed = {
        "material": True,
        "as_of": "2026-08-19T00:00:00+00:00",
        "items": [{"kind": "reentry_upgrade", "symbol": "CSCO", "from": "WAIT", "to": "NEAR", "material": True}],
    }
    nd = _notify(product, changed, {"symbol": "CSCO"}, root=tmp_path, outbox=outbox)
    assert nd.get("outbox_enqueued") is True
    body = (tmp_path / "outbox.jsonl").read_text(encoding="utf-8")
    assert "CSCO" in body
    assert "Technical setup" in body or "Why now" in body


def test_reentry_rationale_uses_one_structured_snapshot(monkeypatch):
    monkeypatch.setattr(
        "scripts.lib.cio_symbol_intelligence._desk_row",
        lambda *a, **k: {
            **_desk("FCNTX", price=27.19, stop=25.10),
            "entry_low": 25.38,
            "entry_high": 26.96,
            "why": ["Price $26.65 is inside the validated entry zone $25.38–$26.96."],
        },
    )
    obj = assemble_symbol_intelligence(
        "FCNTX",
        change_item={"kind": "reentry_added", "symbol": "FCNTX", "to": "NEAR", "material": True},
        product={
            "trigger": "RESEARCH_COMPLETED",
            "reentry_book": {"names": [{"symbol": "FCNTX", "status": "NEAR", "current_price": 27.19}]},
        },
        parent={"symbol": "FCNTX"},
    )
    assert any("$27.19 is 0.9% above" in reason for reason in obj["why_now"])
    assert all("$26.65" not in reason for reason in obj["why_now"])


def test_opportunity_card_does_not_borrow_reentry_mechanics(monkeypatch):
    monkeypatch.setattr("scripts.lib.cio_symbol_intelligence._desk_row", lambda *a, **k: _desk("FCNTX"))
    obj = assemble_symbol_intelligence(
        "FCNTX",
        change_item={"kind": "opportunity_added", "symbol": "FCNTX", "to": 20, "material": True},
        product={
            "trigger": "RESEARCH_COMPLETED",
            "opportunity_book": {"top": [{"symbol": "FCNTX", "rank": 20, "actionability": "RESEARCH_REQUIRED"}]},
        },
        parent={"symbol": "FCNTX"},
    )
    body = render_telegram_card(obj)
    assert "Opportunity membership changed; rank 20" in body
    assert "<b>Levels</b>" not in body
    assert "caused:" not in body


def test_product_desk_price_conflict_is_suppressed(monkeypatch):
    monkeypatch.setattr(
        "scripts.lib.cio_symbol_intelligence._desk_row",
        lambda *a, **k: {
            **_desk("FCNTX", price=27.19, stop=25.10),
            "entry_low": 25.38,
            "entry_high": 26.96,
        },
    )
    cards = cards_for_product_change(
        {
            "trigger": "MARKET_DATA_CHANGED",
            "reentry_book": {"names": [{
                "symbol": "FCNTX", "status": "NEAR", "current_price": 26.65,
            }]},
        },
        {"material": True, "items": [{
            "kind": "reentry_added", "symbol": "FCNTX", "to": "NEAR", "material": True,
        }]},
        {"symbol": "FCNTX"},
        material_items=[{"kind": "reentry_added", "symbol": "FCNTX", "to": "NEAR", "material": True}],
    )
    assert cards == []


def test_supplied_jtai_card_is_suppressed(monkeypatch):
    monkeypatch.setattr(
        "scripts.lib.cio_symbol_intelligence._desk_row",
        lambda *a, **k: {
            **_desk("JTAI", price=1.59, stop=1.60),
            "entry_low": 1.68,
            "entry_high": 1.83,
        },
    )
    cards = cards_for_product_change(
        {"trigger": "RESEARCH_COMPLETED", "reentry_book": {"names": [{
            "symbol": "JTAI", "status": "NEAR", "current_price": 1.59,
        }]}},
        {"material": True, "items": [{
            "kind": "reentry_added", "symbol": "JTAI", "to": "NEAR", "material": True,
        }]},
        {"symbol": "JTAI"},
    )
    assert cards == []
