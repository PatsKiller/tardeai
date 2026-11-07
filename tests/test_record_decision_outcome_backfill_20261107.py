"""record-decision-outcome: the +1d/+7d/+30d price backfill must actually run, fill only what is missing, and the
lane must state what it wrote (LQ-20261107-130, audit78 batch 2).

Read-only evidence for this item (live DB, 2026-11-07): 1013 rows, ``price_1d`` NULL on all 1013, ``price_30d``
NULL on all 1013, ``price_7d`` set on 864 by a different writer, ``decision_id`` NULL on all 1013 -- while
``ticker_prices`` holds a close within +-3 days of the target for 1006 of them at +1d, 114 at +7d and 789 at
+30d. Two causes:

* the n8n argv is ``python scripts/record_decision_outcome.py`` with no ``--backfill``, so ``backfill_prices``
  never ran from the lane at all;
* the other writer (the premarket manifest step ``overnight_batch_outcomes`` -> ``overnight_batch.py
  --outcomes``) stamps ``evaluated_at``, and the lane selected on ``evaluated_at IS NULL`` -- so a row the other
  writer had touched was permanently invisible to the lane, even with the flag.

Hermetic: fake cursor/connection and a fake receipt writer. No DB, no network, no secret.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


class FakeCursor:
    """Records every statement; scripts the read results per statement substring."""

    def __init__(self, rows=()):
        self.executed: list[tuple[str, object]] = []
        self._rows = list(rows)
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))
        # The set-based fill reports how many rows it wrote; a scripted value can be set by the caller.
        if "UPDATE decision_outcomes" in sql and "COALESCE(o.price_1d" in sql:
            self.rowcount = int(self._rows.pop(0)) if self._rows else 0
        if "UPDATE decision_outcomes" in sql and "outcome_score = %s" in sql:
            self.rowcount = 1

    def fetchall(self):
        if not self._rows:
            return []
        head = self._rows.pop(0)
        return head if isinstance(head, list) else []

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def close(self):
        pass


class FakeConn:
    def __init__(self, cursor):
        self._cur = cursor
        self.commits = 0
        self.closed = 0

    def cursor(self, **kwargs):
        return self._cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed += 1

    def set_session(self, **kwargs):
        pass


class FakeReceipt:
    """Captures the receipt the lane writes instead of touching the state root."""

    def __init__(self):
        self.calls: list[dict] = []

    def now_iso(self):
        return datetime.now(timezone.utc).isoformat()

    def write_lane_receipt(self, lane_id, **kwargs):
        self.calls.append({"lane_id": lane_id, **kwargs})
        return None

    def enforce_readonly(self, conn):
        return conn

    def dry_run_report(self, lane_id, summary, **kwargs):
        self.calls.append({"lane_id": lane_id, "dry_run": summary, **kwargs})
        return summary


@pytest.fixture()
def lane(monkeypatch):
    import scripts.record_decision_outcome as m  # noqa: F401 -- imported for its side-effect-free module scope

    receipt = FakeReceipt()
    monkeypatch.setattr(m, "_receipt_lib", lambda: receipt)
    return m, receipt


def _with_cursor(monkeypatch, m, cursor):
    conn = FakeConn(cursor)
    monkeypatch.setattr(m, "_get_conn", lambda: conn)
    return conn


# ── the backfill runs ────────────────────────────────────────────────────────────────────────────────────────────
def test_backfill_is_the_default_for_a_real_run(lane, monkeypatch):
    """The n8n argv has no flags: the price follow-up must run anyway."""
    m, receipt = lane
    calls: list[str] = []
    monkeypatch.setattr(m, "record_current_decisions", lambda real_only=True: (calls.append("record"), 4)[1])
    monkeypatch.setattr(m, "backfill_prices", lambda *a, **k: (calls.append("backfill"), 114)[1])

    assert m.main([]) == 0
    assert calls == ["record", "backfill"], "a real run must record AND backfill"
    out = receipt.calls[-1]["output"]
    assert out["produced_count"] == 118 and out["attempted_count"] == 118, out
    assert receipt.calls[-1]["summary"] == {"recorded": 4, "backfilled": 114}
    assert out["empty_reason"] is None


def test_the_legacy_flag_is_still_accepted_and_does_not_double_run(lane, monkeypatch):
    """`--backfill` was the documented form; the retired cron line may still carry it."""
    m, receipt = lane
    runs: list[int] = []
    monkeypatch.setattr(m, "record_current_decisions", lambda real_only=True: 0)
    monkeypatch.setattr(m, "backfill_prices", lambda *a, **k: (runs.append(1), 5)[1])

    assert m.main(["--backfill"]) == 0
    assert runs == [1], "the backfill runs exactly once"


def test_no_backfill_opts_out(lane, monkeypatch):
    m, receipt = lane
    runs: list[int] = []
    monkeypatch.setattr(m, "record_current_decisions", lambda real_only=True: 2)
    monkeypatch.setattr(m, "backfill_prices", lambda *a, **k: (runs.append(1), 0)[0])

    assert m.main(["--no-backfill"]) == 0
    assert runs == []
    assert receipt.calls[-1]["output"]["produced_count"] == 2
    assert "backfilled" not in receipt.calls[-1]["summary"]


def test_a_run_that_wrote_nothing_states_why(lane, monkeypatch):
    m, receipt = lane
    monkeypatch.setattr(m, "record_current_decisions", lambda real_only=True: 0)
    monkeypatch.setattr(m, "backfill_prices", lambda *a, **k: 0)

    assert m.main([]) == 0
    assert receipt.calls[-1]["output"]["empty_reason"] == "no_new_input"
    assert receipt.calls[-1]["output"]["produced_count"] == 0


def test_a_failed_run_reports_what_it_already_wrote(lane, monkeypatch):
    """The INSERT step commits on its own; a later failure must not report a flat zero (producer flattens)."""
    m, receipt = lane

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(m, "record_current_decisions", lambda real_only=True: 7)
    monkeypatch.setattr(m, "backfill_prices", boom)

    with pytest.raises(RuntimeError):
        m.main([])
    call = receipt.calls[-1]
    assert call["ok"] is False and call["exit_code"] == 1
    assert call["output"]["produced_count"] == 7, call
    assert "db down" in call["error"]


# ── the fill writes only what is missing ───────────────────────────────────────────────────────────────────────
def _fill_update_sql(m) -> str:
    return " ".join(m._FILL_PRICES_SQL.split())


def test_the_fill_never_overwrites_a_stored_price_or_score(lane):
    """A row another writer already scored keeps the price that score was computed from (TSEM 137.36 is live)."""
    m, _ = lane
    sql = _fill_update_sql(m)
    assert "SET" in sql and "UPDATE decision_outcomes o" in sql
    setters = sql.split("SET", 1)[1].split("FROM src", 1)[0]
    assignments = [s.strip() for s in setters.split(",") if "=" in s]
    assert {a.split("=")[0].strip() for a in assignments} >= {
        "price_1d", "price_7d", "price_30d", "decision_id"}, assignments
    for assignment in assignments:
        rhs = assignment.split("=", 1)[1].strip()
        assert rhs.startswith("COALESCE("), f"{assignment!r} would overwrite a stored value"
    assert "COALESCE(o.price_7d, src.p7)" in sql, sql


def test_the_fill_targets_only_rows_with_something_missing(lane):
    m, _ = lane
    sql = _fill_update_sql(m)
    assert ("(src.fill_1d OR src.fill_7d OR src.fill_30d OR src.fill_id)") in sql, sql
    assert "o.id = src.id" in sql


def test_the_fill_reads_ticker_prices_near_each_target_date(lane):
    m, _ = lane
    src = " ".join(m._FILL_SRC_SQL.split())
    for delta in (1, 7, 30):
        assert f"o.created_at::date + {delta} - 3" in src and f"o.created_at::date + {delta} + 3" in src, src
    assert "ticker_prices" in src
    assert "ORDER BY ABS(t.price_date - (o.created_at::date" in src


def test_backfill_reports_only_the_rows_it_wrote(lane, monkeypatch):
    m, _ = lane
    cursor = FakeCursor(rows=[1006])
    conn = _with_cursor(monkeypatch, m, cursor)

    assert m.backfill_prices() == 1006
    assert conn.commits == 1 and conn.closed == 1
    statements = [sql for sql, _ in cursor.executed]
    assert any(s.startswith("WITH src AS") and "UPDATE decision_outcomes" in s for s in statements), statements


# ── the outcome score keeps the ONE definition the live writer uses ───────────────────────────────────────────
@pytest.mark.parametrize("rec,p0,p7,expected", [
    ("BUY", 100.0, 105.0, 1.0),
    ("ADD", 100.0, 101.0, 1.0),
    ("BUY", 100.0, 94.0, -0.5),
    ("SELL", 100.0, 90.0, 1.0),
    ("TRIM", 100.0, 110.0, -0.5),
    ("HOLD", 100.0, 104.0, 1.0),
    ("HOLD", 100.0, 120.0, -0.5),
    ("AVOID", 100.0, 102.0, 0.0),      # no direction: a small move is neutral
    ("AVOID", 100.0, 94.0, -0.5),      # >5% either way is a miss, exactly as the live writer scores it
    ("avoid", 100.0, 102.0, 0.0),      # case is normalised, the stored vocabulary is upper
    (None, 100.0, 102.0, 0.0),
])
def test_outcome_score_is_the_live_writer_definition(lane, rec, p0, p7, expected):
    m, _ = lane
    assert m._outcome_score(rec, p0, p7) == expected


@pytest.mark.parametrize("p0,p7", [(None, 100.0), (100.0, None), (0, 100.0), (0.0, 100.0)])
def test_outcome_score_is_unknown_without_both_prices(lane, p0, p7):
    """Unknown is not zero: an outcome that cannot be computed stays NULL, so the page can tell it apart."""
    m, _ = lane
    assert m._outcome_score("BUY", p0, p7) is None


def test_scoring_selects_only_unscored_rows_that_can_be_scored(lane):
    m, _ = lane
    sql = " ".join(m._SCORE_CANDIDATES_SQL.split())
    assert "outcome_score IS NULL" in sql
    assert "price_at_decision IS NOT NULL" in sql
    assert "price_7d IS NOT NULL" in sql


def test_scoring_never_overwrites_an_existing_score(lane):
    m, _ = lane
    sql = " ".join(m._SCORE_UPDATE_SQL.split())
    assert "WHERE id = %s AND outcome_score IS NULL" in sql, sql
    assert "evaluated_at = COALESCE(evaluated_at, NOW())" in sql, sql


# ── decision_id ────────────────────────────────────────────────────────────────────────────────────────────────
def test_decision_id_is_deterministic_provenance(lane):
    """The same row always yields the same id, in UTC, whatever tz the process runs in."""
    m, _ = lane
    et = timezone(timedelta(hours=-5))
    when = datetime(2026, 11, 1, 13, 30, 0, tzinfo=et)
    assert m.decision_id_for("AAA", when) == "synthesis:AAA:2026-11-01T18:30:00Z"
    assert m.decision_id_for("AAA", when) == m.decision_id_for("AAA", when.isoformat())
    assert m.decision_id_for("AAA", datetime(2026, 11, 1, 18, 30, 0)) == "synthesis:AAA:2026-11-01T18:30:00Z"


def test_the_sql_fill_builds_the_same_decision_id_as_the_insert(lane):
    m, _ = lane
    sql = _fill_update_sql(m)
    assert f"'{m.DECISION_ID_PREFIX}:' || o.symbol || ':'" in sql, sql
    assert f"'{m._TS_FMT_PG}'" in sql, sql


def test_a_new_outcome_row_is_inserted_with_its_decision_id(lane, monkeypatch):
    m, _ = lane
    cursor = FakeCursor(rows=[[{"symbol": "AAA", "strategy_type": "core", "recommendation": "BUY",
                                "latest_price": 10.0,
                                "updated_at": datetime(2026, 11, 1, 18, 30, tzinfo=timezone.utc)}]])
    _with_cursor(monkeypatch, m, cursor)

    assert m.record_current_decisions() == 1
    insert = [p for s, p in cursor.executed if "INSERT INTO decision_outcomes" in s]
    assert insert and insert[0][-1] == "synthesis:AAA:2026-11-01T18:30:00Z", insert


# ── dry run ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_dry_run_previews_the_fill_by_default_and_writes_nothing(lane, monkeypatch):
    m, receipt = lane
    cursor = FakeCursor(rows=[[],                                    # _select_decisions
                              {"rows": 1013, "fill_1d": 1006, "fill_7d": 114, "fill_30d": 789,
                               "fill_id": 1013, "would_backfill": 1013}])
    conn = _with_cursor(monkeypatch, m, cursor)

    out = m.dry_run(True)
    assert out["would_record"] == 0
    assert out["would_backfill"] == 1013 and out["would_fill"]["1d"] == 1006, out
    assert conn.commits == 0 and conn.closed == 1
    # A CTE statement starts with WITH, so look for the write inside it, not at the start of the line.
    for sql, _ in cursor.executed:
        assert "UPDATE decision_outcomes" not in sql and "INSERT INTO decision_outcomes" not in sql, sql
    assert any("SELECT count(*) AS rows" in s for s, _ in cursor.executed), cursor.executed
    assert receipt.calls[-1]["would_write"], receipt.calls[-1]


def test_dry_run_without_the_fill_previews_only_the_inserts(lane, monkeypatch):
    m, _ = lane
    cursor = FakeCursor(rows=[[]])
    _with_cursor(monkeypatch, m, cursor)

    out = m.dry_run(False)
    assert out["would_record"] == 0 and "would_backfill" not in out
    assert not any("WITH src AS" in s for s, _ in cursor.executed)


def test_main_dry_run_never_touches_the_writers(lane, monkeypatch):
    m, _ = lane
    monkeypatch.setattr(m, "record_current_decisions", lambda *a, **k: pytest.fail("dry run must not insert"))
    monkeypatch.setattr(m, "backfill_prices", lambda *a, **k: pytest.fail("dry run must not update"))
    monkeypatch.setattr(m, "dry_run", lambda backfill: {"would_record": 0, "would_backfill": 0})
    assert m.main(["--dry-run"]) == 0
