"""Design home/v006 build: Protect / Hedge / Rotate join, folded groups, glossary, the Defense posture hedge_state
following the inverse stoplight, sector daily closes from ticker_prices, and APPROVED issuer segments in the risk
budget. Synthetic data only (public repo)."""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.lib import defense_hedge_state as dhs
from scripts.lib import market_risk_book_dollars as bd
from scripts.lib import market_risk_book_join as bj
from scripts.lib import market_risk_home_actions as ha
from scripts.lib.market_risk import lookthrough as lt
from scripts.lib.market_risk import reader as rd
from scripts.lib.market_risk import risk_budget as rb
from scripts.lib.market_risk.policy import load_policy

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
POLICY = load_policy()
DEFENSE = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())
TODAY = date(2031, 3, 10)


def _stoplights(thesis: dict[str, str], generated: date = TODAY - timedelta(days=1)) -> dict:
    return {"generated_at": datetime(generated.year, generated.month, generated.day, 21, 55, tzinfo=timezone.utc).isoformat(),
            "candidates": [{"inverse": k, "bench": {"PSQ": "QQQ"}.get(k, "SPY"),
                            "lights": {"THESIS": {"state": v, "label": "x"},
                                       "ENTRY": {"state": "AMBER", "label": "WAIT FOR BOUNCE DAY"}}} for k, v in thesis.items()]}


# ── Defense posture hedge_state follows the stoplight (a stale alert is never a live plan) ───────────────────────
STALE_ALERT = ("QQQ", 720.48, "2031-03-03 11:20:03-05:00")


def test_hedge_state_red_thesis_never_shows_the_stale_bounce_alert():
    hs = dhs.hedge_state(stoplights=_stoplights({"SH": "RED", "PSQ": "RED"}), intent=None, bounce=STALE_ALERT,
                         tech_state="LAGGING", today=TODAY, stale_days=4)
    assert hs["state"] == "no_thesis"
    assert "720.48" not in hs["line"] and "bounce" not in hs["line"]


def test_hedge_state_amber_is_watch_and_missing_or_stale_snapshot_is_unknown():
    assert dhs.hedge_state(stoplights=_stoplights({"PSQ": "AMBER", "SH": "RED"}), intent=None, bounce=STALE_ALERT,
                           tech_state=None, today=TODAY, stale_days=4)["state"] == "watch"
    for snap in (None, {}, {"candidates": [], "generated_at": "x"}, {"config_error": "bad", "candidates": [{}]},
                 _stoplights({"PSQ": "GREEN"}, generated=TODAY - timedelta(days=9))):
        hs = dhs.hedge_state(stoplights=snap, intent=None, bounce=STALE_ALERT, tech_state=None, today=TODAY, stale_days=4)
        assert hs["state"] == "unknown" and "720.48" not in hs["line"]


def test_hedge_state_green_shows_only_this_episodes_bounce_level():
    green = _stoplights({"PSQ": "GREEN", "SH": "RED"})
    since = {"PSQ": datetime(2031, 3, 8, 22, 55, tzinfo=timezone.utc)}
    fresh = ("QQQ", 700.1, None, datetime(2031, 3, 8, 23, 30, tzinfo=timezone.utc))  # armed after the GREEN transition
    hs = dhs.hedge_state(stoplights=green, intent=None, bounce=fresh, tech_state="LAGGING", today=TODAY, stale_days=4, green_since=since)
    assert hs["state"] == "armed" and "QQQ ≥ $700.1" in hs["line"]
    today_fire = (*fresh[:2], f"{TODAY.isoformat()}T15:00:00+00:00", fresh[3])
    hs = dhs.hedge_state(stoplights=green, intent=None, bounce=today_fire, tech_state="LAGGING", today=TODAY, stale_days=4, green_since=since)
    assert hs["state"] == "entry_window_open"
    # an alert armed before this episode's GREEN, one for another bench, or unknown timing: never a live level
    old = ("QQQ", 720.48, None, datetime(2031, 3, 1, 23, 0, tzinfo=timezone.utc))
    other_bench = ("SPY", 769.75, None, datetime(2031, 3, 9, 1, 0, tzinfo=timezone.utc))
    for b, gs in ((old, since), (other_bench, since), (fresh[:3], since), (fresh, None)):
        hs = dhs.hedge_state(stoplights=green, intent=None, bounce=b, tech_state="LAGGING", today=TODAY, stale_days=4, green_since=gs)
        assert hs["state"] == "armed" and "$" not in hs["line"], (b, gs, hs)


