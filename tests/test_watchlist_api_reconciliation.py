"""GET /api/v2/watchlist must include every ACTIVE ticker watch directive.

Operator 2026-09-23: directive 1278 (`S`) was ACTIVE with linked watchlist_items rows, yet
watchlist_combined() served only the 13 watchlist.json names — the gateway said "watched" while
/api/v2/watchlist said missing. These tests pin the union.

Hermetic: _load_json / _db_query / db_adapter.load_watchlist_items and the watch_intelligence
directive reader are monkeypatched, so no database or state file is touched.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402
import db_adapter  # noqa: E402
from lib.data_broker import watch_intelligence  # noqa: E402

T0 = dt.datetime(2026, 9, 23, 8, 24, 26, tzinfo=dt.timezone.utc)


def _directive(did, symbol, created, **kw):
    return {
        "symbol": symbol,
        "id": did,
        "label": "Watchlist",
        "rationale": kw.get("rationale"),
        "trade_ai_enabled": kw.get("trade_ai_enabled", True),
        "hermes_enabled": kw.get("hermes_enabled", True),
        "created_at": created,
        "updated_at": kw.get("updated_at"),
    }


@pytest.fixture
def run(monkeypatch):
    def _run(watchlist_json, directives):
        state = {"watchlist.json": watchlist_json}
        monkeypatch.setattr(api_v2, "_load_json", lambda p: state.get(Path(p).name))
        monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [])
        monkeypatch.setattr(db_adapter, "load_watchlist_items", lambda **kw: [])
        monkeypatch.setattr(watch_intelligence, "active_ticker_directives", lambda: list(directives))
        return api_v2.watchlist_combined()

    return _run


def test_route_is_wired_to_watchlist_combined():
    assert api_v2.ROUTES.get("/api/v2/watchlist") is api_v2.watchlist_combined


def test_watch_directive_appears_in_watchlist_api(run):
    out = run({"PLTR": {}, "NVDA": {}}, [_directive(1278, "S", T0)])
    symbols = [i["symbol"] for i in out["items"]]
    assert "S" in symbols, "Directive-added symbol 'S' must appear in /api/v2/watchlist"
    s = next(i for i in out["items"] if i["symbol"] == "S")
    assert s["source"] == "directive"
    assert s["directive_id"] == 1278
    assert s["is_watched"] is True
    assert s["trade_ai_enabled"] is True and s["hermes_enabled"] is True
    assert s["last_updated"] == T0.isoformat()
    assert out["active_directives_count"] == 1
    assert out["total_count"] == out["count"] == 3


def test_directive_on_already_listed_symbol_annotates_not_duplicates(run):
    out = run({"PLTR": {"thesis": "AI"}}, [_directive(7, "PLTR", T0, hermes_enabled=False)])
    pltr = [i for i in out["items"] if i["symbol"] == "PLTR"]
    assert len(pltr) == 1
    assert pltr[0]["source"] == "user"
    assert pltr[0]["directive_id"] == 7
    assert pltr[0]["hermes_enabled"] is False


def test_manual_items_marked_watched_without_directive(run):
    out = run({"MSFT": {}}, [])
    (msft,) = out["items"]
    assert msft["is_watched"] is True
    assert "directive_id" not in msft
    assert out["active_directives_count"] == 0


def test_directive_reader_failure_still_serves_manual_list(run, monkeypatch):
    def boom():
        raise RuntimeError("db down")

    out = run({"PLTR": {}}, [])
    monkeypatch.setattr(watch_intelligence, "active_ticker_directives", boom)
    out = api_v2.watchlist_combined()
    assert [i["symbol"] for i in out["items"]] == ["PLTR"]
    assert out["active_directives_count"] == 0


def test_active_ticker_directives_maps_rows_newest_first(monkeypatch):
    older = _directive(5, "AAA", T0 - dt.timedelta(days=1))
    newer = _directive(6, "BBB", T0)
    monkeypatch.setattr(db_adapter, "_execute", lambda sql, params=None, fetch=None: [older, newer])
    rows = watch_intelligence.active_ticker_directives()
    assert [r["symbol"] for r in rows] == ["BBB", "AAA"]
    assert rows[0]["id"] == 6


def test_active_ticker_directives_empty_when_no_db(monkeypatch):
    monkeypatch.setattr(db_adapter, "_execute", lambda sql, params=None, fetch=None: None)
    assert watch_intelligence.active_ticker_directives() == []
