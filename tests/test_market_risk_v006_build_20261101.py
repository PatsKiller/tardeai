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


def test_hedge_state_green_keeps_the_bounce_day_rule():
    hs = dhs.hedge_state(stoplights=_stoplights({"PSQ": "GREEN"}), intent=None, bounce=("QQQ", 700.1, None),
                         tech_state="LAGGING", today=TODAY, stale_days=4)
    assert hs["state"] == "armed" and "QQQ ≥ $700.1" in hs["line"]
    hs = dhs.hedge_state(stoplights=_stoplights({"PSQ": "GREEN"}), intent=None, bounce=("QQQ", 700.1, TODAY.isoformat() + " 10:00"),
                         tech_state="LAGGING", today=TODAY, stale_days=4)
    assert hs["state"] == "entry_window_open"


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
BE = {"stressed_usd": 19241.13, "stressed_pct_book": 1.54, "stressed_pct_invested": 4.82}
MOMENTUM = [{"etf": "XLK", "sector": "Technology", "state": "LAGGING", "book_pct": 4.8}, {"etf": "XLV", "sector": "Healthcare", "state": "LEADING", "book_pct": 8.6}]


@pytest.mark.parametrize("thesis,verdict", [({"SH": "RED", "PSQ": "RED"}, "NOT_NOW"), ({"PSQ": "AMBER"}, "WATCH"), ({"PSQ": "GREEN"}, "CONSIDER")])
def test_hedge_verdict_from_the_stoplight_with_the_desks_config_thresholds(thesis, verdict):
    trans = [{"light": "THESIS", "new_state": list(thesis.values())[0], "created_at": "2031-03-07 17:55:02-05:00"}]
    h = ha.hedge(stoplights=_stoplights(thesis), momentum_rows=MOMENTUM, book_exposure=BE, defense_cfg=DEFENSE, today=TODAY, transitions=trans)
    assert h["verdict"] == verdict
    assert h["thresholds"]["trigger_book_pct"] == DEFENSE["inverse_etf"]["trigger_book_pct"]
    assert h["thresholds"]["materiality_exposure_pct"] == DEFENSE["inverse_stoplights"]["materiality_exposure_pct"]
    assert h["largest_weakening"] == {"label": "Technology", "pct_invested": 4.8} and h["lagging_count"] == 1
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
    r = ha.rotate(HEAT, leadership=None, momentum_rows=MOMENTUM, book_groups={"healthcare": {"usd": 34093.07}}, policy=POLICY,
                  sector_groups=[{"key": "healthcare", "kind": "sector", "symbols": ["XLV"]},
                                 {"key": "defensive", "kind": "defensive", "symbols": ["XLP", "XLV", "XLU"]}], as_of="2031-03-07")
    keys = [g["key"] for g in r["groups"]]
    assert keys == ["healthcare", "materials", "energy"]  # mean(rs1, rs5): 2.97, 2.76, 2.59
    assert "fin" not in keys and "disc" not in keys  # NEUTRAL; negative 1d
    assert r["groups"][0]["desk_state"] == "LEADING" and r["groups"][0]["usd"] == 34093.07
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
    f = ha.folded(heat, {"tech": {"usd": 19241}, "ai_basket": {"usd": 28.06}, "real_estate": {"usd": 1.2}}, POLICY)
    assert [x["key"] for x in f] == ["ai_basket", "real_estate"]
    assert POLICY["home_actions"]["sectors"]["fold_below_usd"] == 100


# ── Protect ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _item(sym, acct, kinds, usd, **facts):
    return {"symbol": sym, "account_label": acct, "kinds": kinds, "text": " · ".join(kinds), "usd": usd, "to": f"/risk?symbol={sym}",
            "pct_account": facts.get("pct_account"), "facts": {"value_usd": usd, **facts}}


