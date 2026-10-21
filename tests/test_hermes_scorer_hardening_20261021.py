"""Hermes scorer hardening 2026-10-21 — one bad card must never silence the scorer again.

Incident: watchlist_strategy_cards BHVN held target_price/stop_loss (and latest_price, support, resistance,
ideal_entry) = 'NaN'. hermes_watchlist_scorer aborted EVERY run from 2026-10-19 07:45 ET
(decimal.InvalidOperation in _f_rr) and nothing paged for ~2 days, until a freshness SLO fired.

  1. per-item isolation: an exception scoring one symbol is logged + counted; the run continues; all items
     failing exits non-zero.
  2. every factor treats NaN/Inf/None numerics as missing (a NaN RSI used to clamp to a perfect 100).
  3. loud failure: one queued host comms intent (fixed body, 12h dedupe; DIGEST -> P2) when >20% error or nothing
     lands. Never a send (PR #1899: a dispatched lane may not reach send_telegram).
  4. source fix: materialize_watchlist_strategy_cards drops a 'NaN' close (ticker_prices BHVN 2026-08-28,
     yfinance) and never upserts a non-finite level.
  5. --dry-run: READ ONLY session, writes nothing, sends nothing, no receipt.

Hermetic: fake DB connection, fake intent queue (or a temp ledger), no network, no Telegram.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_watchlist_scorer as hws  # noqa: E402

COVERS = ["scripts/hermes_watchlist_scorer.py", "scripts/materialize_watchlist_strategy_cards.py"]

_COLS = ["symbol", "rsi", "trend", "score", "watch_score_kind", "price", "realized_outcome", "thesis_win",
         "target_price", "stop_loss", "hermes_research_score", "options_edge_score", "thesis_outcome_n",
         "options_edge_n", "hermes_research_n", "social_score", "social_sentiment", "rvol", "confluence_score",
         "catalyst", "catalyst_verified", "sector"]


def _row(sym, **kw):
    base = dict.fromkeys(_COLS)
    base.update(symbol=sym, rsi=55, trend="bullish", score=60, price=Decimal("10"))
    base.update(kw)
    return tuple(base[c] for c in _COLS)


class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self._one = None
        self._all = []
        self.description = None

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.conn.sql.append(s)
        head = s.split(" ", 1)[0].upper()
        if head in ("INSERT", "UPDATE", "DELETE") or s.upper().startswith("CREATE"):
            if self.conn.readonly:
                raise AssertionError(f"write in read-only session: {s[:60]}")
            self.conn.writes.append((s, params))
            if self.conn.fail_write_for and params and self.conn.fail_write_for in params:
                raise RuntimeError("boom write")
        if "scope_tier IS NOT NULL" in s:
            self._one = (0,)
        elif s.startswith("SELECT wi.symbol"):
            self.description = [(c,) for c in _COLS]
            self._all = list(self.conn.rows)
        elif "FROM hermes_score_history" in s:
            self._all = []
        else:
            self._one, self._all = None, []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _Conn:
    def __init__(self, rows, fail_write_for=None):
        self.rows = rows
        self.sql, self.writes = [], []
        self.readonly = False
        self.commits = 0
        self.fail_write_for = fail_write_for

    def cursor(self, *a, **k):
        return _Cur(self)

    def set_session(self, readonly=False, **k):
        self.readonly = readonly

    def rollback(self):
        pass

    def commit(self):
        if self.readonly:
            raise AssertionError("commit in read-only session")
        self.commits += 1


@pytest.fixture
def env(monkeypatch, tmp_path):
    sent = []
    # main()'s G2 dual-import guard sees modules OTHER test files loaded as scripts.lib.X in this process; the
    # guard is exercised by its own tests, not here.
    import lib
    monkeypatch.setattr(lib, "assert_single_import_identity", lambda: None)
    monkeypatch.setattr(hws, "is_off_hours_et", lambda: False)
    monkeypatch.setattr(hws, "scoring_top_n", lambda limit=None: None)
    monkeypatch.setattr(hws, "_pills_map", lambda: {})
    monkeypatch.setattr(hws, "_sector_momentum", lambda conn: {})
    monkeypatch.setattr(hws, "_vix", lambda conn: 20.0)
    monkeypatch.setattr(hws, "_weights", lambda: {"technical_momentum": .3, "setup_quality": .3, "risk_reward": .4})
    # the alert is a queued host comms intent (never a send): capture the queue seam, isolate the cooldown state
    monkeypatch.setattr(hws, "_queue_host_intent", lambda **kw: sent.append((kw["summary"], kw)) or {"intent_id": "i1"})
    monkeypatch.setattr(hws, "ALERT_STATE_PATH", tmp_path / "alert_state.json")

    def use(rows, **kw):
        conn = _Conn(rows, **kw)
        monkeypatch.setattr(hws, "_conn", lambda: conn)
        return conn
    return use, sent


# ── 1. per-item isolation ──────────────────────────────────────────────────────

def test_one_bad_symbol_does_not_abort_the_run(env, monkeypatch):
    use, _ = env
    conn = use([_row("AAA"), _row("BAD"), _row("CCC")])
    real = hws.score_symbol

    def flaky(wi, *a, **k):
        if wi["symbol"] == "BAD":
            raise ValueError("synthetic bad card")
        return real(wi, *a, **k)
    monkeypatch.setattr(hws, "score_symbol", flaky)
    out = hws.run()
    assert out["items"] == 3 and out["scored"] == 2 and out["errored"] == 1
    assert out["skipped_errors"] == {"score:ValueError": 1} and out["error_symbols"] == ["BAD"]
    hist = [p for s, p in conn.writes if s.startswith("INSERT INTO hermes_score_history")]
    assert sorted(p[0] for p in hist) == ["AAA", "CCC"] and conn.commits == 1


def test_bhvn_nan_card_scores_and_writes_no_nan(env):
    use, _ = env
    conn = use([_row("BHVN", target_price=Decimal("NaN"), stop_loss=Decimal("NaN"), price=Decimal("NaN"),
                     rsi=Decimal("NaN")), _row("OK")])
    out = hws.run()
    assert out["errored"] == 0 and out["scored"] == 2
    for sql, params in conn.writes:
        for p in params or ():
            if isinstance(p, str) and p.startswith("{"):
                assert "NaN" not in p and "Infinity" not in p
                json.loads(p)
            if isinstance(p, float):
                assert p == p, f"NaN param in {sql[:50]}"


def test_write_error_rolls_back_only_that_symbol(env):
    use, _ = env
    conn = use([_row("AAA"), _row("ZZZ")], fail_write_for="ZZZ")
    out = hws.run()
    assert out["errored"] == 1 and out["skipped_errors"] == {"write:RuntimeError": 1}
    assert out["landed"] == 1
    assert any(s == "ROLLBACK TO SAVEPOINT hermes_sym" for s in conn.sql)


def test_all_items_failing_exits_nonzero(env, monkeypatch):
    use, sent = env
    use([_row("A"), _row("B")])
    monkeypatch.setattr(hws, "score_symbol", lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
    receipts = []
    import lib.lane_last_receipt as llr
    monkeypatch.setattr(llr, "write_lane_receipt", lambda *a, **k: receipts.append(k))
    monkeypatch.setattr(hws, "_pipeline_run", lambda: _FakeRun())
    with pytest.raises(SystemExit) as ei:
        hws.main(["--once"])
    assert ei.value.code not in (0, None)
    assert receipts[-1]["ok"] is False and receipts[-1]["output"]["produced_count"] == 0
    assert receipts[-1]["output"]["skipped_reasons"] == {"score:KeyError": 2}
    assert len(sent) == 1 and sent[0][0] == hws.ALERT_OUTAGE and sent[0][1]["subject"] == hws.ALERT_OUTAGE_SUBJECT


class _FakeRun:
    n = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def rows(self, n):
        _FakeRun.n = n


def test_clean_run_receipt_and_pipeline_rows(env, monkeypatch):
    use, sent = env
    use([_row("A"), _row("B")])
    receipts = []
    import lib.lane_last_receipt as llr
    monkeypatch.setattr(llr, "write_lane_receipt", lambda *a, **k: receipts.append((a, k)))
    monkeypatch.setattr(hws, "_pipeline_run", lambda: _FakeRun())
    assert hws.main(["--once"]) == 0
    (a, k), = receipts
    assert a == (hws.LANE_ID,) and k["ok"] is True and k["output"]["produced_count"] == 2
    assert k["output"]["attempted_count"] == 2 and _FakeRun.n == 2 and sent == []


# ── 2. NaN/Inf/None guards on every factor ────────────────────────────────────

NAN = Decimal("NaN")


@pytest.mark.parametrize("fn,args", [
    (lambda: hws._f_technical({"rsi": NAN, "trend": None}, {"rvol": float("inf"), "confluence_score": NAN}), None),
    (lambda: hws._f_setup({"score": NAN}), None),
    (lambda: hws._f_analyst({"has_professional_coverage": True, "recommendation_mean": NAN,
                             "upside_to_mean_target_pct": float("nan")}), None),
    (lambda: hws._f_social({"social_score": NAN, "social_sentiment": None}), None),
    (lambda: hws._f_hermes_research({"hermes_research_score": NAN}), None),
    (lambda: hws._f_options_edge({"options_edge_score": float("-inf")}), None),
    (lambda: hws._f_rr({"price": Decimal("10"), "target_price": NAN, "stop_loss": NAN}), None),
])
def test_factor_treats_non_finite_as_missing(fn, args):
    score, detail = fn()
    assert score is None


def test_nan_rsi_no_longer_scores_perfect():
    s, det = hws._f_technical({"rsi": NAN, "trend": "bullish"}, {})
    assert s == 82 and "nan" not in (det or "").lower()


def test_sector_momentum_ignores_nan_quotes():
    class C:
        def cursor(self):
            return self

        def execute(self, sql, params=None):
            self.p = params

        def fetchone(self):
            return (NAN,) if self.p else (Decimal("0.5"),)
    out = hws._sector_momentum(C())
    assert all(v == ("unknown", None) for v in out.values())


# ── 3. loud failure, deduped ───────────────────────────────────────────────────

@pytest.mark.parametrize("summary,cond", [
    ({"items": 10, "errored": 3, "landed": 7}, "degraded"),
    ({"items": 10, "errored": 2, "landed": 8}, None),
    ({"items": 10, "errored": 10, "landed": 0}, "outage"),
    ({"items": 0, "errored": 0, "landed": 0}, None),
    ({"items": 5, "errored": 0, "landed": 0}, None),
])
def test_failure_condition(summary, cond):
    assert hws.failure_condition(summary) == cond


def test_alert_is_queued_once_per_condition_per_12h(tmp_path):
    from datetime import datetime, timedelta, timezone
    queued = []
    state = tmp_path / "s.json"
    t0 = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)

    def q(**kw):
        queued.append(kw)
        return {"intent_id": f"i{len(queued)}"}
    for n, dt in ((3, 0), (4, 15), (9, 600)):  # three DEGRADED runs inside 10h -> one intent
        assert hws.emit_failure_alert({"items": 10, "errored": n, "landed": 10 - n}, queue=q, state_path=state,
                                      now=t0 + timedelta(minutes=dt)) == "degraded"
    assert len(queued) == 1 and queued[0]["subject"] == hws.ALERT_DEGRADED_SUBJECT
    assert queued[0]["summary"] == hws.ALERT_DEGRADED
    # a different condition is its own dedupe key
    hws.emit_failure_alert({"items": 4, "errored": 4, "landed": 0}, queue=q, state_path=state, now=t0)
    assert [k["subject"] for k in queued] == [hws.ALERT_DEGRADED_SUBJECT, hws.ALERT_OUTAGE_SUBJECT]
    # after 12h the same condition queues again
    hws.emit_failure_alert({"items": 10, "errored": 3, "landed": 7}, queue=q, state_path=state,
                           now=t0 + timedelta(minutes=hws.ALERT_DEDUPE_MINUTES + 1))
    assert len(queued) == 3


def test_alert_queue_failure_never_masks_run_and_keeps_retrying(tmp_path):
    calls = []

    def boom(**kw):
        calls.append(kw)
        raise ValueError("ledger_absent")
    state = tmp_path / "s.json"
    for _ in range(2):
        assert hws.emit_failure_alert({"items": 4, "errored": 4, "landed": 0}, queue=boom, state_path=state) == "outage"
    assert len(calls) == 2 and not state.exists()  # a refused queue never stamps the cooldown


def test_queue_host_intent_writes_one_intent_row_and_folds_duplicates(tmp_path, monkeypatch):
    """The real seam against a real (temp) coordination ledger: one QUEUED row on the scorer's own route."""
    sys.path.insert(0, str(ROOT))
    from scripts.lib.n8n_coordination_ledger import CoordinationLedger
    from scripts.lib.n8n_fabric_store import CommsIntentStore, load_intent_routes
    ledger = tmp_path / "ledger.sqlite"
    led = CoordinationLedger(ledger)
    CommsIntentStore(led, routes=load_intent_routes())  # creates comms_intents, as the consumer/gateway do
    getattr(led, "close", lambda: None)()
    r1 = hws._queue_host_intent(subject=hws.ALERT_OUTAGE_SUBJECT, summary=hws.ALERT_OUTAGE, execution_id="t1",
                                ledger_path=ledger)
    r2 = hws._queue_host_intent(subject=hws.ALERT_OUTAGE_SUBJECT, summary=hws.ALERT_OUTAGE, execution_id="t2",
                                ledger_path=ledger)
    assert r1.get("intent_id") and r2.get("duplicate") is True
    import sqlite3
    rows = sqlite3.connect(str(ledger)).execute("SELECT domain, kind, workflow_id FROM comms_intents").fetchall()
    assert rows == [(hws.ALERT_DOMAIN, hws.ALERT_KIND, "host.hermes_watchlist_scorer")]
    with pytest.raises(ValueError, match="ledger_absent"):
        hws._queue_host_intent(subject="x", summary="y", execution_id="t3", ledger_path=tmp_path / "missing.sqlite")


