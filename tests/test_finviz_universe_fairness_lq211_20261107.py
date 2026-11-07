"""ANCHOR: FINVIZ_UNIVERSE_FAIRNESS_LQ211_20261107. LQ-20261107-211 — which symbols the finviz proactive
research lane actually looks at.

Measured read-only on 2026-11-07: ``watchlist_items`` holds 5,679 active research symbols, the lane's cap is
400, and ``news_articles source='finviz_news'`` had ever covered **141** of them (440 rows). The alphabetical
cut that produced that was replaced by an hourly rotation in LQ-20261107-52 (``a568480b0``); the rotation
moved the window by ONE symbol per hour, so at four runs a weekday a full sweep still took ~1,419 days, and
5,538 symbols had never produced a row to prove their turn had come. This file pins the residual fix:

* the cap and lookback are the lane's own reviewed config, not constants in the script (150/72) that had to be
  overridden by two hard-coded argv lists (``--max 400 --lookback-hours 12``);
* the window is STALENESS-FIRST over both kinds of evidence — the newest ``finviz_news`` row for the symbol and
  the lane's own record of having asked — so a symbol the provider never mentions still advances through the
  queue instead of being starved behind the same 400 names forever;
* an unreadable config or sweep cursor is reported, never flattened into a default (AGENTS.md rail 8).

Hermetic: fake cursors, fake provider/scoring modules, a ``tmp_path`` state root. No database, no network.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location("lq211_finviz_proactive",
                                                  ROOT / "scripts" / "finviz_proactive_research.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _dt(text: str) -> datetime:
    return datetime.fromisoformat(text)


class _Cursor:
    """The single universe read: (symbol, last finviz_news row) per active watchlist symbol."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.sql: list[str] = []

    def execute(self, sql, params=()):
        self.sql.append(" ".join(sql.split()))
        assert "watchlist_items" in sql, f"unexpected SQL: {sql[:80]}"

    def fetchall(self):
        return list(self.rows)