def test_H_green_does_not_revive_an_old_episode_alert():
    """The reviewer's probe (review of #2460, B2): THESIS turned GREEN; the only active bounce alert is from an earlier
    episode (10-28 QQQ 720.48) and must not read as this episode's entry level."""
    snap = {"generated_at": datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc).isoformat(),
            "candidates": [{"inverse": "SQQQ", "bench": "QQQ", "lights": {"THESIS": {"state": "GREEN"}, "ENTRY": {"state": "AMBER"}}}]}
    out = dhs.hedge_state(stoplights=snap, intent=None, bounce=("QQQ", 720.48, "2026-10-28T14:00:00+00:00"), tech_state="LAGGING",
                          today=date(2026, 11, 2), stale_days=4)
    assert "720.48" not in out["line"], out
    out = dhs.hedge_state(stoplights=snap, intent=None, bounce=("QQQ", 720.48, None, "2026-10-26T15:00:00+00:00"), tech_state="LAGGING",
                          today=date(2026, 11, 2), stale_days=4, green_since={"SQQQ": "2026-11-02T21:00:00+00:00"})
    assert "720.48" not in out["line"], out


def test_hedge_in_play_and_stand_down_are_reported_whatever_the_stoplight():
    hs = dhs.hedge_state(stoplights=_stoplights({"PSQ": "RED"}), intent=("filled", 30.0, "PSQ"), bounce=None,
                         tech_state="LAGGING", today=TODAY, stale_days=4, in_play_line="HEDGE: PSQ in play +2.0%")
    assert hs == {"state": "in_play", "line": "HEDGE: PSQ in play +2.0%"}
    hs = dhs.hedge_state(stoplights=None, intent=("filled", 30.0, "PSQ"), bounce=None, tech_state="LEADING", today=TODAY, stale_days=4)
    assert hs["state"] == "stand_down"


def test_api_posture_uses_the_stoplight_helper_and_only_active_alerts():
    src = (ROOT / "scripts" / "api_v2.py").read_text()
    i = src.index("def _defense_posture(")
    body = src[i : src.index("\ndef ", i + 10)]
    assert "from lib.defense_hedge_state import hedge_state" in body
    assert "created_by='defense_hedge' AND active" in body


# ── Hedge block ─────────────────────────────────────────────────────────────────────────────────────────────────
BE = {"stressed_usd": 12345.0, "stressed_pct_book": 2.5, "stressed_pct_invested": 4.0}
MOMENTUM = [{"etf": "XLK", "sector": "Technology", "state": "LAGGING", "book_pct": 5.5}, {"etf": "XLV", "sector": "Healthcare", "state": "LEADING", "book_pct": 9.0}]


@pytest.mark.parametrize("thesis,verdict", [({"SH": "RED", "PSQ": "RED"}, "NOT_NOW"), ({"PSQ": "AMBER"}, "WATCH"), ({"PSQ": "GREEN"}, "CONSIDER")])
def test_hedge_verdict_from_the_stoplight_with_the_desks_config_thresholds(thesis, verdict):
    trans = [{"light": "THESIS", "new_state": list(thesis.values())[0], "created_at": "2031-03-07 17:55:02-05:00"}]
    h = ha.hedge(stoplights=_stoplights(thesis), momentum_rows=MOMENTUM, book_exposure=BE, defense_cfg=DEFENSE, today=TODAY, transitions=trans)
    assert h["verdict"] == verdict
    assert h["thresholds"]["trigger_book_pct"] == DEFENSE["inverse_etf"]["trigger_book_pct"]
    assert h["thresholds"]["materiality_exposure_pct"] == DEFENSE["inverse_stoplights"]["materiality_exposure_pct"]
    assert h["largest_weakening"] == {"label": "Technology", "pct_invested": 5.5} and h["lagging_count"] == 1
    assert h["since"] == "2031-03-07"
    assert not set(h) & set(ha.HEDGE_FORBIDDEN)
    if verdict == "CONSIDER":
        assert h["entry"] == {"inverse": "PSQ", "bench": "QQQ", "state": "AMBER", "label": "WAIT FOR BOUNCE DAY"}


