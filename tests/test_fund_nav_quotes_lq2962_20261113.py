"""LQ-20261107-2962: held mutual-fund NAV quotes through the Schwab quote lane, and the Home gate's 1-trading-day rule.

Finding 2943: no sanctioned writer quotes a mutual fund (yfinance retired), so the Home data gate said "no quote source".
Synthetic only (ZQFNDX is not a real symbol), no DB, no network, no Schwab. The injected fetch/read/write stand in for
the broker call and the store; the lane's real parser and the gate's real read_data run.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import vix_index_quotes_schwab as lane  # noqa: E402
from scripts import home_status_verdict as gate  # noqa: E402
from scripts.lib import home_trade_ready as htr  # noqa: E402

ET = ZoneInfo("America/New_York")
FUND = "ZQFNDX"
# Thursday 2026-11-12 10:30 ET (market open). The previous NAV is Wednesday's 11-11 close print.
NOW = datetime(2026, 11, 12, 10, 30, tzinfo=ET).astimezone(timezone.utc)
NAV_AT = datetime(2026, 11, 11, 20, 0, tzinfo=ET).astimezone(timezone.utc)


def ms(dt):
    return int(dt.timestamp() * 1000)


def cfg(enabled=True):
    c = dict(lane.load_config())
    c["held_funds"] = {"enabled": enabled, "max_trading_hours": 24}
    return c


def vix_block(at):
    return {"assetMainType": "INDEX", "quote": {"lastPrice": 17.5, "tradeTime": ms(at)}}


def fund_block(at, nav=12.34, asset="MUTUAL_FUND", key="nAV"):
    q = {"tradeTime": ms(at)} if at is not None else {}
    if nav is not None:
        q[key] = nav
    return {"assetMainType": asset, "quote": q}


def fire(payload, *, c=None, stored=None, now=NOW, funds=(FUND,)):
    calls = {"fetch": None, "funds_read": 0, "rows": None}

    def fetch(syms):
        calls["fetch"] = list(syms)
        return payload

    def read_funds():
        calls["funds_read"] += 1
        return list(funds)

    def write(rows):
        calls["rows"] = rows
        return {"rows_written": len(rows)}

    rec = lane.run(cfg=c or cfg(), now=now, fetch=fetch, read_last=lambda s: {x: (stored or {}).get(x) for x in s},
                   write=write, dry_run=False, force_window=True, read_funds=read_funds)
    return rec, calls


def entry(rec, sym):
    return next(e for e in rec["symbols"] if e["symbol"] == sym)


def full_payload(fund_at=NAV_AT, **kw):
    return {"$VIX": vix_block(NOW - timedelta(minutes=2)), "$VIX9D": vix_block(NOW - timedelta(minutes=2)),
            "$VIX3M": vix_block(NOW - timedelta(minutes=2)), FUND: fund_block(fund_at, **kw)}


def test_shipped_config_has_funds_on_only_with_the_recorded_grant():
    # LQ-2964 ADDENDUM 3: the operator granted the held_funds leg on 2026-11-13; enabled must never outlive the grant.
    assert lane.funds_enabled(lane.load_config()) is True
    dsa = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
    grants = dsa["providers"]["schwab"]["supply_grants"]
    assert any(g["domain"] == "quote_price" and g["approved_on"] == "2026-11-13" and "MUTUAL_FUND" in g["scope"]
               and "held_funds" in g["scope"] for g in grants)


def test_disabled_never_reads_holdings_and_never_asks_for_a_fund():
    rec, calls = fire(full_payload(), c=cfg(False))
    assert calls["funds_read"] == 0 and FUND not in calls["fetch"]
    assert all(e.get("kind") != "fund" for e in rec["symbols"])


def test_enabled_fetches_the_fund_and_writes_its_nav_with_the_nav_time_not_the_fetch_time():
    rec, calls = fire(full_payload())
    assert FUND in calls["fetch"]
    e = entry(rec, FUND)
    assert e["status"] == "written" and e["kind"] == "fund"
    row = next(r for r in calls["rows"] if r["symbol"] == FUND)
    assert row["price"] == 12.34 and row["fetched_at"] == NAV_AT and row["fetched_at"] != NOW
    assert rec["status"] == "ok"


def test_nav_from_friday_read_on_saturday_is_fresh_weekend_is_not_age():
    fri = datetime(2026, 11, 13, 20, 0, tzinfo=ET).astimezone(timezone.utc)
    sat = datetime(2026, 11, 14, 12, 0, tzinfo=ET).astimezone(timezone.utc)
    rec, _ = fire({FUND: fund_block(fri)}, now=sat)
    assert entry(rec, FUND)["status"] == "written"


def test_old_nav_is_written_once_with_its_true_date_and_labelled_stale():
    old = NAV_AT - timedelta(days=4)
    rec, calls = fire(full_payload(fund_at=old))
    assert entry(rec, FUND)["status"] == "written_stale"
    assert next(r for r in calls["rows"] if r["symbol"] == FUND)["fetched_at"] == old


def test_a_nav_the_store_already_holds_is_not_rewritten():
    rec, calls = fire(full_payload(), stored={FUND: NAV_AT})
    assert entry(rec, FUND)["status"] == "unchanged"
    assert all(r["symbol"] != FUND for r in calls["rows"] or [])


def test_refusals_are_named_and_never_written():
    for blk, why in ((fund_block(NAV_AT, asset="EQUITY"), "refused:fund_asset_type_equity"),
                     (fund_block(None), "refused:no_nav_price_or_date"),
                     (fund_block(NAV_AT, nav=None), "refused:no_nav_price_or_date"),
                     (fund_block(NOW + timedelta(hours=3)), "refused:future_timestamp"),
                     (None, "refused:not_in_payload")):
        p = full_payload()
        if blk is None:
            del p[FUND]
        else:
            p[FUND] = blk
        rec, calls = fire(p)
        assert entry(rec, FUND)["status"] == why, why
        assert all(r["symbol"] != FUND for r in calls["rows"] or [])


def test_a_fund_failure_does_not_change_the_vix_verdict():
    p = full_payload()
    del p[FUND]
    rec, _ = fire(p)
    assert rec["status"] == "ok" and entry(rec, "$VIX")["status"] == "written"


def test_lane_never_widens_to_a_non_ticker_symbol():
    assert lane._FUND_SYMBOL_OK.match("ZQFNDX") and not lane._FUND_SYMBOL_OK.match("$VIX")
    assert not lane._FUND_SYMBOL_OK.match("A;DROP") and not lane._FUND_SYMBOL_OK.match("")


def test_holdings_read_is_read_only_and_selects_funds_only():
    import inspect
    src = inspect.getsource(lane.read_fund_symbols)
    assert "SET TRANSACTION READ ONLY" in src and "'MUTUAL_FUND'" in src
    assert "INSERT" not in src.upper() and "UPDATE" not in src.upper() and "DELETE" not in src.upper()


# ---- the Home data gate ----------------------------------------------------------------------------------------
class DB:
    def __init__(self, rows):
        self.rows = rows

    def __call__(self, sql, params=None):
        return self.rows


def held(symbol, asset_type, as_of, mv=None):
    return {"symbol": symbol, "asset_type": asset_type, "as_of": as_of, "market_value": mv}


def gate_rows(fund_as_of):
    t = NOW - timedelta(minutes=2)
    return [held("$VIX", "INDEX", t), held("ZQA", "EQUITY", t, 900.0), held(FUND, "MUTUAL_FUND", fund_as_of, 5000.0)]


def test_gate_a_prior_session_nav_is_ok_while_the_market_is_open():
    r = gate.read_data(DB(gate_rows(NAV_AT)), NOW)   # NAV is ~14 h old: stale under the 0.25 h equity rule
    assert r.state == htr.OK and r.value["funds"] == [FUND]


def test_gate_a_nav_older_than_one_trading_day_is_stale_with_the_fund_named():
    r = gate.read_data(DB(gate_rows(NAV_AT - timedelta(days=4))), NOW)
    assert r.state == htr.STALE and FUND in r.cause and r.threshold_s == 24 * 3600


def test_gate_monday_morning_with_friday_nav_is_ok():
    mon = datetime(2026, 11, 16, 9, 45, tzinfo=ET).astimezone(timezone.utc)
    fri = datetime(2026, 11, 13, 20, 0, tzinfo=ET).astimezone(timezone.utc)
    t = mon - timedelta(minutes=2)
    rows = [held("$VIX", "INDEX", t), held(FUND, "MUTUAL_FUND", fri, 5000.0)]
    assert gate.read_data(DB(rows), mon).state == htr.OK


def test_gate_fund_with_no_quote_is_still_no_source_not_exempt():
    r = gate.read_data(DB(gate_rows(None)), NOW)
    assert r.value["missing"] == [FUND] and r.state != htr.OK


def test_gate_a_stale_equity_still_goes_stale_regardless_of_a_good_fund():
    rows = gate_rows(NAV_AT)
    rows[1]["as_of"] = NOW - timedelta(hours=3)
    assert gate.read_data(DB(rows), NOW).state == htr.STALE


def test_gate_value_shape_is_unchanged_when_no_fund_is_held():
    t = NOW - timedelta(minutes=2)
    r = gate.read_data(DB([held("$VIX", "INDEX", t), held("ZQA", "EQUITY", t, 900.0)]), NOW)
    assert r.state == htr.OK and "funds" not in r.value


def test_gate_monday_friday_nav_stays_ok_through_the_field_builder():
    # LQ-2964 fold: home_trade_ready.field_of re-checks wall-clock age unless the basis is session-aware; a Friday NAV
    # is ~62 wall hours old on Monday morning and must not be flipped to STALE there.
    mon = datetime(2026, 11, 16, 9, 45, tzinfo=ET).astimezone(timezone.utc)
    fri = datetime(2026, 11, 13, 20, 0, tzinfo=ET).astimezone(timezone.utc)
    t = mon - timedelta(minutes=2)
    r = gate.read_data(DB([held("$VIX", "INDEX", t), held(FUND, "MUTUAL_FUND", fri, 5000.0)]), mon)
    assert htr.field_of(r, mon)["state"] == htr.OK


def test_gate_broker_nav_keeps_the_lq2643_rule_and_is_listed_as_a_fund():
    t = NOW - timedelta(minutes=2)
    row = held(FUND, "MUTUAL_FUND", None, 5000.0)
    row.update(broker_as_of=NAV_AT, broker_source="schwab")
    r = gate.read_data(DB([held("$VIX", "INDEX", t), row]), NOW)
    assert r.state == htr.OK and r.value["funds"] == [FUND] and FUND in r.value["fund_nav"]
