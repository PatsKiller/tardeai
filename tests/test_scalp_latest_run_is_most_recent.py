"""`latest` on the scalp scanner must mean MOST RECENT, not BIGGEST.

Cause (2026-09-01 09:45): the Market Opportunities panel showed
run_label "1730" -- a 17:30 run -- at 09:45, with latest_run_timestamp empty and
latest_run_symbols_scanned 0. The rank key was

    (heal, ticker_count, date, generated_at)

so raw ticker_count outranked date and a 38-ticker evening package beat the
morning's 10-ticker run. The variable was named `latest` and returned the largest.

The count term existed only to prefer real packages over empty session-heal
anchors, so it is now a boolean; date decides among real runs; size is the last
tiebreak where it cannot mask recency.
"""

import argparse
import ast
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class FixtureClock(datetime):
    instant = datetime(2026, 10, 12, 13, 10, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


def _real_functions(relative_path, names, namespace):
    path = ROOT / relative_path
    tree = ast.parse(path.read_text(), filename=str(path))
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in functions} == set(names)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


@pytest.fixture
def session_functions():
    namespace = {
        "Path": Path,
        "json": json,
        "os": os,
        "tempfile": tempfile,
        "datetime": FixtureClock,
        "timezone": timezone,
        "LABEL": "HEALTH_AUTOHEAL",
        "argparse": argparse,
        "sys": sys,
    }
    _real_functions(
        "scripts/heal_trade_ai_session_cache.py",
        {"_atomic_write", "_write_json_if_changed", "_heal_root", "main"},
        namespace,
    )
    _real_functions("scripts/api_v2.py", {"_normalize_trade_ai_session_date"}, namespace)
    return namespace


def _cache_fixture(tmp_path, *, today=False):
    day, label = ("2026-10-12", "0900") if today else ("2026-10-09", "1730")
    cache = {
        "ok": True,
        "run_date": day,
        "date": day,
        "run_label": label,
        "latest_run_label": label,
        "run_id": f"{day}::{label}",
        "latest_run_timestamp": f"{day}T13:13:15+00:00",
        "latest_run_symbols_scanned": 67,
        "current_run_scanned": 67,
        "current_run_go": 1,
        "current_run_wait": 0,
        "current_run_nogo": 66,
        "go_count": 1,
        "wait_count": 0,
        "avoid_count": 69,
        "ticker_count": 70,
        "stale": not today,
        "cache_error": None if today else "empty_compute_kept_last_good",
        "_cached_ts": 100.0,
        "_cached_at": f"{day}T13:16:30Z",
        "setup_run_summary": {
            "contract_version": "SetupRunSummary@v1",
            "run_id": f"{day}::{label}",
            "run_date": day,
            "run_label": label,
            "scanned_count": 44,
            "classified_count": 44,
            "go_count": 0,
            "nogo_count": 44,
            "count_integrity": "PARTIAL",
            "count_integrity_reason": "primary44 vs alternate67",
        },
        "tickers": [{"symbol": "FIX", "scan_run_label": label, "decision": "GO", "run_type": "live"}],
    }
    path = tmp_path / "data/runtime/trade_ai_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache))
    return path, cache


def _business_fields(cache):
    return {
        k: v
        for k, v in cache.items()
        if k not in {"session_date", "session_heal", "session_context", "session_date_normalized"}
    }


def rank(rs):
    """Mirror of api_v2._run_rank (the fixed shape)."""
    tc = int(rs.get("ticker_count") or len(rs.get("tickers") or []) or 0)
    lbl = str(rs.get("run_label") or "")
    heal = 0 if lbl == "HEALTH_AUTOHEAL" or rs.get("session_heal") else 1
    date = str(rs.get("date") or rs.get("run_date") or "")
    has_tickers = 1 if tc > 0 else 0
    return (heal, has_tickers, date, str(rs.get("generated_at") or ""), tc)


def pick(runs):
    return sorted(runs, key=rank, reverse=True)[0]


