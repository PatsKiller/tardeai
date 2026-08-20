"""P0.1 — telegram receipts unify dedicated CIO + generic ops + outbox paths."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.maturity_control.telegram_receipts import collect_telegram_receipts


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "data" / "cio").mkdir(parents=True)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.delenv("AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY", raising=False)
    monkeypatch.setenv("ENABLE_TELEGRAM", "true")
    monkeypatch.delenv("CIO_TELEGRAM_INTERDICT", raising=False)
    monkeypatch.delenv("TELEGRAM_CIO_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CIO_CHAT_IDS", raising=False)
    return tmp_path


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_prepare_only_note_and_generic_ops_receipt(root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "GENERICSECRET")
    _write(root / "data/cio/system_telegram_sends.jsonl", [{
        "at": "2026-08-20T12:00:00+00:00",
        "ok": True,
        "message_id": 48357,
        "family": "TRADE_AI_SYSTEM",
        "cio_lineage": False,
        "kind": "daily_heartbeat",
        "identity": "system-heartbeat:2026-08-20",
    }])
    # Pass explicit env so pytest lock does not force INTERDICTED for mode readout
    env = {
        "ENABLE_TELEGRAM": "true",
        "AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY": "0",
        "TELEGRAM_BOT_TOKEN": "GENERICSECRET",
    }
    view = collect_telegram_receipts(root=root, env=env)
    assert view["delivery_mode"] == "PREPARE_ONLY"
    assert view["prepare_only_does_not_mean_never_sent"] is True
    assert "PREPARE_ONLY" in view["delivery_mode_note"]
    assert view["generic_ops_delivered"] is True
    assert "generic_ops" in view["bots_that_delivered"]
    assert view["last_success"]["message_id"] == 48357
    assert view["last_success"]["bot_channel"] == "generic_ops"
    assert "GENERICSECRET" not in json.dumps(view)


def test_cio_alex_receipts_path_read(root: Path):
    _write(root / "data/cio/cio_telegram_receipts.jsonl", [{
        "decision_id": "dec_1",
        "dedupe_key": "k1",
        "delivered_at": "2026-08-19T01:00:00+00:00",
        "message_ids": [194],
        "channel": "telegram_cio",
        "general_channel": False,
    }])
    view = collect_telegram_receipts(root=root)
    assert view["dedicated_cio_delivered"] is True
    assert view["last_success"]["message_id"] == 194
    assert view["last_success"]["bot_channel"] == "dedicated_cio"
    assert "data/cio/cio_telegram_receipts.jsonl" in view["sources_read"]


def test_outbox_delivery_confirmed_surfaced(root: Path):
    _write(root / "data/cio/operator_notification_outbox.jsonl", [
        {
            "event_type": "NOTIFICATION_ENQUEUED",
            "occurred_at": "2026-08-20T04:00:32+00:00",
            "stream_id": "ntf_prod_1",
            "payload": {
                "notification_id": "ntf_prod_1",
                "subject": "CIO material change · BOOK",
                "message_class": "advisory",
                "dedupe_key": "product_what_changed:x",
            },
        },
        {
            "event_type": "DELIVERY_CONFIRMED",
            "occurred_at": "2026-08-20T04:00:33+00:00",
            "stream_id": "ntf_prod_1",
            "payload": {
                "notification_id": "ntf_prod_1",
                "channel": "telegram",
                "external_message_id": "195",
                "worker_id": "cio_delivery_worker",
            },
        },
    ])
    view = collect_telegram_receipts(root=root)
    assert view["receipt_count"] >= 2
    ok = [r for r in view["receipts"] if r.get("ok") is True]
    assert any(r.get("message_id") == "195" for r in ok)
    assert view["last_success"]["message_id"] == "195"
    # enqueue is prep (ok=None), confirm is delivery
    prep = [r for r in view["receipts"] if r.get("event_type") == "NOTIFICATION_ENQUEUED"]
    assert prep and prep[0].get("ok") is None


def test_does_not_invent_receipts(root: Path):
    view = collect_telegram_receipts(root=root)
    assert view["receipt_count"] == 0
    assert view["last_success"] is None
    assert view["bots_that_delivered"] == []
    assert view["generic_ops_delivered"] is False
    assert view["dedicated_cio_delivered"] is False
