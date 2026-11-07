#!/usr/bin/env python3
"""LQ-20261107-52 — finviz proactive research tells the truth.

Three defects, each pinned here so the old behaviour cannot come back:

A. ``news_symbol_guard`` derived the issuer's name from the first comma clause of
   ``symbol_profiles.description_1s``. That column holds a PARAGRAPH ("NVIDIA Corporation operates as a
   data center scale AI infrastructure company in the United States ..."), so for NVDA / AAPL / V the
   "alias" was the whole sentence and never matched the word "Nvidia" / "Apple" / "Visa" a headline
   actually uses. The health agent's auto-remediation then purged truthful rows: 23 on 2026-11-06 in the
   ``db_retention/news_articles/*-symbol_guard_news-*`` archives, 15 of them NVIDIA's own headlines.
B. The lane wrote the TICKER into ``news_articles.strategy_type`` (440 rows), a column topic_curator,
   the iris taxonomy and rag_retrieval key on as a strategy classification.
C. The universe was ``holdings + watchlist-ordered-alphabetically`` cut at ``--max``, so with 5,678
   watchlist symbols and a 400 cap nothing after "ALPX" was ever covered.

Fixtures are synthetic (the repo is public); the description paragraphs are the public company text the
DB returns today.
"""
from __future__ import annotations

import gzip
import json
import inspect
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import news_symbol_guard  # noqa: E402

_company_tokens = news_symbol_guard._company_tokens
purge_mismatched_for_symbol = news_symbol_guard.purge_mismatched_for_symbol
# The provider-tag vocabulary does not exist before this fix. Reading it tolerantly keeps the assertions
# behavioural instead of turning every one of them into an ImportError on the old code.
PROVIDER_TAGGED_SOURCES = getattr(news_symbol_guard, "PROVIDER_TAGGED_SOURCES", frozenset())
_ACCEPTED_KWARGS = set(inspect.signature(news_symbol_guard.headline_matches_symbol).parameters)


def _match(symbol, title, summary="", **kwargs):
    """Call the guard, dropping keyword arguments the old signature does not know (the old code then
    simply cannot honour them, which is exactly what the assertion reports)."""
    return news_symbol_guard.headline_matches_symbol(
        symbol, title, summary, **{k: v for k, v in kwargs.items() if k in _ACCEPTED_KWARGS})

NVDA_DESC = ("NVIDIA Corporation operates as a data center scale AI infrastructure company in the United "
             "States, Japan, Taiwan, China, and internationally.")
AAPL_DESC = ("Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, "
             "wearables, and accessories worldwide.")
V_DESC = ("Visa Inc. operates as a payment technology company in the United States and internationally.")
SPCX_DESC = ("Space Exploration Technologies Corp. provides satellite-based broadband services in the "
             "United States.")
NVDA_HEADLINE = "Nvidia is the top performer in the Dow as the blue-chip stock index turns higher"
AAPL_HEADLINE = "Apple's autocomplete restrictions include 'Dictator Trump,' researcher finds"
V_HEADLINE = "Visa rises after a quarterly beat on cross-border volume"
SPCX_HEADLINE = "SpaceX government contracts to be under 10% of revenue, Musk says"


# ── A. the alias derivation ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("symbol,desc,headline", [
    ("NVDA", NVDA_DESC, NVDA_HEADLINE),
    ("AAPL", AAPL_DESC, AAPL_HEADLINE),
    ("V", V_DESC, V_HEADLINE),
])
def test_company_name_from_a_paragraph_description_is_recognised(symbol, desc, headline):
    """Old code: alias = the first comma clause ("NVIDIA Corporation operates as a data center scale AI
    infrastructure company in the United States") -> no match -> the row was purged."""
    ok, reason = _match(symbol, headline, company_description=desc)
    assert ok, reason
    assert reason == "company_name"


def test_alias_is_the_issuer_not_the_sentence():
    assert "nvidia" in _company_tokens(NVDA_DESC)
    assert "apple" in _company_tokens(AAPL_DESC)
    assert "visa" in _company_tokens(V_DESC)
    # the paragraph, not the name, must never become an alias
    assert not any("operates as a data center" in t for t in _company_tokens(NVDA_DESC))


def test_multiword_name_does_not_yield_a_generic_first_word():
    """"Space Exploration Technologies" must not degrade to the alias "space", which would attach every
    space-adjacent headline to SPCX."""
    assert "space" not in _company_tokens(SPCX_DESC)
    ok, reason = _match("SPCX", SPCX_HEADLINE, company_description=SPCX_DESC)
    assert not ok
    assert reason == "no_symbol_or_company_match"


def test_legacy_comma_name_still_works():
    ok, reason = _match(
        "NFLX", "Netflix adds subscribers", company_description="Netflix, Inc. provides entertainment services.")
    assert ok and reason == "company_name"


