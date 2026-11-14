"""S2 producers-perf (WR-05 / WR-07 / WR-11) — producer-side tests, hermetic.

Three things this file pins:

1. The alert evaluator's run record carries what it could NOT evaluate: ``evaluated`` / ``eligible`` / ``failed`` and
   quote coverage, so a successful no-fire pass is distinguishable from a pass that read no input. A field that was
   never reported stays ``None`` — unknown, never 0.
2. A runs record that was never written says so (``store_missing``), instead of reading as an empty store.
3. ``pullback_trigger_history`` is written by the SCREENER (the producer), not by the candidates GET. The GET's
   write is removed by the wiring patch to ``api_v2.py`` (cc-opus-3's hot file); the producer half is pinned here.

Synthetic fixtures only: a fake ``db_adapter``/``ex`` and a tmp state root. No DB, no network, no .env, no broker.
"""
from __future__ import annotations

import importlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

NOW = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
ANCHOR = "S2_PRODUCERS_PERF"


# ── 1. evaluator counts ────────────────────────────────────────────────────────────────────────────────
class _Ex:
    """Answers the evaluator's SELECTs; records any write so a test can prove none happened on a no-fire pass."""

    def __init__(self, *, rsi=None, directive_hits=0):
        self.rsi, self.directive_hits = rsi, directive_hits
        self.writes: list[str] = []
        self.seen: list[str] = []

    def __call__(self, sql, params=None, fetch=None):
        self.seen.append(sql.strip().split()[0].upper())
        if "FROM alert_events WHERE alert_uid" in sql:
            return None
        if "FROM watchlist_items" in sql:
            return None if self.rsi is None else {"rsi": self.rsi}
        if "FROM watch_directive_hits" in sql:
            return {"n": self.directive_hits}
        if sql.strip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            self.writes.append(sql.strip()[:40])
            return None
        raise AssertionError(f"unexpected SQL: {sql[:60]}")


def _fresh(price=9.0):
    """A covered quote. Its session-freshness verdict is exercised by its own test below and by
    tests/test_session_freshness*; these count tests stub ``_quote_is_current`` so a weekend clock
    cannot turn them into a freshness test by accident."""
    return {"price": price, "as_of": datetime.now(timezone.utc).isoformat(), "source": "finviz"}


def _load_eval(monkeypatch, quotes: dict):
    """Import the evaluator with a fake dotenv and a fake price batch (no Finviz, no DB)."""
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "dotenv", dotenv)
    sys.modules.pop("watch_alerts_eval", None)
    W = importlib.import_module("watch_alerts_eval")
    monkeypatch.setattr(W, "_price_quotes", lambda ex, syms: {s: quotes[s] for s in syms if s in quotes})
    return W


def _alert(aid=1, symbol="AAA", condition="price_cross_above", threshold=10.0, **kw):
    row = {"id": aid, "symbol": symbol, "condition_type": condition, "threshold": threshold,
           "recurring": False, "cooldown_days": None, "last_fired_at": None, "directive_id": None}
    row.update(kw)
    return row


def test_a_covered_quote_is_evaluated_and_a_missing_one_is_a_named_failure(monkeypatch):
    """AAA has a current quote (evaluated, no fire); BBB has none (failed+logged). Both must be counted."""
    W = _load_eval(monkeypatch, {"AAA": _fresh()})
    monkeypatch.setattr(W, "_quote_is_current", lambda v: True)
    ex = _Ex()
    counts: dict = {}
    alerts = [_alert(1, "AAA"), _alert(2, "BBB")]
    lines, fired = W._evaluate_single_condition_alerts(ex, alerts, "2026-11-14", counts)
    assert (lines, fired) == ([], []), "9.0 is below the 10.0 cross — no fire, and that is a successful evaluation"
    assert counts["attempted"] == 2 and counts["eligible"] == 2
    assert counts["evaluated"] == 1, "only AAA's input was actually read and compared"
    assert counts["failed"] == 1, "BBB had no quote: it must be a failure, never a quiet no-fire"
    assert counts["quotes_requested"] == 2 and counts["quotes_covered"] == 1
    assert ex.writes == [], "an unevaluable alert writes nothing"


def test_a_clean_no_fire_pass_reports_failed_zero(monkeypatch):
    W = _load_eval(monkeypatch, {"AAA": _fresh()})
    monkeypatch.setattr(W, "_quote_is_current", lambda v: True)
    counts: dict = {}
    W._evaluate_single_condition_alerts(_Ex(), [_alert()], "2026-11-14", counts)
    assert counts["evaluated"] == 1 and counts["failed"] == 0
    assert counts["quotes_covered"] == 1 and counts["quotes_requested"] == 1


