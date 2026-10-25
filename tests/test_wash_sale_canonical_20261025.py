"""ONE wash-sale implementation (EXCEPTIONS_MATRIX R9, operator 2026-10-25: "I need you to fix everything that's
missing before deployment."). Table-driven over synthetic trade_transactions-shaped rows (fake tickers, test-only
accounts from a stubbed account registry, made-up quantities, prices and dates); no database, no broker."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import account_display  # noqa: E402
from scripts.lib import wash_sale as ws  # noqa: E402

ET = timezone(timedelta(hours=-4))

#: Test-only account registry (replaces config/account_display_names.json for these tests).
REGISTRY = {"names": {"taxable_a": {"name": "Taxable A", "type": "taxable"},
                      "taxable_b": {"name": "Taxable B", "type": "taxable"},
                      "ira_a": {"name": "IRA A", "type": "rollover_ira"},
                      "roth_a": {"name": "Roth A", "type": "roth_ira"},
                      "paper_a": {"name": "Paper A", "type": "paper"}},
            "aliases": {}}


@pytest.fixture(autouse=True)
def account_registry_stub(monkeypatch):
    monkeypatch.setattr(account_display, "_load", lambda *a, **k: REGISTRY)


def tx(account, symbol, action, day, hh, mm, qty, price, fees="0"):
    y, m, d = map(int, day.split("-"))
    return {"account": account, "symbol": symbol, "action": action, "trade_date": date(y, m, d),
            "trade_time": datetime(y, m, d, hh, mm, tzinfo=ET), "quantity": Decimal(qty), "price": Decimal(price),
            "fees": Decimal(fees)}


# ZZA: taxable loss sale 2026-04-10 (basis 50@40 + 30@38 = 3,140; proceeds 80@30 − 0.50 = 2,399.50 → −740.50),
# a cheaper EARLIER IRA lot (must never lower the taxable basis), and rebuys after the sale in both accounts.
ZZA = [
    tx("ira_a", "ZZA", "Buy", "2026-03-01", 10, 0, "40", "25.00"),
    tx("taxable_a", "ZZA", "Buy", "2026-03-02", 10, 0, "50", "40.00"),
    tx("taxable_a", "ZZA", "Buy", "2026-03-03", 10, 0, "30", "38.00"),
    tx("taxable_a", "ZZA", "Sell", "2026-04-10", 14, 0, "80", "30.00", "0.50"),
    tx("ira_a", "ZZA", "Sell", "2026-04-10", 14, 5, "40", "30.00", "0.50"),
    tx("ira_a", "ZZA", "Buy", "2026-04-10", 15, 0, "60", "29.50"),
    tx("taxable_a", "ZZA", "Buy", "2026-04-15", 10, 0, "10", "31.00"),
]
# ZZB: shares arrived without buy rows, so the 2026-04-05 taxable sale has no lots on file → UNVERIFIED.
ZZB = [
    tx("taxable_a", "ZZB", "Buy", "2026-03-01", 10, 0, "5", "10.00"),
    tx("taxable_a", "ZZB", "Sell", "2026-03-10", 10, 0, "100", "9.00"),
    tx("taxable_a", "ZZB", "Sell", "2026-04-05", 10, 0, "5", "8.00"),
]
# ZZC: sold only in the IRA → no deductible loss → no window.
ZZC = [
    tx("ira_a", "ZZC", "Sell", "2026-04-01", 10, 0, "30", "12.00"),
    tx("ira_a", "ZZC", "Sell", "2026-04-12", 10, 0, "40", "13.00"),
]
# ZZD: a taxable GAIN → house hold only, never a wash window.
ZZD = [
    tx("taxable_a", "ZZD", "Buy", "2026-01-05", 10, 0, "100", "20.00"),
    tx("taxable_a", "ZZD", "Sell", "2026-04-01", 10, 0, "100", "25.00", "0.50"),
]


@pytest.mark.parametrize("rows,today,kind,gated,until", [
    (ZZA, "2026-04-19", ws.KIND_WASH_RISK, True, "2026-05-10"),
    (ZZA, "2026-05-10", ws.KIND_WASH_RISK, True, "2026-05-10"),      # day S+30 is still inside (inclusive)
    (ZZA, "2026-05-11", ws.KIND_NONE, False, None),                  # first clear day is S+31
    (ZZB, "2026-04-19", ws.KIND_UNVERIFIED, True, "2026-05-05"),     # unknown basis is never a silent clear
    (ZZC, "2026-04-19", ws.KIND_NONE, False, None),                  # IRA sale: no deductible loss, no window
    (ZZD, "2026-04-10", ws.KIND_HOUSE_HOLD_GAIN, False, None),       # gain: house hold only
])
def test_canonical_window_table(rows, today, kind, gated, until):
    w = ws.symbol_window(rows, today=date.fromisoformat(today))
    assert (w["kind"], w["gated"], w["until"]) == (kind, gated, until)
    if kind == ws.KIND_WASH_RISK:
        assert w["realized_gain"] < 0 and "IRA included" in w["label"] and "through 2026-05-10" in w["label"]
        # Acquisitions in EVERY account inside ±30 d of the loss sale are listed (the IRA rebuy washes the loss).
        assert {a["account"] for a in w["acquisitions_within_30d"]} == {"taxable_a", "ira_a"}


def test_fifo_basis_never_pools_lots_across_accounts():
    # The earlier, cheaper IRA lot must not lower the taxable sale's basis.
    w = ws.symbol_window(ZZA, today=date(2026, 4, 19))
    taxable_sale = next(s for s in w["sales"] if s["account"] == "taxable_a")
    assert taxable_sale["realized_gain"] == pytest.approx(2399.50 - 3140.0, abs=0.01)
    assert all(s["account"] == "taxable_a" for s in w["sales"]), "IRA sales never open a window"


def test_an_earlier_loss_inside_the_window_is_not_hidden_by_a_later_gain():
    rows = [tx("taxable_a", "ZZE", "Buy", "2026-03-01", 10, 0, "10", "100"),
            tx("taxable_a", "ZZE", "Sell", "2026-04-01", 10, 0, "5", "80"),     # loss
            tx("taxable_a", "ZZE", "Sell", "2026-04-10", 10, 0, "5", "120")]    # gain
    w = ws.symbol_window(rows, today=date(2026, 4, 20))
    assert w["kind"] == ws.KIND_WASH_RISK and w["sell_date"] == "2026-04-01" and w["until"] == "2026-05-01"
    assert w["house_hold_until"] == "2026-05-10"


# ── the 61-day window: purchases in the 30 days BEFORE a loss sale wash it too ─────────────────────────────

def _loss_with(*extra):
    base = [tx("taxable_a", "ZZF", "Buy", "2026-01-02", 10, 0, "100", "50.00"),
            tx("taxable_a", "ZZF", "Sell", "2026-04-10", 14, 0, "100", "40.00")]       # loss −1,000
    return sorted([*base, *extra], key=lambda r: (str(r["trade_date"]), str(r["trade_time"])))


@pytest.mark.parametrize("extra,washed,before,after", [
    ((), False, 0, 0),                                                               # nothing bought: loss stands
    ((tx("ira_a", "ZZF", "Buy", "2026-03-31", 10, 0, "20", "41.00"),), True, 20, 0),   # IRA buy 10 d BEFORE
    ((tx("roth_a", "ZZF", "Buy", "2026-03-11", 10, 0, "20", "41.00"),), True, 20, 0),  # day S−30: inside
    ((tx("ira_a", "ZZF", "Buy", "2026-03-10", 10, 0, "20", "41.00"),), False, 0, 0),   # day S−31: outside
    ((tx("taxable_b", "ZZF", "Buy", "2026-04-01", 10, 0, "15", "41.00"),), True, 15, 0),
    ((tx("ira_a", "ZZF", "Buy", "2026-05-10", 10, 0, "5", "41.00"),), True, 0, 5),     # day S+30 after
])
def test_purchases_in_the_30_days_before_a_loss_sale_wash_it(extra, washed, before, after):
    w = ws.symbol_window(_loss_with(*extra), today=date(2026, 4, 12))
    assert w["kind"] == ws.KIND_WASH_RISK and w["loss_washed"] is washed
    assert sum(r["quantity"] for r in w["replacements"] if r["when"] == "before_sale") == before
    assert sum(r["quantity"] for r in w["replacements"] if r["when"] == "after_sale") == after
    if washed:
        assert "already bought back within 30 days before or after the sale" in w["label"]
        assert w["wash_status"] in ("LIKELY_WASHED", "IRA_PERMANENT") and w["gated"] is True   # forward gate kept
    else:
        assert w["wash_status"] == "OPEN_RISK"


def test_same_account_lots_the_sale_disposed_of_are_not_replacements():
    # 100 bought 2026-03-25 (inside S−30) and ALL of them sold at a loss on 2026-04-10: nothing remains → not washed.
    rows = [tx("taxable_a", "ZZG", "Buy", "2026-03-25", 10, 0, "100", "50.00"),
            tx("taxable_a", "ZZG", "Sell", "2026-04-10", 14, 0, "100", "40.00")]
    w = ws.symbol_window(rows, today=date(2026, 4, 12))
    assert w["kind"] == ws.KIND_WASH_RISK and w["loss_washed"] is False and w["replacements"] == []


def test_same_account_pre_sale_lot_still_held_after_the_sale_is_a_replacement():
    # FIFO sells the old January lot; the 2026-03-25 lot (inside S−30) is still held → it washes the loss.
    rows = [tx("taxable_a", "ZZH", "Buy", "2026-01-02", 10, 0, "100", "50.00"),
            tx("taxable_a", "ZZH", "Buy", "2026-03-25", 10, 0, "40", "45.00"),
            tx("taxable_a", "ZZH", "Sell", "2026-04-10", 14, 0, "100", "40.00")]
    w = ws.symbol_window(rows, today=date(2026, 4, 12))
    assert w["loss_washed"] is True
    assert w["replacements"] == [{"account": "taxable_a", "trade_date": "2026-03-25", "quantity": 40.0,
                                  "when": "before_sale"}]


def test_a_gain_sale_reports_no_replacements():
    w = ws.symbol_window(ZZD + [tx("ira_a", "ZZD", "Buy", "2026-03-20", 10, 0, "10", "24.00")],
                         today=date(2026, 4, 10))
    assert w["kind"] == ws.KIND_HOUSE_HOLD_GAIN and w["loss_washed"] is False and w["replacements"] == []


@pytest.mark.parametrize("account,taxable", [("taxable_a", True), ("taxable_b", True), ("ira_a", False),
    ("roth_a", False), ("paper_a", False), ("unregistered_brokerage", True), ("unregistered_ira_x", False)])
def test_account_taxability_comes_from_the_account_registry(account, taxable):
    assert ws.account_taxable(account) is taxable


@pytest.mark.parametrize("sale,today,open_,left", [
    ("2026-04-10", "2026-04-10", True, 31), ("2026-04-10", "2026-05-10", True, 1),
    ("2026-04-10", "2026-05-11", False, 0), ("2026-04-10", "2026-04-09", False, 0),
    (datetime(2026, 4, 10, 23, 30, tzinfo=timezone.utc), "2026-05-10", True, 1)])   # 19:30 ET → trade date 04-10
def test_window_arithmetic(sale, today, open_, left):
    assert ws.window_open(sale, today) is open_ and ws.days_left(sale, today) == left


# ── every former implementation now routes through the canonical module ───────────────────────────────────

def test_former_implementations_share_one_constant_and_one_classifier():
    import rotation_round_trips as rt
    import portfolio_tax
    from scripts.lib import decision_integrity as di, reentry_rules as rr
    from scripts.lib.data_broker import reentry_decision_desk as desk
    assert ws.WASH_DAYS == rr.WASH_DAYS == desk.WASH_DAYS == rt.WASH_DAYS == portfolio_tax.WASH_SALE_DAYS == 30
    loss = di.classify_wash(last_taxable_sell_date="2026-04-10", realized_gain=-740.5, today=date(2026, 4, 19))
    assert loss == ws.classify(last_taxable_sell_date="2026-04-10", realized_gain=-740.5, today=date(2026, 4, 19))
    assert di.fifo_realized_gain is ws.fifo_realized_gain
    assert (di.WASH_SALE_RISK, di.WASH_UNVERIFIED, di.WASH_HOUSE_HOLD_GAIN, di.WASH_NONE) == (
        ws.KIND_WASH_RISK, ws.KIND_UNVERIFIED, ws.KIND_HOUSE_HOLD_GAIN, ws.KIND_NONE)


@pytest.mark.parametrize("account,net_pnl,now,blocked", [
    ("taxable_a", -50.0, datetime(2026, 5, 10, 20, tzinfo=timezone.utc), True),    # was clear (strict < on ts)
    ("taxable_a", -50.0, datetime(2026, 5, 11, 15, tzinfo=timezone.utc), False),
    ("ira_a", -50.0, datetime(2026, 4, 20, 15, tzinfo=timezone.utc), False),       # IRA loss: no window
    ("taxable_a", 75.0, datetime(2026, 4, 20, 15, tzinfo=timezone.utc), False),    # gain: no window
    (None, -50.0, datetime(2026, 4, 20, 15, tzinfo=timezone.utc), True)])          # unknown → conservative
def test_lifecycle_reentry_advice_uses_the_canonical_window(account, net_pnl, now, blocked):
    from scripts.lib import cio_prospect_lifecycle as lcm
    adv = lcm.reentry_advice(symbol="ZZA", security_guid="g", round_trip_key="srt:1", exit_price=30.0,
                             exit_at="2026-04-10T14:00:00-04:00", entry_price=40.0, net_pnl=net_pnl, price=29.0,
                             price_as_of=now.isoformat(), rsi=50, entry_zone=[27, 28], resistance=None,
                             conviction=70, thesis_status="active", now=now, account=account)
    cond = {c["id"]: c for c in adv["conditions"]}["wash_window"]
    assert cond["met"] is (not blocked)
    assert cond["value"] == ("2026-05-10" if net_pnl < 0 and account != "ira_a" else None)


class _Cur:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return None


@pytest.mark.parametrize("account,loss_known,is_loss,shown", [
    ("taxable_a", False, False, True),       # basis unknown → potential loss, shown
    ("taxable_a", True, True, True),
    ("taxable_a", True, False, False),       # known GAIN: no wash window (was shown before 2026-10-25)
    ("taxable_b", True, True, True),         # every taxable account (was one literal account only)
    ("ira_a", True, True, False)])
def test_rotation_round_trip_warning_follows_the_canonical_rule(account, loss_known, is_loss, shown):
    import rotation_round_trips as rt
    detected = datetime.now(timezone.utc) - timedelta(days=2)
    cur = _Cur([(1, "ZZA", account, "stepped_out", detected, detected, "ingest", 30.0, is_loss, loss_known,
                 [], None)])
    row, = rt.evaluate(cur, {}, {}, {})
    assert (row["wash_sale"] is not None) is shown
    if shown:
        assert row["wash_sale"]["until"] == ws.window_until(detected).isoformat()
        assert row["wash_sale"]["days_left"] == ws.days_left(detected, datetime.now(timezone.utc))


# ── review fixes F1–F7 ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("extra,status,matched,permanent", [
    ((), "OPEN_RISK", 0, 0),
    ((tx("taxable_b", "ZZF", "Buy", "2026-04-01", 10, 0, "30", "41.00"),), "LIKELY_WASHED", 30, 0),
    ((tx("ira_a", "ZZF", "Buy", "2026-03-31", 10, 0, "20", "41.00"),
      tx("taxable_b", "ZZF", "Buy", "2026-04-20", 10, 0, "50", "41.00")), "IRA_PERMANENT", 70, 20),
    # Matched oldest first and capped at the 100 shares sold: the 2026-05-01 purchase is only partly matched.
    ((tx("roth_a", "ZZF", "Buy", "2026-03-20", 10, 0, "60", "41.00"),
      tx("taxable_b", "ZZF", "Buy", "2026-05-01", 10, 0, "70", "41.00")), "IRA_PERMANENT", 100, 60),
])
def test_f1_an_already_washed_loss_is_reported_as_washed_not_as_a_future_risk(extra, status, matched, permanent):
    w = ws.symbol_window(_loss_with(*extra), today=date(2026, 5, 2))
    assert w["wash_status"] == status and w["kind"] == ws.KIND_WASH_RISK and w["until"] == "2026-05-10"
    assert w.get("matched_quantity", 0) == matched and w.get("ira_permanent_quantity", 0) == permanent
    assert "Verify with your tax advisor." in w["label"]
    if status == "IRA_PERMANENT":
        assert "lost permanently" in w["label"]
    if status != "OPEN_RISK":
        assert "risks permanent disallowance" not in w["label"]


def test_f2_the_gate_lasts_until_the_last_loss_or_unknown_basis_sale_window_closes():
    rows = [tx("taxable_a", "ZZI", "Buy", "2026-03-01", 10, 0, "10", "100"),
            tx("taxable_a", "ZZI", "Sell", "2026-04-01", 10, 0, "10", "80"),      # loss → until 05-01
            tx("taxable_a", "ZZI", "Sell", "2026-04-15", 10, 0, "7", "70")]       # no lots → unknown → until 05-15
    w = ws.symbol_window(rows, today=date(2026, 4, 20))
    assert w["kind"] == ws.KIND_WASH_RISK and w["sell_date"] == "2026-04-01" and w["until"] == "2026-05-15"
    assert "through 2026-05-15" in w["label"]


def test_f3_today_is_the_new_york_date_not_the_utc_date():
    evening = datetime(2026, 5, 11, 1, 30, tzinfo=timezone.utc)          # 2026-05-10 21:30 ET
    assert ws.today_ny(evening) == date(2026, 5, 10)
    assert ws.symbol_window(ZZA, today=ws.today_ny(evening))["gated"] is True   # UTC date would already be clear


def test_f3_desk_and_decision_integrity_default_to_the_new_york_date(monkeypatch):
    from scripts.lib import decision_integrity as di
    monkeypatch.setattr(ws, "today_ny", lambda now=None: date(2026, 5, 10))
    assert di.classify_wash(last_taxable_sell_date="2026-04-10", realized_gain=-5.0)["kind"] == ws.KIND_WASH_RISK
    src = (ROOT / "scripts/lib/data_broker/reentry_decision_desk.py").read_text()
    assert "today = today_ny()" in src and "wash_today" in src


@pytest.mark.parametrize("action,acq,sale", [
    ("Buy", True, False), ("Reinvest Shares", True, False), ("Reinvest Dividend", True, False),
    ("Buy to Cover", False, False), ("Buy to Close", False, False), ("Sell", False, True),
    ("Sell Short", False, False), ("Sell to Open", False, False), ("Short Sale", False, False),
    ("Sell to Close", False, True), ("Dividend", False, False)])
def test_f4_reinvestments_are_acquisitions_and_short_opens_are_not_sales(action, acq, sale):
    assert ws.is_acquisition(action) is acq and ws.is_sale(action) is sale


def test_f4_a_dividend_reinvestment_washes_and_a_short_open_opens_no_window():
    drip = _loss_with(tx("taxable_a", "ZZF", "Reinvest Shares", "2026-04-20", 10, 0, "2", "40.50"))
    assert ws.symbol_window(drip, today=date(2026, 4, 25))["matched_quantity"] == 2
    short = [tx("taxable_a", "ZZJ", "Sell Short", "2026-04-10", 10, 0, "10", "50")]
    assert ws.symbol_window(short, today=date(2026, 4, 12))["kind"] == ws.KIND_NONE


def test_f5_labels_say_same_symbol_only():
    for rows in (ZZA, ZZB):
        w = ws.symbol_window(rows, today=date(2026, 4, 19))
        assert "same symbol only" in w["label"] and w["scope"] == ws.SCOPE_NOTE


def test_f6_rotation_window_runs_from_the_exit_fill_trade_date_not_detection():
    import rotation_round_trips as rt
    detected = datetime.now(timezone.utc)                                 # operator confirmed today …
    sale_day = ws.today_ny() - timedelta(days=5)                          # … a sale filled 5 days ago

    class Cur(_Cur):
        def fetchone(self):
            return (sale_day,)
    row, = rt.evaluate(Cur([(1, "ZZA", "taxable_a", "stepped_out", detected - timedelta(days=9), detected,
                             "operator_confirm", 30.0, True, True, [], None)]), {}, {}, {})
    assert row["wash_sale"]["sale_date"] == sale_day.isoformat()
    assert row["wash_sale"]["until"] == ws.window_until(sale_day).isoformat()
    assert row["wash_sale"]["days_left"] == 26


def test_f7_fifo_evidence_note_stays_visible():
    w = ws.symbol_window(ZZA, today=date(2026, 4, 19))
    assert w["evidence"] == "FIFO_FROM_TRADE_TRANSACTIONS" and w["evidence_note"] == ws.FIFO_NOTE
    assert "FIFO_FROM_TRADE_TRANSACTIONS — verify with your tax context" in w["label"]
