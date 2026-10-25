"""ONE wash-sale implementation (EXCEPTIONS_MATRIX R9, operator 2026-10-25: "I need you to fix everything that's
missing before deployment."). Table-driven over real trade_transactions rows (SELECT of 2026-10-25, values verbatim);
no database, no broker."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import wash_sale as ws  # noqa: E402

ET = timezone(timedelta(hours=-4))


def tx(account, symbol, action, day, hh, mm, qty, price, fees="0"):
    y, m, d = map(int, day.split("-"))
    return {"account": account, "symbol": symbol, "action": action, "trade_date": date(y, m, d),
            "trade_time": datetime(y, m, d, hh, mm, tzinfo=ET), "quantity": Decimal(qty), "price": Decimal(price),
            "fees": Decimal(fees)}


# Real rows: SPCX (schwab_taxable loss sale 2026-10-14 bracketed by same-day IRA + taxable rebuys).
SPCX = [
    tx("schwab_taxable", "SPCX", "Buy", "2026-06-16", 10, 3, "30", "224.51"),
    tx("schwab_taxable", "SPCX", "Buy", "2026-06-16", 10, 13, "10", "216.41"),
    tx("schwab_rollover_ira", "SPCX", "Buy", "2026-06-16", 10, 26, "80", "210.41"),
    tx("schwab_taxable", "SPCX", "Buy", "2026-09-08", 12, 42, "60", "154.56"),
    tx("schwab_taxable", "SPCX", "Buy", "2026-10-06", 11, 25, "100", "173.67"),
    tx("schwab_rollover_ira", "SPCX", "Buy", "2026-10-07", 12, 56, "200", "167.59"),
    tx("schwab_taxable", "SPCX", "Sell", "2026-10-14", 14, 36, "200", "151.5337", "0.62"),
    tx("schwab_rollover_ira", "SPCX", "Sell", "2026-10-14", 14, 38, "600", "151.50", "1.87"),
    tx("schwab_rollover_ira", "SPCX", "Buy", "2026-10-14", 15, 4, "600", "151.425"),
    tx("schwab_taxable", "SPCX", "Buy", "2026-10-14", 15, 4, "200", "151.385"),
    tx("schwab_rollover_ira", "SPCX", "Buy", "2026-10-23", 12, 50, "100", "147.61"),
]
# Real rows: PFLT (shares transferred in, so the 2026-10-07 taxable sale has no lots on file → UNVERIFIED).
PFLT = [
    tx("schwab_taxable", "PFLT", "Buy", "2026-07-01", 17, 1, "10.9904", "7.6412"),
    tx("schwab_taxable", "PFLT", "Sell", "2026-07-09", 15, 27, "1049", "7.03", "0.35"),
    tx("schwab_taxable", "PFLT", "Sell", "2026-10-07", 9, 34, "11", "6.64"),
]
# Real rows: NFLX sold only in the rollover IRA → no deductible loss → no window.
NFLX = [
    tx("schwab_rollover_ira", "NFLX", "Sell", "2026-10-05", 9, 55, "300", "66.63", "0.41"),
    tx("schwab_rollover_ira", "NFLX", "Sell", "2026-10-16", 9, 30, "400", "70.17", "0.58"),
]
# SCHD (tests/test_decision_integrity_schd_20260925.py TAXABLE_TXS): a GAIN → house hold, never a wash window.
SCHD = [{**r, "account": "schwab_taxable", "symbol": "SCHD"} for r in [
    {"trade_date": "2026-02-25", "action": "Buy", "quantity": 100, "price": 31.4097, "fees": 0},
    {"trade_date": "2026-02-26", "action": "Buy", "quantity": 300, "price": 31.48, "fees": 0},
    {"trade_date": "2026-06-29", "action": "Buy", "quantity": 6.544, "price": 31.2688, "fees": 0},
    {"trade_date": "2026-09-08", "action": "Sell", "quantity": 406, "price": 34.695, "fees": 0.37}]]


@pytest.mark.parametrize("rows,today,kind,gated,until", [
    (SPCX, "2026-10-25", ws.KIND_WASH_RISK, True, "2026-11-13"),
    (SPCX, "2026-11-13", ws.KIND_WASH_RISK, True, "2026-11-13"),      # day S+30 is still inside (inclusive)
    (SPCX, "2026-11-14", ws.KIND_NONE, False, None),                  # first clear day is S+31
    (PFLT, "2026-10-25", ws.KIND_UNVERIFIED, True, "2026-11-06"),     # unknown basis is never a silent clear
    (NFLX, "2026-10-25", ws.KIND_NONE, False, None),                  # IRA sale: no deductible loss, no window
    (SCHD, "2026-09-20", ws.KIND_HOUSE_HOLD_GAIN, False, None),       # gain: house hold only
])
def test_canonical_window_table(rows, today, kind, gated, until):
    w = ws.symbol_window(rows, today=date.fromisoformat(today))
    assert (w["kind"], w["gated"], w["until"]) == (kind, gated, until)
    if kind == ws.KIND_WASH_RISK:
        assert w["realized_gain"] < 0 and "IRA included" in w["label"] and "through 2026-11-13" in w["label"]
        # Acquisitions in EVERY account inside ±30 d of the loss sale are listed (the IRA rebuy washes the loss).
        assert {a["account"] for a in w["acquisitions_within_30d"]} == {"schwab_taxable", "schwab_rollover_ira"}


def test_fifo_basis_never_pools_lots_across_accounts():
    # The IRA lots (cheaper) must not lower the taxable sale's basis.
    w = ws.symbol_window(SPCX, today=date(2026, 10, 25))
    taxable_sale = next(s for s in w["sales"] if s["account"] == "schwab_taxable")
    assert taxable_sale["realized_gain"] == pytest.approx(30306.74 - 0.62 - 35540.0, abs=0.05)
    assert all(s["account"] == "schwab_taxable" for s in w["sales"]), "IRA sales never open a window"


def test_an_earlier_loss_inside_the_window_is_not_hidden_by_a_later_gain():
    rows = [tx("schwab_taxable", "XYZ", "Buy", "2026-09-01", 10, 0, "10", "100"),
            tx("schwab_taxable", "XYZ", "Sell", "2026-10-01", 10, 0, "5", "80"),     # loss
            tx("schwab_taxable", "XYZ", "Sell", "2026-10-10", 10, 0, "5", "120")]    # gain
    w = ws.symbol_window(rows, today=date(2026, 10, 20))
    assert w["kind"] == ws.KIND_WASH_RISK and w["sell_date"] == "2026-10-01" and w["until"] == "2026-10-31"
    assert w["house_hold_until"] == "2026-11-09"


@pytest.mark.parametrize("account,taxable", [("schwab_taxable", True), ("moomoo_taxable_live", True),
    ("alpaca_taxable_live", True), ("schwab_rollover_ira", False), ("schwab_roth_ira", False),
    ("fidelity_rollover_ira", False), ("tradeai_automated", False), ("unregistered_brokerage", True)])
def test_account_taxability_comes_from_the_account_registry(account, taxable):
    assert ws.account_taxable(account) is taxable


@pytest.mark.parametrize("sale,today,open_,left", [
    ("2026-10-14", "2026-10-14", True, 31), ("2026-10-14", "2026-11-13", True, 1),
    ("2026-10-14", "2026-11-14", False, 0), ("2026-10-14", "2026-10-13", False, 0),
    (datetime(2026, 10, 14, 23, 30, tzinfo=timezone.utc), "2026-11-13", True, 1)])   # 19:30 ET → trade date 10-14
def test_window_arithmetic(sale, today, open_, left):
    assert ws.window_open(sale, today) is open_ and ws.days_left(sale, today) == left


# ── every former implementation now routes through the canonical module ───────────────────────────────────

def test_former_implementations_share_one_constant_and_one_classifier():
    import rotation_round_trips as rt
    import portfolio_tax
    from scripts.lib import decision_integrity as di, reentry_rules as rr
    from scripts.lib.data_broker import reentry_decision_desk as desk
    assert ws.WASH_DAYS == rr.WASH_DAYS == desk.WASH_DAYS == rt.WASH_DAYS == portfolio_tax.WASH_SALE_DAYS == 30
    loss = di.classify_wash(last_taxable_sell_date="2026-10-14", realized_gain=-5234.0, today=date(2026, 10, 25))
    assert loss == ws.classify(last_taxable_sell_date="2026-10-14", realized_gain=-5234.0, today=date(2026, 10, 25))
    assert (di.WASH_SALE_RISK, di.WASH_UNVERIFIED, di.WASH_HOUSE_HOLD_GAIN, di.WASH_NONE) == (
        ws.KIND_WASH_RISK, ws.KIND_UNVERIFIED, ws.KIND_HOUSE_HOLD_GAIN, ws.KIND_NONE)


@pytest.mark.parametrize("account,net_pnl,now,blocked", [
    ("schwab_taxable", -50.0, datetime(2026, 11, 13, 20, tzinfo=timezone.utc), True),   # was clear (strict < on ts)
    ("schwab_taxable", -50.0, datetime(2026, 11, 14, 15, tzinfo=timezone.utc), False),
    ("schwab_rollover_ira", -50.0, datetime(2026, 10, 20, 15, tzinfo=timezone.utc), False),   # IRA loss: no window
    ("schwab_taxable", 189.73, datetime(2026, 10, 20, 15, tzinfo=timezone.utc), False),       # gain: no window
    (None, -50.0, datetime(2026, 10, 20, 15, tzinfo=timezone.utc), True)])                    # unknown → conservative
def test_lifecycle_reentry_advice_uses_the_canonical_window(account, net_pnl, now, blocked):
    from scripts.lib import cio_prospect_lifecycle as lcm
    adv = lcm.reentry_advice(symbol="SPCX", security_guid="g", round_trip_key="srt:1", exit_price=151.53,
                             exit_at="2026-10-14T14:36:16-04:00", entry_price=160.0, net_pnl=net_pnl, price=150.0,
                             price_as_of=now.isoformat(), rsi=50, entry_zone=[140, 145], resistance=None,
                             conviction=70, thesis_status="active", now=now, account=account)
    cond = {c["id"]: c for c in adv["conditions"]}["wash_window"]
    assert cond["met"] is (not blocked)
    assert cond["value"] == ("2026-11-13" if net_pnl < 0 and account != "schwab_rollover_ira" else None)


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchall(self):
        return self.rows


@pytest.mark.parametrize("account,loss_known,is_loss,shown", [
    ("schwab_taxable", False, False, True),       # basis unknown → potential loss, shown
    ("schwab_taxable", True, True, True),
    ("schwab_taxable", True, False, False),       # known GAIN: no wash window (was shown before 2026-10-25)
    ("moomoo_taxable_live", True, True, True),    # every taxable account (was schwab_taxable only)
    ("schwab_rollover_ira", True, True, False)])
def test_rotation_round_trip_warning_follows_the_canonical_rule(account, loss_known, is_loss, shown):
    import rotation_round_trips as rt
    detected = datetime.now(timezone.utc) - timedelta(days=2)
    cur = _Cur([(1, "ARKX", account, "stepped_out", detected, detected, "ingest", 31.25, is_loss, loss_known,
                 [], None)])
    row, = rt.evaluate(cur, {}, {}, {})
    assert (row["wash_sale"] is not None) is shown
    if shown:
        assert row["wash_sale"]["until"] == ws.window_until(detected).isoformat()
        assert row["wash_sale"]["days_left"] == ws.days_left(detected, datetime.now(timezone.utc))
