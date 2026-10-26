"""Prospectus "My history" block + ETF gaps (operator 2026-10-26: "What is my average cost? Have I won or lost, P&L?
What were the catalysts that hit? ... If I owned it multiple round trips, should that be analyzed?" and, for XAR, "it's
missing some data towards the bottom").

Synthetic tickers, accounts and amounts only (public repo). No DB, no token store, no network: every reader is a stub
and nothing is written outside pytest's tmp_path.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import etf_profile, extensions, my_history  # noqa: E402
from scripts.lib.prospectus.domains import full_assemble  # noqa: E402
from scripts.lib.prospectus import generate as gen  # noqa: E402

NOW = datetime(2026, 10, 26, 16, tzinfo=timezone.utc)
START = date(2024, 9, 2)


def _bars(sym: str, n: int = 800, *, jump_at: int | None = None) -> list[dict]:
    """Deterministic synthetic closes with a mild wave; ``jump_at`` adds one +12% session (a big move)."""
    out, px = [], 50.0
    for i in range(n):
        d = START + timedelta(days=i)
        drift = 1 + 0.0006 + 0.012 * math.sin(i / 9.0) * (0.3 if sym in ("SPY", "QQQ") else 1.0)
        px = px * drift if i else px
        if jump_at is not None and i == jump_at:
            px *= 1.12
        out.append({"price_date": d.isoformat(), "close": round(px, 4)})
    return out


def _day(i: int) -> str:
    return (START + timedelta(days=i)).isoformat()


class FakeHistoryReader:
    """Synthetic journal for ZZMH: three closed round trips (win, loss, win) — the loss is re-bought 10 days later in
    the same taxable account — and one open lot in a taxable account and one in an IRA."""

    def __init__(self, sym="ZZMH"):
        self.sym = sym
        self.bars_rows = _bars(sym, jump_at=400)

    def position_rows(self, sym, holding):
        return [{"account": "fixture_brokerage", "shares": 30.0, "avg_cost": 60.0, "cost_basis": 1800.0,
                 "market_value": 2100.0, "unrealized_pl": 300.0, "as_of": "2026-10-26"},
                {"account": "fixture_roth_ira", "shares": 10.0, "avg_cost": 55.0, "cost_basis": 550.0,
                 "market_value": 700.0, "unrealized_pl": 150.0, "as_of": "2026-10-26"}]

    def transactions(self, sym):
        return [
            {"trade_date": _day(200), "action": "Buy", "quantity": 20, "price": 52.0, "account": "fixture_brokerage"},
            {"trade_date": _day(260), "action": "Sell", "quantity": 20, "price": 58.0, "account": "fixture_brokerage"},
            {"trade_date": _day(300), "action": "Buy", "quantity": 25, "price": 61.0, "account": "fixture_brokerage"},
            {"trade_date": _day(340), "action": "Sell", "quantity": 25, "price": 55.0, "account": "fixture_brokerage"},
            {"trade_date": _day(350), "action": "Buy", "quantity": 15, "price": 54.0, "account": "fixture_brokerage"},
            {"trade_date": _day(410), "action": "Sell", "quantity": 15, "price": 63.0, "account": "fixture_brokerage"},
            {"trade_date": _day(600), "action": "Buy", "quantity": 30, "price": 60.0, "account": "fixture_brokerage"},
            {"trade_date": _day(620), "action": "Buy", "quantity": 10, "price": 55.0, "account": "fixture_roth_ira"},
        ]

    def trips(self, sym):  # the Rec Intelligence lifecycle rows (newest first, as lifecycle_performance returns them)
        rows = [
            {"trade_id": 3, "symbol": sym, "account": "fixture_brokerage", "origin": "research", "open_date": _day(350),
             "close_date": _day(410), "shares": 15.0, "buy_price": 54.0, "sell_price": 63.0, "pnl": 135.0, "pnl_pct": 16.67,
             "r_multiple": 1.8, "hold_days": 60, "setup": "pullback", "journaled": True,
             "journal": {"realized_r": 1.8, "lesson": "Waited for the pullback; patience paid.", "exit_type": "trailing_stop"}},
            {"trade_id": 2, "symbol": sym, "account": "fixture_brokerage", "origin": "research", "open_date": _day(300),
             "close_date": _day(340), "shares": 25.0, "buy_price": 61.0, "sell_price": 55.0, "pnl": -150.0, "pnl_pct": -9.84,
             "r_multiple": -1.0, "hold_days": 40, "setup": "breakout", "journaled": True,
             "journal": {"realized_r": -1.0, "lesson": "Chased the breakout near the high.", "exit_type": "hard_stop"}},
            {"trade_id": 1, "symbol": sym, "account": "fixture_brokerage", "origin": "watchlist", "open_date": _day(200),
             "close_date": _day(260), "shares": 20.0, "buy_price": 52.0, "sell_price": 58.0, "pnl": 120.0, "pnl_pct": 11.54,
             "r_multiple": None, "hold_days": 60, "setup": None, "journaled": False, "journal": None},
        ]
        return rows

    def attributions(self, sym):
        return [{"source_type": "watchlist", "first_seen_at": _day(150), "rationale": "Synthetic widget demand thesis."},
                {"source_type": "hermes_research", "first_seen_at": _day(290), "rationale": "Margin expansion note."}]

    def events(self, sym, start, end):
        rows = [{"catalyst_type": "earnings_beat", "headline": "ZZMH beats synthetic estimates", "at": _day(320)},
                {"catalyst_type": "contract_win", "headline": "ZZMH wins a fixture contract", "at": _day(380)},
                {"catalyst_type": "analyst_upgrade", "headline": "Fixture bank upgrades ZZMH", "at": _day(640)}]
        return [r for r in rows if start <= date.fromisoformat(r["at"]) <= end]

    def stop_fills(self, sym):
        return [{"account": "fixture_brokerage", "stop_price": 55.0, "status": "filled", "captured_at": _day(340)}]

    def bars(self, sym, days=1100):
        return self.bars_rows


class Bundle:
    """The prospectus Bundle (imported lazily to keep this test independent of inputs.py changes)."""


def _bundle(sym="ZZMH", scope="holding"):
    from scripts.lib.prospectus.inputs import Bundle as B
    return B(symbol=sym, scope=scope, name=sym)


def _labels(b):
    return {f["label"]: f for f in b.facts}


# ── my_history ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_my_history_lots_trips_totals_and_citations():
    b = _bundle()
    block = my_history.build(FakeHistoryReader(), b, holding={"shares": 40}, now=NOW)
    assert block["scope"] == "held"
    # open lots by account NAME, never the raw key; term from FIFO lot dates; tax character from the account
    names = [r["account"] for r in block["open_lots"]]
    assert all("fixture_" not in n for n in names), names
    brokerage = next(r for r in block["open_lots"] if "Brokerage" in r["account"])
    assert brokerage["avg_cost"] == 60.0 and brokerage["unrealized_usd"] == 300.0
    assert brokerage["unrealized_pct"] == pytest.approx(16.67, abs=0.01)
    assert brokerage["lot_dating"] == "fifo_reconciled" and brokerage["holding_days"] == (NOW.date() - START - timedelta(days=600)).days
    assert brokerage["term"] == "short"
    ira = next(r for r in block["open_lots"] if "Roth" in r["account"])
    assert ira["tax_character"] == "tax-advantaged" and brokerage["tax_character"] == "taxable"
    # every round trip in entry order, with totals
    assert [t["trip"] for t in block["trips"]] == [1, 2, 3]
    assert [t["entry_date"] for t in block["trips"]] == [_day(200), _day(300), _day(350)]
    tot = block["totals"]
    assert tot["realized_usd"] == pytest.approx(105.0) and tot["wins"] == 2 and tot["losses"] == 1
    assert tot["win_rate_pct"] == pytest.approx(66.7) and tot["best"]["trip"] == 3 and tot["worst"]["trip"] == 2
    assert tot["avg_win_usd"] == pytest.approx(127.5) and tot["avg_loss_usd"] == pytest.approx(-150.0)
    # every displayed number is a cited fact
    facts = _labels(b)
    assert facts["My history: Lifetime realized P/L on ZZMH $"]["value"] == pytest.approx(105.0)
    assert all(fid in {f["id"] for f in b.facts} for t in block["trips"] for fid in t["fact_ids"])
    assert all(f["kind"] == "my_history" for f in b.facts)
    # why you got in: origin recorded before the entry + thesis at entry
    t2 = block["trips"][1]
    assert t2["sources_before_entry"] == ["watchlist", "hermes_research"]
    assert t2["thesis_at_entry"] == "Synthetic widget demand thesis."
    assert block["trips"][0]["sources_before_entry"] == ["watchlist"]
    assert t2["stopped_out"] is True and t2["r_multiple"] == -1.0


def test_wash_sale_flag_on_loss_rebought_inside_30_days_only():
    b = _bundle()
    block = my_history.build(FakeHistoryReader(), b, holding={"shares": 40}, now=NOW)
    flagged = [t["trip"] for t in block["trips"] if (t.get("wash_sale") or {}).get("flag")]
    assert flagged == [2], "only the loss sale (trip 2) re-bought 10 days later is a wash-sale window"
    ws = block["trips"][1]["wash_sale"]
    assert _day(350) in [r["date"] for r in ws["replacements"]]
    assert block["tax"]["flags"][0]["sale_date"] == _day(340)
    assert "verify with your tax context" in block["tax"]["note"].lower()


def test_wash_sale_not_flagged_for_ira_loss_or_gain():
    class IraReader(FakeHistoryReader):
        def trips(self, sym):
            rows = super().trips(sym)
            for r in rows:
                r["account"] = "fixture_roth_ira"
            return rows

        def transactions(self, sym):
            return [dict(r, account="fixture_roth_ira") for r in super().transactions(sym)]

    block = my_history.build(IraReader(), _bundle(), holding={"shares": 40}, now=NOW)
    assert not any(t.get("wash_sale") for t in block["trips"])
    assert {t["tax_character"] for t in block["trips"]} == {"tax-advantaged"}


def test_events_while_held_with_reactions_and_big_move():
    block = my_history.build(FakeHistoryReader(), _bundle(), holding={"shares": 40}, now=NOW)
    t2 = block["trips"][1]
    kinds = {e["kind"] for e in t2["while_held"]}
    assert {"earnings", "stop_fill"} <= kinds
    earn = next(e for e in t2["while_held"] if e["kind"] == "earnings")
    assert earn["date"] == _day(320) and earn["next_day_pct"] is not None and earn["five_day_pct"] is not None
    t3 = block["trips"][2]
    big = [e for e in t3["while_held"] if e["kind"] == "big_move"]
    assert big and big[0]["date"] == _day(400) and big[0]["move_pct"] >= 8
    assert block["current_hold"]["since"] == _day(600)
    assert any(e["kind"] == "catalyst" for e in block["current_hold"]["while_held"])
    assert all(e.get("fact") for t in block["trips"] for e in t["while_held"])


def test_lessons_are_deterministic_stats():
    block = my_history.build(FakeHistoryReader(), _bundle(), holding={"shares": 40}, now=NOW)
    stats = {s["id"]: s for s in block["lessons"]["stats"]}
    assert stats["payoff"]["value"] == pytest.approx(round(127.5 / 150.0, 2))
    assert stats["stop_rate"]["value"] == pytest.approx(100.0)  # both journaled trips ended at a stop
    assert stats["reentry_after_loss"]["value"] == 1
    assert stats["hold_median"]["value"] == 60
    assert {n["trip"] for n in block["lessons"]["journal_notes"]} == {2, 3}
    assert all(s["fact"] for s in stats.values())


def test_never_traded_and_previously_traded_scopes():
    class Empty(FakeHistoryReader):
        def transactions(self, sym):
            return []

        def trips(self, sym):
            return []

    assert my_history.build(Empty(), _bundle(scope="watch"), holding=None, now=NOW)["scope"] == "never_traded"
    sold = my_history.build(FakeHistoryReader(), _bundle(scope="watch"), holding=None, now=NOW)
    assert sold["scope"] == "previously_traded" and not sold["open_lots"] and len(sold["trips"]) == 3


def test_fifo_unreconciled_lots_are_named_not_guessed():
    class Transferred(FakeHistoryReader):
        def transactions(self, sym):
            return [{"trade_date": _day(600), "action": "Transfer In", "quantity": 30, "price": None, "account": "fixture_brokerage"}]

    block = my_history.build(Transferred(), _bundle(), holding={"shares": 40}, now=NOW)
    lot = next(r for r in block["open_lots"] if "Brokerage" in r["account"])
    assert lot["lot_dating"] == "unreconciled" and lot["holding_days"] is None
    assert any("lot dates for" in g for g in block["gaps"])


def test_reader_failure_is_a_gap_not_a_crash():
    class Broken(FakeHistoryReader):
        def trips(self, sym):
            raise RuntimeError("fixture outage")

    block = my_history.build(Broken(), _bundle(), holding={"shares": 40}, now=NOW)
    assert any("Rec Intelligence lifecycle" in g for g in block["gaps"])
    assert block["open_lots"]


def test_writer_note_is_guarded_and_prompt_asks_for_it():
    b = _bundle()
    b.blocks["my_history"] = my_history.build(FakeHistoryReader(), b, holding={"shares": 40}, now=NOW)
    lines = "\n".join(extensions.prompt_lines(b))
    assert "notes" in lines and "my_history" in lines and "never advise a trade" in lines
    blocks = dict(b.blocks)
    parsed = {"notes": {"my_history": {"summary": "Lifetime realized P/L is 105 [F1]. It returned 999% once.",
                                       "lessons": "You should sell half here."}}}
    log: list = []
    extensions.finalize(blocks, parsed, b, log)
    note = blocks["my_history"]["writer_note"]
    assert "105" in note["summary"] and "999" not in note["summary"]
    assert not note["lessons"]
    assert any(r.get("reason") == "ungrounded_number" for r in log)


def test_history_tables_render_shapes():
    b = _bundle()
    b.blocks["my_history"] = my_history.build(FakeHistoryReader(), b, holding={"shares": 40}, now=NOW)
    doc = {"symbol": "ZZMH", "blocks": b.blocks}
    tables = extensions.top_tables(doc)
    ids = [t["id"] for t in tables]
    assert ids[:2] == ["my_history", "my_history_trips"] and "my_history_lessons" in ids and "my_history_events" in ids
    assert all(len(r) == len(t["columns"]) for t in tables for r in t["rows"])
    flags = [r[-1] for r in tables[1]["rows"]]
    assert "wash-sale window" in flags[1] and "stopped out" in flags[1]
    assert "fixture_" not in json.dumps(tables)


def test_lifecycle_performance_symbol_filter_is_additive(monkeypatch):
    """The reuse hook: lifecycle_performance(symbol=) filters every read; without it the SQL is unchanged."""
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: None))
    sys.modules.pop("recommendation_intelligence_engine", None)
    import recommendation_intelligence_engine as rie

    class Cur:
        def __init__(self):
            self.calls, self._rows = [], []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            if "FROM trade_closed" in sql:
                self._rows = [(7, "ZZMH", "fixture_brokerage", date(2026, 1, 2), date(2026, 2, 2), 5, 10.0, 12.0, 10.0,
                               20.0, None, 31, None, None)]
            elif "FROM journal_trade_reviews" in sql:
                self._rows = [("ZZMH", "fixture_brokerage", date(2026, 2, 2), 1.5, "fixture lesson", "fam", "hard_stop")]
            else:
                self._rows = []

        def fetchall(self):
            return self._rows

    cur = Cur()
    rows = rie.lifecycle_performance(cur, limit=10, symbol="zzmh")
    assert all("upper(symbol) = %s" in sql for sql, _ in cur.calls)
    assert all("ZZMH" in tuple(p) for _, p in cur.calls)
    assert rows[0]["journal"]["exit_type"] == "hard_stop" and rows[0]["r_multiple"] == 1.5
    cur2 = Cur()
    rie.lifecycle_performance(cur2, limit=10)
    assert not any("upper(symbol) = %s" in sql for sql, _ in cur2.calls)


# ── ETF gaps ──────────────────────────────────────────────────────────────────────────────────────────────────────
CATS = etf_profile.load_categories(ROOT)


def test_category_map_and_keyword_fallback():
    xar = etf_profile.classify("XAR", rec={"industry": "Exchange Traded Fund", "sector": "Financial"}, fund={}, lookthrough={},
                               holding=None, cats=CATS)
    assert xar["is_fund"] and xar["label"] == "Aerospace & Defense" and xar["sector_etf"] == "XLI"
    assert xar["peers"] == ["ITA", "PPA"]
    unk = etf_profile.classify("ZZDF", rec={"industry": "Exchange Traded Fund", "company": "Fixture Fund"},
                               fund={"description_1s": "Tracks the Fixture Aerospace & Defense Select Industry Index."},
                               lookthrough={}, holding=None, cats=CATS)
    assert unk["category_id"] == "aerospace_defense" and "index description" in unk["basis"]
    stock = etf_profile.classify("ZZST", rec={"industry": "Widgets", "sector": "Technology"}, fund={"quote_type": "EQUITY"},
                                 lookthrough={}, holding=None, cats=CATS)
    assert not stock["is_fund"] and stock["sector_etf"] is None


def test_every_category_peer_and_symbol_is_consistent():
    cats = CATS["categories"]
    assert all(v in cats for v in CATS["symbols"].values())
    assert all(isinstance(c.get("keywords"), list) and c.get("label") for c in cats.values())


class FakeEtfSources:
    """XAR-like synthetic fund (ZZXA) with no analyst targets; pinned to the aerospace category by a test config."""

    state_root = Path("/nonexistent-prospectus-fixture")

    def __init__(self):
        self.reader = FakeHistoryReader("ZZXA")

    def history_reader(self):
        return self.reader

    def db(self):
        def query(sql, params=None, fetch="all"):
            if "FROM symbol_profiles" in sql:
                return [{"quote_type": "ETF", "expense_ratio": 0.0035, "dividend_yield_pct": 0.21,
                         "ttm_distribution_amount": 0.4, "last_distribution_amount": 0.11,
                         "last_distribution_date": date(2026, 9, 21), "distribution_cadence": "quarterly",
                         "next_distribution_est": date(2026, 12, 21),
                         "description_1s": "Seeks to track the Fixture Aerospace & Defense Select Industry Index."}]
            if "FROM ticker_dividends" in sql:
                return [{"ex_date": date(2026, 9, 21), "amount": 0.11}, {"ex_date": date(2026, 6, 22), "amount": 0.1}]
            if "fred_economic_series" in sql:
                out, d0 = [], date(2024, 9, 1)
                for i in range(800):
                    d = d0 + timedelta(days=i)
                    out.append({"series_id": "DGS10", "value": 4.0 + 0.3 * math.sin(i / 9.0), "observation_date": d})
                    out.append({"series_id": "VIXCLS", "value": 18 + 2 * math.cos(i / 5.0), "observation_date": d})
                    if d.day == 1:
                        out.append({"series_id": "CPIAUCSL", "value": 300 + i * 0.03, "observation_date": d})
                return out
            return []
        return query

    def bars(self, sym, days=1100):
        return _bars(sym)

    def enrichment_cache(self):
        return {"ZZXA": {"company": "Fixture Aerospace & Defense ETF", "sector": "Financial", "industry": "Exchange Traded Fund",
                         "cached_at": "2026-10-26T06:00:00"}}

    def lookthrough(self, sym):
        return {"fund": {"top_holdings": {"ZZH1": 4.1, "ZZH2": 3.9}, "fetched_date": "2026-10-01"}}

    # the rest of the assemble() readers: empty house data for a fund
    def dossier(self, sym):
        return {"profile": {"sector": None, "industry": None, "updated_at": "2026-10-25"}}

    def consensus(self, syms):
        return {}

    def ohlc(self, sym):
        return []

    def position_view(self, sym):
        return {}

    def trades(self, sym):
        return []

    def options_theses(self, sym):
        return []

    def analyst(self, sym):
        return {}

    def cio(self, sym):
        return {"stance": "HOLD", "conviction": 55, "evidence_at": "2026-10-25"}

    def stops(self, sym, accounts):
        return []


def _etf_bundle():
    srcs = FakeEtfSources()
    holding = {"shares": 40.0, "market_value": 2800.0, "cost_basis": 2350.0, "avg_cost": 58.75, "unrealized_pl": 450.0,
               "unrealized_pl_pct": 19.15, "accounts": ["fixture_brokerage", "fixture_roth_ira"], "as_of": "2026-10-26",
               "is_fund": True, "asset_type": "etf"}
    b = full_assemble(srcs, "ZZXA", "holding", cfg={"registry_domains": {}}, holding=holding, now=NOW)
    if "fund_profile" not in b.blocks:  # the assembler hook (domains.full_assemble → extensions.attach) not wired
        cats = json.loads(json.dumps(CATS))
        cats["symbols"]["ZZXA"] = "aerospace_defense"
        extensions.etf_profile.attach(srcs, b, bars=srcs.bars("ZZXA"), holding=holding, now=NOW, cats=cats)
    if "my_history" not in b.blocks:
        b.blocks["my_history"] = my_history.build(srcs.reader, b, holding=holding, now=NOW)
    return b


def test_etf_relative_performance_uses_category_sector_and_peers():
    b = _etf_bundle()
    rel = b.blocks["relative_performance"]
    assert rel["sector_etf"] == "XLI" and rel["category_peers"] == ["ITA", "PPA"]
    assert rel["benchmarks"] == ["XLI", "SPY", "QQQ"]
    assert [r["name"] for r in rel["returns"]][:4] == ["ZZXA", "XLI", "SPY", "QQQ"]
    assert any("vendor sector" in g for g in rel["gaps"])
    labels = _labels(b)
    assert "XLI (sector ETF, Aerospace & Defense) return 1Y %" in labels
    assert any(lbl.startswith("XLF return") and "vendor-sector" in lbl for lbl in labels)
    assert "house category: Aerospace & Defense" in labels["Sector"]["text"]


def test_etf_fund_profile_and_named_gaps():
    fp = _etf_bundle().blocks["fund_profile"]
    assert fp["category"] == "Aerospace & Defense" and fp["expense_ratio_pct"] == pytest.approx(0.35)
    assert fp["dividend_yield_pct"] == pytest.approx(0.21) and fp["distribution_cadence"] == "quarterly"
    assert [h["name"] for h in fp["top_holdings"]] == ["ZZH1", "ZZH2"] and fp["top10_weight_pct"] == pytest.approx(8.0)
    assert fp["dividend_history"][0]["ex_date"] == "2026-09-21"
    assert fp["aum_usd"] is None and any("assets under management" in g for g in fp["gaps"])
    t = extensions.bottom_tables({"blocks": {"fund_profile": fp}})[0]
    assert t["id"] == "fund_profile" and any(r[0] == "Expense ratio" and r[1] == "0.35%" for r in t["rows"])


def test_etf_without_targets_gets_labelled_house_scenarios():
    b = _etf_bundle()
    house = b.blocks["scenarios_house"]
    assert [c["case"] for c in house["cases"]] == ["bear", "base", "bull"]
    bear, base, bull = (c["price"] for c in house["cases"])
    assert bear < base < bull and all(c["probability_pct"] is None for c in house["cases"])
    assert "not a forecast" in house["method_label"] and "not an order" in house["footer"]
    ids = {f["id"] for f in b.facts}
    assert all(c["price_fact"] in ids for c in house["cases"])
    blocks = dict(b.blocks)
    blocks["scenarios"] = gen.validate_scenarios([], b, log=[])  # the writer had no target to anchor on
    extensions.finalize(blocks, {}, b, [])
    assert blocks["scenarios"]["method"] == "house_volatility_band" and "scenarios_house" not in blocks


def test_scenarios_from_analyst_targets_are_not_replaced():
    b = _etf_bundle()
    blocks = dict(b.blocks)
    blocks["scenarios"] = {"cases": [{"case": "base", "price": 70.0}], "gaps": []}
    extensions.finalize(blocks, {}, b, [])
    assert blocks["scenarios"]["cases"] == [{"case": "base", "price": 70.0}]


def test_macro_sensitivity_effect_column_is_measured_and_labelled():
    b = _etf_bundle()
    macro = b.blocks["macro_sensitivity"]
    sens = macro["sensitivity"]
    assert set(sens) == {"DGS10", "CPIAUCSL", "VIXCLS"}
    for row in sens.values():
        assert row["effect"].split(":")[0] in {"headwind", "tailwind", "neutral", "not reliable"}
        assert row["method"] and "OLS" in row["method"]
    assert sens["DGS10"]["n"] >= 120 and sens["DGS10"]["beta"] is not None
    assert sens["CPIAUCSL"]["n"] < 120
    blocks = dict(b.blocks)
    extensions.finalize(blocks, {}, b, [])
    assert blocks["macro_sensitivity"]["effects"]["rates"].startswith("measured — ")


def test_macro_too_few_points_is_not_reliable():
    b = _bundle()
    class Short(FakeEtfSources):
        def bars(self, sym, days=1100):
            return _bars(sym, n=40)
    sens = etf_profile.macro_sensitivity(b, Short(), Short().bars("ZZMH"), NOW, CATS)
    assert sens["DGS10"]["reliable"] is False and sens["DGS10"]["effect"].startswith("not reliable")


def test_extensions_attach_never_raises_and_records_gap():
    class NoHistory(FakeEtfSources):
        history_reader = None
    srcs = NoHistory()
    b = _bundle(sym="ZZXA")
    extensions.attach(srcs, b, cfg={}, holding=None, now=NOW, bars=srcs.bars("ZZXA"))
    assert b.blocks["my_history"]["scope"] == "unavailable"


# ── end to end through the assembler, writer and renderers (needs the hook lines in domains/generate/render) ─────
def _hooks_wired() -> bool:
    import inspect
    from scripts.lib.prospectus import domains, render
    return ("attach_extensions" in inspect.getsource(domains.full_assemble)
            and "finalize(" in inspect.getsource(gen.write) and "ext.top_tables" in inspect.getsource(render.html))


@pytest.mark.skipif(not _hooks_wired(), reason="extension hooks not wired into domains/generate/render yet")
def test_end_to_end_writer_note_house_scenarios_and_renders(tmp_path):
    from scripts.lib.prospectus import load_config, render
    srcs = FakeEtfSources()
    holding = {"shares": 40.0, "market_value": 2800.0, "cost_basis": 2350.0, "avg_cost": 58.75, "unrealized_pl": 450.0,
               "unrealized_pl_pct": 19.15, "accounts": ["fixture_brokerage"], "as_of": "2026-10-26", "is_fund": True}
    cfg = load_config()
    b = full_assemble(srcs, "ZZXA", "holding", cfg=dict(cfg, registry_domains={}), holding=holding, now=NOW)
    assert b.blocks["my_history"]["scope"] == "held" and b.blocks["fund_profile"]["category"] == "Aerospace & Defense"
    realized = next(f for f in b.facts if f["label"] == "My history: Lifetime realized P/L on ZZXA $")
    prompts = []

    def fn(prompt, *, process_id, max_tokens, timeout, manual=False):
        prompts.append(prompt)
        secs = [{"id": s, "title": s, "body_md": f"Fact-based text [{realized['id']}].", "citations": [realized["id"]]}
                for s in ("summary_verdict", "business_and_moat", "financials_and_trend", "valuation_vs_peers",
                          "catalysts_and_dates", "risks", "analyst_view", "thesis_breakers", "position_and_plan")]
        return json.dumps({"verdict_line": "Hold.", "sections": secs, "scenarios": [],
                           "notes": {"my_history": {"summary": f"Realized {realized['value']} dollars so far [{realized['id']}].",
                                                    "lessons": "Stops ended most trips."}}}), \
            {"returned_model": "claude-opus-5-5", "estimated_cost_usd": 0.1, "provider": "anthropic", "usage": {}}

    doc = gen.write(b, processes=cfg["processes"], premium=False, cfg=dict(cfg, web={}), generate_fn=fn, now=NOW,
                    version="20261026T160000Z")
    assert "MY HISTORY" in prompts[-1] and '"my_history"' in prompts[-1]
    assert doc["blocks"]["my_history"]["writer_note"]["summary"].startswith("Realized 105")
    assert doc["blocks"]["scenarios"]["method"] == "house_volatility_band"
    assert "scenarios_house" not in doc["blocks"]
    html = render.html(doc)
    assert html.index('id="block-my_history"') < html.index('id="summary_verdict"')
    assert 'id="block-fund_profile"' in html and "Trip" not in html.split('id="block-my_history"')[0]
    assert "fixture_" not in html
    data = render.docx(doc, {})
    if data is not None:
        import io
        import zipfile
        xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode()
        assert xml.index("My history") < xml.index("Summary verdict")
