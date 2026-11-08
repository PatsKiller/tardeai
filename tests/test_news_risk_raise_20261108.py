"""LQ-20261107-1239: weekend/overnight news and the futures/overseas prints reach the Home Risk card.

Part 1: lane ``news-risk-raise`` tags held / stopped-out / watchlist articles since the last close and raises the
material ones (market_event_candidates + catalyst_events). Part 2: the join reads futures + overseas index levels
from ``market_quotes_extended`` and the held-name news from ``catalyst_events`` into two additive blocks.

Synthetic data only (public repo). No database, no network: every read is a test double, and the pure functions are
driven with dicts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts import news_risk_raise as nrr
from scripts.lib import market_risk_book_dollars as bd
from scripts.lib import market_risk_book_join as bj
from scripts.lib import market_risk_home_actions as ha
from scripts.lib.market_risk.policy import load_policy

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
POLICY = load_policy()
#: Sunday 2026-11-08 16:45 ET — the operator's "as of now" for this task.
SUNDAY = datetime(2026, 11, 8, 16, 45, tzinfo=ET)
FRIDAY_CLOSE = datetime(2026, 11, 6, 16, 0, tzinfo=ET)


# ── the window ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_last_close_is_fridays_close_on_a_weekend_and_the_shared_calendar_decides():
    assert nrr.last_close(SUNDAY) == FRIDAY_CLOSE
    # the floor is the CLOSE, not midnight: Friday 16:00-24:00 articles are in the window
    assert nrr.last_close(SUNDAY).astimezone(ET).hour == 16
    # a Wednesday after the close looks back to that Wednesday, not to last Friday
    assert nrr.last_close(datetime(2026, 11, 11, 20, 0, tzinfo=ET)).astimezone(ET).date().isoformat() == "2026-11-11"


def test_a_missing_policy_file_is_a_named_abort_not_a_silent_default(tmp_path):
    with pytest.raises(SystemExit) as exc:
        nrr.load_policy(tmp_path / "absent.json")
    assert "NewsRiskRaisePolicy@v1" in str(exc.value) or "unreadable" in str(exc.value)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "something-else"}))
    with pytest.raises(SystemExit):
        nrr.load_policy(bad)


# ── scope ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_ticker_rejects_cusip_placeholders_and_spaces():
    assert nrr.ticker("nvda") == "NVDA"
    assert nrr.ticker("BRK.B") == "BRK.B"
    assert nrr.ticker("543354104") is None  # a CUSIP is not a ticker
    assert nrr.ticker(" AAPL ") == "AAPL"
    for junk in (None, "", "  ", "TOO LONG NAME", "$SPX"):
        assert nrr.ticker(junk) is None, junk


def test_held_is_never_also_stopped_out():
    scope = nrr.build_scope(["NVDA", "nvda"], ["NVDA", "PFE"], ["NVDA", "V", "V"])
    assert scope == {"NVDA": ["held"], "PFE": ["stopped_out"], "V": ["watchlist"]}


# ── materiality: the lane and the card read the same scale ───────────────────────────────────────────────────────
def test_lane_and_card_agree_on_what_is_material():
    lane = {str(s).lower() for s in nrr.load_policy().get("material_severities")}
    card = {str(s).lower() for s in (POLICY["home_review"]["material_news"]["severities"])}
    assert lane == card == {"high", "critical"}


def test_unclassified_article_uses_the_canonical_keyword_map_and_weights():
    ctype, sev = nrr.classify_untagged("Acme wins contract for defense work", None)
    assert ctype == "contract_win" and sev == "medium"  # 0.70 on the canonical weight scale
    # the same keyword map news-to-catalyst uses: a known type never degrades to "other"
    assert nrr.classify_untagged("Acme beats estimates", None)[0] == "earnings_beat"
    assert nrr.classify_untagged("something entirely unremarkable", None) == ("other", "low")


# ── plan: tag everything scoped, raise only what is material ────────────────────────────────────────────────────
ARTICLES = [
    {"id": 1, "symbol": "NVDA", "title": "NVDA merger closes", "summary": None,
     "published_at": "2026-11-08T03:36:00+00:00", "created_at": "2026-11-08T03:37:00+00:00"},
    {"id": 2, "symbol": "V", "title": "V raises guidance", "summary": None,
     "published_at": "2026-11-06T18:38:00+00:00", "created_at": "2026-11-06T18:39:00+00:00"},
    {"id": 3, "symbol": "SCHD", "title": "SCHD dividend increase announced", "summary": None,
     "published_at": "2026-11-07T10:35:00+00:00", "created_at": "2026-11-07T10:36:00+00:00"},
    {"id": 4, "symbol": "ANET", "title": "ANET unveils a switch", "summary": None,
     "published_at": "2026-11-07T12:00:00+00:00", "created_at": "2026-11-07T12:01:00+00:00"},
]
SCOPE = {"NVDA": ["held"], "V": ["watchlist"], "SCHD": ["held"]}
CATALYST = {
    "1": {"catalyst_type": "merger_acquisition", "severity": "high"},   # already classified: the row decides
    "2": {"catalyst_type": "guidance_raise", "severity": "critical"},
    "3": {"catalyst_type": "dividend_increase", "severity": "medium"},  # scoped, not material
}


def test_every_scoped_article_is_tagged_and_a_canonical_row_decides_severity():
    tagged, raised = nrr.plan_raises(ARTICLES, CATALYST, SCOPE, nrr.load_policy())
    assert [r["news_id"] for r in tagged] == [1, 2, 3]  # ANET is not in scope at all
    assert {r["news_id"]: r["classification_basis"] for r in tagged}[1] == "catalyst_events"
    assert [r["news_id"] for r in raised] == [2, 1]  # critical before high
    assert all(r["material"] for r in raised) and 3 not in [r["news_id"] for r in raised]


def test_an_article_with_no_catalyst_row_is_classified_once_and_marked_as_such():
    tagged, raised = nrr.plan_raises([ARTICLES[3]], {}, {"ANET": ["held"]}, nrr.load_policy())
    assert tagged[0]["classification_basis"] == "news_to_catalyst_keywords"
    assert tagged[0]["catalyst_type"] == "other" and raised == []


def test_tag_payload_is_utc_stamped_and_names_its_writer():
    row = {"scopes": ["held"], "material": True, "catalyst_type": "contract_win", "severity": "high"}
    p = nrr.tag_payload(row, now=SUNDAY, writer="news-risk-raise")
    assert p["kind"] == "risk_scope" and p["writer"] == "news-risk-raise" and p["scopes"] == ["held"]
    assert p["tagged_at"].endswith("Z") and p["severity"] == "high"


# ── the lane run: dry is read-only and writes nothing ───────────────────────────────────────────────────────────
class _Cur:
    """A cursor double that answers by statement shape and records every statement it is given."""

    def __init__(self, log: list[str], results: dict[str, list]):
        self.log = log
        self.results = results
        self._rows: list = []
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.log.append(" ".join(str(sql).split()))
        s = " ".join(str(sql).split())
        for needle, rows in self.results.items():
            if needle in s:
                self._rows = list(rows)
                return
        self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _Conn:
    def __init__(self, results: dict[str, list]):
        self.log: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self._results = results

    def cursor(self):
        return _Cur(self.log, self._results)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE")


def _lane_conn(articles=None, stopped=("PFE",), watch=("V",)):
    return _Conn({
        "FROM trade_closed": [(s,) for s in stopped],
        "FROM watchlist_items": [(s,) for s in watch],
        "FROM news_articles": [(a["id"], a["symbol"], a["title"], a["summary"], a["published_at"], a["created_at"])
                               for a in (ARTICLES if articles is None else articles)],
        "FROM catalyst_events": [("1", "merger_acquisition", "high"), ("2", "guidance_raise", "critical"),
                                 ("3", "dividend_increase", "medium")],
        "FROM market_event_episodes": [("broad_selloff:market:2026-11-04",)],
    })


STORE = {"holdings": [{"symbol": "NVDA", "account": "a1"}, {"symbol": "CASH", "account": "a1", "is_cash": True}]}


def test_dry_run_is_the_default_and_executes_no_write():
    conn = _lane_conn()
    out = nrr.run(SUNDAY, apply=False, policy=nrr.load_policy(), connect=lambda: conn, store_loader=lambda: STORE)
    assert out["mode"] == "DRY" and out["since"] == FRIDAY_CLOSE.isoformat()
    assert out["articles_seen"] == 4 and out["tagged"] == 2 and out["raised"] == 2
    assert out["scopes"] == {"held": 1, "stopped_out": 1, "watchlist": 1}
    assert out["produced_count"] == 2 and out["episode_id"] == "broad_selloff:market:2026-11-04"
    assert not [s for s in conn.log if s.split(" ")[0] in WRITE_PREFIXES]
    assert conn.commits == 0 and conn.rollbacks == 1


def test_apply_tags_raises_the_unclassified_and_never_overwrites_a_canonical_catalyst():
    conn = _lane_conn()
    out = nrr.run(SUNDAY, apply=True, policy=nrr.load_policy(), connect=lambda: conn, store_loader=lambda: STORE)
    writes = [s for s in conn.log if s.split(" ")[0] in WRITE_PREFIXES]
    # one tag statement per scoped article, and the tag statement replaces this writer's own previous entry
    tag_sql = [s for s in writes if s.startswith("UPDATE news_articles")]
    assert len(tag_sql) == 2 and "e->>'kind'" in tag_sql[0] and "e->>'writer'" in tag_sql[0]
    # catalysts exist for both raised articles' news ids, so this lane inserts none of them
    assert not [s for s in writes if s.startswith("INSERT INTO catalyst_events")]
    # provenance-only candidates: one per raised (episode, symbol), ON CONFLICT DO NOTHING
    cand = [s for s in writes if s.startswith("INSERT INTO market_event_candidates")]
    assert len(cand) == 2 and all("ON CONFLICT (episode_id, symbol) DO NOTHING" in s for s in cand)
    assert out["applied"]["tagged"] == 2 and out["applied"]["candidates"] == 2 and conn.commits == 1


def test_hours_override_is_explicit_and_moves_the_floor():
    conn = _lane_conn(articles=[])
    out = nrr.run(SUNDAY, apply=False, hours=6, policy=nrr.load_policy(), connect=lambda: conn,
                  store_loader=lambda: STORE)
    since = datetime.fromisoformat(out["since"])
    assert since == SUNDAY - timedelta(hours=6)  # the same instant, in whatever zone it was formed
    assert out["produced_count"] == 0


def test_a_disabled_policy_refuses_before_any_connection():
    pol = {**nrr.load_policy(), "enabled": False}

    def boom():
        raise AssertionError("must not connect when the lane is disabled")

    out = nrr.run(SUNDAY, apply=False, policy=pol, connect=boom, store_loader=lambda: STORE)
    assert out["mode"] == "REFUSED" and out["reason"] == "disabled_by_config"


def test_a_refused_apply_writes_no_receipt(monkeypatch):
    calls = []
    monkeypatch.setattr(nrr, "run", lambda *a, **k: {"mode": "REFUSED", "reason": "disabled_by_config",
                                                     "produced_count": 0})
    monkeypatch.setattr(nrr, "_write_receipt", lambda out, started: calls.append(out))
    assert nrr.main(["--apply", "--json"]) == 0
    assert calls == []  # nothing was written, so no receipt may claim a run


def test_the_receipt_refuses_to_invent_a_count():
    import pytest

    with pytest.raises(KeyError):
        nrr._write_receipt({"mode": "APPLY"}, "2026-11-08T00:00:00+00:00")


# ── the card: held-name news ────────────────────────────────────────────────────────────────────────────────────
class _JoinCur:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self._rows

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _JoinConn:
    def __init__(self, rows, fail=False):
        self._rows, self._fail = rows, fail
        self.rolled = 0

    def cursor(self):
        if self._fail:
            raise RuntimeError("boom")
        return _JoinCur(self._rows)

    def rollback(self):
        self.rolled += 1


def test_material_news_keeps_the_worst_severity_and_the_latest_article():
    rows = [("SPCX", "contract_win", "high", "2026-11-07 10:01:00+00"),
            ("SPCX", "analyst_upgrade", "high", "2026-11-08 09:00:00+00"),
            ("V", "earnings_beat", "critical", "2026-11-06 18:38:00+00")]
    news = bj.material_news(_JoinConn(rows), POLICY, SUNDAY, ["SPCX", "V", "nvda"])
    assert news["SPCX"]["count"] == 2 and news["SPCX"]["latest"].startswith("2026-11-08")
    assert news["V"]["severity"] == "critical"
    assert "NVDA" not in news  # no material row: no block item


def test_a_failed_news_read_is_an_empty_map_never_a_failed_card():
    conn = _JoinConn([], fail=True)
    assert bj.material_news(conn, POLICY, SUNDAY, ["NVDA"]) == {}
    assert conn.rolled == 1  # the aborted transaction is cleared, not left open


def test_a_failed_news_read_is_stated_on_the_card_and_never_looks_like_no_news():
    # "no material news" and "the read failed" must not render the same (taxonomy #2: unknown vs confident)
    gaps = []
    assert bj.material_news(_JoinConn([], fail=True), POLICY, SUNDAY, ["NVDA"], gaps=gaps) == {}
    assert gaps == [{"reason": "read_failed: RuntimeError"}]
    block = bj.material_news_block({}, SUNDAY, POLICY, gaps=gaps)
    assert block["items"] == [] and block["gaps"] == gaps
    assert bj.material_news_block({}, SUNDAY, POLICY)["gaps"] == []  # a clean read says nothing


def test_an_unresolvable_window_is_a_gap_not_a_silent_none(monkeypatch):
    def boom(_name):
        raise ImportError("no sessions module")

    monkeypatch.setattr(bj, "_import", boom)
    block = bj.material_news_block({"V": {"count": 1, "catalyst_type": "other", "severity": "high", "latest": "x"}},
                                   SUNDAY, POLICY)
    assert block["since"] is None and block["gaps"] and block["gaps"][0]["reason"].startswith("window_unresolved")


def test_material_news_block_is_bounded_severity_first_and_states_its_floor():
    news = {f"S{i}": {"count": 1, "catalyst_type": "other", "severity": "high", "latest": "x"} for i in range(5)}
    news["V"] = {"count": 3, "catalyst_type": "earnings beat", "severity": "critical", "latest": "y"}
    block = bj.material_news_block(news, SUNDAY, POLICY)
    assert block["schema"] == "MaterialNews@v1"
    assert block["since"].startswith("2026-11-06T16:00")
    assert [i["symbol"] for i in block["items"]][:1] == ["V"]
    assert len(block["items"]) == POLICY["home_review"]["material_news"]["max_items"]
    off = {**POLICY, "home_review": {**POLICY["home_review"], "material_news": {"enabled": False}}}
    assert bj.material_news_block(news, SUNDAY, off)["items"] == []


# ── the card: futures + overseas levels ─────────────────────────────────────────────────────────────────────────
def test_overnight_markets_reads_the_configured_futures_and_indices():
    rows = [
        ("/NQ", "futures_open", "2026-11-01", 25400.25, None, "none_level_only_no_dated_reference_in_payload",
         None, SUNDAY),
        ("$SPX", "overnight", "2026-11-06", 6712.5, 0.8, "schwab_quote_close_price_settle_dated",
         "2026-11-06", SUNDAY),
    ]
    out = bj.overnight_markets(_JoinConn(rows), SUNDAY, POLICY)
    assert out["schema"] == "OvernightMarkets@v1"
    by = {i["symbol"]: i for i in out["items"]}
    assert by["/NQ"]["label"] == "Nasdaq 100 futures" and by["/NQ"]["level_only"] is True
    assert by["/NQ"]["change_pct"] is None
    assert by["$SPX"]["label"] == "S&P 500" and by["$SPX"]["level_only"] is False
    assert by["$SPX"]["change_pct"] == 0.8
    assert by["/NQ"]["stale"] is False  # the print is the snapshot instant here


def test_a_failed_overnight_read_is_a_stated_gap():
    out = bj.overnight_markets(_JoinConn([], fail=True), SUNDAY, POLICY)
    assert out["items"] == [] and out["gaps"] and out["gaps"][0]["reason"].startswith("read_failed")


def test_a_configured_symbol_with_no_print_is_named_not_silently_absent():
    rows = [("/NQ", "futures_open", "2026-11-01", 25400.25, None, "none_level_only_no_dated_reference_in_payload",
             None, SUNDAY)]
    out = bj.overnight_markets(_JoinConn(rows), SUNDAY, POLICY)
    gap = next(g["reason"] for g in out["gaps"] if g["reason"].startswith("no_recent_print:"))
    named = set(gap.split(": ", 1)[1].split(","))
    assert "/NQ" not in named and "/ES" in named and "$SPX" in named
    # every symbol the config asks for is either an item or named in the gap: nothing vanishes
    assert {i["symbol"] for i in out["items"]} | named == set(
        __import__("yaml").safe_load((ROOT / "config" / "market_risk_offhours_quotes.yaml").read_text())["schwab"]["futures"]
        + __import__("yaml").safe_load((ROOT / "config" / "market_risk_offhours_quotes.yaml").read_text())["schwab"]["indices"])


def test_the_offhours_config_lists_every_symbol_it_can_actually_deliver():
    """LQ-20261107-1264 measured that no overseas index is available to this lane (Schwab does not return one; Finviz
    publishes no foreign index level). They are therefore NOT configured: they would add four permanent refusals to
    every receipt. The card's honest source is an ETF proxy labelled ``etf_derived``."""
    import yaml

    schwab = yaml.safe_load((ROOT / "config" / "market_risk_offhours_quotes.yaml").read_text())["schwab"]
    assert set(schwab["futures"]) >= {"/ES", "/NQ", "/YM", "/RTY"}
    assert set(schwab["indices"]) >= {"$SPX", "$COMPX", "$VIX"}
    assert not {i for i in schwab["indices"] if i in {"$NIKKEI", "$DAX", "$FTSE", "$HSI"}}
    assert all(s in schwab["labels"] for s in schwab["futures"] + schwab["indices"])