# ── 4. the NaN writer, at the source ──────────────────────────────────────────

import materialize_watchlist_strategy_cards as mat  # noqa: E402


class _TPConn:
    def __init__(self, closes):
        self.closes = closes

    def cursor(self, *a, **k):
        outer = self

        class C:
            def execute(self, *a, **k):
                pass

            def fetchall(self):
                return [(c,) for c in outer.closes]

            def close(self):
                pass
        return C()


def test_bhvn_nan_close_is_not_the_latest_price():
    # live ticker_prices BHVN (read-only 2026-10-21): four closes then close_price='NaN' on 2026-08-28.
    sr = mat.compute_support_resistance(_TPConn([Decimal("13.68"), Decimal("14.38"), Decimal("14.65"),
                                                 Decimal("16.12"), Decimal("NaN")]), "BHVN")
    assert sr["latest"] == 16.12


def test_level_helper():
    assert mat._level(Decimal("NaN")) is None and mat._level(float("inf")) is None
    assert mat._level(None) is None and mat._level("x") is None and mat._level(True) is None
    assert mat._level(Decimal("12.5")) == 12.5


def test_materialize_never_upserts_nan_levels(monkeypatch):
    """Full writer path for the BHVN shape: NaN close + 52w-range fallback + ATR (enrichment price None)."""
    # materialize() does `import psycopg2.extras` for RealDictCursor; CI has no psycopg2, and the fake
    # cursor ignores the factory, so a stub module keeps this test hermetic everywhere.
    import types
    pg = types.ModuleType("psycopg2")
    pg.extras = types.ModuleType("psycopg2.extras")
    pg.extras.RealDictCursor = object
    monkeypatch.setitem(sys.modules, "psycopg2", pg)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", pg.extras)

    class Cur:
        def __init__(self, conn):
            self.conn = conn
            self._all = []
            self._one = None

        def execute(self, sql, params=None):
            s = " ".join(sql.split())
            if s.startswith("INSERT INTO watchlist_strategy_cards"):
                self.conn.upserts.append(params)
            self._one = None
            self._all = [(c,) for c in self.conn.closes] if "FROM ticker_prices" in s else []

        def fetchall(self):
            return self._all

        def fetchone(self):
            return self._one

        def close(self):
            pass

    class Conn:
        closes = [Decimal("13.68"), Decimal("14.38"), Decimal("14.65"), Decimal("16.12"), Decimal("NaN")]

        def __init__(self):
            self.upserts = []

        def cursor(self, *a, **k):
            return Cur(self)

        def commit(self):
            pass

        def close(self):
            pass

        def rollback(self):
            pass

    conn = Conn()
    monkeypatch.setattr(mat, "_get_conn", lambda: conn)
    enrich = {"BHVN": {"price": None, "week52_low_pct": 51.6, "week52_high_pct": -38.92, "atr": 0.77}}
    monkeypatch.setattr(mat, "_load", lambda f, default=None: enrich if f == "ticker_enrichment_cache.json" else {})
    for closes in (Conn.closes, [Decimal("NaN")] * 3):
        Conn.closes = closes
        conn.upserts.clear()
        mat.materialize(["BHVN"])
        (params,), = [conn.upserts]
        for v in params[2:11] + (params[18],):
            assert v is None or (isinstance(v, float) and v == v), params[:12]


# ── 5. write-free --dry-run (the n8n shadow health probe) ─────────────────────

def test_dry_run_writes_nothing_and_sends_nothing(env, monkeypatch, capsys):
    use, sent = env
    conn = use([_row("AAA"), _row("BHVN", target_price=NAN, stop_loss=NAN)])
    import lib.lane_last_receipt as llr
    monkeypatch.setattr(llr, "write_lane_receipt", lambda *a, **k: pytest.fail("dry run wrote a receipt"))
    monkeypatch.setattr(hws, "_pipeline_run", lambda: pytest.fail("dry run opened a pipeline_runs row"))
    assert hws.main(["--once", "--dry-run"]) == 0
    assert conn.readonly is True and conn.writes == [] and conn.commits == 0 and sent == []
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and '"lane_id": "hermes-watchlist-scorer"' in out


def test_dry_run_reports_would_alert_and_exits_1_when_all_fail(env, monkeypatch):
    use, sent = env
    conn = use([_row("A")])
    monkeypatch.setattr(hws, "score_symbol", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
    assert hws.main(["--dry-run"]) == 1
    assert sent == [] and conn.writes == []
