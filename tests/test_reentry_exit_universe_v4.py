from __future__ import annotations

import sys
import types
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib import sale_event_detector as detector


class FakeCursor:
    def __init__(self, records):
        self.records = records
        self.description = [(name,) for name in (
            "id", "trade_date", "action", "symbol", "quantity", "price",
            "amount", "fees", "description", "account", "import_source",
            "dedupe_key", "trade_time",
        )]
        self.sql = ""
        self.params = ()

    def execute(self, sql, params=()):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.records


class FakeConn:
    def __init__(self, records):
        self.cursor_obj = FakeCursor(records)

    def cursor(self):
        return self.cursor_obj


def install_db(monkeypatch, records):
    conn = FakeConn(records)
    module = types.SimpleNamespace(_get_conn=lambda: conn)
    monkeypatch.setitem(sys.modules, "db_adapter", module)
    return conn


def rec(row_id, account, action="SELL", symbol="SCHG", quantity=1, price=10, amount=10, description=""):
    return (
        row_id, date.today(), action, symbol, quantity, price, amount, 0,
        description, account, "test-ingest", f"d:{row_id}", "15:30:00",
    )


def test_history_defaults_include_small_exits_from_every_real_account(monkeypatch):
    conn = install_db(monkeypatch, [
        rec(1, "schwab_taxable", amount=25),
        rec(2, "fidelity_roth_ira", amount=40),
        rec(3, "snaptrade_taxable", amount=12),
        rec(4, "alpaca_paper", amount=900),
        rec(5, "trade_ai_test", amount=900),
    ])

    rows = detector.load_sell_transactions(days=1)

    assert [row["account"] for row in rows] == [
        "schwab_taxable", "fidelity_roth_ira", "snaptrade_taxable",
    ]
    assert "account = ANY" not in conn.cursor_obj.sql
    assert all(detector._proceeds(row) < detector.MIN_PROCEEDS_USD for row in rows)


def test_assignment_expiration_and_close_actions_are_exit_rows():
    assert detector._is_sell_row({
        "action": "ASSIGNED", "description": "option assignment reduced shares", "symbol": "XYZ",
    })
    assert detector._is_sell_row({
        "action": "EXPIRED", "description": "short call expired", "symbol": "XYZ240101C00100000",
    })
    assert detector._is_sell_row({
        "action": "CLOSE", "description": "sell to close", "symbol": "XYZ240101C00100000",
    })
    assert not detector._is_sell_row({
        "action": "BUY TO OPEN", "description": "open buy", "symbol": "XYZ240101C00100000",
    })


def test_material_detector_preserves_legacy_account_and_minimum(monkeypatch):
    captured = {}

    def fake_load(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(detector, "load_sell_transactions", fake_load)
    deploy_db = types.SimpleNamespace(backfill_status_for_date=lambda *_args, **_kwargs: ("open", None))
    monkeypatch.setitem(sys.modules, "lib.deploy_events_db", deploy_db)

    assert detector.detect_sell_events(days=14) == []
    assert captured["include_all_real_accounts"] is False
    assert captured["accounts"] == detector.DEFAULT_ACCOUNTS
    assert captured["min_proceeds_usd"] == detector.MIN_PROCEEDS_USD


def test_normalized_exit_keeps_same_day_source_details():
    row = {
        "id": 11,
        "trade_date": date.today(),
        "trade_time": "14:05:00",
        "action": "SELL",
        "symbol": "SCHG",
        "quantity": -15,
        "price": 31.25,
        "amount": 468.75,
        "account": "schwab_taxable",
        "description": "protective stop fill",
        "import_source": "schwab_api",
        "dedupe_key": "schwab:11",
    }
    event = detector.normalize_sell_row(row, source="reentry_history")
    assert event["symbol"] == "SCHG"
    assert event["shares_sold"] == 15
    assert event["proceeds_usd"] == 468.75
    assert event["metadata"]["action"] == "SELL"
    assert event["metadata"]["trade_time"] == "14:05:00"
