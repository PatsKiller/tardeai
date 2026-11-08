"""LQ-20261107-478 — build-hermes-canonical-status reads live DB table lineage, not a 5-month-old snapshot.

ANCHOR: BUILD_HERMES_CANONICAL_STATUS_LINEAGE_20261107

The canonical snapshot's table list and its counts came from ``data/hermes/hermes_db_lineage_latest.json``
(generated 2026-06-07, and nothing schedules its producer), so a 2026-11-07 run answered with June's rows:
hermes_research_intelligence 1976 vs 21,202 live, hermes_memory_events 438 vs 17,492, six tables vs 27.
The lane now measures them read-only through the shared credential loader; the snapshot is a labelled
fallback that is never presented as a measurement. Hermetic: the DB, the endpoints and the host are faked.
"""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from psycopg2 import sql as psql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _render(query):
    """What psycopg2's driver sends for a Composable: SQL parts verbatim, identifiers quoted."""
    if isinstance(query, str):
        return query
    out = []
    for part in query.seq:
        if isinstance(part, psql.Identifier):
            out.append('"' + part.string.replace('"', '""') + '"')
        elif isinstance(part, psql.SQL):
            out.append(part.string)
        else:  # pragma: no cover - a new part type must be taught to the fake, not guessed at
            raise AssertionError(f"unexpected composed part: {type(part).__name__}")
    return "".join(out)


class _FakeCursor:
    """Answers the three shapes measure_db_lineage issues, from canned data."""

    def __init__(self, relations, ts_rows, aggregates):
        self.relations = relations
        self.ts_rows = ts_rows
        self.aggregates = aggregates
        self.rows = []
        self.executed = []
        self.composed = []

    def execute(self, sql, params=None):
        # measure_db_lineage composes psycopg2.sql.Composable, never an f-string; this renders what
        # the driver would send (SQL parts verbatim, Identifier parts quoted) so the shapes route.
        text = _render(sql)
        self.executed.append(text)
        if not isinstance(sql, str):
            self.composed.append(sql)
        if "information_schema.tables" in text:
            self.rows = list(self.relations)
        elif "information_schema.columns" in text:
            self.rows = list(self.ts_rows)
        elif " from public." in text:
            table = text.split(" from public.", 1)[1].split(None, 1)[0].strip('"')
            if "count(*), max(" in text:
                self.rows = [self.aggregates[table]]
            else:
                self.rows = [(self.aggregates[table][0],)]
        else:  # pragma: no cover - a new query shape must be taught to the fake, not guessed at
            raise AssertionError(f"unexpected SQL: {text[:80]}")

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0]

    def close(self):
        pass


class _FakeConn:
    def __init__(self, **kwargs):
        self.cursor_obj = _FakeCursor(**kwargs)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def _fake_connect(relations, ts_rows, aggregates):
    conn = _FakeConn(relations=relations, ts_rows=ts_rows, aggregates=aggregates)
    factory = lambda: conn  # noqa: E731 — a connection factory, the seam measure_db_lineage takes
    factory.conn = conn
    return factory


@pytest.fixture
def bh(monkeypatch):
    mod = importlib.import_module("build_hermes_canonical_status")
    monkeypatch.setattr(mod, "measure_host_counts", lambda: {
        "crons_count": 327, "timers_count": 83, "timers_system_count": 12,
        "counts_provenance": {"crons_count": {"estimated": True}, "timers_count": {}, "timers_system_count": {},
                              "services_count": {}, "llm_jobs_count": {}}})
    return mod


STALE_LINEAGE = [
    {"table": "hermes_research_intelligence", "exists": True, "rows": 1976,
     "last_write": "2026-06-07 12:30:45-04:00", "writes_24h": 436, "written_by": ["hermes_coordinator.py"],
     "read_by": ["api_v2.py"]},
    {"table": "hermes_memory_events", "exists": True, "rows": 438, "last_write": "2026-06-07 12:17:15-04:00",
     "writes_24h": 95, "written_by": ["hermes_coordinator.py"], "read_by": ["api_v2.py"]},
]


