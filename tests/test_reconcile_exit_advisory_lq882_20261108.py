"""LQ-20261107-882: reconcile-exit-advisory-outcomes failed weekly (exit 1) against an input it never read.

Reproduction (2026-11-08 09:00 ET, read-only): the served run wrote
``status: failed``, ``empty_reason: dependency_unavailable``, ``skip_reasons {dependency_unavailable: 1}`` and the
text "no exit_intelligence rows exist and Gain Guardian is unpublished ... nothing has ever been published to
reconcile". Meanwhile ``hermes_research_intelligence`` held 670 ``protection_advisory`` rows (612 due), 972
``stop_health`` rows (936 due) and 3,070 ``stop_curation`` rows, newest 2026-11-06 17:10 ET. Only
``exit_intelligence`` — written solely by ``gain_guardian_publish.publish_run``, which returns early while
``config/gain_guardian_thresholds.json`` has ``published: false`` — was empty, and it was the only type the
selector read. ``exit_advisory_outcomes`` therefore held 0 rows ever.

Pins (fail before, pass after):

* the selector and the producer counts read the SAME accepted type list, so a live producer is never reported
  as "nothing has ever been published";
* "nothing to do" is measured as *pending* (advisories still owing an outcome), so 1,548 due rows can never
  read as a clean week;
* 0 rows ever, a dead feed and unreadable counts are each named and exit 1 — none of them is green;
  up-to-date is the only clean empty;
* one bar fetch per symbol per run (a 200-advisory run used to make four per advisory);
* ``operator_acted`` is measured over the horizon window; it used to query ``created_at BETWEEN x AND x``, an
  always-empty range that recorded ``false`` on every row.

Hermetic: fake ``db_adapter`` and fake bars, tmp ``TRADEAI_STATE_ROOT``, no DB, no network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

SCRIPT = SCRIPTS / "reconcile_exit_advisory_outcomes.py"
LANE = "reconcile-exit-advisory-outcomes"
NOW = datetime.now(timezone.utc)


# ----------------------------------------------------------------------------------------------------------
# fake infrastructure
# ----------------------------------------------------------------------------------------------------------

def _norm(sql: str) -> str:
    return " ".join(str(sql).split())


def _accepted_types(sql: str, params):
    """The research types a statement filters on: the ANY(%s) list, or the legacy literal."""
    import re
    if re.search(r"research_type\s*=\s*ANY\(%s\)", sql):
        return list(params[0]) if params else []
    m = re.search(r"research_type\s*=\s*'([^']+)'", sql)
    return [m.group(1)] if m else []


def _ri_row(rid, research_type, symbol, age_days, evidence):
    return {"id": rid, "research_type": research_type, "symbol": symbol,
            "topic": research_type, "created_at": NOW - timedelta(days=age_days),
            "evidence_json": evidence}


def _protection(symbol, price=10.0, atr=0.5, pct=9.0):
    return {"inputs": {"price": price, "atr": atr},
            "recommendation": {"stop_pct_below": pct, "stop_price": price * (1 - pct / 100)}}


def _stop_health(symbol, price=20.0):
    return {"health": "healthy", "current_price": price}


def _exit_intel(price=30.0, atr=1.0):
    return {"metrics_row": {"price": price, "atr14": atr, "advisory": "TRIM", "giveback_frac": 0.3}}


class FakeDB:
    """Answers the lane's exact statements from in-memory tables; records inserts and the alert window."""

    def __init__(self, rows, *, outcomes=(), fail_counts=False, hide_pending=False):
        import copy
        self.rows = [copy.deepcopy(r) for r in rows]
        self.outcomes = [dict(o) for o in outcomes]
        self.fail_counts = fail_counts
        self.hide_pending = hide_pending  # selector returns nothing although rows are pending
        self.inserts: list[dict] = []
        self.alert_params: list[tuple] = []
        self.legacy_age_calls = 0

    # helpers ------------------------------------------------------------------------------------------
    def _outcome_count(self, advisory_id):
        return sum(1 for o in self.outcomes if o["advisory_id"] == advisory_id)

    def _selected(self, types):
        due = [r for r in self.rows
               if r["research_type"] in types and r.get("symbol")
               and r["created_at"] < NOW - timedelta(days=5)
               and self._outcome_count(r["id"]) < 2]
        due.sort(key=lambda r: r["created_at"])
        if self.hide_pending:
            return []
        return due[:200]

    # the adapter --------------------------------------------------------------------------------------
    def __call__(self, sql, params=None, fetch=None):
        s = _norm(sql)
        if s.startswith("CREATE TABLE"):
            return True
        if "count(*) AS ever" in s:
            if self.fail_counts:
                return None
            types = _accepted_types(s, params)
            rows = [r for r in self.rows if r["research_type"] in types and r.get("symbol")]
            due = [r for r in rows if r["created_at"] < NOW - timedelta(days=5)]
            pending = [r for r in due if self._outcome_count(r["id"]) < 2]
            newest = max((r["created_at"] for r in rows), default=None)
            return {"ever": len(rows), "due": len(due), "pending": len(pending), "newest": newest}
        if "FROM hermes_research_intelligence" in s and "LIMIT 200" in s:
            return self._selected(_accepted_types(s, params))
        if "SELECT 1 FROM exit_advisory_outcomes" in s:
            advisory_id, horizon = params
            hit = [o for o in self.outcomes if o["advisory_id"] == advisory_id and o["horizon_days"] == horizon]
            return {"?column?": 1} if hit else None
        if "EXTRACT(day FROM now()" in s:  # the legacy per-advisory age query
            self.legacy_age_calls += 1
            when = params[0]
            return {"d": max(0, (NOW - when).days)}
        if "SELECT 1 FROM alert_events" in s:
            self.alert_params.append(tuple(params))
            return None
        if "INSERT INTO exit_advisory_outcomes" in s:
            (advisory_id, symbol, advisory, advisory_at, horizon, price_at_advisory, price_at_horizon,
             symbol_return_pct, spy_return_pct, max_drawdown_atr, giveback_frac_then, operator_acted,
             verdict) = params
            row = {"advisory_id": advisory_id, "symbol": symbol, "advisory": advisory,
                   "advisory_at": advisory_at, "horizon_days": horizon,
                   "price_at_advisory": price_at_advisory, "price_at_horizon": price_at_horizon,
                   "symbol_return_pct": symbol_return_pct, "spy_return_pct": spy_return_pct,
                   "max_drawdown_atr": max_drawdown_atr, "giveback_frac_then": giveback_frac_then,
                   "operator_acted": operator_acted, "verdict": verdict}
            self.inserts.append(row)
            self.outcomes.append({"advisory_id": advisory_id, "horizon_days": horizon})
            return True
        raise AssertionError(f"unexpected SQL in the lane under test: {s[:160]}")