# ── A2. a provider tag is evidence, and a contradiction still wins ────────────────────────────────────

def test_provider_tagged_row_without_name_evidence_is_kept():
    assert "finviz_news" in PROVIDER_TAGGED_SOURCES
    ok, reason = _match("SPCX", SPCX_HEADLINE, company_description=SPCX_DESC,
                                         provider_tagged=True)
    assert ok, "the feed listed SPCX for this article; silence in the text is not a wrong tag"
    assert reason == "provider_tag"


def test_provider_tag_still_rejects_a_contradicted_52_week_level():
    ok, reason = _match(
        "XYZ", "XYZ stock hits 52-week high at 27.99 USD",
        reference_52w=(4.0, 6.0), provider_tagged=True)
    assert not ok
    assert reason.startswith("price_conflict_52w")


def test_provider_tag_still_rejects_a_foreign_issuer():
    ok, reason = _match(
        "MRLN", "What to Know About Pasqal, the Quantum Start-Up Going Public Soon", provider_tagged=True)
    assert not ok and reason.startswith("foreign_company")


def test_a_yahoo_row_with_no_evidence_is_still_rejected():
    ok, reason = _match("SPCX", SPCX_HEADLINE, company_description=SPCX_DESC)
    assert not ok and reason == "no_symbol_or_company_match"


# ── A3. the purge honours the row's own source ────────────────────────────────────────────────────────

class _StubCursor:
    def __init__(self, description, news_rows, catalyst_rows=()):
        self.description = description
        self.news_rows = list(news_rows)
        self.catalyst_rows = list(catalyst_rows)
        self._result = []

    def execute(self, sql, params=()):
        low = " ".join(sql.split()).lower()
        if "from symbol_profiles" in low:
            self._result = [(self.description,)] if self.description else []
        elif "from news_articles" in low:
            assert "source" in low, "the purge must read the row's source to decide the provider tag"
            self._result = list(self.news_rows)
        elif "from catalyst_events" in low:
            assert "source" in low
            self._result = list(self.catalyst_rows)
        else:  # pragma: no cover - a query this test did not expect
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


class _StubConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):  # pragma: no cover - apply=False in every assertion here
        pass


def test_purge_keeps_a_provider_tagged_row_and_removes_an_unverifiable_yahoo_one():
    cur = _StubCursor(
        NVDA_DESC,
        news_rows=[(1, NVDA_HEADLINE, "", "finviz_news"),        # provider tag -> keep
                   (2, "Something entirely unrelated", "", "yahoo_rss")],  # no tag, no evidence -> remove
    )
    out = purge_mismatched_for_symbol(_StubConn(cur), "NVDA", apply=False)
    assert out["news_removed"] == 1, out
    assert out["symbol"] == "NVDA"


def test_purge_removes_a_provider_row_whose_headline_contradicts_the_book():
    cur = _StubCursor(NVDA_DESC, news_rows=[(3, "Something entirely unrelated", "", "finviz_news")])
    # A provider-tagged row with no textual evidence is KEPT; this asserts the same call path reaches the
    # contradiction branch through purge (the foreign-issuer veto runs before the provider tag).
    cur.news_rows = [(3, "What to Know About Pasqal, the Quantum Start-Up", "", "finviz_news")]
    out = purge_mismatched_for_symbol(_StubConn(cur), "NVDA", apply=False)
    assert out["news_removed"] == 1, out


# ── B. the lane never writes the ticker as a strategy class ───────────────────────────────────────────

def _install_fake_lane_deps(monkeypatch, captured):
    import finviz_proactive_research as lane

    fake_news = types.ModuleType("finviz_news")
    fake_news.fetch_finviz_stock_news_all = lambda lookback_hours=12: [
        {"headline": NVDA_HEADLINE, "url": "https://example.invalid/a", "tickers": ["NVDA"], "datetime": 1},
    ]
    scoring = types.ModuleType("content_scoring")
    scoring.score_content = lambda **kw: {"relevance_score": 0.5}
    scoring.tag_content = lambda **kw: {"strategy_tags": ["ai"], "agent_tags": []}
    policy = types.ModuleType("hermes_source_policy")
    policy.should_ingest = lambda source: (True, "ok")

    class _Receipt:
        rows_written = 1

    def _write(cur, rows, **kw):
        captured.extend(rows)
        return _Receipt()

    monkeypatch.setitem(sys.modules, "finviz_news", fake_news)
    monkeypatch.setitem(sys.modules, "content_scoring", scoring)
    monkeypatch.setitem(sys.modules, "hermes_source_policy", policy)
    monkeypatch.setattr(lane, "write_news_articles", _write)
    monkeypatch.setattr(lane, "is_duplicate", lambda *a, **k: False)
    monkeypatch.setattr(lane, "_get_conn", lambda: _FakeConn())
    monkeypatch.setattr(lane, "_universe", lambda cur, max_n, **kw: (["NVDA"], {
        "holdings": 1, "holdings_used": 1, "holdings_source": "positions_current",
        "watchlist_available": 0, "watchlist_used": 0, "truncated": 0,
        "selection": "staleness_first", "window_asked_at": None, "next_in_line": None}))
    return lane