def test_hedge_unknown_when_the_stoplight_is_stale():
    h = ha.hedge(stoplights=_stoplights({"PSQ": "RED"}, generated=TODAY - timedelta(days=10)), momentum_rows=[], book_exposure=BE,
                 defense_cfg=DEFENSE, today=TODAY)
    assert h["verdict"] == "UNKNOWN" and h["reason"] == "stale"


# ── Rotate ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _heat(key, state, rs1, rs5, kind="sector"):
    return {"key": key, "label": key.title(), "kind": kind, "state": state, "rs1": rs1, "rs5": rs5}


HEAT = [_heat("tech", "STRESS", -3.1, -1.5), _heat("healthcare", "RESILIENT", 2.25, 3.69), _heat("materials", "RESILIENT", 2.19, 3.33),
        _heat("energy", "RESILIENT", 3.66, 1.52), _heat("staples", "RESILIENT", 3.23, 1.84), _heat("industrials", "RESILIENT", 0.18, 2.23),
        _heat("utilities", "RESILIENT", 2.5, 2.62), _heat("fin", "NEUTRAL", 1.0, 1.6), _heat("disc", "RESILIENT", -0.2, 2.5)]


def test_rotate_ranks_resilient_groups_leading_on_both_horizons():
    r = ha.rotate(HEAT, leadership=None, momentum_rows=MOMENTUM, book_groups={"healthcare": {"usd": 11111.0}}, policy=POLICY,
                  sector_groups=[{"key": "healthcare", "kind": "sector", "symbols": ["XLV"]},
                                 {"key": "defensive", "kind": "defensive", "symbols": ["XLP", "XLV", "XLU"]}], as_of="2031-03-07")
    keys = [g["key"] for g in r["groups"]]
    assert keys == ["healthcare", "materials", "energy"]  # mean(rs1, rs5): 2.97, 2.76, 2.59
    assert "fin" not in keys and "disc" not in keys  # NEUTRAL; negative 1d
    assert r["groups"][0]["desk_state"] == "LEADING" and r["groups"][0]["usd"] == 11111.0
    assert not any(k in json.dumps(r).lower() for k in ("buy", "add ", "size"))


def test_rotate_fading_leadership_is_dropped_and_nothing_qualifying_says_so():
    lead = {"groups": {"healthcare": {"class": "LEADERSHIP_FADING"}}}
    r = ha.rotate(HEAT, leadership=lead, momentum_rows=None, book_groups=None, policy=POLICY)
    assert "healthcare" not in [g["key"] for g in r["groups"]]
    none = ha.rotate([_heat("tech", "STRESS", -3, -1)], leadership=None, momentum_rows=None, book_groups=None, policy=POLICY)
    assert none["groups"] == [] and none["none_reason"].startswith("No group is beating SPY")


def test_folded_groups_under_the_config_amount():
    heat = [_heat("tech", "STRESS", -3, -1), _heat("ai_basket", "STRESS", -3, -3, "theme"), _heat("real_estate", "UNKNOWN", None, None),
            _heat("staples", "RESILIENT", 1, 1)]
    f = ha.folded(heat, {"tech": {"usd": 12000}, "ai_basket": {"usd": 50.0}, "real_estate": {"usd": 5.0}}, POLICY)
    assert [x["key"] for x in f] == ["ai_basket", "real_estate"]
    assert POLICY["home_actions"]["sectors"]["fold_below_usd"] == 100


# ── Protect ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _item(sym, acct, kinds, usd, **facts):
    return {"symbol": sym, "account_label": acct, "kinds": kinds, "text": " · ".join(kinds), "usd": usd, "to": f"/risk?symbol={sym}",
            "pct_account": facts.get("pct_account"), "facts": {"value_usd": usd, **facts}}


