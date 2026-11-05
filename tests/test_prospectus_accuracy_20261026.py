"""Prospectus accuracy audit 2026-10-26 (operator: "Money is riding on this. We can't have inaccuracies.").

One test per defect class the audit found, each reproducing the defect on synthetic data first, plus the new
quality-gate checks. Synthetic tickers (ZZ*), accounts and amounts only (public
repo); no DB, no token store, no network.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import blocks as bk  # noqa: E402
from scripts.lib.prospectus import domains as dm  # noqa: E402
from scripts.lib.prospectus import etf_profile, my_history  # noqa: E402
from scripts.lib.prospectus import pipeline as pl  # noqa: E402
from scripts.lib.prospectus import quality_gate as qg  # noqa: E402
from scripts.lib.prospectus.inputs import Bundle  # noqa: E402

NOW = datetime(2026, 10, 26, 22, tzinfo=timezone.utc)
S = qg.load_settings()


def _calendar_rows(start: date, n_days: int, *, px=100.0, step=0.1) -> list[dict]:
    """Calendar-daily rows the way ticker_prices holds them: weekend and holiday rows copy the prior close."""
    out, last = [], px
    for i in range(n_days):
        d = start + timedelta(days=i)
        if bk.is_session(d):
            last = round(last + step, 4)
        out.append({"price_date": d.isoformat(), "close": last})
    return out


# ── D1 non-session bars ───────────────────────────────────────────────────────────────────────────────────────────
def test_series_drops_weekend_and_holiday_rows():
    rows = _calendar_rows(date(2026, 8, 31), 14)  # spans Labor Day 2026-09-07 and two weekends
    s = bk._series(rows)
    days = [d for d, _ in s]
    assert "2026-09-05" not in days and "2026-09-06" not in days and "2026-09-07" not in days
    assert all(date.fromisoformat(d).weekday() < 5 for d in days) and len(days) == 9


def test_window_returns_use_calendar_spans_not_bar_counts():
    rows = _calendar_rows(date(2025, 10, 27), 365)
    s = bk._series(rows)
    # 1M = the last session on or before (last date - 30 days); with weekend rows counted as bars it started later
    end = date.fromisoformat(s[-1][0])
    start = max(d for d, _ in s if d <= (end - timedelta(days=30)).isoformat())
    want = round((s[-1][1] / dict(s)[start] - 1) * 100, 2)
    assert bk.window_return(s, "1M") == want
    assert bk.window_return(s, "1Y") is not None  # one year of sessions still yields a 1Y figure (start grace)
    raw_count = [(r["price_date"], r["close"]) for r in rows]
    assert bk.window_return(raw_count, "1M") == want  # _start_index is calendar-based for any input


# ── D2 dividends ──────────────────────────────────────────────────────────────────────────────────────────────────
class _DivSources:
    def __init__(self, rows):
        self.rows = rows

    def db(self):
        rows = self.rows
        return lambda sql, params=None, fetch="all": rows


def test_dividend_guard_withholds_an_annual_figure_the_history_contradicts():
    b = Bundle(symbol="ZZDV", scope="holding", name="ZZDV")
    b.add("fundamental", "Annual dividend per share", value=4.0, unit="$", source="ticker_dividend_data")
    b.blocks["options_sentiment_dividends"] = {"dividend": {"yield_pct": None, "annual_per_share": 4.0}}
    hist = [{"ex_date": date(2026, 9, 20), "amount": 0.25}, {"ex_date": date(2026, 6, 20), "amount": 0.25},
            {"ex_date": date(2026, 3, 20), "amount": 0.25}, {"ex_date": date(2025, 12, 20), "amount": 0.25}]
    out = dm.dividend_guard(b, _DivSources(hist))
    assert out and out["withheld"] == 4.0 and out["reference"] == 1.0
    f = next(x for x in b.facts if x["label"] == "Annual dividend per share")
    assert "value" not in f and f["unreliable"] == "dividend_cross_source"
    assert b.blocks["options_sentiment_dividends"]["dividend"]["annual_per_share"] is None
    assert any(x["label"].startswith("Dividends paid, trailing year") and x["value"] == 1.0 for x in b.facts)


def test_dividend_guard_keeps_an_agreeing_figure():
    b = Bundle(symbol="ZZDV", scope="holding", name="ZZDV")
    b.add("fundamental", "Annual dividend per share", value=1.04, unit="$", source="ticker_dividend_data")
    hist = [{"ex_date": date(2026, 9, 20), "amount": 0.26}, {"ex_date": date(2026, 6, 20), "amount": 0.26},
            {"ex_date": date(2026, 3, 20), "amount": 0.26}, {"ex_date": date(2025, 12, 20), "amount": 0.25}]
    assert dm.dividend_guard(b, _DivSources(hist)) is None
    assert next(x for x in b.facts if x["label"] == "Annual dividend per share")["value"] == 1.04


# ── D4 stop fills dated by the journal sell, not the snapshot time ────────────────────────────────────────────────
def test_stop_fill_is_dated_by_the_matching_journal_sell():
    fills = [{"account": "fixture_rollover_ira", "stop_price": 50.0, "status": "filled", "captured_at": "2026-10-26T20:55:08"}]
    txs = [{"trade_date": "2026-09-09", "action": "Sell", "quantity": 200, "price": 49.9, "account": "fixture_rollover_ira"},
           {"trade_date": "2026-06-01", "action": "Sell", "quantity": 5, "price": 61.0, "account": "fixture_rollover_ira"}]
    out = my_history.date_stop_fills(fills, txs)
    assert out[0]["fill_date"] == date(2026, 9, 9) and out[0]["fill_qty"] == 200
    assert my_history.date_stop_fills(fills, txs[1:])[0]["fill_date"] is None  # no match: never the capture time


# ── D13 open-lot P/L read from the key value_and_pl actually returns ──────────────────────────────────────────────
def test_position_rows_reads_gain_loss(monkeypatch):
    fake = types.SimpleNamespace(
        load_store=lambda: {"as_of": "2026-10-26", "holdings": [{"account": "fixture_ira", "symbol": "ZZPL", "shares": 10,
                                                                 "cost_basis": 500.0}]},
        is_cash=lambda r: False, resolve_mark=lambda r, quote=None: {"price": 60.0},
        value_and_pl=lambda r, m: {"market_value": 600.0, "cost_basis": 500.0, "gain_loss": 100.0, "gain_loss_pct": 20.0},
        per_share_cost=lambda r: 50.0)
    monkeypatch.setattr(my_history, "_plib", lambda name: fake)
    reader = my_history.HouseHistoryReader.__new__(my_history.HouseHistoryReader)
    rows = reader.position_rows("ZZPL", None)
    assert rows[0]["unrealized_pl"] == 100.0


# ── D14 realized history that omits sells with no basis says so ───────────────────────────────────────────────────
def test_unmatched_sells_are_named():
    from test_prospectus_my_history_20261026 import FakeHistoryReader  # noqa: PLC0415

    class Transferred(FakeHistoryReader):
        def transactions(self, sym):
            return super().transactions(sym) + [
                {"trade_date": "2026-04-06", "action": "Sell", "quantity": 400, "price": 70.0, "account": "fixture_rollover_ira"}]

    b = Bundle(symbol="ZZMH", scope="holding", name="ZZMH")
    block = my_history.build(Transferred(), b, holding={"shares": 40}, now=NOW)
    assert block["unmatched_sells"]["shares_without_basis"] == 400
    assert any("not in the round trips" in g for g in block["gaps"])


# ── D15 look-through rows keyed ticker / pct ──────────────────────────────────────────────────────────────────────
def test_lookthrough_rows_accept_ticker_and_pct():
    rows = etf_profile.lookthrough_rows([{"ticker": "ZZA", "name": "Fixture A", "pct": 4.3}, {"ticker": "ZZB", "pct": 4.1}])
    assert rows == [{"name": "ZZA", "weight_pct": 4.3}, {"name": "ZZB", "weight_pct": 4.1}]
    assert etf_profile.lookthrough_rows({"ZZA": {"weight": 2.0}, "ZZB": 1.5}) == [
        {"name": "ZZA", "weight_pct": 2.0}, {"name": "ZZB", "weight_pct": 1.5}]


# ── D12 macro calendar schema ─────────────────────────────────────────────────────────────────────────────────────
def test_calendar_events_reads_macro_calendar_dates():
    cal = {"schema": "MacroCalendar@v1", "dates": {"2026-11-13": {"events": [{"event": "CPI", "name": "Consumer Price Index",
                                                                              "time_et": "08:30"}]}},
           "fomc_decisions": ["2026-12-09"]}
    ev = dm.calendar_events(cal)
    assert [e["date"] for e in ev] == ["2026-11-13", "2026-12-09"] and ev[0]["event"] == "CPI"
    assert dm.calendar_events({"events": [{"date": "2026-11-01", "name": "x"}]})[0]["date"] == "2026-11-01"


# ── D5/D19 fundamental_data freshness and the sec_xbrl columns ────────────────────────────────────────────────────
class _FundSources:
    state_root = Path("/nonexistent")

    def __init__(self, fund_rows, xbrl_rows):
        self.fund_rows, self.xbrl_rows = fund_rows, xbrl_rows

    def db(self):
        def q(sql, params=None, fetch="all"):
            return self.xbrl_rows if "sec_xbrl" in sql else self.fund_rows
        return q


def test_fundamentals_withhold_stale_rows_and_read_xbrl():
    old, fresh = NOW - timedelta(days=180), NOW - timedelta(days=1)
    fund = [{"source": "fixture_vendor_a", "metric_name": "52WeekHigh", "metric_value": 90.0, "period": "latest", "fetched_at": old},
            {"source": "fixture_vendor_b", "metric_name": "PE", "metric_value": 20.0, "period": "latest", "fetched_at": fresh}]
    xbrl = [{"metric_name": "revenue", "metric_value": 1.5e9, "unit": "USD", "period_start": date(2026, 1, 1),
             "period_end": date(2026, 3, 31), "filing_date": date(2026, 4, 29), "form_type": "10-Q", "sec_url": None},
            {"metric_name": "revenue", "metric_value": 1.2e9, "unit": "USD", "period_start": date(2025, 1, 1),
             "period_end": date(2025, 3, 31), "filing_date": date(2026, 4, 29), "form_type": "10-Q", "sec_url": None}]
    b = Bundle(symbol="ZZFD", scope="watch", name="ZZFD")
    rows, as_of, _ = dm.r_fundamentals(dm.Ctx(sources=_FundSources(fund, xbrl), bundle=b, now=NOW))
    labels = [f["label"] for f in b.facts]
    assert not any(lab.startswith("52WeekHigh") for lab in labels)
    assert any(lab.startswith("PE") for lab in labels) and all(f.get("as_of") for f in b.facts)
    assert sum(lab.startswith("SEC XBRL revenue") for lab in labels) == 2
    assert any("older than" in g for g in b.gaps)


def test_technical_snapshot_skips_its_price_and_placeholders(tmp_path):
    p = tmp_path / "data/portfolios/state"
    p.mkdir(parents=True)
    (p / "technical_snapshot.json").write_text(json.dumps({
        "ZZTS": {"price": 7.77, "change_pct": 0.0, "target": 0.0, "rsi": 39.7, "perf_week": 1.2},
        "_meta": {"last_updated": "2026-10-26 07:38"}}))
    b = Bundle(symbol="ZZTS", scope="watch", name="ZZTS")
    dm.r_technicals(dm.Ctx(sources=types.SimpleNamespace(state_root=tmp_path), bundle=b, now=NOW))
    labels = {f["label"]: f for f in b.facts}
    assert "Technical snapshot: price" not in labels and "Technical snapshot: target" not in labels
    assert labels["Technical snapshot: rsi"]["as_of"] == "2026-10-26 07:38"


# ── D9 stop_event trigger ─────────────────────────────────────────────────────────────────────────────────────────
class _TrigSources:
    def __init__(self, levels, held=True):
        self.levels, self.held = levels, held

    def holdings(self):
        return {"ZZST": {"accounts": ["fixture_ira"]}} if self.held else {}

    def stops(self, sym, accounts):
        return [{"stop_price": v} for v in self.levels]

    def catalysts(self, sym):
        return []

    def bars(self, sym):
        return []

    def cio(self, sym):
        return {}


def test_stop_event_trigger_fires_when_the_stop_moved_or_the_name_was_sold():
    trig = {"stop_event": True}
    gen = NOW - timedelta(days=1)
    assert pl._trigger(_TrigSources([47.5]), "ZZST", "holding", gen, {"stop_levels": [50.0]}, trig) == "stop_event"
    assert pl._trigger(_TrigSources([50.0]), "ZZST", "holding", gen, {"stop_levels": [50.0]}, trig) is None
    assert pl._trigger(_TrigSources([], held=False), "ZZST", "holding", gen, {"stop_levels": [50.0]}, trig) == "position_closed"


# ── fund peers when the Finviz cache does not carry the fund ──────────────────────────────────────────────────────
def test_fund_missing_from_cache_still_gets_its_peer_group():
    cache = {"ZZPB": {"industry": "Exchange Traded Fund", "forward_pe": 15.0}, "ZZPC": {"industry": "Exchange Traded Fund"}}
    out = bk.peer_comparison("ZZPA", cache, etf_groups={"fixture_dividend": ["ZZPA", "ZZPB", "ZZPC"]})
    assert [r["symbol"] for r in out["rows"]] == ["ZZPA", "ZZPB", "ZZPC"] and out["peer_group"] == "fixture_dividend"


# ── quality gate: packet-only forms of each class ─────────────────────────────────────────────────────────────────
def _packet(facts, *, scope="holding", blocks=None, series=None):
    for i, f in enumerate(facts, 1):
        f.setdefault("id", f"F{i}")
    return {"symbol": "ZZQG", "name": "ZZQG", "scope": scope, "facts": facts, "blocks": blocks or {},
            "series": series or [], "as_of": NOW.isoformat(), "context": {}}


def _codes(packet):
    return {f["code"] for f in qg.check_accuracy(packet, S)}


def test_gate_flags_dividend_stale_rows_snapshot_and_quote():
    facts = [{"label": "Annual dividend per share", "value": 4.0},
             {"label": "Dividends paid, trailing year to the latest ex-date ($/share)", "value": 1.0},
             {"label": "52WeekHigh (latest)", "value": 90.0, "source": "fundamental_data (fixture)"},
             {"label": "Last close", "value": 7.5}, {"label": "Technical snapshot: price", "value": 7.8},
             {"label": "Latest quote", "value": 0.3}]
    assert {"dividend_cross_source", "stale_fundamental_rows", "stale_technical_snapshot",
            "quote_close_contradiction"} <= _codes(_packet(facts, scope="watch"))


def test_gate_flags_position_arithmetic_and_stop_contradiction():
    facts = [{"label": "Shares held (all accounts)", "value": 10.0, "kind": "position"},
             {"label": "Market value $", "value": 900.0, "kind": "position"},
             {"label": "Average cost $", "value": 50.0, "kind": "position"},
             {"label": "Unrealized P/L $", "value": 100.0, "kind": "position"},
             {"label": "Last close", "value": 60.0},
             {"label": "Recorded protective stop level (Fixture IRA, broker_resting, active)", "value": 55.0, "kind": "position"}]
    blocks = {"stop_plan": {"broker": {"accounts": [{"account": "Fixture IRA", "level": 54.0}]}}}
    assert {"position_arithmetic", "stop_level_contradiction"} <= _codes(_packet(facts, blocks=blocks))


def test_gate_flags_non_session_bars_lookthrough_and_open_lot_pl():
    blocks = {"fund_profile": {"top_holdings": []}, "fund_lookthrough": {"top_holdings": [{"ticker": "ZZA", "pct": 4.0}]},
              "my_history": {"open_lots": [{"account": "Fixture IRA", "shares": 10, "avg_cost": 50.0, "market_value": 600.0,
                                            "unrealized_usd": None}]}}
    codes = _codes(_packet([], blocks=blocks, series=[("2026-10-24", 10.0), ("2026-10-26", 10.1)]))
    assert {"non_session_bars", "fund_lookthrough_dropped", "open_lot_pl_missing"} <= codes


def test_gate_clean_packet_has_no_accuracy_findings():
    facts = [{"label": "Annual dividend per share", "value": 1.0},
             {"label": "Dividends paid, trailing year to the latest ex-date ($/share)", "value": 1.0},
             {"label": "PE (latest)", "value": 20.0, "source": "fundamental_data (fixture)", "as_of": NOW.isoformat()},
             {"label": "Last close", "value": 7.5}, {"label": "Latest quote", "value": 7.6}]
    assert _codes(_packet(facts, scope="watch", series=[("2026-10-23", 7.4), ("2026-10-26", 7.5)])) == set()


def test_gate_market_cap_ceiling_admits_a_real_mega_cap():
    facts = [{"label": "Market cap ($B)", "value": 5200.0, "id": "F1"}]
    assert not [f for f in qg.check_units(_packet(facts, scope="watch"), S) if f["code"] == "market_cap_units"]
    facts = [{"label": "Market cap ($B)", "value": 5_200_000.0, "id": "F1"}]
    assert [f for f in qg.check_units(_packet(facts, scope="watch"), S) if f["code"] == "market_cap_units"]