def test_an_unsupported_condition_is_counted_not_silently_skipped(monkeypatch):
    W = _load_eval(monkeypatch, {})
    counts: dict = {}
    W._evaluate_single_condition_alerts(_Ex(), [_alert(condition="moon_phase", threshold=None)], "2026-11-14", counts)
    assert counts["eligible"] == 1 and counts["failed"] == 1 and counts["evaluated"] == 0


def test_a_session_stale_quote_is_a_failure_not_a_quiet_no_fire(monkeypatch):
    """A present-but-stale print is exactly the case that used to read as "did not fire": it must count as failed."""
    W = _load_eval(monkeypatch, {"AAA": {"price": 9.0, "as_of": "2026-01-05T15:00:00+00:00", "source": "market_quotes"}})
    counts: dict = {}
    W._evaluate_single_condition_alerts(_Ex(), [_alert()], "2026-11-14", counts)
    assert counts["evaluated"] == 0 and counts["failed"] == 1
    assert counts["quotes_covered"] == 1, "the helper covered the symbol; the session freshness is what failed"


def test_an_rsi_alert_with_no_rsi_row_is_a_failure(monkeypatch):
    W = _load_eval(monkeypatch, {})
    counts: dict = {}
    W._evaluate_single_condition_alerts(_Ex(rsi=None), [_alert(condition="rsi_below", threshold=30)], "2026-11-14", counts)
    assert counts["failed"] == 1 and counts["evaluated"] == 0
    counts2: dict = {}
    W._evaluate_single_condition_alerts(_Ex(rsi=25.0), [_alert(condition="rsi_below", threshold=30)], "2026-11-14", counts2)
    assert counts2["failed"] == 0 and counts2["evaluated"] == 1


def test_the_counts_parameter_is_optional_so_existing_callers_keep_working(monkeypatch):
    W = _load_eval(monkeypatch, {})
    lines, fired = W._evaluate_single_condition_alerts(_Ex(), [_alert()], "2026-11-14")
    assert lines == [] and fired == []


# ── 2. the runs record ───────────────────────────────────────────────────────────────────────────────
def _rec():
    from lib import watch_alerts_record as rec
    return rec


def test_counts_ride_the_record_and_a_never_written_store_says_so(tmp_path):
    rec = _rec()
    missing = rec.read_record(root=tmp_path, now=NOW)
    assert missing["store_missing"] is True and missing["readable"] is True
    assert "no runs record" in (missing["reason"] or "")
    assert rec.append_run(armed=18, fired=0, composites=0, rc=0, evaluated=17, eligible=18, failed=1,
                          quotes_covered=12, quotes_missing=3, run_id="r-1", root=tmp_path, now=NOW)
    d = rec.read_record(root=tmp_path, now=NOW + timedelta(minutes=1))
    assert d["store_missing"] is False
    assert d["last_counts"]["evaluated"] == 17 and d["last_counts"]["failed"] == 1
    assert d["last_counts"]["run_id"] == "r-1"
    assert d["certified"]["evaluated"] == 17 and d["certified"]["quotes_covered"] == 12
    assert d["certified"]["quotes_missing"] == 3 and d["certified"]["failed_24h"] == 1


def test_an_older_writer_without_counts_reads_unknown_not_zero(tmp_path):
    rec = _rec()
    line = {"ts": (NOW - timedelta(minutes=5)).isoformat(), "rc": 0, "armed": 4, "fired": 0,
            "composites": 0, "error": None}
    path = rec.record_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(line) + "\n")
    d = rec.read_record(root=tmp_path, now=NOW)
    assert d["last_counts"] is None, "a line with no counts is unknown, not a zero count"
    assert d["certified"].get("evaluated") is None and d["certified"].get("failed_24h") is None
    assert "evaluated" not in d["certified"], "an unreported count is absent, not an explicit null"


def test_failed_24h_is_unknown_when_any_ok_run_in_the_window_omitted_the_count(tmp_path):
    rec = _rec()
    rec.append_run(armed=1, fired=0, composites=0, rc=0, evaluated=3, failed=0, root=tmp_path,
                   now=NOW - timedelta(minutes=40))
    rec.append_run(armed=1, fired=0, composites=0, rc=0, root=tmp_path, now=NOW - timedelta(minutes=20))
    d = rec.read_record(root=tmp_path, now=NOW)
    assert d["certified"].get("failed_24h") is None, "one unreported run makes the window total unknown"