@pytest.fixture()
def lane(monkeypatch, tmp_path):
    """The lane module with an empty book (so every case is about the watchlist) and a tmp state root."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    mod = _load()
    monkeypatch.setattr(mod, "_holdings_symbols", lambda: ([], "positions_current"))
    return mod


def _universe(lane, monkeypatch, watch, attempts=None, max_n=3, coverage=None):
    monkeypatch.setattr(lane, "_holdings_symbols", lambda: ([], "positions_current"))
    rows = [(sym, (coverage or {}).get(sym)) for sym in watch]
    return lane._universe(_Cursor(rows), max_n, attempts=attempts or {})


# ── the fairness property: the queue advances even when the provider says nothing ─────────────────────────────

def test_a_symbol_never_asked_about_is_picked_before_one_that_was_asked_last_run(lane, monkeypatch):
    """Old code ordered by symbol and rotated by ONE hour step, so A/B/C kept coming back."""
    asked = {s: _dt("2026-11-07T15:30:00+00:00") for s in ("AAA", "BBB", "CCC")}
    symbols, stats = _universe(lane, monkeypatch, ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"], attempts=asked)
    assert symbols == ["DDD", "EEE", "FFF"]
    assert stats["never_attempted"] == 3
    assert stats["selection"] == lane.SELECTION == "staleness_first"


def test_each_run_covers_the_next_window_so_a_symbol_with_no_headline_still_gets_its_turn(lane, monkeypatch):
    """The whole point: three runs of three cover all six symbols — no repeats, nothing starved.

    The provider only ever tags a handful of names, so nothing here writes a ``finviz_news`` row: if the
    attempt record were missing, run 2 and run 3 would return the same three symbols as run 1.
    """
    watch = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
    first, _ = _universe(lane, monkeypatch, watch)
    t1 = _dt("2026-11-07T14:30:00+00:00")
    second, _ = _universe(lane, monkeypatch, watch, attempts={s: t1 for s in first})
    t2 = _dt("2026-11-07T16:30:00+00:00")
    third, _ = _universe(lane, monkeypatch, watch, attempts={**{s: t1 for s in first}, **{s: t2 for s in second}})
    assert first == ["AAA", "BBB", "CCC"]
    assert second == ["DDD", "EEE", "FFF"]
    assert third == ["AAA", "BBB", "CCC"], "after a full sweep the least-recently-asked names come back"
    assert set(first) | set(second) == set(watch)


def test_coverage_is_the_staleness_evidence_before_any_attempt_record_exists(lane, monkeypatch):
    """Day one: no state file yet, so the newest finviz_news row per symbol decides. Never-covered first."""
    coverage = {"AAA": _dt("2026-11-06T20:30:00+00:00"), "BBB": None, "CCC": _dt("2026-11-01T13:00:00+00:00")}
    symbols, stats = _universe(lane, monkeypatch, ["AAA", "BBB", "CCC"], max_n=2, coverage=coverage)
    assert symbols == ["BBB", "CCC"], "never-covered, then the oldest covered row"
    assert stats["never_covered"] == 1
    assert stats["truncated"] == 1 and stats["next_in_line"] == "AAA"


def test_the_attempt_wins_when_it_is_newer_than_the_last_row(lane, monkeypatch):
    """A symbol asked about an hour ago with no row must sort behind one covered a week ago or never."""
    coverage = {"OLD": _dt("2026-10-31T13:00:00+00:00"), "NEW": _dt("2026-11-07T15:00:00+00:00")}
    asked = {"NEW": _dt("2026-11-07T19:00:00+00:00")}
    symbols, _stats = _universe(lane, monkeypatch, ["OLD", "NEW", "NONE"], max_n=3, attempts=asked,
                                coverage=coverage)
    assert symbols == ["NONE", "OLD", "NEW"]


def test_holdings_stay_first_and_are_never_truncated(lane, monkeypatch):
    monkeypatch.setattr(lane, "_holdings_symbols", lambda: (["NVDA", "V"], "positions_current"))
    rows = [("AAA", None), ("BBB", None), ("CCC", None)]
    symbols, stats = lane._universe(_Cursor(rows), 3, attempts={})
    assert symbols == ["NVDA", "V", "AAA"]
    assert stats["holdings_used"] == 2 and stats["watchlist_used"] == 1 and stats["truncated"] == 2


# ── the cap is config, and an unreadable config is not a default ─────────────────────────────────────────────

def test_the_cap_and_lookback_come_from_the_lane_config_and_a_flag_wins(monkeypatch, tmp_path):
    mod = _load()
    cfg = tmp_path / "finviz_proactive_research.json"
    cfg.write_text(json.dumps({"max_symbols": 400, "lookback_hours": 12}))
    monkeypatch.setattr(mod, "CONFIG_PATH", cfg)
    assert mod.resolve_window(None, None) == (400, 12, "config", "config")
    assert mod.resolve_window(250, 6) == (250, 6, "cli", "cli")
    assert mod.resolve_window(250, None) == (250, 12, "cli", "config")


@pytest.mark.parametrize("body", [
    None,                                        # absent
    "{not json",                                 # unreadable as JSON
    json.dumps({"lookback_hours": 12}),          # no max_symbols: the old 150 would have been invented
    json.dumps({"max_symbols": 0}),
    json.dumps({"max_symbols": True}),
    json.dumps({"max_symbols": 400, "selection": "alphabetical"}),
])
def test_an_unusable_config_is_unavailable_not_a_default_cap(monkeypatch, tmp_path, body):
    mod = _load()
    cfg = tmp_path / "finviz_proactive_research.json"
    if body is not None:
        cfg.write_text(body)
    monkeypatch.setattr(mod, "CONFIG_PATH", cfg)
    with pytest.raises(mod.ConfigUnavailable):
        mod.resolve_window(None, None)


def test_a_run_without_a_usable_config_refuses_with_a_failed_receipt(lane, monkeypatch, tmp_path):
    """A scheduled run must not quietly shrink to 150 (or fail to start) when the config is gone."""
    receipts = []
    import lib.lane_last_receipt as llr
    monkeypatch.setattr(llr, "write_lane_receipt", lambda lane_id, **kw: receipts.append({"lane_id": lane_id, **kw}))
    monkeypatch.setattr(lane, "CONFIG_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(lane, "_load_env", lambda: pytest.fail("a refused run reached credentials"))
    assert lane.main([]) == 1
    assert receipts and receipts[0]["ok"] is False and receipts[0]["exit_code"] == 1
    assert "ConfigUnavailable" in receipts[0]["error"]


def test_the_shipped_config_agrees_with_the_scheduled_arguments():
    """Two sources of the same number: the config default and the argv n8n runs. They must not drift."""
    cfg = json.loads((ROOT / "config" / "finviz_proactive_research.json").read_text())
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())
    cmd = next(row["command"] for row in allow["lanes"] if row["lane_id"] == "finviz-proactive-research")
    assert cmd[cmd.index("--max") + 1] == str(cfg["max_symbols"])
    assert cmd[cmd.index("--lookback-hours") + 1] == str(cfg["lookback_hours"])
    assert cfg["selection"] == "staleness_first"


# ── the sweep cursor: written by a live run, never by a dry run, reported when unreadable ─────────────────────

def _fake_deps(monkeypatch, lane, watch=("AAA", "BBB", "CCC"), tickers=("AAA",)):
    conn = types.SimpleNamespace(cursor=lambda: _Cursor([(s, None) for s in watch]),
                                 commit=lambda: None, rollback=lambda: None, close=lambda: None)
    monkeypatch.setattr(lane, "_get_conn", lambda: conn)
    news = types.ModuleType("finviz_news")
    news.fetch_finviz_stock_news_all = lambda lookback_hours=12: [
        {"headline": "synthetic headline", "url": "https://example.invalid/1",
         "tickers": list(tickers), "datetime": 1760000000}]
    scoring = types.ModuleType("content_scoring")
    scoring.score_content = lambda **kw: {"relevance_score": 0.5}
    scoring.tag_content = lambda **kw: {"strategy_tags": [], "agent_tags": []}
    policy = types.ModuleType("hermes_source_policy")
    policy.should_ingest = lambda source: (True, "ok")
    for name, mod in (("finviz_news", news), ("content_scoring", scoring), ("hermes_source_policy", policy)):
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(lane, "is_duplicate", lambda *a, **k: False)
    monkeypatch.setattr(lane, "write_news_articles",
                        lambda cur, rows, **kw: types.SimpleNamespace(rows_written=1))


def test_a_live_run_records_every_symbol_it_asked_about(lane, monkeypatch, tmp_path):
    _fake_deps(monkeypatch, lane)
    summary = {}
    assert lane.run(max_n=3, lookback_hours=12, dry_run=False, summary=summary) == 0
    doc = json.loads((tmp_path / "data" / "runtime" /
                      "finviz_proactive_research_universe.json").read_text())
    assert doc["schema"] == "FinvizProactiveUniverse@v1"
    assert sorted(doc["attempts"]) == ["AAA", "BBB", "CCC"], "all three were asked, only AAA produced a row"
    assert summary["universe_state"] == "ok"


def test_a_dry_run_never_touches_the_sweep_cursor(lane, monkeypatch, tmp_path):
    _fake_deps(monkeypatch, lane)
    summary = {}
    assert lane.run(max_n=3, lookback_hours=12, dry_run=True, summary=summary) == 0
    assert not (tmp_path / "data" / "runtime" / "finviz_proactive_research_universe.json").exists()
    assert "universe_state" not in summary


def test_an_unreadable_sweep_cursor_is_reported_and_the_lane_still_runs(lane, monkeypatch, tmp_path):
    path = tmp_path / "universe.json"
    path.write_text("{torn")
    assert lane.load_attempts(path) == ({}, "unreadable:JSONDecodeError")
    assert lane.load_attempts(tmp_path / "absent.json") == ({}, "absent")


def test_the_preview_reports_the_sweep_facts(lane, monkeypatch, tmp_path):
    watch = [f"SYM{i:03d}" for i in range(10)]
    conn = types.SimpleNamespace(cursor=lambda: _Cursor([(s, None) for s in watch]), close=lambda: None)
    monkeypatch.setattr(lane, "_get_conn", lambda: conn)
    state = tmp_path / "data" / "runtime"
    state.mkdir(parents=True)
    (state / "finviz_proactive_research_universe.json").write_text(json.dumps({
        "schema": "FinvizProactiveUniverse@v1",
        "attempts": {s: "2026-11-07T15:30:00+00:00" for s in watch[:4]}}))
    symbols, stats = lane._universe_preview(6)
    assert symbols == watch[4:10]
    assert stats["attempts_source"] == "ok" and stats["attempts_known"] == 4
    # six never-asked symbols fill the window; the next in line is the least-recently-asked one
    assert stats["next_in_line"] == watch[0] and stats["window_asked_at"] is None