# ── the card: the review item and the Protect clause it builds ────────────────────────────────────────────────
STORE_HOME = {
    "data_as_of": "2026-11-06",
    "portfolio_totals": {"total_value": 100_000.0},
    "holdings": [{"symbol": "SPCX", "account": "a1", "market_value": 40_000.0, "shares": 100, "price": 400.0}],
}
PROJ_HOME = {
    "heatmap": [{"key": "tech", "kind": "sector", "state": "STRESS"}],
    "positions": {"SPCX": {"label": "hold", "look_through": {"groups": {"tech": 1.0}, "basis": "stock"}}},
    "book": {"budgets": []},
}
NEWS = {"SPCX": {"count": 2, "catalyst_type": "contract win", "severity": "high", "latest": "2026-11-07T10:01"}}


def _built(news=NEWS):
    # a resting stop 25% below is neither "stop near" nor "no stop": the item's page target stays the prospectus
    return bd.build(PROJ_HOME, STORE_HOME, stops=[{"account": "a1", "symbol": "SPCX", "stop_price": 300.0}],
                    policy=POLICY, label_fn=lambda k: "Acct One", canon_fn=str, material_news=news)


def test_material_news_becomes_a_review_item_carrying_its_facts():
    review = _built()["review"]
    item = next(i for i in review if i["symbol"] == "SPCX")
    assert "material_news" in item["kinds"]
    assert item["usd"] == 40_000.0 and item["to"] == "/prospectus/SPCX"
    assert item["facts"]["news_count"] == 2 and item["facts"]["news_type"] == "contract win"
    assert item["facts"]["news_severity"] == "high"
    assert "material news since the last close: contract win (2 articles)" in item["text"]


