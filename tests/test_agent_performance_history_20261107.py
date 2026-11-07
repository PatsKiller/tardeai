"""LQ-20261107-264 — agent_performance_history: one write path, and no accuracy from one sample.

Two writers inserted blindly (daily scripts/update_agent_performance.py, weekly
scripts/overnight_batch.py::record_agent_performance) and the table has no key over
(agent, period_start, period_end), so a second run of the same period added a duplicate — six such rows
remain for 2026-05-24..2026-05-31, written 15 minutes apart on 2026-05-31.

Hermetic: the cursor is a recorder, there is no database and no network. Synthetic agent names only.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import learning_governance  # noqa: E402
from lib.agent_performance_history import (  # noqa: E402
    MIN_SAMPLES,
    NOT_ENOUGH_DATA,
    accuracy_label,
    annotate_sample,
    upsert_period_rows,
)


class FakeCursor:
    """Answers a statement by substring (first match wins); each answer is a queue for fetchone()."""

    def __init__(self, answers=None):
        self.answers = answers or []
        self.log: list[tuple[str, object]] = []
        self._queue: list = []

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.log.append((flat, params))
        self._queue = []
        for sub, rows in self.answers:
            if sub in flat:
                self._queue = list(rows)
                return
        self._queue = []

    def fetchone(self):
        return self._queue.pop(0) if self._queue else None

    def statements(self):
        return [sql for sql, _ in self.log]


def _row(agent="AAAA", total=5, accuracy=100.0, conf=0.8, overrides=0):
    return {"agent": agent, "total_recommendations": total, "accuracy_pct": accuracy,
            "avg_confidence": conf, "rule_violations": 0, "human_overrides": overrides}


# ── the write path ───────────────────────────────────────────────────────────────────────────────
def test_the_period_lock_is_taken_before_any_row_statement():
    cur = FakeCursor([("UPDATE agent_performance_history", [(7,)])])
    upsert_period_rows(cur, "2026-11-01", "2026-11-07", [_row()])
    first, params = cur.log[0]
    assert first.startswith("SELECT pg_advisory_xact_lock"), first
    assert "2026-11-01" in params[0] and "2026-11-07" in params[0], params


def test_an_existing_period_row_is_updated_and_never_inserted():
    cur = FakeCursor([("UPDATE agent_performance_history", [(7,)])])
    out = upsert_period_rows(cur, "2026-11-01", "2026-11-07", [_row()])
    assert out == [{"id": 7, "outcome": "updated"}]
    assert not any(s.startswith("INSERT") for s in cur.statements()), cur.statements()


def test_a_missing_period_row_is_inserted_after_the_update_probe():
    cur = FakeCursor([("INSERT INTO agent_performance_history", [(9,)])])
    out = upsert_period_rows(cur, "2026-11-01", "2026-11-07", [_row()])
    assert out == [{"id": 9, "outcome": "inserted"}]
    kinds = [s.split()[0] for s in cur.statements()]
    assert kinds == ["SELECT", "UPDATE", "INSERT"], kinds


def test_an_unmeasured_count_is_written_as_null_not_zero():
    """rule_violations/human_overrides absent from the row mean "not measured", not "none observed"."""
    cur = FakeCursor()
    upsert_period_rows(cur, "2026-11-01", "2026-11-07",
                      [{"agent": "AAAA", "total_recommendations": 5, "accuracy_pct": 50.0,
                        "avg_confidence": 0.5}])
    insert_params = [p for sql, p in cur.log if sql.startswith("INSERT")][0]
    assert insert_params[6] is None and insert_params[7] is None, insert_params


def test_a_real_dict_cursor_reads_the_id_key():
    """overnight_batch uses psycopg2.extras.RealDictCursor, where RETURNING id comes back as {'id': …}."""
    cur = FakeCursor([("UPDATE agent_performance_history", [{"id": 41}])])
    assert upsert_period_rows(cur, "2026-11-01", "2026-11-07", [_row()])[0]["id"] == 41


def test_each_agent_gets_its_own_outcome_in_order():
    seq = FakeCursor()

    def execute(sql, params=None):
        flat = " ".join(sql.split())
        seq.log.append((flat, params))
        if flat.startswith("SELECT"):
            seq._queue = []
        elif flat.startswith("UPDATE"):
            seq._queue = [(1,)] if "AAAA" in params else []
        elif flat.startswith("INSERT"):
            seq._queue = [(2,)]

    seq.execute = execute  # type: ignore[method-assign] -- a per-test recorder, not the FakeCursor method
    out = upsert_period_rows(seq, "2026-11-01", "2026-11-07", [_row("AAAA"), _row("BBBB")])
    assert out == [{"id": 1, "outcome": "updated"}, {"id": 2, "outcome": "inserted"}]


def test_the_daily_lane_writes_through_the_upsert():
    import update_agent_performance as uap

    assert "upsert_period_rows" in inspect.getsource(uap._write_rows)
    cur = FakeCursor([("UPDATE agent_performance_history", [(7,)])])
    scored = {"period_start": "2026-11-01", "period_end": "2026-11-07",
              "rows": [{"agent": "AAAA", "total": 5, "correct": 5, "accuracy_pct": 100.0,
                        "avg_confidence": 0.8, "overrides": 0}]}
    written = uap._write_rows(cur, scored)
    assert written[0]["id"] == 7 and written[0]["outcome"] == "updated"
    assert uap._write_rows.__doc__ and "LQ-20261107-264" in uap._write_rows.__doc__
    assert not any(s.startswith("INSERT") for s in cur.statements()), cur.statements()


# ── the minimum-sample rule ─────────────────────────────────────────────────────────────────────
def test_min_samples_is_the_repositorys_agent_calibration_bar():
    assert MIN_SAMPLES == learning_governance.AGENT_SAMPLE_INSIGHT == 25


def test_sample_size_ok_boundaries():
    for n in (None, 0, 1, 5, 24):
        assert annotate_sample({"total_recommendations": n})["sample_size_ok"] is False, n
    for n in (25, 26, 176):
        assert annotate_sample({"total_recommendations": n})["sample_size_ok"] is True, n


def test_one_sample_at_100_percent_is_not_an_accuracy():
    assert accuracy_label({"total_recommendations": 1, "accuracy_pct": 100.0}) == NOT_ENOUGH_DATA
    assert accuracy_label({"total_recommendations": 5, "accuracy_pct": 0.0}) == NOT_ENOUGH_DATA


def test_a_measured_accuracy_is_shown_and_an_unmeasured_one_is_not():
    assert accuracy_label({"total_recommendations": 25, "accuracy_pct": 47.2}) == "47.2%"
    assert accuracy_label({"total_recommendations": 25, "accuracy_pct": None}) == "—"
    assert accuracy_label({"total_recommendations": 25, "accuracy_pct": 0.0}) == "0.0%"


def test_the_weekly_aggregate_never_asserts_a_zero_accuracy():
    import overnight_batch

    rows = overnight_batch._weekly_performance_rows(
        [{"agent": "AAAA", "total": 889, "avg_conf": None}])
    assert rows[0]["accuracy_pct"] is None, rows
    assert rows[0]["rule_violations"] is None and rows[0]["human_overrides"] is None, rows
    assert rows[0]["avg_confidence"] is None, rows  # unknown confidence, not a confident 0.0
    assert "upsert_period_rows" in inspect.getsource(overnight_batch.record_agent_performance)


def test_the_weekly_review_uses_the_same_label():
    src = (ROOT / "scripts" / "generate_weekly_portfolio_review.py").read_text()
    assert "accuracy_label(a)" in src
    assert "SELECT agent, accuracy_pct, total_recommendations FROM agent_performance_history" in src


def test_the_dashboard_threshold_matches_the_python_bar():
    """A duplicated constant is a future drift; this pins the page's copy to the governance number."""
    lib = (ROOT / "apps" / "command-center-v2" / "src" / "lib" / "agentAccuracy.ts").read_text()
    m = re.search(r"MIN_SAMPLES_FOR_ACCURACY\s*=\s*(\d+)", lib)
    assert m, "agentAccuracy.ts no longer declares MIN_SAMPLES_FOR_ACCURACY"
    assert int(m.group(1)) == MIN_SAMPLES
    assert "not enough data" in lib
    # Every surface that prints an agent accuracy takes the shared cell, not its own copy of the rule.
    pages = ROOT / "apps" / "command-center-v2" / "src" / "pages"
    for page in ("AgentDashboard.tsx", "CIODashboard.tsx"):
        src = (pages / page).read_text()
        assert "from '../lib/agentAccuracy'" in src, page
    assert "MIN_SAMPLES_FOR_ACCURACY" not in (pages / "AgentDashboard.tsx").read_text()
    assert "MIN_SAMPLES_FOR_ACCURACY" not in (pages / "CIODashboard.tsx").read_text()