def test_protect_clauses_are_built_from_facts_in_config_order():
    review = [
        _item("DEMOA", "Roth", ["stop_near"], 53233, pct_account=96.3, stop_distance_pct=3.6, groups={"financials": 1.0}),
        _item("DEMOA", "Rollover", ["no_stop"], 41117, pct_account=3.7, groups={"financials": 1.0}),
        _item("DEMOB", "Individual", ["no_stop"], 29498, pct_account=45.9, groups={"industrials": 1.0}),
        _item("DEMOC", "Rollover", ["stop_near"], 25980, pct_account=2.3, stop_distance_pct=4.5),
    ]
    budgets = [
        {"account_label": "Roth", "budget": "growth_style_pct", "limit": 50, "actual": 96.31, "actual_usd": 53232.5, "drivers": [{"name": "DEMOA", "usd": 53233}]},
        {"account_label": "Roth", "budget": "single_sector_pct", "limit": 30, "actual": 96.31, "actual_usd": 53232.5, "drivers": [{"name": "Financial Services", "usd": None}]},
        {"account_label": "Individual", "budget": "unprotected_pct", "limit": 10, "actual": 46.6, "actual_usd": 29938, "drivers": [{"name": "DEMOB", "usd": 29498}, {"name": "X", "usd": 128}]},
    ]
    reentry = {"DEMOB": {"wash_sale": {"state": "occurred", "account_label": "Individual", "rebuy_date": "2031-03-05"}}}
    p = ha.protect(review, budgets=budgets, reentry=reentry, overnight={"DEMOB"}, policy=POLICY)
    a, b, c = p["items"]
    assert a["consideration"] == ("stop 3.6% below last; one stock is 96% of the account, far above the 30% sector budget; "
                                  "with the Rollover position, $94,350 in DEMOA across 2 accounts")
    assert b["consideration"] == "no stop; with the Roth position, $94,350 in DEMOA across 2 accounts"
    assert c["consideration"] == "no stop; trades overnight now; 46.6% of the account unprotected vs the 10% budget"
    assert p["more"] == [{"symbol": "DEMOC", "account_label": "Rollover", "short": "stop 4.5% below last", "to": "/risk?symbol=DEMOC"}]
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


def test_daily_bars_use_ticker_prices_for_a_symbol_without_ohlcv_bars():
    tp = [{"symbol": "XLC", "price_date": date(2031, 3, d), "close_price": 100.0 + d, "source": "yfinance", "created_at": _et(2031, 3, d, 16, 7)}
          for d in (5, 6, 7)]
    conn = _Conn({"FROM market_ohlcv_bars": (["symbol"], []), "FROM ticker_prices": (["symbol", "price_date", "close_price", "source", "created_at"], tp)})
    r = rd.PgReader(lambda: conn)
    bars = r.daily_bars(["XLC"], sessions=10, end=_et(2031, 3, 7, 18))
    assert [(b["date"], b["close"]) for b in bars] == [("2031-03-05", 105.0), ("2031-03-06", 106.0), ("2031-03-07", 107.0)]
    assert all(b["source"] == "ticker_prices:yfinance" for b in bars)
    sql, params = next((s, p) for s, p in conn.log if "FROM ticker_prices" in s)
    assert "created_at <= %s" in sql  # as-of correct: a row written after `end` is not knowable
    assert params[-1] == _et(2031, 3, 7, 18)


def test_daily_bars_prefer_ohlcv_then_ticker_prices_and_skip_an_open_session():
    bcols = ["symbol", "bar_time", "open", "high", "low", "close", "volume", "source", "created_at"]
    bars = [{"symbol": "SPY", "bar_time": _et(2031, 3, 5, 0), "open": 1, "high": 2, "low": 0.5, "close": 680, "volume": 1, "source": "yfinance",
             "created_at": _et(2031, 3, 5, 17)}]
    tp = [{"symbol": "SPY", "price_date": date(2031, 3, d), "close_price": 600.0 + d, "source": "market_quotes", "created_at": _et(2031, 3, d, 16, 7)}
          for d in (5, 6, 7)]
    conn = _Conn({"FROM market_ohlcv_bars": (bcols, bars), "FROM ticker_prices": (["symbol", "price_date", "close_price", "source", "created_at"], tp)})
    out = rd.PgReader(lambda: conn).daily_bars(["SPY"], sessions=10, end=_et(2031, 3, 7, 12))
    assert [(b["date"], b["close"], b["source"]) for b in out] == [
        ("2031-03-05", 680.0, "market_ohlcv_bars:yfinance"),  # the bar wins over ticker_prices
        ("2031-03-06", 606.0, "ticker_prices:market_quotes"),
    ]  # 03-07 is still trading at 12:00 ET: no close yet


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
