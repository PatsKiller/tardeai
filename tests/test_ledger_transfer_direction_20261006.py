"""Schwab ledger keeps the direction of transfers (2026-10-06).

schwab_transaction_ingest took abs() of the security leg, so every RECEIVE_AND_DELIVER / share JOURNAL row read as
an INFLOW (rollover IRA: 21 of 55 transfers were outflows). Lots rebuilt from the ledger over-counted (SCHG 12,000
vs the broker's 2,000); with direction kept, 9 lot gaps fell to 3, all explained (broker lot-relief method, one
pre-ledger fund). Also: requests over a year are split (Schwab refuses > 1 year), and a dry run never pages.
Fakes only: no network, no database, no broker.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import schwab_transaction_ingest as si  # noqa: E402
import positions_sync as ps  # noqa: E402


def _xfer(typ, sym, amount, aid, day="2026-07-17"):
    return {"type": typ, "tradeDate": f"{day}T00:00:00+0000", "netAmount": 0.0, "activityId": aid,
            "description": "SCHWAB U.S. LARGE-CAP GROWTH ETF",
            "transferItems": [{"instrument": {"assetType": "COLLECTIVE_INVESTMENT", "symbol": sym}, "amount": amount}]}


def test_transfer_direction_is_kept():
    rows = si._map_rows("schwab_rollover_ira", [_xfer("RECEIVE_AND_DELIVER", "SCHG", 5000.0, 1),
                                                _xfer("RECEIVE_AND_DELIVER", "SCHG", -5000.0, 2)])
    assert [(r["action"], r["quantity"]) for r in rows] == [("Security Transfer", 5000.0),
                                                           ("Security Transfer Out", 5000.0)]


def test_share_journal_direction_is_kept_and_cash_journal_unchanged():
    out = si._map_rows("schwab_taxable", [_xfer("JOURNAL", "SPCX", -100.0, 3)])
    assert out[0]["action"] == "Journaled Shares Out"
    cash = dict(_xfer("JOURNAL", "X", 0, 4), transferItems=[{"instrument": {"assetType": "CURRENCY"}, "amount": 5}])
    assert si._map_rows("schwab_taxable", [cash])[0]["action"] == "Journal"


def test_lots_follow_transfers_out():
    t = lambda i, d, a, q, amt=0.0: {"id": i, "trade_date": d, "account": "schwab_rollover_ira", "symbol": "SCHG",
                                     "action": a, "quantity": q, "price": 0, "amount": amt, "fees": 0}
    led = [t(1, dt.date(2026, 7, 15), "Buy", 2774, -95000.0), t(2, dt.date(2026, 7, 16), "Security Transfer", 5000),
           t(3, dt.date(2026, 7, 17), "Security Transfer", 5000), t(4, dt.date(2026, 7, 17), "Security Transfer Out", 5000),
           t(5, dt.date(2026, 7, 23), "Sell", 7774, 259411.52), t(6, dt.date(2026, 9, 29), "Buy", 2000, -72735.0)]
    lots, realized = ps.build_lots(led)
    assert sum(l["qty_open"] for l in lots) == 2000           # the broker's 2,000 — was 12,000
    assert not any(r["qty"] == 5000 and r["proceeds"] for r in realized if r["sell_txn_id"] == 4)


def test_reconcile_fifo_consumes_transfers_out_without_a_sale():
    import portfolio_reconcile as pr
    tx = [{"symbol": "V", "action": "Security Transfer", "quantity": 130, "price": 0, "trade_date": "2026-02-24"},
          {"symbol": "V", "action": "Security Transfer Out", "quantity": 130, "price": 0, "trade_date": "2026-02-24",
           "trade_time": "1"},
          {"symbol": "V", "action": "Buy", "quantity": 10, "price": 300.0, "trade_date": "2026-03-01"},
          {"symbol": "V", "action": "Sell", "quantity": 10, "price": 0, "trade_date": "2026-04-01", "dedupe_key": "k"}]
    out = pr.fifo_sell_basis(tx)
    assert out[("V", "2026-04-01", "k")][0] == 3000.0          # basis known: the transfer-in lot left first


class _Resp:
    def __init__(self, v): self.v = v
    def json(self): return self.v


class _Client:
    def __init__(self, fail_after=None):
        self.calls, self.fail_after = [], fail_after

    def get_transactions(self, h, start_date, end_date):
        assert (end_date - start_date).days <= si.MAX_WINDOW_DAYS
        self.calls.append((start_date, end_date))
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            return _Resp({"message": "boom"})
        return _Resp([{"activityId": len(self.calls)}, {"activityId": 999}])   # 999 repeats on the boundary


def test_fetch_is_chunked_under_a_year_and_dedupes_boundaries():
    U = dt.timezone.utc
    c = _Client()
    out = si._fetch_chunked(c, "h", dt.datetime(2025, 7, 1, tzinfo=U), dt.datetime(2026, 10, 6, tzinfo=U))
    assert len(c.calls) == 2 and sorted(x["activityId"] for x in out) == [1, 2, 999]


def test_a_failed_window_is_reported_not_returned_as_partial_history():
    U = dt.timezone.utc
    out = si._fetch_chunked(_Client(fail_after=1), "h", dt.datetime(2025, 7, 1, tzinfo=U),
                            dt.datetime(2026, 10, 6, tzinfo=U))
    assert out == {"message": "boom"}


def test_a_dry_run_never_pages():
    src = (ROOT / "scripts" / "schwab_transaction_ingest.py").read_text()
    body = src[src.index("def run("):]
    assert body.count("_emit_health_alert(report)") == 2 and body.count("if apply") >= 2
