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

    assert d.supervise(once, lambda: False, lambda s: None, 5, 30) == 1 and len(calls) == 1
    calls.clear()
    assert d.supervise(once, lambda: True, lambda s: None, 3, 30) == 1 and len(calls) == 4
    src = (ROOT / "scripts/schwab_stream_daemon.py").read_text(encoding="utf-8")
    assert "line_buffering=True" in src


# ── interpreter resolution in release dirs ────────────────────────────────────────────────────────────────
def test_ri_overnight_resolves_an_interpreter_that_exists():
    sh = ROOT / "scripts/run_research_intelligence_overnight.sh"
    src = sh.read_text(encoding="utf-8")
    assert 'PY="${PROJ}/.venv/bin/python"\n' not in src
    assert '"${TRADEAI_VENV_PYTHON:-}"' in src and 'PY="${PY:-python3}"' in src
    assert subprocess.run(["bash", "-n", str(sh)]).returncode == 0


def test_post_close_processors_use_the_running_interpreter():
    for f in ("alpaca_paper_adapter.py", "paper_trade_closer.py", "paper_trade_monitor.py"):
        src = (ROOT / "scripts" / f).read_text(encoding="utf-8")
        assert 'str(PROJECT_ROOT / ".venv/bin/python")' not in src, f
        assert "[sys.executable,  # release dirs have no .venv" in src, f


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
