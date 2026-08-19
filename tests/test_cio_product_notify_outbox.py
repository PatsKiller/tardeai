"""Material product what_changed enqueues NotificationOutbox; non-material does not."""
from __future__ import annotations

from pathlib import Path

from scripts.lib.cio_notification_outbox import NotificationOutbox
from scripts.lib.cio_product_reassessment import (
    _notify,
    should_enqueue_product_notification,
)


def test_should_enqueue_material_only():
    assert should_enqueue_product_notification({"material": False, "items": [{"kind": "reentry_added", "material": True}]}) is False
    assert should_enqueue_product_notification({"material": True, "items": [{"kind": "thesis_version", "material": True}]}) is False
    assert should_enqueue_product_notification({
        "material": True,
        "items": [{"kind": "reentry_upgrade", "symbol": "CSCO", "material": True}],
    }) is True


def test_notify_material_enqueues_outbox(tmp_path: Path, monkeypatch):
    store_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(event_store_path=store_path)
    product = {
        "product_id": "prod_material_1",
        "decision_id": "dec_material_1",
        "trigger": "RESEARCH_COMPLETED",
        "action_book": {},
        "reentry_book": {"names": []},
    }
    changed = {
        "material": True,
        "as_of": "2026-08-19T00:00:00+00:00",
        "items": [{"kind": "reentry_upgrade", "symbol": "CSCO", "from": "WAIT", "to": "NEAR", "material": True}],
    }
    nd = _notify(product, changed, {"symbol": "CSCO"}, root=tmp_path, outbox=outbox)
    assert nd.get("outbox_enqueued") is True
    assert store_path.is_file()
    text = store_path.read_text(encoding="utf-8")
    assert "NOTIFICATION_ENQUEUED" in text
    assert "prod_material_1" in text or "CSCO" in text


def test_notify_non_material_does_not_enqueue(tmp_path: Path):
    store_path = tmp_path / "outbox.jsonl"
    outbox = NotificationOutbox(event_store_path=store_path)
    product = {
        "product_id": "prod_quiet_1",
        "action_book": {},
        "reentry_book": {"names": []},
    }
    changed = {
        "material": False,
        "items": [{"kind": "thesis_version", "material": False}],
    }
    nd = _notify(product, changed, {"symbol": "SCHG"}, root=tmp_path, outbox=outbox)
    assert nd.get("outbox_enqueued") is False
    assert nd.get("outbox_skip_reason") == "non_material_what_changed"
    text = store_path.read_text(encoding="utf-8") if store_path.exists() else ""
    assert "NOTIFICATION_ENQUEUED" not in text
