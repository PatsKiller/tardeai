"""Dividend refresh universe + retired-provider rows (operator decision 2026-10-26).

Verbatim: "widen the dividend refresh to cover everything you hold or watch; Yahoo Finance feed … switched on: yes".
Synthetic symbols only (ZZA..ZZK); no database (psycopg2 is absent in CI), no network, no production state.
"""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import sync_dividend_data as sdd  # noqa: E402
from lib import dividend_source_trust as dst  # noqa: E402


class Cur:
    def __init__(self, conn):
        self.conn = conn
        self._all = []

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.conn.sql.append((flat, params))
        self._all = self.conn.responder(flat) or []

    def fetchall(self):
        return list(self._all)


class Conn:
    def __init__(self, responder):
        self.responder, self.sql, self.commits, self.rollbacks, self.readonly = responder, [], 0, 0, False

    def cursor(self, *a, **k):
        return Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass

    def set_session(self, readonly=False, **_k):
        self.readonly = readonly

    def upserts(self):
        return [(s, p) for s, p in self.sql if s.startswith("INSERT INTO ticker_dividend_data")]


ROTATION = [{"symbol": f"ZR{i:02d}"} for i in range(40)] + [{"symbol": "FID-X"}, {"symbol": "ZZA"}]


def _responder(watch=("ZZD", "ZZE"), superseded_col=False, watch_raises=False):
    def r(sql):
        if "FROM ticker_strategy_classifications" in sql:
            return ROTATION
        if "FROM operator_starred_symbols" in sql:
            if watch_raises:
                raise RuntimeError("relation missing")
            return [{"s": s, "at": None, "ref": None, "label": None} for s in watch]
        if "information_schema.columns" in sql:
            return [{"column_name": "superseded_at"}] if superseded_col else []
        return []
    return r


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(sdd.time, "sleep", lambda *_a: None)
    import lib.portfolio_positions as pp
    store = pp.store_path(tmp_path)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({"holdings": [
        {"symbol": "ZZA", "shares": 10}, {"symbol": "ZZB", "quantity": 3},
        {"symbol": "ZZC", "shares": 0}, {"symbol": "CASH", "shares": 100, "is_cash": True},
        {"symbol": "FID-PROP", "shares": 5}]}))
    pros = tmp_path / "data" / "prospectus"
    pros.mkdir(parents=True)
    (pros / "universe.json").write_text(json.dumps({"schema": "ProspectusUniverse@v1", "items": [
        {"symbol": "ZZB"}, {"symbol": "ZZF"}]}))
    return tmp_path


def test_priority_universe_held_watch_prospectus_first(state):
    conn = Conn(_responder())
    pri = sdd.priority_universe(conn.cursor(), state_root=state, conn=conn)
    assert pri["symbols"] == ["ZZA", "ZZB", "ZZD", "ZZE", "ZZF"]  # held, Watch, prospectus; deduped; no cash/0/FID-
    assert {k: v["status"] for k, v in pri["sources"].items()} == {"held": "ok", "watch": "ok", "prospectus": "ok"}
    batch = sdd.plan_batch(pri["symbols"], sdd._universe(conn.cursor()))
    assert batch[:5] == pri["symbols"]
    assert len(batch) == 5 + sdd.SYMBOL_CAP and "ZZA" not in batch[5:] and "FID-X" not in batch


def test_rotation_is_stalest_first_not_alphabetical(state):
    conn = Conn(_responder())
    sdd._universe(conn.cursor())
    sql = conn.sql[-1][0]
    assert "LEFT JOIN ticker_dividend_data" in sql and "ORDER BY d.last_updated ASC NULLS FIRST" in sql


def test_priority_cap_and_rotation_cap():
    pri = [f"P{i:03d}" for i in range(sdd.PRIORITY_CAP + 20)]
    batch = sdd.plan_batch(pri, [f"R{i}" for i in range(100)])
    assert len(batch) == sdd.PRIORITY_CAP + sdd.SYMBOL_CAP and batch[0] == "P000"


def test_one_source_failing_keeps_the_others(state, monkeypatch):
    def boom(_root):
        raise OSError("no store")
    monkeypatch.setattr(sdd, "_held", boom)
    conn = Conn(_responder())
    pri = sdd.priority_universe(conn.cursor(), state_root=state, conn=conn)
    assert pri["sources"]["held"]["status"] == "error" and pri["symbols"] == ["ZZD", "ZZE", "ZZB", "ZZF"]


def test_failed_watch_select_rolls_back_before_any_write(state):
    conn = Conn(_responder(watch_raises=True))
    cur = conn.cursor()
    cur.connection = conn
    pri = sdd.priority_universe(cur, state_root=state, conn=conn)
    assert conn.rollbacks >= 1 and "ZZA" in pri["symbols"]


def test_sync_fetches_priority_first_and_paces(state, monkeypatch):
    conn = Conn(_responder())
    monkeypatch.setattr(sdd, "_get_conn", lambda: conn)
    pauses, fetched = [], []
    monkeypatch.setattr(sdd.time, "sleep", lambda s: pauses.append(s))
    monkeypatch.setattr(sdd, "_fetch_yf_dividend",
                        lambda s: fetched.append(s) or {"annual_dividend_per_share": 1.0, "dividend_yield_pct": 2.0})
    r = sdd.sync()
    assert fetched[:5] == ["ZZA", "ZZB", "ZZD", "ZZE", "ZZF"]
    assert r["priority_planned"] == 5 and r["priority_checked"] == 5 and r["symbols_checked"] == 5 + sdd.SYMBOL_CAP
    assert len(pauses) == r["symbols_checked"] - 1 and set(pauses) == {sdd.FETCH_PAUSE_S}
    assert r["budget_stopped"] is False and conn.commits == 1