def test_a_live_read_replaces_the_snapshot_list_and_counts(bh, monkeypatch):
    live = [
        {"table": "hermes_research_intelligence", "exists": True, "rows": 21202, "last_write": "2026-11-07T18:19:00",
         "writes_24h": 57, "writes_7d": 900, "counted_by": "created_at", "written_by": ["hermes_coordinator.py"],
         "read_by": ["api_v2.py"]},
        {"table": "hermes_memory_events", "exists": True, "rows": 17492, "last_write": "2026-11-07T18:00:00",
         "writes_24h": 12, "writes_7d": 300, "counted_by": "created_at", "written_by": None, "read_by": None},
    ]
    prov = {"definition": bh.LIVE_LINEAGE_DEFINITION, "source": "live", "measured_at": "2026-11-07T23:00:00+00:00",
            "tables_counted": 2, "views_counted": 13, "error": None}
    seen = {}

    def fake_measure(static_tables=None, connect=None):
        seen["static"] = static_tables
        return live, ["hermes_v_ticker_context"], prov

    monkeypatch.setattr(bh, "measure_db_lineage", fake_measure)
    monkeypatch.setattr(bh, "api", lambda ep: {
        "db_lineage": STALE_LINEAGE, "safe_views_count": 13,
        "audit_sources": {"files": {"db_lineage": {"path": "data/hermes/hermes_db_lineage_latest.json",
                                                   "present": True, "modified_at": "2026-06-07T12:31:00"}}},
    } if ep == "workflow-matrix" else {})

    snap, _ = bh.build_snapshot()

    # The endpoint's list is what the measurement is asked about; passing it as the connection seam
    # was a real defect (the live read never ran) that no test asserting only the output caught.
    assert [t["table"] for t in seen["static"]] == ["hermes_research_intelligence", "hermes_memory_events"]
    assert snap["db_tables_count"] == 2
    assert snap["db_tables"][0]["rows"] == 21202            # measured, not June's 1976
    assert snap["db_writes_24h"] == {"research_intelligence": 57, "memory_events": 12}
    assert snap["safe_views_count"] == 1
    assert snap["counts_provenance"]["db_tables_count"]["source"] == "live"
    assert snap["counts_provenance"]["db_writes_24h"]["fresh"] is True
    assert snap["counts_provenance"]["db_tables_count"]["snapshot_age_days"] > 100


def test_a_failed_db_read_keeps_the_snapshot_and_labels_it(bh, monkeypatch):
    monkeypatch.setattr(bh, "measure_db_lineage", lambda static_tables=None, connect=None: (
        None, None, {"source": "snapshot", "measured_at": None, "snapshot_path": str(bh.LINEAGE_SNAPSHOT),
                     "error": "RuntimeError: DB_PASSWORD missing from process configuration"}))
    monkeypatch.setattr(bh, "api", lambda ep: {
        "db_lineage": STALE_LINEAGE, "safe_views_count": 13,
        "audit_sources": {"files": {"db_lineage": {"path": "data/hermes/hermes_db_lineage_latest.json",
                                                   "present": True, "modified_at": "2026-06-07T12:31:00"}}},
    } if ep == "workflow-matrix" else {})

    snap, _ = bh.build_snapshot()

    prov = snap["counts_provenance"]["db_tables_count"]
    assert snap["db_tables_count"] == 2 and snap["db_tables"][0]["rows"] == 1976   # the snapshot, unchanged
    assert prov["source"] == "data/hermes/hermes_db_lineage_latest.json"           # labelled, not presented as live
    assert prov["stale"] is True and prov["age_days"] > 100
    assert prov["live_error"].startswith("RuntimeError: DB_PASSWORD missing")
    assert snap["counts_provenance"]["db_writes_24h"]["fresh"] is False             # June's writes_24h is unknown


