"""Stale / silent cron jobs found by the 2026-10-09 cron audit (operator: "fix the broken cron jobs").

- document_mentions backfill: re-read the same ~4000 undecidable documents per table every hour, was killed by
  its 25-min timeout in the third table since 09-30 (sec_form4 never reached, log empty) → per-table
  watermark, time budget, flushed progress lines.
- job_coverage_monitor: 9 FAILs that were schedule-blind (market-hours jobs checked at 08:30/20:30), matched a
  retired line or a pre-fold script, ignored systemd timers and the dev-tree logs.
- schwab_stream_daemon: one websocket drop ended capture for the day (no supervisor ever restarted it) and the
  log stayed empty until exit (block-buffered).
- run_research_intelligence_overnight.sh: "${PROJ}/.venv/bin/python" does not exist in a release dir.
- paper post-close processors (thesis outcomes, TCA): spawned "<release>/.venv/bin/python" → silent since 09-16.
- outcome checkpoints: "BOOK" pseudo-subjects sat in OUTCOME_PENDING_DATA forever.
Fakes only: no DB, no network, no broker.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


# ── document_mentions backfill ────────────────────────────────────────────────────────────────────────────
def test_backfill_scans_forward_from_the_watermark():
    import backfill_document_mentions as b

    spec = {"id": "id", "own_symbol": "symbol"}
    sql, params = b.select_sql("news_articles", spec, "''", None)
    assert "ORDER BY id DESC" in sql and params == ("news_articles",)
    sql, params = b.select_sql("news_articles", spec, "''", 5000)
    assert "AND id > %s" in sql and "ORDER BY id ASC" in sql
    assert params == ("news_articles", 5000 - b.WATERMARK_MARGIN)
    assert b.select_sql("t", spec, "''", 10)[1] == ("t", 0)


def test_backfill_moves_marks_only_on_apply_and_respects_budget(monkeypatch, tmp_path, capsys):
    import backfill_document_mentions as b
    import lib.document_mentions as dm

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(dm, "SOURCES", {"a_table": {}, "b_table": {}}, raising=False)
    seen = []

    def fake_run(table, limit, apply, mark=None, deadline=None, seed=False):
        seen.append((table, mark, seed))
        return {"table": table, "documents": 3, "scanned": 3, "multi": 0, "subject": 1, "mentioned": 0,
                "undecided_docs": 0, "no_mention": 2, "written": 1 if apply else 0,
                "max_id": {"a_table": 120, "b_table": 7}[table], "budget_hit": False}

    monkeypatch.setattr(b, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["x", "--all"])
    assert b.main() == 0
    assert not b.watermark_path().exists()                      # dry run never moves a mark
    monkeypatch.setattr(sys, "argv", ["x", "--all", "--apply"])
    assert b.main() == 0
    assert b.load_watermarks() == {"a_table": 120, "b_table": 7}
    seen.clear()
    assert b.main() == 0
    assert seen == [("a_table", 120, True), ("b_table", 7, True)]
    monkeypatch.setattr(sys, "argv", ["x", "--all", "--apply", "--rescan"])
    seen.clear()
    assert b.main() == 0
    assert seen == [("a_table", None, False), ("b_table", None, False)]
    out = capsys.readouterr().out
    assert "scanned=3" in out and "mark=120" in out


def test_backfill_budget_spent_skips_remaining_tables(monkeypatch, tmp_path, capsys):
    import backfill_document_mentions as b
    import lib.document_mentions as dm

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(dm, "SOURCES", {"a_table": {}, "b_table": {}}, raising=False)
    monkeypatch.setattr(sys, "argv", ["x", "--all", "--budget-s", "0.000001"])
    monkeypatch.setattr(b, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran past budget")))
    assert b.main() == 0
    assert capsys.readouterr().out.count("skipped (budget spent)") == 2


# ── job coverage monitor ──────────────────────────────────────────────────────────────────────────────────
def test_hours_since_due_measures_from_the_last_scheduled_fire():
    import job_coverage_monitor as m

    fri_0830 = dt.datetime(2026, 10, 9, 8, 30)
    # */30 10-15 weekdays: last due Thu 15:30 → 17 h idle at Fri 08:30.
    assert abs(m._hours_since_due(["*/30 10-15 * * 1-5"], fri_0830) - 17.0) < 0.01
    assert m._hours_since_due(["*/5 * * * *"], fri_0830) == 0.0
    assert m._hours_since_due([], fri_0830) == 0.0
    # hermes_coordinator is deferred 06-12 weekdays by llm_priority_guard.sh: last due 05:45.
    hc = next(j for j in m.REGISTRY if j["name"] == "hermes_coordinator")
    assert abs(m._hours_since_due(hc["schedule_exprs"], fri_0830) - 2.75) < 0.01


def _evaluate(monkeypatch, *, cron, ages, idle, timers=()):
    import job_coverage_monitor as m

    monkeypatch.setattr(m, "_crontab_lines", lambda: cron)
    monkeypatch.setattr(m, "_log_age_h", lambda f: ages.get(f))
    monkeypatch.setattr(m, "_db_age_h", lambda sql: 1.0)
    monkeypatch.setattr(m, "_timer_active", lambda u: u in timers)
    monkeypatch.setattr(m, "_hours_since_due", lambda exprs, now=None: idle)
    return {r["job"]: r for r in m.evaluate()}


def test_market_hours_job_is_not_stale_before_its_window(monkeypatch):
    cron = ["*/30 10-15 * * 1-5 cd $PROJ && $PY scripts/watchlist_proposal_bridge.py --apply"]
    r = _evaluate(monkeypatch, cron=cron, ages={"watchlist_proposal_bridge.log": 17.0}, idle=17.0)
    assert r["watchlist_proposal_bridge"]["status"] == "OK"
    # In its window the old cadence still applies.
    r = _evaluate(monkeypatch, cron=cron, ages={"watchlist_proposal_bridge.log": 1.5}, idle=0.2)
    assert r["watchlist_proposal_bridge"]["status"] == "STALE"


def test_daily_job_that_missed_its_fire_is_still_stale(monkeypatch):
    cron = ["0 7 * * 1-5 cd $PROJ && $PY scripts/iris_proposal_curator.py"]
    r = _evaluate(monkeypatch, cron=cron, ages={"iris_proposal_curator.log": 37.5}, idle=13.5)
    assert r["iris_proposal_curator"]["status"] == "STALE"


def test_schedulers_that_moved_are_recognised(monkeypatch):
    cron = ["*/15 10-20 * * * /x/scripts/run_watchlist_agent_jobs_offpeak.sh >> /x/logs/w.log 2>&1",
            "5 * * * * bash /x/scripts/run_drive_syncs.sh --apply >> /home/johnclaw/logs/drive-syncs.log 2>&1",
            "*/30 9-16 * * 1-5 cd $PROJ && bash scripts/market_day_gate.sh bash scripts/run_protection_pipeline.sh"]
    r = _evaluate(monkeypatch, cron=cron, ages={"drive-syncs.log": 0.2, "protection_pipeline.log": 0.3},
                  idle=0.0, timers={"aegis-overnight.timer"})
    assert r["process_watchlist_agent_jobs"]["status"] == "OK"
    assert r["drive_sync"]["status"] == "OK"
    assert r["aegis_overnight"]["status"] == "OK"
    assert r["protection_pipeline"]["status"] == "OK"
    r = _evaluate(monkeypatch, cron=[], ages={}, idle=0.0)
    assert r["aegis_overnight"]["status"] == "NOT_SCHEDULED"


def test_log_bases_include_the_dev_tree(monkeypatch, tmp_path):
    import job_coverage_monitor as m

    monkeypatch.setenv("TRADEAI_DEV_TREE", str(tmp_path))
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "options_monitor.log").write_text("x")
    monkeypatch.setattr(m, "LOGS", tmp_path / "nowhere")
    assert m._log_age_h("options_monitor.log") == 0.0


# ── schwab stream supervisor ──────────────────────────────────────────────────────────────────────────────
def test_stream_reconnects_after_a_drop_while_market_open():
    import schwab_stream_daemon as d

    rcs, sleeps = iter([1, 1, 0]), []
    assert d.supervise(lambda: next(rcs), lambda: True, sleeps.append, 5, 30) == 0
    assert sleeps == [30, 60]


def test_stream_stops_reconnecting_when_market_closes_or_cap_reached():
    import schwab_stream_daemon as d

    calls = []

    def once():
        calls.append(1)
        return 1

    # session closed → nothing left to capture → clean exit 0 (Agent A review of #1627), no reconnect
    assert d.supervise(once, lambda: False, lambda s: None, 5, 30) == 0 and len(calls) == 1
    calls.clear()
    assert d.supervise(once, lambda: True, lambda s: None, 3, 30) == 1 and len(calls) == 4
    src = (ROOT / "scripts/schwab_stream_daemon.py").read_text(encoding="utf-8")
    assert "line_buffering=True" in src


# ── interpreter resolution in release dirs ────────────────────────────────────────────────────────────────
def test_ri_overnight_resolves_an_interpreter_that_exists():
    sh = ROOT / "scripts/run_research_intelligence_overnight.sh"
    src = sh.read_text(encoding="utf-8")
    assert 'PY="${PROJ}/.venv/bin/python"\n' not in src
    # Train 2026-10-09: the shared resolver from #1575 (scripts/lib/venv_python.sh) replaced the inline loop.
    assert 'tradeai_venv_python "$PROJ"' in src
    assert subprocess.run(["bash", "-n", str(sh)]).returncode == 0


def test_post_close_processors_use_the_running_interpreter():
    for f in ("alpaca_paper_adapter.py", "paper_trade_closer.py", "paper_trade_monitor.py"):
        src = (ROOT / "scripts" / f).read_text(encoding="utf-8")
        assert 'str(PROJECT_ROOT / ".venv/bin/python")' not in src, f
        assert "[_child_python(PROJECT_ROOT)," in src, f  # shared resolver (#1575/#1576)


# ── outcome checkpoints ───────────────────────────────────────────────────────────────────────────────────
def test_book_level_checkpoints_are_never_price_resolvable():
    from lib import outcome_resolution as o

    cp = {"checkpoint_id": "x", "subject_id": "BOOK", "status": o.STATUS_PENDING_DATA,
          "due_at": "2026-09-29T08:30:59+00:00",
          "original_decision_state": {"as_of": "2026-08-30T08:30:59+00:00"}}
    assert o.price_resolvable(cp) == (False, "book_level_subject_book")
    row = o.classify_pending_checkpoint(cp, price_lookup=lambda s, d: None,
                                        now=dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc))
    assert row["class"] == o.CLASS_NEVER and row["action"] == "expire"
    aapl = dict(cp, subject_id="AAPL")
    assert o.price_resolvable(aapl) == (True, None)


# ── schwab stream: session window + quote dedupe + receipt (operator "fix", 2026-10-09 evening) ───────────────
def _et(h, m, day=9):
    from zoneinfo import ZoneInfo

    return dt.datetime(2026, 10, day, h, m, tzinfo=ZoneInfo("America/New_York"))


def test_stream_session_window_stops_at_the_close(monkeypatch):
    import schwab_stream_daemon as d

    monkeypatch.delenv("STREAM_SESSIONS", raising=False)
    assert d._in_session(_et(9, 31)) and d._in_session(_et(15, 59))
    assert not d._in_session(_et(16, 0)) and not d._in_session(_et(18, 30)) and not d._in_session(_et(9, 0))
    assert not d._in_session(_et(12, 0, day=10))                               # Saturday
    assert not d._in_session(dt.datetime(2026, 11, 27, 13, 30, tzinfo=_et(9, 31).tzinfo))  # early close 13:00
    monkeypatch.setenv("STREAM_SESSIONS", "regular, afterhours")              # config opt-in to post-market
    assert d._in_session(_et(18, 30)) and not d._in_session(_et(20, 30))


def test_stream_schwab_isopen_only_vetoes(monkeypatch):
    import schwab_stream_daemon as d

    monkeypatch.delenv("STREAM_SESSIONS", raising=False)
    monkeypatch.setattr(d, "_schwab_is_open", lambda: True)                    # whole-day flag true after close
    assert d._market_open(_et(10, 0)) and not d._market_open(_et(17, 0))
    monkeypatch.setattr(d, "_schwab_is_open", lambda: False)
    assert not d._market_open(_et(10, 0))


class _Cur:
    def __init__(self):
        self.rows = []

    def execute(self, sql, params=None):
        self.rows.append((sql.split("INTO")[1].split()[0], params))


class _Conn:
    def __init__(self):
        self.c = _Cur()

    def cursor(self):
        return self.c

    def commit(self):
        pass


def test_stream_unchanged_quote_is_not_reinserted():
    import schwab_stream_daemon as d

    cap, conn = d.Capture(), _Conn()
    cap.on_l1({"content": [{"key": "AAPL", "LAST_PRICE": 1.0, "BID_PRICE": 0.9, "ASK_PRICE": 1.1}]})
    cap.flush(conn)
    cap.flush(conn)                                                            # nothing changed → skipped
    cap.on_l1({"content": [{"key": "AAPL", "LAST_PRICE": 1.0}]})               # same values re-sent → skipped
    cap.flush(conn)
    cap.on_l1({"content": [{"key": "AAPL", "BID_PRICE": 0.95}]})               # changed → written
    cap.flush(conn)
    quotes = [r for r in conn.c.rows if r[0] == "schwab_stream_quotes"]
    assert len(quotes) == 2 and cap.q_writes == 2 and cap.q_skipped == 2


def test_stream_receipt_latest_and_run_log(tmp_path):
    import json as _json

    import schwab_stream_daemon as d

    rec = {"pid": 1, "status": "running", "heartbeats": 0}
    d._write_receipt(rec, dirpath=tmp_path)
    d._write_receipt({**rec, "heartbeats": 1}, dirpath=tmp_path)                # heartbeat: latest only
    d._write_receipt({**rec, "status": "stopped", "stop_reason": "session_end"}, final=True, dirpath=tmp_path)
    latest = _json.loads((tmp_path / "schwab_stream_receipt.json").read_text(encoding="utf-8"))
    assert latest["stop_reason"] == "session_end" and latest["updated_at"]
    lines = (tmp_path / "schwab_stream_runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert [_json.loads(x)["status"] for x in lines] == ["running", "stopped"]
    d._write_receipt(rec, dirpath=tmp_path / "f" / "x\0bad")                    # never raises


def test_stream_run_outside_session_exits_with_receipt(monkeypatch, tmp_path):
    import asyncio
    import json as _json

    import schwab_stream_daemon as d

    monkeypatch.setenv("STREAM_RECEIPT_DIR", str(tmp_path))
    monkeypatch.setattr(d, "KILL_FILE", tmp_path / "nope")
    monkeypatch.setattr(d, "_market_open", lambda now=None: False)
    assert asyncio.run(d.run()) == 0
    assert _json.loads((tmp_path / "schwab_stream_receipt.json").read_text(encoding="utf-8"))["stop_reason"] == "outside_session"


# ── #1627 review follow-ups: fail-closed session check, clean session_end rc, per-symbol quote heartbeat ─────
class _FakeSC:
    def __init__(self, raise_on_msg=False):
        self.raise_on_msg = raise_on_msg

    async def login(self):
        pass

    async def logout(self):
        pass

    def add_level_one_equity_handler(self, h):
        pass

    def add_nasdaq_book_handler(self, h):
        pass

    async def level_one_equity_subs(self, s):
        pass

    async def nasdaq_book_subs(self, s):
        pass

    async def handle_message(self):
        if self.raise_on_msg:
            raise ConnectionError("1000 normal closure")


class _ClosingConn(_Conn):
    closed = False

    def close(self):
        self.closed = True


def _run_with_fakes(monkeypatch, tmp_path, statuses, sc):
    import asyncio
    import json as _json
    import types

    import schwab_stream_daemon as d

    seq = iter(statuses)
    conn = _ClosingConn()
    monkeypatch.setenv("STREAM_RECEIPT_DIR", str(tmp_path))
    monkeypatch.setattr(d, "KILL_FILE", tmp_path / "nope")
    monkeypatch.setattr(d, "_session_status", lambda now=None, sessions=None: next(seq))
    monkeypatch.setattr(d, "_schwab_is_open", lambda: True)
    monkeypatch.setattr(d, "_symbols", lambda limit: ["AAPL"])
    monkeypatch.setattr(d, "_scalp_symbols", lambda limit: [])
    monkeypatch.setattr(d, "_conn", lambda: conn)
    monkeypatch.setitem(sys.modules, "schwab_transport",
                        types.SimpleNamespace(build_stream_client=lambda: (sc, None)))
    rc = asyncio.run(d.run())
    rec = _json.loads((tmp_path / "schwab_stream_receipt.json").read_text(encoding="utf-8"))
    return rc, rec, conn


def test_stream_session_check_error_fails_closed(monkeypatch, tmp_path):
    import schwab_stream_daemon as d

    def boom(now=None):
        raise RuntimeError("tz db missing")

    monkeypatch.setattr(sys.modules.get("market_session") or __import__("market_session"), "current_market_session", boom)
    assert d._session_status() == "error" and d._in_session() is False and d._market_open() is False
    rc, rec, conn = _run_with_fakes(monkeypatch, tmp_path, ["open", "error"], _FakeSC())
    assert rec["stop_reason"] == "session_check_error" and rc == d.SESSION_CHECK_ERROR_RC != 1 and conn.closed
    assert d.supervise(lambda: d.SESSION_CHECK_ERROR_RC, lambda: True, lambda s: None, 5, 30) == 2   # no retry


def test_stream_session_end_is_a_clean_exit(monkeypatch, tmp_path):
    rc, rec, conn = _run_with_fakes(monkeypatch, tmp_path, ["open", "closed"], _FakeSC())
    assert (rc, rec["stop_reason"], rec["rc"], conn.closed) == (0, "session_end", 0, True)
    # the socket closing at/after the close is a session end, not a stream_error/rc=1
    rc, rec, conn = _run_with_fakes(monkeypatch, tmp_path, ["open", "closed"], _FakeSC(raise_on_msg=True))
    assert (rc, rec["stop_reason"], conn.closed) == (0, "session_end", True)
    # a drop mid-session is still a stream_error for the supervisor to reconnect
    rc, rec, _ = _run_with_fakes(monkeypatch, tmp_path, ["open", "open"], _FakeSC(raise_on_msg=True))
    assert (rc, rec["stop_reason"]) == (1, "stream_error")


def test_stream_unchanged_quote_heartbeat_once_per_interval(monkeypatch):
    import schwab_stream_daemon as d

    monkeypatch.setenv("STREAM_QUOTE_HEARTBEAT_S", "60")
    cap, conn = d.Capture(), _Conn()
    assert cap.heartbeat_s == 60.0
    cap.on_l1({"content": [{"key": "QUIET", "LAST_PRICE": 5.0}]})
    for t in (0, 5, 30, 59.9, 60, 65, 119, 120):
        cap.flush(conn, now=1000.0 + t)
    quotes = [r for r in conn.c.rows if r[0] == "schwab_stream_quotes"]
    assert len(quotes) == 3 and cap.q_skipped == 5      # t=0, t=60, t=120
    off = d.Capture(heartbeat_s=0)
    off.on_l1({"content": [{"key": "QUIET", "LAST_PRICE": 5.0}]})
    c2 = _Conn()
    for t in (0, 600, 6000):
        off.flush(c2, now=t)
    assert off.q_writes == 1