def test_protect_clauses_are_built_from_facts_in_config_order():
    review = [
        _item("DEMOA", "Acct-1", ["stop_near"], 40000, pct_account=88.0, stop_distance_pct=3.6, groups={"financials": 1.0}),
        _item("DEMOA", "Acct-2", ["no_stop"], 30000, pct_account=5.0, groups={"financials": 1.0}),
        _item("DEMOB", "Acct-3", ["no_stop"], 20000, pct_account=40.0, groups={"industrials": 1.0}),
        _item("DEMOC", "Acct-2", ["stop_near"], 10000, pct_account=1.5, stop_distance_pct=4.5),
    ]
    budgets = [
        {"account_label": "Acct-1", "budget": "growth_style_pct", "limit": 50, "actual": 88.0, "actual_usd": 40000.0, "drivers": [{"name": "DEMOA", "usd": 40000}]},
        {"account_label": "Acct-1", "budget": "single_sector_pct", "limit": 30, "actual": 88.0, "actual_usd": 40000.0, "drivers": [{"name": "Financial Services", "usd": None}]},
        {"account_label": "Acct-3", "budget": "unprotected_pct", "limit": 10, "actual": 41.2, "actual_usd": 21000, "drivers": [{"name": "DEMOB", "usd": 20000}, {"name": "X", "usd": 128}]},
    ]
    reentry = {"DEMOB": {"wash_sale": {"state": "occurred", "account_label": "Acct-3", "rebuy_date": "2031-03-05"}}}
    p = ha.protect(review, budgets=budgets, reentry=reentry, overnight={"DEMOB"}, policy=POLICY)
    a, b, c = p["items"]
    assert a["consideration"] == ("stop 3.6% below last; one stock is 88% of the account, far above the 30% sector budget; "
                                  "with the Acct-2 position, $70,000 in DEMOA across 2 accounts")
    assert b["consideration"] == "no stop; with the Acct-1 position, $70,000 in DEMOA across 2 accounts"
    assert c["consideration"] == "no stop; trades overnight now; 41.2% of the account unprotected vs the 10% budget"
    assert p["more"] == [{"symbol": "DEMOC", "account_label": "Acct-2", "short": "stop 4.5% below last", "to": "/risk?symbol=DEMOC"}]
    for it in p["items"]:
        assert not ha.has_action_verb(it["consideration"]), it["consideration"]
        assert not re.search(r"\$\d+(\.\d+)? stop|stop (at|to) \$", it["consideration"])  # never a stop level


def test_protect_sector_budget_needs_the_symbol_in_that_sector():
    review = [_item("DEMOX", "Acct", ["no_stop"], 90, pct_account=45.0, groups={"tech": 1.0})]
    budgets = [{"account_label": "Acct", "budget": "single_sector_pct", "limit": 30, "actual": 50, "actual_usd": 100,
                "drivers": [{"name": "Industrials", "usd": None}]}]
    p = ha.protect(review, budgets=budgets, reentry={}, overnight=set(), policy=POLICY)
    assert p["items"][0]["consideration"] == "no stop"


def test_book_dollars_review_items_carry_the_facts():
    proj = {"heatmap": [{"key": "tech", "kind": "sector", "state": "STRESS"}],
            "positions": {"DEMOA": {"look_through": {"groups": {"financials": 1.0}, "basis": "stock"}, "label": "hold"}}}
    store = {"holdings": [{"symbol": "DEMOA", "account": "A", "market_value": 5000.0, "shares": 10, "canonical_mark": 500.0}],
             "portfolio_totals": {"total_value": 5000.0}}
    out = bd.build(proj, store, stops=[{"account": "A", "symbol": "DEMOA", "stop_price": 485.0}], policy={"home_review": {"stop_near_pct": 5}},
                   label_fn=lambda a: a, canon_fn=lambda a: a)
    it = out["review"][0]
    assert it["pct_account"] == 100.0 and it["facts"]["stop_distance_pct"] == 3.0 and it["facts"]["groups"] == {"financials": 1.0}
    assert "groups" not in out["book_exposure"]["rows"][0] if out["book_exposure"]["rows"] else True


# ── Glossary ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_glossary_texts_resolve_are_short_and_advisory():
    budget = rb.load_budget()
    g = ha.glossary(POLICY, DEFENSE, budget)
    need = {"stress", "weak", "resilient", "holding", "not_measured", "look_through", "pct_book", "stressed_pct", "usd_exposed", "pc_oi",
            "carried", "shadow", "stage1", "stage2", "invalidates_below", "budget_breach", "vulnerability", "hedge_verdict", "rotate_rs", "protect"}
    assert need <= set(g)
    assert ha.unresolved_placeholders(g) == []
    for k, v in g.items():
        assert len(v["text"]) <= POLICY["glossary"]["max_chars"], k
        assert len([s for s in re.split(r"(?<=[.!?])\s+", v["text"].strip()) if s]) <= 2, k
        assert not ha.has_action_verb(v["text"]), k
    assert "10%" in g["hedge_verdict"]["text"] and "30%" in g["budget_breach"]["text"]