class FakeBars:
    """Daily closes per symbol; counts fetches so the per-run cache is measurable."""

    def __init__(self, closes: dict[str, list[float]]):
        self.closes = closes
        self.calls: list[str] = []

    def __call__(self, symbol, days=400):
        self.calls.append(symbol)
        series = self.closes.get(symbol)
        if series is None:
            return []
        return [{"date": (NOW - timedelta(days=len(series) - 1 - i)).isoformat(), "close": c}
                for i, c in enumerate(series)]


def _decline(start: float, step: float, n_pre: int = 9, n: int = 70) -> list[float]:
    """A positive close series, flat for the first ``n_pre`` sessions then declining slowly.

    ``n_pre`` aligns the start of the decline with a 60-day-old advisory (index 9 of 70 daily bars)."""
    return [start if i < n_pre else round(start - step * (i - n_pre), 4) for i in range(n)]


def _load():
    spec = importlib.util.spec_from_file_location("_lq882_exit_advisory_outcomes", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def lane(monkeypatch, tmp_path):
    """The lane module with a fake adapter and fake bars; receipts land in tmp_path."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    mod = _load()
    bars = FakeBars({"AAA": _decline(10.0, 0.1), "BBB": _decline(20.0, 0.05), "SPY": _decline(100.0, 0.0)})
    fake_gg = types.SimpleNamespace(_bars_with_volume=bars)
    monkeypatch.setitem(sys.modules, "holdings_gain_guardian", fake_gg)
    mod.bars = bars  # type: ignore[attr-defined]
    return mod


def _wire(monkeypatch, mod, db):
    monkeypatch.setitem(sys.modules, "db_adapter",
                        types.SimpleNamespace(_execute=db, USE_DB=True))
    return db


def _receipt(tmp_path):
    p = tmp_path / "data" / "runtime" / f"{LANE}_last.json"
    return json.loads(p.read_text()) if p.exists() else {}


# ----------------------------------------------------------------------------------------------------------
# pure helpers
# ----------------------------------------------------------------------------------------------------------

def test_advisory_fields_reads_every_producer_shape(lane):
    assert lane.advisory_fields("protection_advisory", _protection("AAA", price=8.01, atr=0.4588, pct=11.0)) \
        == ({"advisory": "stop_11.0pct"}, 8.01, 0.4588)
    assert lane.advisory_fields("stop_health", _stop_health("AAA", price=20.5)) \
        == ({"advisory": "stop_health:healthy"}, 20.5, None)
    m, price, atr = lane.advisory_fields("exit_intelligence", _exit_intel(price=30.0, atr=1.0))
    assert (m["advisory"], price, atr) == ("TRIM", 30.0, 1.0)
    # a legacy metrics_row wins over the type-specific shape
    assert lane.advisory_fields("protection_advisory", _exit_intel(price=7.0, atr=0.25))[1:] == (7.0, 0.25)
    # a missing/garbage price is None, never 0
    assert lane.advisory_fields("protection_advisory", {})[1:] == (0.0, None)


def test_empty_input_reason_names_the_producers(lane):
    reason, why = lane.empty_input_reason({"ever": 0, "due": 0, "pending": 0, "newest_age_days": None}, False)
    assert reason == "dependency_unavailable"
    for writer in ("holding_protection_advisor", "stop_health_check", "gain_guardian_publish"):
        assert writer in why
    assert "published=false" in why
    # a live producer is never described as "nothing has ever been published"
    assert lane.empty_input_reason({"ever": 1548, "due": 1548, "pending": 0,
                                    "newest_age_days": 1}, False)[0] == "up_to_date"
    assert lane.empty_input_reason({"ever": 1548, "due": 1548, "pending": 7,
                                    "newest_age_days": 1}, False)[0] == "input_inconsistent"
    assert lane.empty_input_reason({"ever": 9, "due": 9, "pending": 9,
                                    "newest_age_days": lane.INPUT_DEAD_DAYS + 1}, False)[0] \
        == "dependency_unavailable"
    # unknown never becomes 0
    assert lane.empty_input_reason({"ever": None, "due": None, "pending": None,
                                    "newest_age_days": None}, False)[0] == "input_unreadable"
    assert lane.empty_input_reason({"ever": 0, "due": 0, "pending": 0,
                                    "newest_age_days": None}, None)[0] == "input_unreadable"


# ----------------------------------------------------------------------------------------------------------
# the live defect: rows exist, the lane must reconcile them
# ----------------------------------------------------------------------------------------------------------

def test_create_products_advisory_rows_are_reconciled_and_reported(lane, monkeypatch, tmp_path, capsys):
    """The exact live shape: 0 exit_intelligence rows, live protection_advisory/stop_health rows due."""
    rows = [_ri_row(1, "protection_advisory", "AAA", 60, _protection("AAA")),
            _ri_row(2, "stop_health", "BBB", 40, _stop_health("BBB"))]
    db = _wire(monkeypatch, lane, FakeDB(rows))
    rc = lane.reconcile()
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "evaluated 4 advisory-horizon pairs" in out.out  # 2 advisories x (5d, 21d)
    assert {i["symbol"] for i in db.inserts} == {"AAA", "BBB"}
    assert all(i["price_at_advisory"] > 0 for i in db.inserts)
    # AAA falls 10% over 5 calendar-ish sessions against a flat SPY -> the exit call was right
    five = [i for i in db.inserts if i["symbol"] == "AAA" and i["horizon_days"] == 5][0]
    assert five["verdict"] == "SIGNAL_CORRECT"
    assert five["symbol_return_pct"] < -3.0
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "ok"
    assert receipt["produced_count"] == 4


def test_create_exit_intelligence_still_reconciled(lane, monkeypatch, tmp_path):
    """The union: a promoted Gain Guardian must not be dropped by the new selector."""
    rows = [_ri_row(7, "exit_intelligence", "AAA", 60, _exit_intel(10.0, 0.5))]
    db = _wire(monkeypatch, lane, FakeDB(rows))
    assert lane.reconcile() == 0
    assert [i["advisory"] for i in db.inserts] == ["TRIM", "TRIM"]
    assert all(i["price_at_advisory"] == 10.0 for i in db.inserts)


def test_create_stop_curation_stays_out(lane, monkeypatch, tmp_path, capsys):
    """stop_curation carries no price at all: it stays out of the accepted types and is never selected."""
    rows = [_ri_row(9, "stop_curation", "AAA", 60, {"no_price": True})]
    db = _wire(monkeypatch, lane, FakeDB(rows))
    assert "stop_curation" not in lane.EXIT_ADVISORY_TYPES
    assert lane.reconcile() == 1  # nothing accepted exists -> a named dependency failure, not a silent 0
    assert db.inserts == []
    assert "dependency_unavailable" in capsys.readouterr().err


def test_up_to_date_is_clean_and_named(lane, monkeypatch, tmp_path, capsys):
    rows = [_ri_row(1, "protection_advisory", "AAA", 60, _protection("AAA")),
            _ri_row(2, "protection_advisory", "BBB", 2, _protection("BBB"))]  # producer is alive
    db = FakeDB(rows, outcomes=[{"advisory_id": 1, "horizon_days": 5},
                                {"advisory_id": 1, "horizon_days": 21},
                                {"advisory_id": 2, "horizon_days": 5},
                                {"advisory_id": 2, "horizon_days": 21}])
    _wire(monkeypatch, lane, db)
    assert lane.reconcile() == 0
    out = capsys.readouterr()
    assert "up_to_date" in out.out
    assert db.inserts == []
    assert _receipt(tmp_path)["empty_reason"] == "up_to_date"


def test_no_rows_ever_is_a_named_failure_not_a_clean_week(lane, monkeypatch, tmp_path, capsys):
    db = _wire(monkeypatch, lane, FakeDB([]))
    assert lane.reconcile() == 1
    err = capsys.readouterr().err
    assert "dependency_unavailable" in err and "holding_protection_advisor" in err
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["empty_reason"] == "dependency_unavailable"


def test_unreadable_counts_are_not_zero(lane, monkeypatch, tmp_path):
    db = _wire(monkeypatch, lane, FakeDB([], fail_counts=True))
    assert lane.reconcile() == 1
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["empty_reason"] == "input_unreadable"
    assert receipt.get("attempted_count") is None  # unknown stayed unknown


def test_dead_feed_is_dependency_unavailable(lane, monkeypatch, tmp_path):
    rows = [_ri_row(1, "protection_advisory", "AAA", lane.INPUT_DEAD_DAYS + 20, _protection("AAA"))]
    db = FakeDB(rows, hide_pending=True)  # rows exist, producers silent, nothing pending
    _wire(monkeypatch, lane, db)
    assert lane.reconcile() == 1
    assert _receipt(tmp_path)["empty_reason"] == "dependency_unavailable"


def test_pending_but_nothing_selected_is_a_contradiction(lane, monkeypatch, tmp_path):
    rows = [_ri_row(1, "protection_advisory", "AAA", 60, _protection("AAA")),
            _ri_row(2, "protection_advisory", "BBB", 2, _protection("BBB"))]
    db = FakeDB(rows, outcomes=[{"advisory_id": 2, "horizon_days": 5}, {"advisory_id": 2, "horizon_days": 21}],
                hide_pending=True)
    _wire(monkeypatch, lane, db)
    assert lane.reconcile() == 1
    assert _receipt(tmp_path)["empty_reason"] == "input_inconsistent"


# ----------------------------------------------------------------------------------------------------------
# cost and truthfulness of the rows written
# ----------------------------------------------------------------------------------------------------------

def test_one_bar_fetch_per_symbol_per_run(lane, monkeypatch, tmp_path):
    rows = [_ri_row(1, "protection_advisory", "AAA", 60, _protection("AAA")),
            _ri_row(2, "stop_health", "BBB", 40, _stop_health("BBB")),
            _ri_row(3, "protection_advisory", "AAA", 50, _protection("AAA"))]
    _wire(monkeypatch, lane, FakeDB(rows))
    assert lane.reconcile() == 0
    assert sorted(lane.bars.calls) == ["AAA", "BBB", "SPY"]  # not 12 calls for 3 advisories x 2 horizons


def test_operator_acted_window_covers_the_horizon(lane, monkeypatch, tmp_path):
    rows = [_ri_row(1, "protection_advisory", "AAA", 60, _protection("AAA"))]
    db = _wire(monkeypatch, lane, FakeDB(rows))
    assert lane.reconcile() == 0
    assert len(db.alert_params) == 2  # one per horizon
    for symbol, start, end in db.alert_params:
        assert symbol == "AAA"
        assert end > start, "the alert window must not be the empty created_at..created_at range"
    assert (db.alert_params[1][2] - db.alert_params[1][1]).days == 31  # 21 trading days x 1.5


def test_no_per_advisory_age_query(lane, monkeypatch, tmp_path):
    """The legacy per-row EXTRACT(day ...) roundtrip is gone: age comes from created_at."""
    rows = [_ri_row(i, "protection_advisory", "AAA", 60 + i, _protection("AAA")) for i in range(1, 4)]
    db = _wire(monkeypatch, lane, FakeDB(rows))
    assert lane.reconcile() == 0
    assert db.legacy_age_calls == 0