def test_run_budget_drops_rotation_never_priority(state, monkeypatch):
    conn = Conn(_responder())
    monkeypatch.setattr(sdd, "_get_conn", lambda: conn)
    clock = iter(range(0, 10_000, 60))
    monkeypatch.setattr(sdd.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(sdd, "_fetch_yf_dividend", lambda s: {"annual_dividend_per_share": 1.0})
    r = sdd.sync()
    assert r["budget_stopped"] is True and r["symbols_checked"] < r["planned"]
    assert [p[0] for _, p in conn.upserts()][:r["symbols_checked"]][0] == "ZZA"


def test_upsert_replaces_retired_provider_values_and_clears_marker(state, monkeypatch):
    sql = sdd._upsert_sql(clear_superseded=False)
    assert "CASE WHEN NOT (COALESCE(ticker_dividend_data.source, '') !~* '^(fmp)([_-]|$)') THEN EXCLUDED" in " ".join(sql.split())
    assert "superseded_at" not in sql and "%" not in sql.replace("%s", "")
    assert "superseded_at = NULL, superseded_reason = NULL" in sdd._upsert_sql(clear_superseded=True)
    conn = Conn(_responder(superseded_col=True))
    monkeypatch.setattr(sdd, "_get_conn", lambda: conn)
    monkeypatch.setattr(sdd, "_fetch_yf_dividend", lambda s: {"annual_dividend_per_share": 1.0})
    sdd.sync()
    assert conn.upserts() and all("superseded_at = NULL" in s for s, _ in conn.upserts())


def test_fund_fallback_trailing_annual_rate(monkeypatch):
    info = {"dividendRate": None, "trailingAnnualDividendRate": 2.5, "regularMarketPrice": 50.0,
            "exDividendDate": 1790000000}
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=lambda s: types.SimpleNamespace(info=info)))
    out = sdd._fetch_yf_dividend("ZZF")
    assert out["annual_dividend_per_share"] == 2.5 and out["dividend_yield_pct"] == 5.0
    info2 = dict(info, dividendRate=3.0)
    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=lambda s: types.SimpleNamespace(info=info2)))
    assert sdd._fetch_yf_dividend("ZZF")["annual_dividend_per_share"] == 3.0


def test_dry_run_is_offline_and_names_the_universe(capsys, monkeypatch):
    monkeypatch.setattr(sdd, "_get_conn", lambda: (_ for _ in ()).throw(AssertionError("dry run opened a DB")))
    assert sdd.main(["--dry-run", "--json"]) == 0
    out = capsys.readouterr().out
    plan = json.loads(out.splitlines()[0])
    assert plan["priority_cap"] == sdd.PRIORITY_CAP and "held + Watch + prospectus first" in plan["universe"]


def test_retired_providers_come_from_the_registry():
    assert dst.retired_providers() == ("fmp",)
    assert dst.is_retired_source("fmp_api") and dst.is_retired_source("FMP") and not dst.is_retired_source("yfinance")
    assert not dst.is_retired_source("fmpx")
    with pytest.raises(ValueError):
        dst.trusted_row_sql("source; DROP TABLE x")


_READERS = ["scripts/lib/subject_dossier.py", "scripts/portfolio_alerts.py", "scripts/portfolio_dividend_calendar.py",
            "scripts/lib/hermes_discovery/coverage.py", "scripts/materialize_income_engine.py",
            "scripts/alex_retirement_advisor.py"]


def test_every_reader_query_filters_retired_rows():
    """Every SELECT ... FROM ticker_dividend_data in scripts/ carries the trusted-row predicate."""
    offenders = []
    # Not queries: the predicate's own docstring; a validator that greps a source file for a query string.
    exempt = {"scripts/lib/dividend_source_trust.py", "scripts/validate_closed_loop_intelligence.py"}
    for path in sorted((ROOT / "scripts").rglob("*.py")):
        if str(path.relative_to(ROOT)) in exempt:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"FROM ticker_dividend_data\b", text):
            window = text[m.start(): m.start() + 400]
            if "_div_trusted" not in window.lower():
                offenders.append(f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, m.start()) + 1}")
    assert offenders == []
    for rel in _READERS:
        assert "dividend_source_trust" in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_migration_marks_never_deletes():
    up = (ROOT / "migrations/2026_10_26_ticker_dividend_superseded.sql").read_text(encoding="utf-8")
    down = (ROOT / "migrations/2026_10_26_ticker_dividend_superseded.down.sql").read_text(encoding="utf-8")
    body = "\n".join(l for l in (up + down).splitlines() if not l.lstrip().startswith("--")).upper()
    assert "DELETE" not in body and "DROP" not in body and "TRUNCATE" not in body
    assert "ADD COLUMN IF NOT EXISTS SUPERSEDED_AT" in body and "~* '^(FMP)([_-]|$)'" in body
