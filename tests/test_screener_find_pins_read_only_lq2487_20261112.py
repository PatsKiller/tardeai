"""LQ-20261107-2487: the Screener Finds GET handlers must not write screener_find_pins.

Part A drives lib/screener_find_pins_read (the new read side) with a recording fake. Part B drives the REAL api_v2 handlers
(`_screener_finds_candidates`, `_wl_items?lane=screener_finds`) with `_db_query` replaced by a recorder that FAILS the test on
any statement that is not a plain SELECT, and checks the source of both handlers names no sync/ensure helper. Part B needs
the api_v2.py hunk (PATCH-LQ-20261107-2487-api_v2-screener-finds-read-only.patch); alone it fails by design. Synthetic rows only.
"""
from __future__ import annotations

import ast
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "scripts", ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from lib import screener_find_pins_read as R  # noqa: E402

T = datetime(2026, 11, 12, 13, 3, 57, tzinfo=timezone.utc)


def row(sym, live, stored_active=False, ar=T, pinned=T, stored_cio=None):
    return {"symbol": sym, "pinned_at": pinned, "auto_research_at": ar, "discovery_reason": "r", "strategy_type": "x",
            "brief_snippet": "b", "stored_cio_recommendation": stored_cio, "stored_active": stored_active,
            "live_cio_recommendation": live}


class Rec:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def __call__(self, sql, params=None, fetch="all"):
        self.calls.append(sql)
        assert re.match(r"\s*(WITH|SELECT)\b", sql, re.I), f"non-SELECT statement: {sql[:60]}"
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE)\b", sql, re.I), sql[:80]
        return self.rows


# ---- Part A: module ----------------------------------------------------------------------------------------------
def test_pins_sql_is_one_select_without_write_keywords():
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b", R.PINS_SQL, re.I)
    q = Rec([])
    R.read_pins(q)
    assert len(q.calls) == 1


@pytest.mark.parametrize("rec", ["BUY", "STRONG_BUY", "ADD", "ADD_ON_PULLBACK", " buy ", "add_on_pullback"])
def test_buy_side_is_active(rec):
    assert R.read_pins(Rec([row("A", rec)]))[0]["active"] is True


@pytest.mark.parametrize("rec", ["HOLD", "AVOID", "SELL", "RESEARCH_MORE", "IGNORE", "", None, "BUYING", "NOT_BUY"])
def test_not_buy_side_is_inactive(rec):
    p = R.read_pins(Rec([row("A", rec)]))[0]
    assert p["active"] is False and p["cio_recommendation"] in (None, str(rec).upper().strip())


def test_active_pins_keeps_only_buy_side_in_query_order():
    rows = [row("Z", "BUY"), row("Y", "HOLD"), row("X", "ADD")]
    assert [p["symbol"] for p in R.active_pins(Rec(rows))] == ["Z", "X"]


def test_active_follows_live_verdict_not_the_stored_flag():
    p = R.read_pins(Rec([row("A", "HOLD", stored_active=True), row("B", "BUY", stored_active=False)]))
    assert [(x["symbol"], x["active"], x["stored_active"]) for x in p] == [("A", False, True), ("B", True, False)]
    assert R.drifted(p) == ["A", "B"]


def test_unreadable_store_is_none_and_active_pins_is_empty_not_a_write():
    class Dead(Rec):
        def __call__(self, *a, **k):
            self.calls.append("x")
            return None
    assert R.read_pins(Dead([])) is None
    assert R.active_pins(Dead([])) == []


def test_reading_does_not_change_the_stamps():
    ar = datetime(2026, 11, 1, tzinfo=timezone.utc)
    out = R.read_pins(Rec([row("A", "BUY", ar=ar)]))
    assert out[0]["auto_research_at"] == ar  # no now() stamp on read


# ---- Part B: the real handlers (needs the api_v2 hunk) -------------------------------------------------------------
def _handler_src(name):
    tree = ast.parse((ROOT / "scripts" / "api_v2.py").read_text())
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment((ROOT / "scripts" / "api_v2.py").read_text(), n)
    raise AssertionError(name)


@pytest.mark.parametrize("handler", ["_screener_finds_candidates", "_wl_items"])
def test_get_handler_names_no_sync_or_ddl_helper(handler):
    src = _handler_src(handler)
    for banned in ("_sync_all_screener_find_pins", "_sync_screener_find_pin", "_ensure_screener_find_pins_table"):
        assert banned not in src, f"{handler} still references {banned}"


class _Spy:
    def __init__(self, rows):
        self.rows, self.sql = rows, []

    def __call__(self, sql, params=None, fetch="all"):
        self.sql.append(sql)
        s = sql.lstrip().upper()
        assert s.startswith(("SELECT", "WITH")), f"GET issued a write/DDL statement: {sql.strip()[:70]}"
        if "SCREENER_FIND_PINS P" in s.replace("\n", " ").replace("  ", " ") or "LATERAL" in s:
            return self.rows
        return [] if fetch == "all" else None


def test_candidates_handler_issues_only_selects(monkeypatch):
    import api_v2

    spy = _Spy([row("AAA", "BUY"), row("BBB", "HOLD")])
    monkeypatch.setattr(api_v2, "_db_query", spy)
    monkeypatch.setattr(api_v2, "_wide_finds_payload", lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(api_v2, "_finds_track_record", lambda *a, **k: {}, raising=False)
    out = api_v2._screener_finds_candidates({})
    assert [c["symbol"] for c in out["candidates"]] == ["AAA"]
    assert all(s.lstrip().upper().startswith(("SELECT", "WITH")) for s in spy.sql)


def test_watchlist_items_lane_issues_only_selects(monkeypatch):
    import api_v2

    spy = _Spy([row("AAA", "BUY")])
    monkeypatch.setattr(api_v2, "_db_query", spy)
    api_v2._wl_items({"lane": ["screener_finds"]})
    assert spy.sql and all(s.lstrip().upper().startswith(("SELECT", "WITH")) for s in spy.sql)


def test_plain_watchlist_items_has_no_ddl(monkeypatch):
    import api_v2

    spy = _Spy([])
    monkeypatch.setattr(api_v2, "_db_query", spy)
    api_v2._wl_items({})
    assert not any("CREATE TABLE" in s.upper() for s in spy.sql)


def test_pins_are_ordered_newest_research_first_with_stable_tiebreaks():
    assert re.search(r"ORDER BY p\.auto_research_at DESC NULLS LAST,\s*p\.pinned_at DESC,\s*p\.symbol", R.PINS_SQL)