def test_every_ui_explain_term_is_in_the_glossary():
    src = "".join(p.read_text() for p in (ROOT / "apps/command-center-v3/src/components/home").glob("MarketRisk*.tsx"))
    terms = set(re.findall(r'<Explain term="([a-z_0-9]+)"', src))
    terms |= {"stress", "weak", "resilient", "holding", "not_measured"}  # CHIP_TERM map
    doc = json.loads((ROOT / "config" / "market_risk_glossary.json").read_text())["terms"]
    assert terms and terms <= set(doc), terms - set(doc)


# ── Join wiring (synthetic store; no DB) ─────────────────────────────────────────────────────────────────────────
def test_home_actions_fail_soft_and_add_every_block():
    proj = {"heatmap": HEAT, "sectors": {"as_of": "2031-03-07", "groups": [{"key": "healthcare", "symbols": ["XLV"]}]}}
    out = {"review": [], "budgets": [], "reentry": {}, "book_exposure": {**BE, "groups": {}, "rows": []}}
    files = {"data/runtime/inverse_stoplights_latest.json": _stoplights({"PSQ": "RED"}), "data/runtime/sector_momentum_latest.json": {"rows": MOMENTUM},
             "config/defense_recommendations.json": DEFENSE, "config/issuer_segments.json": {"issuers": {}}}
    res = bj.home_actions(proj, out, policy=POLICY, overnight=None, transitions=[], now=datetime(2031, 3, 10, 15, tzinfo=timezone.utc),
                          load_json=lambda rel: files.get(rel))
    assert {"protect", "hedge", "rotate", "sectors_folded", "glossary", "segments_status"} <= set(res), res
    assert res["hedge"]["verdict"] == "NOT_NOW"
    assert not [k for k in res if k.endswith("_error")]
    assert bj.card_config(POLICY)["fold_below_usd"] == 100


# ── Sector daily closes: ticker_prices fills what market_ohlcv_bars lacks ─────────────────────────────────────────
class _Cur:
    def __init__(self, routes, log):
        self.routes, self.log, self.description, self._rows = routes, log, [], []

    def execute(self, sql, params=None):
        self.log.append((sql, params))
        for needle, (cols, rows) in self.routes.items():
            if needle in sql:
                self.description = [(c,) for c in cols]
                self._rows = [tuple(r[c] for c in cols) for r in rows]
                return
        self.description, self._rows = [], []

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _Conn:
    def __init__(self, routes):
        self.routes, self.log = routes, []

    def set_session(self, readonly=False):
        self.readonly = readonly

    def cursor(self):
        return _Cur(self.routes, self.log)

    def close(self):
        pass