class _FakeConn:
    def cursor(self):
        return types.SimpleNamespace(execute=lambda *a, **k: None, fetchall=lambda: [], fetchone=lambda: None)

    def commit(self):
        pass

    def rollback(self):  # pragma: no cover
        pass

    def close(self):
        pass


def test_writer_does_not_send_the_ticker_as_strategy_type(monkeypatch, tmp_path):
    captured: list[dict] = []
    # a LIVE run records its sweep cursor; keep it in the test's own state root, never the live one
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    lane = _install_fake_lane_deps(monkeypatch, captured)
    rc = lane.run(max_n=5, lookback_hours=12, dry_run=False, summary={})
    assert rc == 0
    assert captured, "the lane must have written the synthetic headline"
    row = captured[0]
    assert "strategy_type" not in row, "strategy_type is a strategy class, never the ticker"
    assert row["symbol"] == "NVDA"


# ── C. the universe: DB-first holdings, never truncated, rotating watchlist ───────────────────────────

class _UniverseCursor:
    def __init__(self, watchlist):
        self.watchlist = list(watchlist)

    def execute(self, sql, params=()):
        assert "watchlist_items" in sql

    def fetchall(self):
        return [(s,) for s in self.watchlist]


def test_holdings_are_never_truncated_by_the_cap(monkeypatch):
    import finviz_proactive_research as lane
    monkeypatch.setattr(lane, "_holdings_symbols", lambda: (["NVDA", "SPCX", "AAPL", "V"], "positions_current"))
    symbols, stats = lane._universe(_UniverseCursor(["AAA", "BBB", "CCC"]), 5)
    assert symbols[:4] == ["NVDA", "SPCX", "AAPL", "V"]
    assert stats["holdings"] == 4 and stats["holdings_used"] == 4
    assert stats["watchlist_used"] == 1 and stats["truncated"] == 2


def test_a_holdings_only_book_smaller_than_the_cap_never_crashes(monkeypatch):
    import finviz_proactive_research as lane
    monkeypatch.setattr(lane, "_holdings_symbols", lambda: (["NVDA"], "positions_current"))
    symbols, stats = lane._universe(_UniverseCursor([]), 400)
    assert symbols == ["NVDA"] and stats["truncated"] == 0


def test_a_cusip_holding_is_reported_not_counted_as_research_coverage(monkeypatch):
    """"543354104" is a real holding identifier and can never be a Finviz ticker; counting it as held
    coverage would overstate the book by three names (measured 2026-11-07: 26 held, 23 researchable)."""
    import finviz_proactive_research as lane
    monkeypatch.setattr(lane, "_holdings_symbols",
                        lambda: (["NVDA", "543354104", "BRK.B"], "positions_current"))
    symbols, stats = lane._universe(_UniverseCursor([]), 400)
    assert symbols == ["NVDA", "BRK.B"]
    assert stats["holdings"] == 2 and stats["held_without_ticker"] == 1
    assert stats["held_without_ticker_sample"] == ["543354104"]


def test_the_watchlist_window_advances_so_the_alphabet_tail_is_reached(monkeypatch):
    """LQ-20261107-211 superseded the hour rotation this case used to pin: the window now advances by the
    symbols a run actually asked about (never-asked first), so two runs never repeat a window."""
    import finviz_proactive_research as lane
    monkeypatch.setattr(lane, "_holdings_symbols", lambda: ([], "positions_current"))
    watch = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    first, s0 = lane._universe(_UniverseCursor(watch), 3)
    asked = {s: lane._as_utc("2026-11-07T15:30:00+00:00") for s in first}
    later, s1 = lane._universe(_UniverseCursor(watch), 3, attempts=asked)
    assert first == ["AAA", "BBB", "CCC"] and s0["next_in_line"] == "DDD"
    assert later == ["DDD", "EEE", "FFF"] and s1["selection"] == "staleness_first"


def test_holdings_come_from_the_db_document_first(monkeypatch):
    import finviz_proactive_research as lane
    doc = {"document_source": "positions_current",
           "holdings": [{"symbol": "NVDA"}, {"symbol": "cash", "is_cash": True}, {"symbol": "V"}]}
    fake = types.SimpleNamespace(load_document=lambda: doc)
    monkeypatch.setitem(sys.modules, "lib.holdings_document", fake)
    syms, source = lane._holdings_symbols()
    assert syms == ["NVDA", "V"], "cash rows are not research symbols"
    assert source == "positions_current"