BIG_STALE = {"run_label": "1730", "date": "2026-08-31", "ticker_count": 38, "generated_at": "2026-08-31T17:30:00"}
SMALL_FRESH = {"run_label": "0930", "date": "2026-09-01", "ticker_count": 10, "generated_at": "2026-09-01T09:30:00"}


def test_a_small_fresh_run_beats_a_large_stale_one():
    """The exact 2026-09-01 failure: 38 tickers yesterday vs 10 today."""
    assert pick([BIG_STALE, SMALL_FRESH])["run_label"] == "0930"


def test_the_old_key_would_have_picked_the_stale_run():
    """Positive control -- proves this test detects the defect it describes."""

    def old_rank(rs):
        tc = int(rs.get("ticker_count") or 0)
        heal = 0 if rs.get("run_label") == "HEALTH_AUTOHEAL" else 1
        return (heal, tc, str(rs.get("date") or ""), str(rs.get("generated_at") or ""))

    worst = sorted([BIG_STALE, SMALL_FRESH], key=old_rank, reverse=True)[0]
    assert worst["run_label"] == "1730", "old key must reproduce the bug"


def test_empty_heal_anchors_never_win():
    """The behaviour the count term was actually there to protect."""
    heal = {"run_label": "HEALTH_AUTOHEAL", "date": "2026-09-02", "ticker_count": 0}
    assert pick([heal, SMALL_FRESH])["run_label"] == "0930"


def test_an_empty_run_never_beats_a_real_one_on_the_same_day():
    empty = {"run_label": "0935", "date": "2026-09-01", "ticker_count": 0, "generated_at": "2026-09-01T09:35:00"}
    assert pick([empty, SMALL_FRESH])["run_label"] == "0930"


def test_same_day_prefers_the_later_generated_at():
    later = dict(SMALL_FRESH, run_label="1000", generated_at="2026-09-01T10:00:00")
    assert pick([SMALL_FRESH, later])["run_label"] == "1000"


def test_size_still_breaks_a_genuine_tie():
    a = {"run_label": "A", "date": "2026-09-01", "generated_at": "2026-09-01T09:30:00", "ticker_count": 5}
    b = {"run_label": "B", "date": "2026-09-01", "generated_at": "2026-09-01T09:30:00", "ticker_count": 40}
    assert pick([a, b])["run_label"] == "B"


def test_friday_heal_and_normal_read_keep_monday_business_freshness_false(tmp_path, session_functions):
    path, original = _cache_fixture(tmp_path)
    result = session_functions["_heal_root"](tmp_path, "2026-10-12", False)
    healed = json.loads(path.read_text())
    served = session_functions["_normalize_trade_ai_session_date"](healed)
    assert result["business_run_changed"] is False
    assert _business_fields(healed) == _business_fields(original)
    assert _business_fields(served) == _business_fields(original)
    assert served["run_date"] != served["session_date"] == "2026-10-12"
    assert served["stale"] and served["cache_error"] == "empty_compute_kept_last_good"
    assert served["session_context"]["business_run_date"] == "2026-10-09"
    anchor = json.loads((tmp_path / "reports/2026-10-12/HEALTH_AUTOHEAL/run_summary.json").read_text())
    assert anchor["session_heal"] is True and anchor["ticker_count"] == 0
    assert pick([anchor, BIG_STALE])["run_label"] == "1730"


def test_same_session_heal_is_idempotent_even_when_clock_advances(tmp_path, session_functions, monkeypatch):
    path, _ = _cache_fixture(tmp_path)
    session_functions["_heal_root"](tmp_path, "2026-10-12", False)
    files = [p for p in tmp_path.rglob("*.json")]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}

    class LaterClock(FixtureClock):
        instant = datetime(2026, 10, 12, 15, 10, tzinfo=timezone.utc)

    monkeypatch.setitem(session_functions, "datetime", LaterClock)
    result = session_functions["_heal_root"](tmp_path, "2026-10-12", False)
    assert result["changed"] is False
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files} == before