def _et(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


TPCOLS = ["symbol", "price_date", "close_price", "source", "created_at"]
QCOLS = ["symbol", "price", "prev_close", "fetched_at"]


class _AllRows(_Conn):
    """Returns every routed row whatever the SQL says, so the reader's own as-of check must reject (kills a mutant that
    forces the created_at filter to pass, review of #2460 T1)."""


def test_daily_bars_use_ticker_prices_for_a_symbol_without_ohlcv_bars():
    tp = [{"symbol": "XLC", "price_date": date(2031, 3, d), "close_price": 100.0 + d, "source": "yfinance", "created_at": _et(2031, 3, d, 16, 7)}
          for d in (5, 6, 7)]
    conn = _Conn({"FROM market_ohlcv_bars": (["symbol"], []), "FROM ticker_prices": (TPCOLS, tp)})
    bars = rd.PgReader(lambda: conn).daily_bars(["XLC"], sessions=10, end=_et(2031, 3, 7, 18))
    assert [(b["date"], b["close"]) for b in bars] == [("2031-03-05", 105.0), ("2031-03-06", 106.0), ("2031-03-07", 107.0)]
    assert all(b["source"] == "ticker_prices:yfinance" for b in bars)
    sql, params = next((s, p) for s, p in conn.log if "FROM ticker_prices" in s)
    assert "created_at IS NOT NULL AND created_at <= %s" in sql and "source = ANY(%s)" in sql
    assert params[3] == _et(2031, 3, 7, 18) and params[4] == list(rd.TICKER_PRICE_CLOSE_SOURCES)


def test_ticker_prices_as_of_rejects_late_null_preclose_and_intraday_rows():
    end = _et(2031, 3, 9, 18)
    tp = [
        {"symbol": "XLC", "price_date": date(2031, 3, 3), "close_price": 103.0, "source": "yfinance", "created_at": _et(2031, 3, 3, 16, 30)},  # ok
        {"symbol": "XLC", "price_date": date(2031, 3, 4), "close_price": 999.0, "source": "yfinance", "created_at": _et(2031, 3, 9, 19)},  # after end
        {"symbol": "XLC", "price_date": date(2031, 3, 5), "close_price": 777.0, "source": "yfinance", "created_at": None},  # unknowable
        {"symbol": "XLC", "price_date": date(2031, 3, 6), "close_price": 555.0, "source": "yfinance", "created_at": _et(2031, 3, 6, 10)},  # pre-close
        {"symbol": "XLC", "price_date": date(2031, 3, 9), "close_price": 333.0, "source": "market_quotes", "created_at": _et(2031, 3, 9, 16, 7)},  # intraday print
    ]
    conn = _AllRows({"FROM market_ohlcv_bars": (["symbol"], []), "FROM ticker_prices": (TPCOLS, tp)})
    bars = rd.PgReader(lambda: conn).daily_bars(["XLC"], sessions=10, end=end)
    assert [(b["date"], b["close"]) for b in bars] == [("2031-03-03", 103.0)]


def test_ticker_prices_rank_after_bars_and_quote_closes_so_spy_is_unchanged():
    bcols = ["symbol", "bar_time", "open", "high", "low", "close", "volume", "source", "created_at"]
    bars = [{"symbol": "SPY", "bar_time": _et(2031, 3, 5, 0), "open": 1, "high": 2, "low": 0.5, "close": 680, "volume": 1, "source": "yfinance",
             "created_at": _et(2031, 3, 5, 17)}]
    quotes = [{"symbol": "SPY", "price": 605.0, "prev_close": 680.0, "fetched_at": _et(2031, 3, 6, 9, 35)},
              {"symbol": "SPY", "price": 611.0, "prev_close": 606.0, "fetched_at": _et(2031, 3, 7, 9, 35)},
              {"symbol": "SPY", "price": 612.0, "prev_close": 606.0, "fetched_at": _et(2031, 3, 7, 15, 59)}]
    tp = [{"symbol": "SPY", "price_date": date(2031, 3, d), "close_price": 900.0 + d, "source": "yfinance", "created_at": _et(2031, 3, d, 16, 30)}
          for d in (3, 5, 6, 7)]
    conn = _Conn({"FROM market_ohlcv_bars": (bcols, bars), "FROM market_quotes WHERE source": (QCOLS, quotes), "FROM ticker_prices": (TPCOLS, tp)})
    out = rd.PgReader(lambda: conn).daily_bars(["SPY"], sessions=10, end=_et(2031, 3, 7, 18))
    assert [(b["date"], b["close"], b["source"]) for b in out] == [
        ("2031-03-03", 903.0, "ticker_prices:yfinance"),  # only a session neither bars nor quotes have
        ("2031-03-05", 680.0, "market_ohlcv_bars:yfinance"),
        ("2031-03-06", 606.0, "market_quotes:alpaca_prev_close"),  # the quote close wins over ticker_prices
        ("2031-03-07", 612.0, "market_quotes:alpaca_last"),
    ]


# ── APPROVED issuer segments: look-through and the risk budget ───────────────────────────────────────────────────
def test_the_operator_approved_spcx_entry_validates_with_the_capex_ai_overlay():
    cfg = json.loads((ROOT / "config" / "issuer_segments.json").read_text())["issuers"]
    e = cfg["SPCX"]
    assert e["status"] == "APPROVED" and "A + capex AI" in e["approved_by"] and e["approved_at"] == "2026-11-01"
    assert "0001628280-26-066880" in e["source"]
    seg = lt.issuer_segments_for("SPCX", cfg)
    assert seg["groups"] == {"industrials": 0.1212, "comm": 0.397, "tech": 0.4818, "ai_basket": 0.839}


SEGS = {"DEMOS": {"industrials": 0.1212, "comm": 0.397, "tech": 0.4818, "ai_basket": 0.839}}


def _measure(positions, segments):
    return rb.measure(positions, profiles={"DEMOS": {"sector": "Industrials"}, "DEMOI": {"sector": "Industrials"}, "DEMOT": {"sector": "Technology"}},
                      etf_lookthrough=None, stops=[], earnings={}, entries=[], event_symbols=[], today=TODAY, budget=rb.load_budget(), segments=segments)


def test_risk_budget_splits_a_segmented_issuer_across_sectors():
    book = [{"symbol": "DEMOS", "market_value": 30000.0}, {"symbol": "DEMOI", "market_value": 1000.0}, {"symbol": "CASH", "market_value": 33000.0, "is_cash": True}]
    old = _measure(book, {})
    assert old["drivers"]["single_sector_pct"] == ["Industrials"] and old["actual"]["single_sector_pct"] == pytest.approx(48.44, abs=0.01)
    new = _measure(book, SEGS)
    # tech 30000*0.4818 = 14454 of 64000 = 22.6%; Industrials now 3636 + 1000
    assert new["drivers"]["single_sector_pct"] == ["Technology"]
    assert new["actual"]["single_sector_pct"] == pytest.approx(22.58, abs=0.01)
    assert new["actual"]["ai_basket_pct"] == pytest.approx(39.33, abs=0.01)  # 30000 * 0.839 / 64000
    # growth: Technology + Communication Services segments (0.4818 + 0.397) of the position
    assert new["actual"]["growth_style_pct"] == pytest.approx(41.19, abs=0.01)
    assert "DEMOS" in new["drivers"]["growth_style_pct"]


def test_risk_budget_without_approved_segments_is_unchanged():
    book = [{"symbol": "DEMOT", "market_value": 500.0}, {"symbol": "DEMOI", "market_value": 500.0}]
    assert _measure(book, {}) == _measure(book, {"OTHER": {"tech": 1.0}})


def test_risk_budget_default_reads_the_approved_file():
    segs = rb.approved_segments()
    assert "SPCX" in segs and segs["SPCX"]["tech"] == 0.4818
    assert all(s == s.upper() for s in segs)


def test_segments_are_point_in_time():
    """Weights approved after the evaluation instant were not known then (review of #2460, follow-up 2)."""
    cfg = json.loads((ROOT / "config" / "issuer_segments.json").read_text())["issuers"]
    approved = date.fromisoformat(cfg["SPCX"]["approved_at"])
    assert lt.issuer_segments_for("SPCX", cfg, today=approved - timedelta(days=1)) is None
    assert lt.issuer_segments_for("SPCX", cfg, today=datetime(approved.year, approved.month, approved.day, 21, tzinfo=timezone.utc)) is not None
    before = lt.exposure_for("SPCX", ai_basket=[], profiles={"SPCX": {"sector": "Industrials"}}, fund_cfg={}, ipos={},
                             as_of=datetime(2026, 10, 30, 21, tzinfo=timezone.utc))
    assert before["groups"] == {"industrials": 1.0} and before["basis"].startswith("stock")
    assert rb.approved_segments(approved - timedelta(days=1)) == {} and "SPCX" in rb.approved_segments(approved)


def test_group_to_sector_is_derived_from_the_lookthrough_map():
    assert set(rb.GROUP_TO_SECTOR) == set(lt.SECTOR_TO_GROUP.values())
    for g, label in rb.GROUP_TO_SECTOR.items():
        assert lt.SECTOR_TO_GROUP[label.lower()] == g


def test_hedge_block_refuses_a_forbidden_key_without_asserts(monkeypatch):
    monkeypatch.setattr(ha, "HEDGE_FORBIDDEN", ("thresholds",))
    with pytest.raises(ValueError):
        ha.hedge(stoplights=_stoplights({"PSQ": "RED"}), momentum_rows=[], book_exposure=BE, defense_cfg=DEFENSE, today=TODAY)