def test_measure_reads_rows_write_windows_and_columns(bh):
    connect = _fake_connect(
        relations=[("hermes_alerts", "BASE TABLE"), ("hermes_research_intelligence", "BASE TABLE"),
                   ("hermes_entity_cooccurrence", "BASE TABLE"), ("hermes_v_ticker_context", "VIEW")],
        ts_rows=[("hermes_alerts", "updated_at"), ("hermes_alerts", "created_at"),
                 ("hermes_research_intelligence", "created_at"),
                 ("hermes_research_intelligence", "updated_at")],
        aggregates={"hermes_alerts": (0, None, 0, 0),
                    "hermes_research_intelligence": (21202, datetime(2026, 11, 7, 23, 19, tzinfo=timezone.utc), 57, 900),
                    "hermes_entity_cooccurrence": (41,)})

    tables, views, prov = bh.measure_db_lineage(connect=connect, static_tables=STALE_LINEAGE)

    assert prov["source"] == "live" and prov["error"] is None and prov["tables_counted"] == 3
    assert views == ["hermes_v_ticker_context"]
    by = {t["table"]: t for t in tables}
    assert by["hermes_research_intelligence"]["rows"] == 21202
    assert by["hermes_research_intelligence"]["counted_by"] == "created_at"      # preferred over updated_at
    assert by["hermes_research_intelligence"]["writes_24h"] == 57
    assert by["hermes_research_intelligence"]["last_write"].startswith("2026-11-07")
    assert by["hermes_research_intelligence"]["written_by"] == ["hermes_coordinator.py"]  # static audit, by name
    assert by["hermes_entity_cooccurrence"]["rows"] == 41
    assert by["hermes_entity_cooccurrence"]["writes_24h"] is None                # no timestamp column: unknown
    assert prov["snapshot_tables_not_in_db"] == ["hermes_memory_events"]
    # Identifiers are composed by the driver, so a table name cannot become SQL.
    assert 'from public."hermes_research_intelligence"' in "\n".join(connect.conn.cursor_obj.executed)
    assert any(isinstance(q, psql.Composed) for q in connect.conn.cursor_obj.composed)


def test_a_connection_that_cannot_open_reports_the_reason_never_a_number(bh):
    def boom():
        raise RuntimeError("DB_PASSWORD missing from process configuration")

    tables, views, prov = bh.measure_db_lineage(connect=boom)

    assert tables is None and views is None
    assert prov["source"] == "snapshot" and prov["measured_at"] is None
    assert prov["error"] == "RuntimeError: DB_PASSWORD missing from process configuration"


def test_a_snapshot_entry_whose_table_is_gone_is_named(bh):
    connect = _fake_connect(relations=[("hermes_memory_events", "BASE TABLE")],
                            ts_rows=[("hermes_memory_events", "created_at")],
                            aggregates={"hermes_memory_events": (10, None, 0, 0)})

    _tables, _views, prov = bh.measure_db_lineage(connect=connect, static_tables=STALE_LINEAGE)

    assert prov["snapshot_tables_not_in_db"] == ["hermes_research_intelligence"]


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = tmp_path / "persistent"
    (root / "data" / "runtime").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(root))
    monkeypatch.delenv("TRADEAI_STATE_ROOT", raising=False)  # outranks the persistent root
    return root


@pytest.mark.parametrize("live_ok,expected", [(True, "live"), (False, "snapshot")])
def test_the_receipt_names_which_source_answered(bh, state, tmp_path, monkeypatch, live_ok, expected):
    """A fallback that only the snapshot file records is invisible to anyone reading the receipt."""
    monkeypatch.setattr(bh, "OUT", tmp_path / "out" / "hermes_canonical_status_latest.json")
    monkeypatch.setattr(bh, "sysd", lambda cmd: "active")
    monkeypatch.setattr(bh, "api", lambda ep: {"db_lineage": STALE_LINEAGE, "safe_views_count": 13}
                        if ep == "workflow-matrix" else {})
    if live_ok:
        monkeypatch.setattr(bh, "measure_db_lineage", lambda static_tables=None, connect=None: (
            [{"table": "hermes_memory_events", "rows": 17492, "writes_24h": 191}], ["hermes_v_ticker_context"],
            {"source": "live", "measured_at": "2026-11-07T23:00:00+00:00", "error": None}))
    else:
        monkeypatch.setattr(bh, "measure_db_lineage", lambda static_tables=None, connect=None: (
            None, None, {"source": "snapshot", "measured_at": None, "error": "RuntimeError: no DB"}))

    assert bh.main([]) == 0
    receipt = json.loads((state / "data" / "runtime" / f"{bh.LANE_ID}_last.json").read_text())

    assert receipt["summary"]["db_lineage_source"] == expected
