from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lib.reentry_exit_cache import CACHE_KEY, refresh_exit_cache


class FakeExecute:
    def __init__(self):
        self.saved = None
        self.transactions = [
            {
                "id": 1,
                "trade_date": dt.date(2026, 7, 23),
                "trade_time": dt.time(14, 5),
                "action": "SELL",
                "symbol": "SCHG",
                "quantity": -15,
                "price": 31.25,
                "amount": 468.75,
                "fees": 0.05,
                "description": "protective stop fill",
                "account": "schwab_taxable",
                "import_source": "schwab_api",
                "dedupe_key": "schwab:1",
            },
            {
                "id": 2,
                "trade_date": dt.date(2026, 7, 23),
                "trade_time": dt.time(14, 6),
                "action": "SELL",
                "symbol": "TEST",
                "quantity": -100,
                "price": 10,
                "amount": 1000,
                "fees": 0,
                "description": "paper sell",
                "account": "alpaca_paper",
                "import_source": "paper",
                "dedupe_key": "paper:2",
            },
            {
                "id": 3,
                "trade_date": dt.date(2026, 7, 22),
                "trade_time": dt.time(11, 30),
                "action": "ASSIGNED",
                "symbol": "XYZ",
                "quantity": -100,
                "price": None,
                "amount": 2500,
                "fees": 1.25,
                "description": "option assignment reduced exposure",
                "account": "snaptrade_taxable",
                "import_source": "snaptrade",
                "dedupe_key": "snap:3",
            },
        ]
        self.events = [
            {
                "id": 44,
                "event_key": "txn:schwab:1",
                "status": "open",
                "completion_status": "pending",
                "operator_status": "open",
                "proceeds_settled": False,
                "sold_at": dt.date(2026, 7, 23),
                "source": "live_detect",
            }
        ]

    def __call__(self, sql, params=(), fetch=None):
        normalized = " ".join(sql.split()).lower()
        if "from trade_transactions" in normalized:
            return self.transactions
        if "from deploy_events" in normalized:
            return self.events
        if "insert into ui_prefs" in normalized:
            assert params[0] == CACHE_KEY
            self.saved = json.loads(params[1])
            return None
        raise AssertionError(f"unexpected SQL: {normalized}")


def test_cache_preserves_full_source_fields_and_pending_rows():
    ex = FakeExecute()

    payload = refresh_exit_cache(ex)

    assert payload["counts"]["exits_found"] == 2
    assert payload["counts"]["matched"] == 1
    assert payload["counts"]["pending_reconciliation"] == 1
    assert {row["symbol"] for row in payload["rows"]} == {"SCHG", "XYZ"}

    schg = next(row for row in payload["rows"] if row["symbol"] == "SCHG")
    assert schg["trade_date"] == "2026-07-23"
    assert schg["trade_time"] == "14:05:00"
    assert schg["action"] == "SELL"
    assert schg["quantity"] == 15
    assert schg["signed_quantity"] == -15
    assert schg["price"] == 31.25
    assert schg["proceeds_usd"] == 468.75
    assert schg["fees"] == 0.05
    assert schg["description"] == "protective stop fill"
    assert schg["import_source"] == "schwab_api"
    assert schg["matched_event_id"] == 44
    assert schg["reconciliation"] == "matched"

    xyz = next(row for row in payload["rows"] if row["symbol"] == "XYZ")
    assert xyz["action"] == "ASSIGNED"
    assert xyz["price"] == 25.0
    assert xyz["matched_event_id"] is None
    assert xyz["reconciliation"] == "pending"
    assert ex.saved == payload


def test_paper_account_is_not_cached():
    ex = FakeExecute()

    payload = refresh_exit_cache(ex)

    assert all(row["account"] != "alpaca_paper" for row in payload["rows"])
    assert "alpaca_paper" not in payload["counts"]["accounts"]
