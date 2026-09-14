"""One write module for data_gap_registry, and an honest resolver schedule.

The data gap queue had two writers with two dedup rules (the retired overnight
lane deduped on 'open' only; the resolver moved rows through their states with
its own SQL) and a third caller, the operator desk, whose bridge module never
reached main, so it queued nothing on every call. The operator approved
reconnecting the desk on 2026-09-13. These tests pin:

1. GOLDEN EQUIVALENCE: the overnight lane's row renders to the same
   column->value map it rendered before; the resolver issues the same status
   transitions in the same order.
2. RAILS: a gap the resolver cannot act on is returned with a reason, never
   written; one dedup rule (open OR enriching) hands back the existing id.
3. THE REDUCTION: the authority gate counts exactly one writer file.
4. CRON: the next firing of the resolver's schedule is computed, not guessed.

Pure: fake cursors that record SQL and params. Nothing touches a database.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import cron_schedule as C  # noqa: E402
from lib.writers import data_gap_registry_writer as W  # noqa: E402


class FakeCursor:
    def __init__(self, fetchone=None, fetchall=None, rowcount=1):
        self.calls: list[tuple[str, list | None]] = []
        self._one = list(fetchone or [])
        self._all = list(fetchall or [])
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self.calls.append((" ".join(str(sql).split()), None if params is None else list(params)))

    def fetchone(self):
        return self._one.pop(0) if self._one else None

    def fetchall(self):
        return self._all.pop(0) if self._all else []


class FakeConn:
    def __init__(self, cur):
        self.cur = cur
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _inserted_rows(cur: FakeCursor) -> list[dict]:
    """Render every INSERT into data_gap_registry to a column -> value map."""
    out = []
    for sql, params in cur.calls:
        if not sql.startswith("INSERT INTO data_gap_registry"):
            continue
        m = re.search(r"\(([^)]*)\) VALUES \(([^)]*)\)", sql)
        cols = [c.strip() for c in m.group(1).split(",")]
        vals = [v.strip() for v in m.group(2).split(",")]
        ps = list(params or [])
        row = {}
        for c, v in zip(cols, vals):
            row[c] = ps.pop(0) if v == "%s" else v.strip("'")
        out.append(row)
    return out


# ── 1. golden equivalence ────────────────────────────────────────────────────


def test_overnight_row_renders_to_the_legacy_column_map():
    cur = FakeCursor(fetchone=[None, (74,)])
    rec = W.register_gaps(
        cur,
        [{"symbol": "AAPL", "gap_type": "missing_catalyst",
          "gap_detail": "Detected in AAPL overnight response", "source_job_id": 9}],
        detected_by="gemma3_overnight",
    )
    # The legacy SQL: VALUES (%s, %s, %s, 'gemma3_overnight', %s, %s, 'open')
    # with [symbol, gap_type, detail, queue_id, severity] and severity 'high' for
    # missing_catalyst / missing_market_data / explicit.
    assert _inserted_rows(cur) == [{
        "symbol": "AAPL", "gap_type": "missing_catalyst",
        "gap_detail": "Detected in AAPL overnight response", "detected_by": "gemma3_overnight",
        "source_job_id": 9, "severity": "high", "status": "open",
    }]
    assert rec.gap_ids == [74] and rec.queued_ids == [74] and rec.rows_rejected == []


def test_overnight_extractor_goes_through_the_module():
    import run_deep_overnight_llm_queue as rq

    assert set(rq._GAP_PATTERNS) <= set(W.GAP_TYPES), "every overnight gap type needs a resolver action"
    cur = FakeCursor(fetchone=[None, (5,)])
    conn = FakeConn(cur)
    rq._extract_and_register_gaps(7, "AAPL", {"data_gaps": ["zz"]}, conn)
    rows = _inserted_rows(cur)
    assert rows and rows[0]["detected_by"] == "gemma3_overnight"
    assert rows[0]["gap_type"] == "explicit" and rows[0]["severity"] == "high"
    assert rows[0]["source_job_id"] == 7 and conn.commits == 1


def test_resolver_issues_the_legacy_transitions_in_order(monkeypatch):
    import data_gap_resolver as R

    cur = FakeCursor(fetchall=[[(1, "AAPL", "missing_sector", "d", None),
                                (2, "MSFT", "missing_catalyst", "d", None)]])
    conn = FakeConn(cur)
    monkeypatch.setattr(R, "get_db_connection", lambda: conn)
    monkeypatch.setattr(R, "GAP_RESOLVERS", {
        "missing_sector": lambda s, c: True,
        "missing_catalyst": lambda s, c: False,
    })
    R.resolve_gaps()
    updates = [(sql, params) for sql, params in cur.calls if sql.startswith("UPDATE data_gap_registry")]
    assert updates == [
        ("UPDATE data_gap_registry SET status = 'enriching' WHERE id = %s", [1]),
        ("UPDATE data_gap_registry SET status = 'resolved', resolved_at = NOW(), resolved_by = %s WHERE id = %s",
         ["gap_resolver_v1", 1]),
        ("UPDATE data_gap_registry SET status = 'enriching' WHERE id = %s", [2]),
        ("UPDATE data_gap_registry SET status = 'open' WHERE id = %s", [2]),
    ]
    assert conn.closed


def test_resolver_weekly_audit_abandons_through_the_module(monkeypatch):
    import data_gap_resolver as R

    cur = FakeCursor(fetchall=[[(3, "NOC", "stale_news", "d", None)],
                               [("NOC", "stale_news", "2026-08-01")]])
    conn = FakeConn(cur)
    monkeypatch.setattr(R, "get_db_connection", lambda: conn)
    monkeypatch.setattr(R, "GAP_RESOLVERS", {"stale_news": lambda s, c: False})
    R.resolve_gaps(weekly_audit=True)
    assert ("UPDATE data_gap_registry SET status = 'abandoned' WHERE status = 'open' "
            "AND detected_at < NOW() - (%s * INTERVAL '1 day')", [30]) in cur.calls


# ── 2. rails and the one dedup rule ──────────────────────────────────────────


def test_an_open_or_enriching_gap_is_not_inserted_again():
    cur = FakeCursor(fetchone=[(12,)])
    rec = W.register_gaps(cur, [{"symbol": "SCHG", "gap_type": "missing_market_data"}], detected_by="cio_operator_desk")
    assert [s for s, _ in cur.calls if s.startswith("INSERT")] == []
    assert "status IN ('open', 'enriching')" in cur.calls[0][0]
    assert rec.existing_ids == [12] and rec.gap_ids == [] and rec.queued_ids == [12]


@pytest.mark.parametrize("row,reason", [
    ({"symbol": "BOOK", "gap_type": "missing_market_data"}, "tradable"),
    ({"symbol": None, "gap_type": "missing_market_data"}, "tradable"),
    ({"symbol": "SCHG", "gap_type": "soft"}, "no resolver action"),
    ({"symbol": "SCHG", "gap_type": "stale_news", "severity": "urgent"}, "severity"),
    ({"symbol": "SCHG", "gap_type": "stale_news", "source_job_id": "x"}, "source_job_id"),
])
def test_rails_return_the_row_with_a_reason_and_write_nothing(row, reason):
    cur = FakeCursor()
    rec = W.register_gaps(cur, [row], detected_by="cio_operator_desk")
    assert cur.calls == []
    assert len(rec.rows_rejected) == 1 and reason in rec.rows_rejected[0]["reason"]


def test_detected_by_is_required():
    cur = FakeCursor()
    rec = W.register_gaps(cur, [{"symbol": "SCHG", "gap_type": "stale_news"}], detected_by=" ")
    assert cur.calls == [] and rec.rows_rejected[0]["reason"] == "detected_by is required"


def test_same_gap_twice_in_one_call_is_queried_once():
    cur = FakeCursor(fetchone=[None, (9,)])
    rec = W.register_gaps(cur, [{"symbol": "schg", "gap_type": "stale_news"}] * 2, detected_by="cio_operator_desk")
    assert len([s for s, _ in cur.calls if s.startswith("SELECT")]) == 1
    assert rec.deduped_in_call == 1 and rec.gap_ids == [9]
    assert _inserted_rows(cur)[0]["symbol"] == "SCHG" and _inserted_rows(cur)[0]["severity"] == "medium"


def test_status_transitions_refuse_blank_or_nonsense_arguments():
    with pytest.raises(ValueError):
        W.mark_resolved(FakeCursor(), 1, resolved_by="")
    with pytest.raises(ValueError):
        W.abandon_stale(FakeCursor(), older_than_days=0)


def test_receipt_serialises_the_ids():
    cur = FakeCursor(fetchone=[None, (81,), (40,)])
    rec = W.register_gaps(cur, [{"symbol": "SCHG", "gap_type": "missing_market_data"},
                                {"symbol": "SPCX", "gap_type": "missing_thesis"}], detected_by="cio_operator_desk")
    d = rec.as_dict()
    json.dumps(d)
    assert d["gap_ids"] == [81] and d["existing_ids"] == [40] and d["table"] == "data_gap_registry"


# ── 3. the reduction ─────────────────────────────────────────────────────────


def test_gate_counts_one_writer_and_the_registry_carries_the_grant():
    import check_data_source_authority as G

    auth = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
    dom = next(d for d in auth["domains"] if d.get("domain") == "data_gaps")
    assert dom["store"]["table"] == "data_gap_registry"
    assert dom["writer"] == "scripts/lib/writers/data_gap_registry_writer.py"
    assert all(str(dom["approval"].get(k) or "").strip() for k in ("approved_by", "approved_on", "reference", "scope"))
    files = [p for p in (ROOT / "scripts").rglob("*")
             if p.suffix in (".py", ".sh") and p.is_file() and "__pycache__" not in p.parts]
    assert G.count_writers(auth, files)["data_gap_registry"] == 1
    baseline = json.loads((ROOT / "config" / "data_source_authority_baseline.json").read_text())
    assert baseline["writers"]["data_gap_registry"] == 1


# ── 4. cron ──────────────────────────────────────────────────────────────────


def test_next_run_skips_the_weekend_and_the_evening():
    sat_evening = datetime(2026, 9, 12, 20, 0)  # Saturday
    assert C.next_run("0 10-16 * * 1-5", sat_evening) == datetime(2026, 9, 14, 10, 0)
    mon_1630 = datetime(2026, 9, 14, 16, 30)
    assert C.next_run("0 10-16 * * 1-5", mon_1630) == datetime(2026, 9, 15, 10, 0)
    assert C.next_run_any(["0 10-16 * * 1-5", "0 18 * * 1-5"], mon_1630) == datetime(2026, 9, 14, 18, 0)


def test_next_run_is_strictly_after_and_handles_steps_lists_and_sunday_seven():
    t = datetime(2026, 9, 14, 10, 0)
    assert C.next_run("0 10-16 * * 1-5", t) == datetime(2026, 9, 14, 11, 0)
    assert C.next_run("*/15 * * * *", datetime(2026, 9, 14, 10, 7)) == datetime(2026, 9, 14, 10, 15)
    assert C.next_run("30 8 * * 7", t) == datetime(2026, 9, 20, 8, 30)
    assert C.next_run("5 9 1,15 * *", t) == datetime(2026, 9, 15, 9, 5)


def test_malformed_expressions_raise_or_are_skipped():
    with pytest.raises(ValueError):
        C.next_run("0 25 * * *", datetime(2026, 9, 14))
    assert C.next_run_any(["nonsense", "0 18 * * 1-5"], datetime(2026, 9, 14, 17, 0)) == datetime(2026, 9, 14, 18, 0)