def test_today_partial_population_is_preserved_after_late_warm(tmp_path, session_functions):
    path, _ = _cache_fixture(tmp_path)
    session_functions["_heal_root"](tmp_path, "2026-10-12", False)
    path, warm = _cache_fixture(tmp_path, today=True)
    session_functions["_heal_root"](tmp_path, "2026-10-12", False)
    served = session_functions["_normalize_trade_ai_session_date"](json.loads(path.read_text()))
    assert _business_fields(served) == _business_fields(warm)
    assert served["current_run_scanned"] == 67
    assert served["setup_run_summary"]["scanned_count"] == 44
    assert served["setup_run_summary"]["go_count"] == 0 and served["go_count"] == 1
    assert served["setup_run_summary"]["count_integrity"] == "PARTIAL"


def test_legacy_date_normalization_is_exposed_without_rewriting_business_fields(tmp_path, session_functions):
    _, cache = _cache_fixture(tmp_path)
    cache["run_date"] = cache["date"] = "2026-10-12"
    legacy = {"from": "2026-10-09", "to": "2026-10-12", "go": 1}
    cache["session_date_normalized"] = legacy
    before = json.loads(json.dumps(cache))
    served = session_functions["_normalize_trade_ai_session_date"](cache)
    assert _business_fields(served) == _business_fields(before)
    assert cache == before
    assert "session_date_normalized" not in served
    assert served["session_context"]["legacy_date_normalization"] == legacy
    assert served["session_context"]["business_date_mismatch"] is True
    assert served["session_context"]["business_run_date"] == "2026-10-09"
    assert session_functions["_normalize_trade_ai_session_date"](served) == served


def test_dry_run_does_not_write_cache_or_session_anchors(tmp_path, session_functions):
    path, _ = _cache_fixture(tmp_path)
    before = path.read_bytes()
    result = session_functions["_heal_root"](tmp_path, "2026-10-12", True)
    assert result["dry_run"] is True and path.read_bytes() == before
    assert not (tmp_path / "reports").exists()


def test_missing_cache_never_becomes_a_proven_business_run(tmp_path, session_functions):
    session_functions["_heal_root"](tmp_path, "2026-10-12", False)
    cache = json.loads((tmp_path / "data/runtime/trade_ai_cache.json").read_text())
    assert cache["ok"] is False and cache["stale"] is True
    assert cache["cache_error"] == "business_run_not_proven"
    assert "run_date" not in cache and "run_id" not in cache
    assert "current_run_scanned" not in cache and "setup_run_summary" not in cache


@pytest.mark.parametrize("raw", ["{broken", "[]"])
def test_unreadable_cache_is_preserved_and_cli_reports_failure(tmp_path, session_functions, monkeypatch, raw):
    path = tmp_path / "data/runtime/trade_ai_cache.json"
    path.parent.mkdir(parents=True)
    path.write_text(raw)
    result = session_functions["_heal_root"](tmp_path, "2026-10-12", False)
    assert result["status"] == "CACHE_UNREADABLE" and path.read_text() == raw
    assert not (tmp_path / "reports").exists()
    monkeypatch.setitem(session_functions, "get_live_project_root", lambda: tmp_path)
    monkeypatch.setitem(session_functions, "DEV_ROOT", tmp_path)
    monkeypatch.setitem(session_functions, "_today_et", lambda: "2026-10-12")
    monkeypatch.setattr(sys, "argv", ["heal_trade_ai_session_cache.py"])
    assert session_functions["main"]() == 1
    assert path.read_text() == raw


@pytest.mark.parametrize(
    "instant,day",
    [
        (datetime(2026, 6, 1, 3, 30, tzinfo=timezone.utc), "2026-05-31"),
        (datetime(2026, 11, 2, 4, 30, tzinfo=timezone.utc), "2026-11-01"),
    ],
)
def test_calendar_context_uses_new_york_day_across_dst(session_functions, monkeypatch, instant, day):
    class DayClock(FixtureClock):
        pass

    DayClock.instant = instant
    monkeypatch.setitem(session_functions, "datetime", DayClock)
    out = session_functions["_normalize_trade_ai_session_date"]({"run_date": "2026-05-30"})
    assert out["session_date"] == day
    assert out["session_context"]["timezone"] == "America/New_York"
    assert out["run_date"] == "2026-05-30"
