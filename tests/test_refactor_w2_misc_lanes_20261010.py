"""Refactor wave 2, bucket V2 (cron -> n8n, 2026-10-10): five single-script lanes.

- trade_backtest_engine.py (cron L365): --dry-run [--limit N] selects on a READ ONLY session, backtests
  (yfinance reads) and never reaches upsert_result/commit; receipt + exit 1 on failure.
- hermes_news_bridge.py (cron L413): --dry-run runs the candidate SELECT + scoring READ ONLY and never
  reaches write_news_articles/commit; a real run exits 1 when every insert attempt errored.
- update_lockup_earnings_dates.py (cron L490): --dry-run computes the snaps and never writes the config
  or an alert row; receipt.
- prewarm_eligible_cache.py (cron L573, new entrypoint for an inline `python -c`): --dry-run computes with
  write_cache=False; a real run exits 1 when the DB probe fails or the cache write did not land.
- journal_tilt_morning_hook.py (cron L626): --dry-run reports would_queue / already_queued and never
  reaches the INSERT; a swallowed INSERT failure (db_adapter returns None) is now exit 1.
Hermetic: fake DB connections / modules, tmp files, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Required CI has no psycopg2 (these tests use fake connections only). Install a minimal stand-in ONLY when the real
# driver is absent, so the dry-run safety tests still run in CI instead of being skipped by importorskip.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    import types as _types

    _pg = _types.ModuleType("psycopg2")
    _pg_extras = _types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import hermes_news_bridge as hnb  # noqa: E402
import journal_tilt_morning_hook as jt  # noqa: E402
import prewarm_eligible_cache as pec  # noqa: E402
import trade_backtest_engine as tbe  # noqa: E402
import update_lockup_earnings_dates as ule  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402


def _forbid(monkeypatch, obj, name):
    def boom(*a, **k):
        raise AssertionError(f"dry run reached {name}")

    monkeypatch.setattr(obj, name, boom)


class FakeConn:
    def __init__(self, answers=()):
        self.answers = list(answers)
        self.log: list = []

    def cursor(self, *a, **k):
        conn = self

        class C:
            def execute(self, sql, params=None):
                flat = " ".join(sql.split())
                conn.log.append(("execute", flat))
                self._rows = next((rows for sub, rows in conn.answers if sub in flat), [])

            def fetchall(self):
                return list(self._rows)

            def fetchone(self):
                return self._rows[0] if self._rows else None

            def close(self):
                pass

        return C()

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))

    def set_session(self, **kw):
        self.log.append(("set_session", kw))

    def close(self):
        self.log.append(("close",))

    def writes(self):
        return [e for e in self.log if e[0] == "execute" and e[1].split()[0].upper() in ("INSERT", "UPDATE", "DELETE")]


@pytest.fixture(autouse=True)
def _state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))


def _receipt(name):
    return json.loads(llr.receipt_path(name).read_text())


# ── trade_backtest_engine (L365) ──────────────────────────────────────────────────────

TRADES = [{"trade_key": f"S{i}:acct:2026-01-0{i}", "symbol": f"S{i}"} for i in range(1, 5)]


def _fake_backtest(trade, cache):
    return {"trade_key": trade["trade_key"], "data_quality": "full", "left_on_table_20d": 10.0, "overall_grade": "B"}


def test_backtest_dry_run_never_upserts(monkeypatch):
    conns = []

    def fake_db():
        conns.append(FakeConn([("FROM trade_closed", TRADES)]))
        return conns[-1]

    monkeypatch.setattr(tbe, "get_db", fake_db)
    monkeypatch.setattr(tbe, "backtest_trade", _fake_backtest)
    _forbid(monkeypatch, tbe, "upsert_result")
    rep = tbe.preview(limit=3)
    assert rep["trades_selected"] == 4 and rep["trades_backtested"] == 3 and rep["would_upsert"] == 3
    assert rep["left_on_table_20d_preview_sum"] == 30.0
    assert len(conns) == 1 and ("set_session", {"readonly": True}) in conns[0].log
    assert conns[0].writes() == [] and ("commit",) not in conns[0].log
    assert tbe.main(["--dry-run", "--limit", "2"]) == 0
    assert not llr.receipt_path("trade_backtest_engine").exists()


def test_backtest_preview_source_never_names_the_writer():
    src = inspect.getsource(tbe.preview)
    assert "upsert_result" not in src and "commit" not in src and "readonly=True" in src


def test_backtest_receipt_and_exit(monkeypatch):
    monkeypatch.setattr(tbe, "run_all", lambda limit=None: {"full": 2, "partial": 0, "insufficient": 1, "error": 1})
    monkeypatch.setattr(tbe, "print_summary", lambda: None)
    assert tbe.main([]) == 0  # per-trade data gaps are findings
    r = _receipt("trade_backtest_engine")
    assert r["status"] == "ok" and r["summary"]["trades"] == 4

    def boom(limit=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(tbe, "run_all", boom)
    assert tbe.main([]) == 1
    r2 = _receipt("trade_backtest_engine")
    assert r2["status"] == "failed" and r2["ok_at"] == r["ok_at"]


# ── hermes_news_bridge (L413) ─────────────────────────────────────────────────────────

HROWS = [
    (11, "AAA", "AAA beats", "summary", '["https://x/a"]', 0.8, None, "2026-10-09", "momentum_catalyst", None),
    (12, "BBB", "BBB guides up", None, None, None, None, "2026-10-09", "momentum_catalyst", None),
]


def test_news_bridge_dry_run_never_writes(monkeypatch):
    conn = FakeConn([("FROM hermes_research_intelligence", HROWS)])
    monkeypatch.setattr(hnb, "db", lambda: conn)
    monkeypatch.setattr(hnb, "load_env", lambda: None)
    calls = []  # recorded, not raised: run() catches Exception around the writer
    monkeypatch.setattr(hnb, "write_news_articles", lambda *a, **k: calls.append(a))
    rep = hnb.run(dry_run=True)
    assert calls == []
    assert rep["dry_run"] is True and rep["candidates"] == 2 and rep["would_bridge"] == 2
    assert ("set_session", {"readonly": True}) in conn.log
    assert conn.writes() == [] and ("commit",) not in conn.log


def test_news_bridge_dry_branch_precedes_writer():
    src = inspect.getsource(hnb.run)
    assert src.index("if dry_run:\n            would.append") < src.index("write_news_articles(")


def test_news_bridge_all_inserts_errored_is_exit_1(monkeypatch):
    conn = FakeConn([("FROM hermes_research_intelligence", HROWS)])
    monkeypatch.setattr(hnb, "db", lambda: conn)
    monkeypatch.setattr(hnb, "load_env", lambda: None)

    def bad_write(cur, rows, source):
        raise RuntimeError("relation news_articles is locked")

    monkeypatch.setattr(hnb, "write_news_articles", bad_write)
    assert hnb.main([]) == 1
    r = _receipt("hermes_news_bridge")
    assert r["status"] == "failed" and r["summary"]["insert_errors"] == 2


def test_news_bridge_dup_skips_are_success(monkeypatch):
    conn = FakeConn([("FROM hermes_research_intelligence", HROWS)])
    monkeypatch.setattr(hnb, "db", lambda: conn)
    monkeypatch.setattr(hnb, "load_env", lambda: None)
    monkeypatch.setattr(
        hnb, "write_news_articles", lambda cur, rows, source: types.SimpleNamespace(rows_written=0, ids=[])
    )
    assert hnb.main([]) == 0
    r = _receipt("hermes_news_bridge")
    assert r["status"] == "ok" and r["summary"]["skipped_dup"] == 2 and ("commit",) in conn.log


# ── update_lockup_earnings_dates (L490) ───────────────────────────────────────────────


def _lockup_cfg(tmp_path, monkeypatch):
    est = (date.today() + timedelta(days=30)).isoformat()
    cfg = {
        "lockups": {
            "SPCX": {
                "tranches": [
                    {"date": est, "approx": True, "desc": "2nd trading day after Q3 earnings", "pct": 10},
                    {"date": "2027-06-01", "approx": False, "desc": "fixed", "pct": 5},
                ]
            }
        }
    }
    p = tmp_path / "ipo_lockups.json"
    p.write_text(json.dumps(cfg, indent=2))
    monkeypatch.setattr(ule, "CFG", p)
    monkeypatch.setattr(ule, "_next_earnings", lambda sym: date.today() + timedelta(days=33))
    return p


def test_lockup_dry_run_writes_nothing(tmp_path, monkeypatch):
    p = _lockup_cfg(tmp_path, monkeypatch)
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    _forbid(monkeypatch, ule, "_apply")
    fake = types.ModuleType("alert_event_writer")
    fake.save_alert_event = lambda **k: (_ for _ in ()).throw(AssertionError("dry run wrote an alert row"))
    monkeypatch.setitem(sys.modules, "alert_event_writer", fake)
    res = ule.run(dry_run=True)
    assert res["dry_run"] is True and len(res["changed"]) == 1 and res["would_alert"] == 1
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before
    assert ule.main(["--dry-run"]) == 0
    assert hashlib.sha256(p.read_bytes()).hexdigest() == before
    assert not llr.receipt_path("update_lockup_earnings_dates").exists()


def test_lockup_live_writes_config_alert_and_receipt(tmp_path, monkeypatch):
    p = _lockup_cfg(tmp_path, monkeypatch)
    sent = []
    fake = types.ModuleType("alert_event_writer")
    fake.save_alert_event = lambda **k: sent.append(k)
    monkeypatch.setitem(sys.modules, "alert_event_writer", fake)
    assert ule.main([]) == 0
    t = json.loads(p.read_text())["lockups"]["SPCX"]["tranches"][0]
    assert t["approx"] is False and "snapped" in t["note"] and len(sent) == 1
    r = _receipt("update_lockup_earnings_dates")
    assert r["status"] == "ok" and r["summary"]["changed"] == 1


def test_lockup_unreadable_config_is_exit_1(tmp_path, monkeypatch):
    monkeypatch.setattr(ule, "CFG", tmp_path / "missing.json")
    assert ule.main([]) == 1
    assert _receipt("update_lockup_earnings_dates")["status"] == "failed"


# ── prewarm_eligible_cache (L573) ─────────────────────────────────────────────────────


def _fake_engine(tmp_path, monkeypatch, *, really_write=True):
    calls = []
    mod = types.ModuleType("reporting_engine")
    mod._ELIGIBLE_CACHE = tmp_path / "analyst_eligible_cache.json"

    def payload(*, use_cache=True, write_cache=True, **kw):
        calls.append({"use_cache": use_cache, "write_cache": write_cache})
        doc = {"count": 3, "watchlist_count": 7, "needs_refresh": 2, "stale_days": 6, "_cached_at": 123.5}
        if write_cache and really_write:
            mod._ELIGIBLE_CACHE.write_text(json.dumps(doc))
        return doc

    mod.eligible_report_payload = payload
    monkeypatch.setitem(sys.modules, "reporting_engine", mod)
    return mod, calls


def test_prewarm_dry_run_never_writes_cache(tmp_path, monkeypatch):
    mod, calls = _fake_engine(tmp_path, monkeypatch)
    probes = []
    monkeypatch.setattr(pec, "_probe_db", lambda readonly=False: probes.append(readonly))
    res = pec.run(dry_run=True)
    assert calls == [{"use_cache": False, "write_cache": False}] and probes == [True]
    assert res["dry_run"] is True and res["watchlist_count"] == 7
    assert not mod._ELIGIBLE_CACHE.exists()
    assert pec.main(["--dry-run"]) == 0 and not mod._ELIGIBLE_CACHE.exists()
    assert not llr.receipt_path("prewarm_eligible_cache").exists()


def test_prewarm_live_verifies_cache_landed(tmp_path, monkeypatch):
    mod, calls = _fake_engine(tmp_path, monkeypatch)
    monkeypatch.setattr(pec, "_probe_db", lambda readonly=False: None)
    assert pec.main([]) == 0
    assert calls == [{"use_cache": False, "write_cache": True}]
    assert _receipt("prewarm_eligible_cache")["status"] == "ok"


def test_prewarm_swallowed_write_or_db_failure_is_exit_1(tmp_path, monkeypatch):
    _fake_engine(tmp_path, monkeypatch, really_write=False)
    monkeypatch.setattr(pec, "_probe_db", lambda readonly=False: None)
    assert pec.main([]) == 1
    assert _receipt("prewarm_eligible_cache")["status"] == "failed"

    def no_db(readonly=False):
        raise RuntimeError("no database connection")

    monkeypatch.setattr(pec, "_probe_db", no_db)
    assert pec.main([]) == 1
    assert _receipt("prewarm_eligible_cache")["error"] == "RuntimeError"  # helper scrubs to the type


# ── journal_tilt_morning_hook (L626) ──────────────────────────────────────────────────


def _tilt(monkeypatch, *, existing=None, insert_result=True, tilt_trades=3):
    import db_adapter

    conn = FakeConn()
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    sql_log = []

    def fake_execute(sql, params=None, fetch=None):
        sql_log.append(" ".join(sql.split()))
        if sql.strip().upper().startswith("SELECT"):
            return existing
        return insert_result

    monkeypatch.setattr(db_adapter, "_execute", fake_execute)
    tiv = types.ModuleType("journal_trade_in_view")
    tiv.behavioral_analytics = lambda days=7: {
        "tilt": {"trades": tilt_trades, "net_pnl": -900},
        "after_losing_day": {"trades": 2, "win_rate": 50, "net_pnl": 10},
    }
    monkeypatch.setitem(sys.modules, "journal_trade_in_view", tiv)
    return conn, sql_log


def test_tilt_dry_run_reports_would_queue_and_never_inserts(monkeypatch):
    conn, sql_log = _tilt(monkeypatch)
    _forbid(monkeypatch, jt, "_insert")
    res = jt.run(dry_run=True)
    assert res["outcome"] == "would_queue" and res["review_item_id"].startswith("tradeinview-tilt-")
    assert all(s.startswith("SELECT") for s in sql_log)
    assert ("set_session", {"readonly": True}) in conn.log
    assert jt.main(["--dry-run"]) == 0
    assert not llr.receipt_path("journal_tilt_morning_hook").exists()


def test_tilt_dry_run_output_follows_state(monkeypatch):
    _tilt(monkeypatch, existing={"id": 1})
    assert jt.run(dry_run=True)["outcome"] == "already_queued"
    _tilt(monkeypatch, tilt_trades=0)
    assert jt.run(dry_run=True)["outcome"] == "not_needed"


def test_tilt_live_queues_and_receipts(monkeypatch):
    _, sql_log = _tilt(monkeypatch)
    assert jt.main([]) == 0
    assert any(s.startswith("INSERT INTO operator_review_queue") for s in sql_log)
    r = _receipt("journal_tilt_morning_hook")
    assert r["status"] == "ok" and r["summary"]["outcome"] == "queued"


def test_tilt_swallowed_insert_failure_is_exit_1(monkeypatch):
    _tilt(monkeypatch, insert_result=None)  # db_adapter._execute returns None on SQL error
    assert jt.main([]) == 1
    assert _receipt("journal_tilt_morning_hook")["status"] == "failed"