# ── 3. the producer writes the trigger history ───────────────────────────────────────────────────────
class _ScreenerDB:
    def __init__(self):
        self.statements: list[str] = []

    def __call__(self, sql, params=None, fetch=None):
        self.statements.append(sql)
        return None


def _screener(monkeypatch, db):
    import pandas  # noqa: F401 — a real import: the module needs it, and the test must not fake the data layer
    sys.modules.pop("pullback_macd_screener", None)
    M = importlib.import_module("pullback_macd_screener")
    monkeypatch.setattr(M, "_db", db)
    return M


def test_the_screener_records_trigger_history_once_per_pass(monkeypatch):
    db = _ScreenerDB()
    M = _screener(monkeypatch, db)
    assert M._record_trigger_history() == 1
    assert len(db.statements) == 1
    sql = db.statements[0]
    assert "INSERT INTO pullback_trigger_history" in sql
    assert "ON CONFLICT (symbol, trigger_date) DO NOTHING" in sql, "the recorder must stay idempotent"
    assert "FROM pullback_macd_candidates WHERE tier='trigger' AND status='active'" in sql


def test_a_recorder_failure_is_named_and_never_fails_the_scan(monkeypatch):
    def boom(sql, params=None, fetch=None):
        raise RuntimeError("history table unavailable")

    M = _screener(monkeypatch, boom)
    assert M._record_trigger_history() == 0


def test_the_recorders_sql_suppresses_a_repeat_pass_and_records_a_later_day(monkeypatch):
    """Execute the producer's OWN SQL against a real engine: a fake-only test proves the call, not the idempotency.

    Operator ruling 2026-11-14: "the producer, tested separately: duplicate suppression, plus a later legitimate
    update IS recorded." Same text as production, executed twice for the same scan day, then again for the next day.
    """
    import sqlite3

    M = _screener(monkeypatch, lambda sql, params=None, fetch=None: None)
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE pullback_macd_candidates (symbol TEXT, scan_date TEXT, score REAL, entry REAL, "
                "stop REAL, target1 REAL, tier TEXT, status TEXT)")
    con.execute("CREATE TABLE pullback_trigger_history (symbol TEXT, trigger_date TEXT, score REAL, entry REAL, "
                "stop REAL, target1 REAL, UNIQUE (symbol, trigger_date))")
    con.execute("INSERT INTO pullback_macd_candidates VALUES ('AAA','2026-11-14',88.0,10,9,12,'trigger','active')")
    con.execute("INSERT INTO pullback_macd_candidates VALUES ('BBB',NULL,77.0,10,9,12,'trigger','active')")

    con.execute(M._TRIGGER_HISTORY_INSERT)
    con.execute(M._TRIGGER_HISTORY_INSERT)  # the intraday monitor repeats the day's pass
    rows = con.execute("SELECT symbol, trigger_date, score FROM pullback_trigger_history").fetchall()
    assert len(rows) == 2, f"the repeated pass must add no row, got {rows}"
    assert ("AAA", "2026-11-14", 88.0) in rows

    # A later pass on a new scan day is a legitimate update and IS recorded — suppression is not a freeze.
    con.execute("UPDATE pullback_macd_candidates SET scan_date='2026-11-15', score=91.5 WHERE symbol='AAA'")
    con.execute(M._TRIGGER_HISTORY_INSERT)
    aaa = con.execute("SELECT trigger_date, score FROM pullback_trigger_history WHERE symbol='AAA' "
                      "ORDER BY trigger_date").fetchall()
    assert [(d, s) for d, s in aaa] == [("2026-11-14", 88.0), ("2026-11-15", 91.5)]


def test_the_producer_is_the_only_writer_outside_the_hot_router():
    """The candidate GET's INSERT is removed by the wiring patch; this pins where the write LIVES now.

    ``api_v2.py`` belongs to the integrator and is not edited in this branch, so this file cannot assert its
    content green here. What it can pin is that the producer owns a recorder and that no OTHER producer script
    writes the table.
    """
    writers = []
    for path in sorted((ROOT / "scripts").glob("*.py")):
        if path.name == "api_v2.py":
            continue
        if "INSERT INTO pullback_trigger_history" in path.read_text(encoding="utf-8", errors="ignore"):
            writers.append(path.name)
    assert writers == ["pullback_macd_screener.py"], writers
    assert ANCHOR  # keep the anchor greppable