def test_no_news_key_means_no_news_item_and_the_rest_of_the_card_is_unchanged():
    without = {i["symbol"]: set(i["kinds"]) for i in _built(news=None)["review"]}
    with_news = {i["symbol"]: set(i["kinds"]) for i in _built()["review"]}
    assert "material_news" not in without["SPCX"]
    assert with_news["SPCX"] - {"material_news"} == without["SPCX"]


def test_protect_renders_the_clause_from_the_facts_not_the_prose():
    review = _built()["review"]
    out = ha.protect(review, budgets=[], reentry={}, overnight=None, policy=POLICY)
    clauses = {c["key"]: c["text"] for it in out["items"] for c in it["clauses"]}
    assert clauses["material_news"] == "news since the last close: contract win"


# ── the join hands both blocks to the API ──────────────────────────────────────────────────────────────────────
def test_join_returns_the_two_new_blocks_even_when_the_db_is_unreachable():
    def stalled(**kw):
        raise TimeoutError("connect timeout expired")

    proj = {"state": "evaluated", "as_of": "2026-11-06T21:00:00+00:00", "mode": "shadow"}
    out = bj.join(proj, get_conn=stalled, store=STORE_HOME, policy=POLICY, budgets=[])
    assert out["material_news"]["schema"] == "MaterialNews@v1"
    assert out["overnight_markets"]["gaps"] == [{"reason": "db_unavailable"}]
    assert out["material_news"]["items"] == []
    # the news read never ran either: the block names that, so an empty list is never read as "no news"
    assert out["material_news"]["gaps"] == [{"reason": "db_unavailable"}]


def test_the_two_blocks_are_additive_keys_on_the_joined_payload():
    out = bj.join({"state": "not_evaluated", "as_of": None}, store=STORE_HOME, policy=POLICY, budgets=[])
    # a projection that was never evaluated is returned untouched: no block, no error, nothing invented
    assert "material_news" not in out and "overnight_markets" not in out
