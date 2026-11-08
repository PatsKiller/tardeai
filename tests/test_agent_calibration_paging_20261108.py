"""LQ-20261107-1032 — agent-calibration-engine: read the eligible set, write each pair once.

Measured DB read-only on 2026-11-08 12:20 ET, on the first live run of the lane (12:03 ET):

    the script carried ``ROW_CAP = 2000`` and ``... LIMIT 2000``: its own log said
    "Calibration: 2000 events, 7 windows (applied) NOTE: event count hit the 2000-row query cap"
    out of 73,525 eligible joined rows (2.7%);
    agent_calibration_events held 49,106 rows in 7,849 (rec, window) pairs — 6,411 groups with
    41,257 extra rows — because the event id was a random uid, so ``ON CONFLICT
    (calibration_event_id)`` never fired and each weekly run inserted the same recommendations
    again;
    agent_calibration_windows held 25 rows per agent (one per run), because its conflict key was
    rebuilt from ``now()`` on every run and carried a ``strategy_id`` the INSERT never wrote.

These are the four properties the fix must hold: no constant cap, every page read, one row per
recommendation, and an upsert whose conflict target is a key the code actually writes.

Hermetic: no DB, no network, no clock dependence (the only time assertion is midnight alignment
of an explicit datetime).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import agent_calibration_engine as ace   # noqa: E402
from lib import calibration_keys as keys  # noqa: E402


# ── fakes ────────────────────────────────────────────────────────────────────────────────────
class FakeCursor:
    """Answers by the SQL marker it sees; records every statement and its params."""

    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        self.conn.statements.append((sql, params))
        s = " ".join(sql.split())
        self._rows = []
        if "JOIN LATERAL" in s:
            self._rows = self.conn.page_queue.pop(0) if self.conn.page_queue else []
        elif "FROM stopped_out_watch" in s:
            self._rows = [(sym,) for sym in self.conn.relist_symbols]
        elif "FROM paper_trades WHERE id = ANY" in s:
            self._rows = [(i, *self.conn.trades[i]) for i in (params[0] or []) if i in self.conn.trades]
        elif "FROM paper_trade_proposals WHERE id = ANY" in s:
            self._rows = [(i, self.conn.proposals[i]) for i in (params[0] or [])
                          if i in self.conn.proposals]
        elif "GROUP BY 1, 2" in s:
            self._rows = list(self.conn.duplicate_groups)
        elif "calibration_event_id = ANY" in s:
            self._rows = [(k,) for k in self.conn.present_event_ids]
        elif "SELECT count(*) FROM agent_calibration_events" in s:
            self._rows = [(self.conn.events_total,)]

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class FakeConn:
    def __init__(self, *, pages=None, relist_symbols=(), trades=None, proposals=None,
                 duplicate_groups=(), present_event_ids=(), events_total=0):
        self.page_queue = [list(p) for p in (pages or [])]
        self.relist_symbols = list(relist_symbols)
        self.trades = dict(trades or {})
        self.proposals = dict(proposals or {})
        self.duplicate_groups = list(duplicate_groups)
        self.present_event_ids = list(present_event_ids)
        self.events_total = events_total
        self.statements = []
        self.committed = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass

    def close(self):
        pass


def _row(rec_id="AREC_1", agent="maria", symbol="NVDA", rec_type="buy", conf=0.7,
         when=None, outcome_type="paper_trade", trade_id=11, proposal_id=None, link_conf=0.9):
    return (rec_id, agent, symbol, "swing", rec_type, conf,
            when or datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc),
            outcome_type, trade_id, proposal_id, link_conf)


CFG = {"page_rows": 2, "max_rows_per_run": 0, "window_days": 90, "path": "<test>"}


# ── 1. the cap is config, not a constant ────────────────────────────────────────────────────
def test_the_hard_coded_row_cap_is_gone():
    assert not hasattr(ace, "ROW_CAP"), "a module constant cap is what truncated the read"
    assert "LIMIT 2000" not in ace.PAGE_SQL
    assert "LIMIT %s" in ace.PAGE_SQL, "the page size must travel as a parameter"


def test_the_shipped_config_is_the_only_place_the_read_size_is_set():
    cfg = ace.load_config()
    doc = json.loads((ROOT / "config" / "agent_calibration_engine.json").read_text())
    assert doc["schema"] == ace.CONFIG_SCHEMA
    assert cfg["page_rows"] == doc["page_rows"] > 0
    assert cfg["max_rows_per_run"] == doc["max_rows_per_run"] == 0, "0 means: no cap, read it all"


def test_a_missing_config_is_a_failure_not_a_silent_default(tmp_path):
    with pytest.raises(RuntimeError, match="config missing"):
        ace.load_config(tmp_path / "nope.json")


# ── 2. every eligible page is read ──────────────────────────────────────────────────────────
def test_the_walk_reads_every_page_until_the_eligible_set_is_exhausted():
    conn = FakeConn(pages=[[_row("R1"), _row("R2")], [_row("R3"), _row("R4")], [_row("R5")]])
    events, stats = ace.score_recommendations(conn, config=CFG)
    assert stats["pages_read"] == 3, "2 + 2 + 1 rows at page_rows=2 is three pages"
    assert stats["eligible_recommendations"] == 5
    assert stats["events_scored"] == len(events) == 5
    assert stats["capped"] is False

    page_calls = [(s, p) for s, p in conn.statements if "JOIN LATERAL" in " ".join(s.split())]
    assert len(page_calls) == 3
    assert page_calls[0][1] == [90, 2], "first page: window + limit, no keyset"
    assert page_calls[1][1] == [90, _row("R2")[6], "R2", 2], \
        "the second page is bounded by the last (recommendation_time, recommendation_id) read"


def test_a_configured_cap_stops_the_walk_and_says_so():
    conn = FakeConn(pages=[[_row("R1"), _row("R2")], [_row("R3")]])
    events, stats = ace.score_recommendations(
        conn, config={"page_rows": 2, "max_rows_per_run": 3, "window_days": 90, "path": "<t>"})
    assert len(events) == 3
    assert stats["capped"] is True, "a run that stopped early must never read like a complete one"
    assert stats["pages_read"] == 2


# ── 3. one row per recommendation, not one per outcome link ────────────────────────────────
def test_the_page_query_takes_one_link_per_recommendation():
    """The link table fans out (up to 169 trades on one recommendation); the read must not."""
    sql = " ".join(ace.PAGE_SQL.split())
    assert "JOIN LATERAL" in sql
    assert sql.count("LIMIT 1") == 1, "the lateral subquery keeps exactly one link"
    assert "(l.paper_trade_id IS NOT NULL) DESC" in sql, \
        "a realised paper-trade outcome outranks a proposal status"
    assert "ORDER BY r.recommendation_time DESC, r.recommendation_id DESC" in sql


def test_a_page_of_n_recommendations_scores_n_events():
    conn = FakeConn(pages=[[_row("R1"), _row("R2"), _row("R3")]],
                    trades={11: ("closed", 10.0, 1.5)})
    events, _ = ace.score_recommendations(conn, config={"page_rows": 10, "max_rows_per_run": 0,
                                                       "window_days": 90, "path": "<t>"})
    assert len(events) == 3
    assert len({e["calibration_event_id"] for e in events}) == 3
    assert {e["actual_outcome"] for e in events} == {"correct"}


# ── 4. the natural key is the id, so a re-run updates instead of inserting ─────────────────
def test_the_event_id_is_the_natural_key():
    a = ace.score_row(_row("AREC_1"), window_days=90, trades={11: ("closed", 1.0, 0.1)})
    b = ace.score_row(_row("AREC_1"), window_days=90, trades={11: ("closed", -1.0, -0.1)})
    c = ace.score_row(_row("AREC_2"), window_days=90, trades={11: ("closed", 1.0, 0.1)})
    assert a["calibration_event_id"] == b["calibration_event_id"], \
        "the same pair scored again is the same row, whatever the trade did in between"
    assert a["calibration_event_id"] != c["calibration_event_id"]
    assert a["calibration_event_id"] == keys.event_key("AREC_1", "90d")
    assert a["calibration_event_id"].startswith("ACE_")
    assert len(a["calibration_event_id"]) == len("ACE_") + 24


def test_save_events_upserts_the_fields_a_later_run_changes():
    conn = FakeConn()
    events = [ace.score_row(_row("AREC_1"), window_days=90, trades={11: ("closed", 5.0, 0.2)})]
    ace.save_events(conn, events, dry_run=False)
    sql = " ".join(conn.statements[-1][0].split())
    assert "ON CONFLICT (calibration_event_id) DO UPDATE" in sql
    assert "DO NOTHING" not in sql
    for field in ("actual_outcome=EXCLUDED.actual_outcome", "outcome_score=EXCLUDED.outcome_score",
                  "pnl=EXCLUDED.pnl", "r_multiple=EXCLUDED.r_multiple",
                  "calibration_error=EXCLUDED.calibration_error"):
        assert field in sql, field
    assert conn.committed == 1


def test_a_dry_run_never_reaches_the_write():
    conn = FakeConn()
    ace.save_events(conn, [ace.score_row(_row("AREC_1"))], dry_run=True)
    ace.save_windows(conn, [], dry_run=True)
    assert conn.statements == [] and conn.committed == 0


# ── 5. windows: day-aligned bounds and a reachable conflict target ─────────────────────────
def test_window_bounds_are_day_aligned():
    start, end = keys.day_bounds(datetime(2026, 11, 8, 12, 3, 51, tzinfo=timezone.utc), 90)
    assert end == datetime(2026, 11, 8, tzinfo=timezone.utc)
    assert start == datetime(2026, 8, 10, tzinfo=timezone.utc)


def test_two_runs_the_same_day_are_the_same_window():
    events = [ace.score_row(_row("R1", agent="steph"), window_days=90)]
    first = ace.aggregate_windows(events, window_days=90)[0]
    second = ace.aggregate_windows(events, window_days=90)[0]
    assert first["window_id"] == second["window_id"]
    assert first["window_id"] == keys.window_key(first["agent_name"], first["window_start"],
                                                 first["window_end"], first["domain"], None)
    assert first["window_start"].hour == first["window_end"].hour == 0
    assert first["window_end"].minute == first["window_end"].second == 0


def test_save_windows_upserts_on_the_window_id_and_updates_every_count():
    conn = FakeConn()
    w = ace.aggregate_windows([ace.score_row(_row("R1"))], window_days=90)
    ace.save_windows(conn, w, dry_run=False)
    sql = " ".join(conn.statements[-1][0].split())
    assert "ON CONFLICT (window_id) DO UPDATE" in sql
    assert "strategy_id" in sql, "a NULL column in the conflict target made it unreachable"
    for field in ("recommendations=EXCLUDED.recommendations", "incorrect=EXCLUDED.incorrect",
                  "neutral=EXCLUDED.neutral", "resolved=EXCLUDED.resolved"):
        assert field in sql, field


# ── 6. the DB the run reads is the render's, not a stale checkout .env ─────────────────────
@pytest.mark.parametrize("script", ["agent_calibration_engine.py",
                                    "archive_duplicate_calibration_events.py"])
def test_import_never_pins_a_checkout_dotenv_over_the_env_render(script):
    """env_bootstrap.load_env() reads the tmpfs render first and never overrides a name that is
    already set. Both scripts used to call load_dotenv($PROJECT_ROOT/.env) at import -- before
    that loader -- so a worktree .env pointing at a scratch cluster won: a 2026-11-08 "live" dry
    run read an empty emulated database and printed 0 events as if that were the answer."""
    stale = "/nonexistent/stale-pgemul.sock"
    orig = Path.read_text

    def read_text(self, *a, **k):
        return f"DB_HOST={stale}\n" if self.name == ".env" else orig(self, *a, **k)

    with mock.patch.object(Path, "read_text", read_text), mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DB_HOST", None)
        spec = importlib.util.spec_from_file_location(f"fresh_{script[:-3]}", ROOT / "scripts" / script)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        assert os.environ.get("DB_HOST") != stale, "an import pinned the checkout .env"


# ── 7. the archive half ────────────────────────────────────────────────────────────────────
def _archive_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "archive_duplicate_calibration_events",
        ROOT / "scripts" / "archive_duplicate_calibration_events.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class _FakeArchive:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def estimate(self, conn, *, table, where_sql, key="id", sample_rows=500):
        self.calls.append(("estimate", table))
        return {"rows": self.rows, "stored_bytes": 1024 * self.rows, "est_archive_bytes": 64 * self.rows,
                "sample_rows": 1}

    def archive_root(self):
        return Path("/tmp/does-not-exist/archive/db_retention")

    def archive_then_delete_batches(self, *a, **kw):
        self.calls.append(("archive", kw.get("table")))
        return {"status": "ok", "rows_archived": self.rows, "rows_deleted": self.rows,
                "batches": [{"batch": 1, "rows": self.rows}]}


def test_the_dedupe_predicate_keeps_exactly_one_row_of_each_group():
    mod = _archive_module()
    sql = " ".join(mod.DUPLICATE_PREDICATE.split())
    assert "NOT IN" in sql and "DISTINCT ON (recommendation_id, COALESCE(scoring_window, ''))" in sql
    assert "created_at DESC NULLS LAST, id DESC" in sql, "the survivor is the newest row"
    assert sql.strip().upper().startswith("T.ID"), "a WHERE predicate on the table alias, not a statement"


def test_dry_run_reports_the_counts_and_writes_nothing(monkeypatch, capsys):
    mod = _archive_module()
    conn = FakeConn(duplicate_groups=[("AREC_1", "90d", 3), ("AREC_2", "90d", 2)],
                    present_event_ids=[keys.event_key("AREC_1", "90d")], events_total=49_106)
    monkeypatch.setattr(mod, "_get_conn", lambda: conn)
    monkeypatch.setattr(mod, "_retention_archive", lambda: _FakeArchive(rows=3))
    assert mod.main(["--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run"
    assert out["rows_total"] == 49_106
    assert out["duplicate_groups"] == 2 and out["rows_in_duplicate_groups"] == 5
    assert out["rows_to_archive"] == 3, "5 rows in 2 groups leaves 3 duplicates"
    assert out["groups_without_natural_key_row"] == 1
    assert out["would_write"]["rows_archived"] == 3
    assert out["predicate_matches_groups"] is True
    joined = " ".join(" ".join(s.split()) + " " + repr(p) for s, p in conn.statements).upper()
    assert "INSERT INTO" not in joined and "DELETE FROM" not in joined
    assert conn.committed == 0


def test_apply_needs_the_operator_word(monkeypatch):
    mod = _archive_module()

    def _never():
        raise AssertionError("--apply without --confirm APPLY must not even open the DB")

    monkeypatch.setattr(mod, "_get_conn", _never)
    assert mod.main(["--apply"]) == 2
    assert mod.main(["--apply", "--confirm", "yes"]) == 2