def test_an_unreadable_document_falls_back_to_the_file_and_says_so(monkeypatch, tmp_path):
    import finviz_proactive_research as lane

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setitem(sys.modules, "lib.holdings_document", types.SimpleNamespace(load_document=_boom))
    (tmp_path / "data" / "portfolios" / "state").mkdir(parents=True)
    # nosemgrep: tq-py-nonatomic-store-write -- synthetic fixture inside pytest's tmp_path, not a live store
    (tmp_path / "data" / "portfolios" / "state" / "holdings.json").write_text(
        json.dumps({"holdings": [{"symbol": "aapl"}]}))
    monkeypatch.setattr(lane, "ROOT", tmp_path)
    syms, source = lane._holdings_symbols()
    assert syms == ["AAPL"]
    assert source.startswith("holdings_json_fallback:")


def test_neither_document_nor_file_is_reported_unavailable_not_as_an_empty_book(monkeypatch, tmp_path):
    import finviz_proactive_research as lane

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setitem(sys.modules, "lib.holdings_document", types.SimpleNamespace(load_document=_boom))
    monkeypatch.setattr(lane, "ROOT", tmp_path)  # no file at all
    syms, source = lane._holdings_symbols()
    assert syms == []
    assert source.startswith("holdings_unavailable:")


# ── D. the repair of the rows already written: dry by default, archive before it writes ──────────────

class _RepairCursor:
    def __init__(self, rows_by_table, log):
        self.rows_by_table = rows_by_table
        self.log = log
        self._result = []
        self.rowcount = 0

    def execute(self, sql, params=()):
        self.log.append((" ".join(sql.split()), params))
        low = " ".join(sql.split()).lower()
        if "count(*)" in low:
            table = "catalyst_events" if "catalyst_events" in low else "news_articles"
            self._result = [(len(self.rows_by_table[table]),)]
        elif low.startswith("select"):
            table = "catalyst_events" if "catalyst_events" in low else "news_articles"
            self._result = list(self.rows_by_table[table])
        elif low.startswith("update"):
            self.rowcount = len(params[0])
            for table in ("catalyst_events", "news_articles"):
                if f"update {table} " in low:
                    self.rows_by_table[table] = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


class _RepairConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed += 1

    def rollback(self):  # pragma: no cover - only on a short update
        pass

    def close(self):
        pass


def _repair_module(monkeypatch, tmp_path, rows_by_table):
    import repair_finviz_strategy_type_20261107 as repair
    log: list[tuple[str, tuple]] = []
    cur = _RepairCursor(rows_by_table, log)
    monkeypatch.setattr(repair, "_connect", lambda: _RepairConn(cur))
    monkeypatch.setattr(repair, "_load_env", lambda: None)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    return repair, log


def test_the_repair_is_read_only_unless_apply_is_passed(monkeypatch, tmp_path):
    rows = {"news_articles": [(1, "NVDA", "NVDA", "Nvidia headline")],
            "catalyst_events": [(2, "NVDA", "NVDA", "Nvidia headline")]}
    repair, log = _repair_module(monkeypatch, tmp_path, rows)
    assert repair.main([]) == 0
    assert not [s for s, _ in log if s.lower().startswith(("update", "insert", "delete"))]
    assert not (tmp_path / "archive").exists(), "a dry run must not even create the archive tree"


def test_the_repair_archives_the_old_values_before_it_nulls_them(monkeypatch, tmp_path):
    rows = {"news_articles": [(11, "NVDA", "NVDA", "Nvidia headline")],
            "catalyst_events": [(22, "NVDA", "NVDA", "Nvidia headline")]}
    repair, log = _repair_module(monkeypatch, tmp_path, rows)
    assert repair.main(["--apply"]) == 0
    updates = [(s, p) for s, p in log if s.lower().startswith("update")]
    assert len(updates) == 2
    assert all("set strategy_type = null" in s.lower() for s, _ in updates)
    assert updates[0][1][0] == [11] and updates[1][1][0] == [22]
    archived = sorted((tmp_path / "archive" / "db_retention").rglob("*.jsonl.gz"))
    assert [p.parent.name for p in archived] == ["catalyst_events", "news_articles"]
    for p in archived:
        assert p.with_name(p.name + ".manifest.json").exists()
        assert (p.parent / "TRIPWIRE.jsonl").exists()
        body = gzip.decompress(p.read_bytes()).decode()
        assert '"strategy_type": "NVDA"' in body, "the destroyed value is recoverable from the archive"
