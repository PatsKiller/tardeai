"""One price truth for positions; reconciliation vs broker; no new direct position-store readers.

Operator 2026-10-05: "This discrepancy is real, and we need to validate that everything in the command
center and the portfolio is correct … I need this to be the source of truth. You have to get this right."
The Command Center showed SPCX $136.46 / value $40,938 / P&L −$8,272 while Schwab had $171.09 / +$2,122:
the holdings API preferred a stored `current_price` that schwab_position_sync never refreshed (22 of 27
rows off), scaled stale April cost anchors to today's share counts (SCHD $125,341 vs broker $132,173),
measured analyst upside against a snapshot price ($115), counted health-probe rows as trades, and dated an
after-hours fund sale by order time. Fakes only: no network, no database, no broker, no token store.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import portfolio_positions as pp  # noqa: E402

NOW = dt.datetime(2026, 10, 5, 20, 50, tzinfo=dt.timezone.utc)
SPCX = {"symbol": "SPCX", "account": "schwab_rollover_ira", "shares": 300.0, "price": 171.09,
        "current_price": 136.46, "canonical_mark": 171.09, "cost_basis": 49210.13,
        "last_repriced": "2026-10-05 16:45:02 ET", "market_value": 51327.0}


# ── the accessor ──────────────────────────────────────────────────────────────

def test_data_broker_quote_wins_and_current_price_is_never_read():
    m = pp.resolve_mark(SPCX, quote={"price": 171.34, "as_of": "2026-10-05T16:45:02-04:00", "source": "market_quotes:alpaca"},
                        now=NOW)
    assert m["price"] == 171.34 and m["source"].startswith("data_broker") and m["live"]
    vp = pp.value_and_pl(SPCX, m)
    assert vp["market_value"] == pytest.approx(51402.0) and vp["gain_loss"] == pytest.approx(2191.87)


def test_without_quotes_the_stored_mark_is_used_with_its_age_never_the_fossil():
    m = pp.resolve_mark(SPCX, now=NOW)
    assert m["price"] == 171.09 and m["source"] == "stored_mark" and not m["live"]
    assert m["price"] != SPCX["current_price"]
    only_fossil = {**SPCX, "price": None, "canonical_mark": None}
    assert pp.resolve_mark(only_fossil, now=NOW)["price"] is None     # a fossil alone is never a price


def test_stale_marks_are_flagged():
    old = {**SPCX, "last_repriced": "2026-09-28 16:00:00 ET"}
    assert pp.resolve_mark(old, now=NOW)["stale"] is True
    q = pp.resolve_mark(SPCX, quote={"price": 171.3, "as_of": "2026-10-04T10:00:00-04:00"}, now=NOW)
    assert q["stale"] is True and q["live"] is False


def test_cash_and_per_share_cost():
    assert pp.resolve_mark({"symbol": "CASH", "is_cash": True, "shares": 10}, now=NOW)["price"] == 1.0
    assert pp.per_share_cost(SPCX) == pytest.approx(164.033767, abs=1e-6)


def test_store_path_resolves_under_the_persistent_root(monkeypatch, tmp_path):
    (tmp_path / "PERSISTENT_STATE_ROOT.json").write_text("{}")
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    assert pp.store_path() == tmp_path / "data" / "portfolios" / "state" / ("holdings" + ".json")


# ── the surfaces use it ───────────────────────────────────────────────────────

API = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    i = API.index(f"def {name}(")
    j = API.index("\ndef ", i + 10)
    return API[i:j]


def test_holdings_api_prices_through_the_accessor():
    body = _fn("portfolio_holdings")
    assert "_pp_mod.resolve_mark(" in body
    assert 'p.get("current_price")' not in body          # the frozen field is not read for pricing
    assert "per_share" not in body.split("_anchor = basis_map.get")[1].split("_gl =")[0].replace(
        "per-share", "")                                   # stale anchors are never scaled to today's shares
    assert '"cost_basis_broker"' in body and '"price_stale"' in body


def test_accounts_live_avg_price_is_per_share():
    body = API[API.index("def _schwab_accounts_live"):]
    body = body[:body.index("\ndef ", 10)]
    assert '"avg_price": _pp_live.per_share_cost(h)' in body
    assert 'h.get("current_price")' not in body


def test_analyst_upside_uses_the_live_price():
    body = _fn("_analyst_detail")
    assert "_ad_price_batch" in body and '"price_at_snapshot"' in body


def test_realized_kpis_exclude_probe_rows_and_disclose_basis_unknown():
    assert "tc.account <> ALL(%s)" in API and '"realized_excluded_basis_unknown"' in API
    assert "journal_check" in pp.load_closed_config()["test_accounts"]


def test_repricer_keeps_the_legacy_alias_in_sync():
    import portfolio_repricer as rp
    h = {"current_price": 136.46}
    rp._sync_legacy_price_alias(h, 171.09)
    assert h["current_price"] == 171.09 and h["current_price_is_alias_of"] == "canonical_mark"


def test_builder_dates_closes_by_broker_trade_date():
    import schwab_journal_builder as b
    tz = dt.timezone(dt.timedelta(hours=-4))
    fills = [{"side": "Buy", "qty": 10, "price": 20.0, "fees": 0, "t": dt.datetime(2026, 2, 6, 10, tzinfo=tz),
              "d": dt.date(2026, 2, 6)},
             {"side": "Sell", "qty": 10, "price": 26.53, "fees": 0, "t": dt.datetime(2026, 7, 13, 21, 5, tzinfo=tz),
              "d": dt.date(2026, 7, 14)}]
    trips = b._round_trips("schwab_rollover_ira", "FCNTX", b._group_legs(fills))
    assert trips[0]["exit_trade_date"] == dt.date(2026, 7, 14) and trips[0]["entry_trade_date"] == dt.date(2026, 2, 6)
    src = (ROOT / "scripts" / "schwab_journal_builder.py").read_text()
    assert "COALESCE(exit_trade_date, exit_time::date)" in src
    assert src.index("if apply:  # schema change only on --apply") < src.index("_ensure_trade_date_columns(cur); conn.commit()")


# ── the reconciliation ────────────────────────────────────────────────────────

import portfolio_reconcile as rc  # noqa: E402

BROKER = [{"account": "schwab_rollover_ira", "symbol": "SPCX", "qty": 300, "avg_price": 164.033767,
           "market_value": 51297.0, "unrealized_pl": 2086.87, "captured_at": "2026-10-05 16:33"},
          {"account": "schwab_rollover_ira", "symbol": "543354104", "qty": 3000, "avg_price": 1.58,
           "market_value": 0, "unrealized_pl": -4762.95, "captured_at": "x"}]
QUOTES = {"SPCX": {"last": 171.34, "as_of": "2026-10-05T16:45:02-04:00"}}


def test_reconcile_names_the_frozen_field_and_the_value_gap():
    cc = [{"symbol": "SPCX", "account": "schwab_rollover_ira", "shares": 300, "price": 136.46, "price_source": "schwab",
           "market_value": 40938.0, "cost_basis": 49210.13},
          {"symbol": "CASH", "account": "schwab_rollover_ira", "is_cash": True, "shares": 803051.28, "market_value": 803051.28}]
    raw = {("schwab_rollover_ira", "SPCX"): SPCX}
    rows = {r["symbol"]: r for r in rc.reconcile_positions(BROKER, cc, QUOTES, raw)}
    issues = " ".join(rows["SPCX"]["issues"])
    assert "PRICE" in issues and "current_price" in issues and "VALUE" in issues
    assert rows["SPCX"]["value_at_quote"] == pytest.approx(51402.0)
    assert rows["543354104"]["issues"] == [] and "CUSIP" in rows["543354104"]["note"]
    assert rows["CASH"]["issues"] == [] and rows["CASH"].get("cash")


def test_reconcile_after_fix_is_clean():
    cc = [{"symbol": "SPCX", "account": "schwab_rollover_ira", "shares": 300, "price": 171.34,
           "price_source": "data_broker:market_quotes", "market_value": 51402.0, "cost_basis": 49210.13}]
    rows = rc.reconcile_positions(BROKER[:1], cc, QUOTES, {})
    assert rows[0]["issues"] == []


def _tx(d, act, q, px, amt, key, t=None):
    return {"trade_date": d, "trade_time": t or f"{d}T10:00:00-04:00", "account": "schwab_rollover_ira", "symbol": "SCHG",
            "action": act, "quantity": q, "price": px, "amount": amt, "fees": 0, "dedupe_key": key,
            "import_source": "schwab_api"}


def test_closed_reconcile_classifies_basis_unknown_and_flags_real_gaps():
    txns = [_tx("2026-04-06", "Buy", 1000, 29.51, -29510, "b1"),
            _tx("2026-07-16", "Security Transfer", 5000, 0, 0, "x1"),
            _tx("2026-07-23", "Sell", 6000, 33.37, 200220.0, "s1")]
    sells = [t for t in txns if t["action"] == "Sell"]
    closed = [{"id": 1, "account": "schwab_rollover_ira", "symbol": "SCHG", "close_date": "2026-07-23", "shares": 1000,
               "cost_basis": 29510.0, "pnl": 3860.0, "proceeds": 33370.0, "dedupe_key": "srt:1"},
              {"id": 2, "account": "journal_check", "symbol": "HEALTH", "close_date": "2026-08-07", "shares": 1,
               "cost_basis": 1, "pnl": 0.01, "dedupe_key": ""}]
    excluded = [{"account": "schwab_rollover_ira", "symbol": "SCHG", "date": "2026-07-23", "qty": 5000, "proceeds": 166850.0}]
    rep = rc.reconcile_closed(sells, closed, txns, excluded)
    row = rep["rows"][0]
    assert row["issues"] == [] and row["note"].startswith("PARTIAL_BASIS_UNKNOWN")
    assert row.get("basis_verifiable") is False            # the transferred lot has no ledger basis
    assert len(rep["test_rows"]) == 1
    missing = rc.reconcile_closed(sells, [], txns, [])
    assert "MISSING_CLOSE" in " ".join(missing["rows"][0]["issues"])


def test_closed_reconcile_detects_trade_date_shift():
    txns = [_tx("2026-07-14", "Sell", 10, 26.53, 265.3, "s1")]
    closed = [{"id": 1, "account": "schwab_rollover_ira", "symbol": "SCHG", "close_date": "2026-07-13", "shares": 10,
               "cost_basis": 200.0, "pnl": 65.3, "dedupe_key": "srt:1"}]
    rep = rc.reconcile_closed(txns, closed, [], [])
    assert any("DATE" in i for r in rep["rows"] for i in r["issues"])


def test_fifo_marks_transferred_lots_unverifiable():
    out = rc.fifo_sell_basis([_tx("2026-07-16", "Security Transfer", 100, 0, 0, "x"),
                              _tx("2026-07-23", "Sell", 100, 33.0, 3300, "s")])
    assert list(out.values())[0][0] is None


def test_reconcile_tool_is_read_only():
    src = (ROOT / "scripts" / "portfolio_reconcile.py").read_text()
    assert "SET TRANSACTION READ ONLY" in src
    assert not re.search(r"\b(INSERT|UPDATE|DELETE)\b", src.split("def load_all")[1].split("def build_report")[0])
    assert "schwab_transport" not in src and "place_order" not in src


# ── no new direct readers of the position store ───────────────────────────────

ALLOW = ROOT / "tests" / "fixtures" / "holdings_json_direct_readers_allowlist_20261005.txt"
_PAT = re.compile(r"""["'/]holdings\.json\b""")


def test_no_new_direct_position_store_readers():
    allowed = {l.strip() for l in ALLOW.read_text().splitlines() if l.strip() and not l.startswith("#")}
    found = set()
    for base in ("scripts", "apps/command-center-v3/src", "bin", "deploy"):
        for p in (ROOT / base).rglob("*"):
            if p.suffix not in (".py", ".sh", ".ts", ".tsx") or "node_modules" in p.parts or "__pycache__" in p.parts:
                continue
            try:
                text = p.read_text(errors="ignore")
            except OSError:
                continue
            if _PAT.search(text):
                found.add(str(p.relative_to(ROOT)))
    new = sorted(found - allowed)
    assert not new, ("new direct readers of holdings.json — read positions through "
                     f"scripts/lib/portfolio_positions.py instead: {new}")
