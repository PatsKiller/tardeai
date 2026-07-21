#!/usr/bin/env python3
"""GET-only transport + live read sync no-op merge (read-only integration 2026-07-21)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from brokers import alpaca_read_client as arc  # noqa: E402
import alpaca_live_read_sync as sync  # noqa: E402


def test_http_get_allows_get():
    with mock.patch("urllib.request.urlopen") as uo:
        resp = mock.MagicMock()
        resp.read.return_value = b'{"status":"ACTIVE"}'
        resp.__enter__ = mock.Mock(return_value=resp)
        resp.__exit__ = mock.Mock(return_value=False)
        uo.return_value = resp
        out = arc.http_get("https://paper-api.alpaca.markets/v2/account", {"APCA-API-KEY-ID": "k"})
        assert out["status"] == "ACTIVE"
        req = uo.call_args[0][0]
        assert req.get_method() == "GET"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "post", "delete"])
def test_http_refuses_non_get(method):
    with pytest.raises(arc.MethodNotAllowedError, match="GET only"):
        arc.http_get("https://api.alpaca.markets/v2/orders", {}, method=method)


def test_fetch_json_skips_when_api_read_disabled():
    with mock.patch.object(arc, "_api_read_enabled", return_value=(False, {"credential_slot": "ALPACA_TAXABLE"})):
        with mock.patch.object(arc, "http_get") as hg:
            assert arc.fetch_json("alpaca_taxable_live", "/v2/positions") is None
            hg.assert_not_called()


def test_fetch_positions_empty_when_disabled():
    with mock.patch.object(arc, "_api_read_enabled", return_value=(False, None)):
        assert arc.fetch_positions("alpaca_ira_live") == []


def test_merge_empty_noop_no_prior(tmp_path, monkeypatch):
    """Empty positions + no prior rows for account → must not rewrite portfolio."""
    hp = tmp_path / "holdings.json"
    payload = {
        "holdings": [
            {"symbol": "AAPL", "account": "schwab_taxable", "market_value": 1000, "shares": 5},
        ],
        "portfolio_totals": {"total_value": 1000},
    }
    hp.write_text(json.dumps(payload))
    monkeypatch.setattr(sync, "HOLDINGS_PATH", hp)

    with mock.patch("holdings_guard.protected_holdings_write") as phw:
        res = sync._merge_account_into_holdings("alpaca_taxable_live", [], dry_run=False)
        assert res["ok"] is True
        assert res["wrote"] is False
        assert res["reason"] == "empty_noop_no_prior"
        phw.assert_not_called()
        # file untouched
        after = json.loads(hp.read_text())
        assert after["holdings"][0]["symbol"] == "AAPL"
        assert after["portfolio_totals"]["total_value"] == 1000


def test_merge_replaces_only_target_account(tmp_path, monkeypatch):
    hp = tmp_path / "holdings.json"
    payload = {
        "holdings": [
            {"symbol": "AAPL", "account": "schwab_taxable", "market_value": 1000, "shares": 5},
            {"symbol": "OLD", "account": "alpaca_taxable_live", "market_value": 50, "shares": 1},
        ],
        "portfolio_totals": {"total_value": 1050},
    }
    hp.write_text(json.dumps(payload))
    monkeypatch.setattr(sync, "HOLDINGS_PATH", hp)

    new_rows = [{
        "symbol": "TSLA", "account": "alpaca_taxable_live",
        "shares": 2, "quantity": 2, "price": 200, "market_value": 400,
        "source": "alpaca_live_read",
    }]
    captured = {}

    def _fake_write(data, **kwargs):
        captured["data"] = data
        return {"wrote": True, "status": "ok"}

    with mock.patch("holdings_guard.protected_holdings_write", side_effect=_fake_write):
        res = sync._merge_account_into_holdings("alpaca_taxable_live", new_rows, dry_run=False)
        assert res["ok"] and res["wrote"]
        holds = captured["data"]["holdings"]
        accts = {h["account"] for h in holds}
        assert "schwab_taxable" in accts
        assert "alpaca_taxable_live" in accts
        assert any(h["symbol"] == "TSLA" for h in holds)
        assert not any(h["symbol"] == "OLD" for h in holds)
        assert not any(h["account"] == "alpaca_taxable_live" and h["symbol"] == "AAPL" for h in holds)


def test_run_zero_api_when_no_enabled_accounts():
    with mock.patch.object(sync, "_live_read_accounts", return_value=[]):
        with mock.patch.object(sync, "sync_one") as s1:
            out = sync.run(dry_run=True)
            assert out["ok"] is True
            assert out["api_calls"] == 0
            s1.assert_not_called()


def test_positions_to_holdings_rows_skips_zero_qty():
    rows = sync._positions_to_holdings_rows("alpaca_ira_live", [
        {"symbol": "SPY", "qty": "0", "current_price": "500", "market_value": "0"},
        {"symbol": "QQQ", "qty": "3", "current_price": "400", "market_value": "1200", "avg_entry_price": "390"},
    ])
    assert len(rows) == 1
    assert rows[0]["symbol"] == "QQQ"
    assert rows[0]["account"] == "alpaca_ira_live"
    assert rows[0]["source"] == "alpaca_live_read"
