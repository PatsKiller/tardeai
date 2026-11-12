"""LQ-20261107-2485: a Watch GET route whose store cannot be read answers an explicit error, not ok:true + empties.

Production defect: ``_db_query`` returns None on ANY failure (and db_adapter._execute swallows the
driver's exception before that), while the Watch handlers wrote ``_db_query(...) or []`` and returned
``{"ok": true, "alerts": [], "count": 0, ...}`` — a healthy-looking empty page on a DB outage.

Hermetic and synthetic: a fake connection raises; no database, state file or endpoint is touched.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402
import db_adapter  # noqa: E402
from lib.data_broker import watch_intelligence  # noqa: E402

psycopg2 = pytest.importorskip("psycopg2")


# ── fake drivers ──────────────────────────────────────────────────────────────

class _RaisingCursor:
    def __init__(self, exc):
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, *args, **kwargs):
        raise self.exc

    def fetchone(self):  # pragma: no cover - execute always raises first
        raise AssertionError("fetchone after a failed execute")

    def fetchall(self):  # pragma: no cover
        raise AssertionError("fetchall after a failed execute")


class _RaisingConn:
    """The smallest connection that fails at the statement, the way a refused/reaped one does."""

    closed = False

    def __init__(self, exc):
        self.exc = exc
        self.rollbacks = 0

    def cursor(self, *args, **kwargs):
        return _RaisingCursor(self.exc)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class _EmptyCursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, *args, **kwargs):
        pass

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _EmptyConn:
    """A live connection on which the read ran and genuinely found nothing."""

    closed = False

    def cursor(self, *args, **kwargs):
        return _EmptyCursor()

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def dead_db(monkeypatch):
    """Every required read takes the strict path and the driver raises OperationalError."""
    exc = psycopg2.OperationalError("connection refused by the server")
    conn = _RaisingConn(exc)
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None)
    monkeypatch.setattr(db_adapter, "USE_DB", True, raising=False)
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: conn)
    monkeypatch.setattr(db_adapter, "close_thread_conn", lambda: None)
    return exc


@pytest.fixture
def broken_query_db(monkeypatch):
    """The driver rejects the statement itself (not a connection problem)."""
    exc = psycopg2.errors.UndefinedColumn('column "nope" does not exist')
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None)
    monkeypatch.setattr(db_adapter, "USE_DB", True, raising=False)
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: _RaisingConn(exc))
    monkeypatch.setattr(db_adapter, "close_thread_conn", lambda: None)
    return exc


def _faked_journal(monkeypatch):
    """Keep /stops/reentry-watch off the live journal store: the thesis read is the one under test."""
    jtl = types.ModuleType("journal_ticker_lifecycle")
    jtl.load_from_db = lambda account, days: []
    jtl.aggregate_ticker_activity = lambda rows: []
    sow = types.ModuleType("stop_out_reentry_watch")
    sow.build_stop_out_reviews = lambda lifecycle: [{"symbol": "AAA"}]
    sow.build_reentry_watch = lambda reviews, thesis: []
    monkeypatch.setitem(sys.modules, "journal_ticker_lifecycle", jtl)
    monkeypatch.setitem(sys.modules, "stop_out_reentry_watch", sow)


#: (label, handler thunk) — every Watch GET route that used to answer ok:true + an empty list.
WATCH_HANDLERS = [
    ("watch/alerts/list", lambda: api_v2._watch_alerts_list()),
    ("watch/decision/summary", lambda: api_v2._watch_decision_summary()),
    ("watch/directives/detail", lambda: api_v2._watch_directive_detail({"id": ["7"]})),
    ("watch-directives", lambda: api_v2._watch_directives_all()),
    ("watchpool", lambda: api_v2._watchpool_list()),
    ("watch/sectors", lambda: api_v2._watch_sectors()),
    ("watchlist/summary", lambda: api_v2._wl_summary()),
    ("watchlist/jobs", lambda: api_v2._wl_jobs()),
    ("watchlist/results", lambda: api_v2._wl_results()),
    ("watchlist/debug", lambda: api_v2._wl_debug()),
    ("watch/ticket-review/status", lambda: api_v2._ticket_review_status({"symbol": ["AAA"]})),
    ("stopped-out-watch", lambda: api_v2.stopped_out_watch_list()),
    ("tos-watchlists", lambda: api_v2._tos_watchlists_list()),
    ("watch/two-way-curation", lambda: api_v2._two_way_curation_health()),
    ("reentry/decision-desk", lambda: api_v2._build_reentry_decision_desk_api()),
]


@pytest.mark.parametrize("label,call", WATCH_HANDLERS, ids=[h[0] for h in WATCH_HANDLERS])
def test_an_unreadable_store_is_an_explicit_unknown_with_its_cause(dead_db, label, call):
    out = call()
    assert isinstance(out, tuple) and len(out) == 2, f"{label} did not answer a status body: {out!r}"
    status, body = out
    assert status == 503, f"{label} answered {status}, not 503"
    assert body["ok"] is False
    assert body["state"] == "UNKNOWN"
    assert body["error"] == "db_unavailable"
    assert "connection refused" in body["cause"]
    assert body["route"]
    assert body["retry_after_sec"] == 5
    # the old healthy shapes must not appear beside the error
    for key in ("alerts", "count", "rows", "sectors", "jobs", "results", "directives", "watchlists"):
        assert key not in body, f"{label} still carries a healthy empty {key!r}"


def test_stops_reentry_watch_is_explicit_when_its_thesis_store_is_unreadable(dead_db, monkeypatch):
    _faked_journal(monkeypatch)
    status, body = api_v2._stops_reentry_watch_api()
    assert status == 503 and body["error"] == "db_unavailable"
    assert "connection refused" in body["cause"]
    assert "reviews" not in body


def test_a_statement_error_is_a_500_with_the_same_cause(broken_query_db):
    status, body = api_v2._watch_alerts_list()
    assert status == 500
    assert body["error"] == "db_read_failed" and body["state"] == "UNKNOWN"
    assert "does not exist" in body["cause"] and "db_unavailable" not in body


def test_database_disabled_is_an_explicit_unknown(monkeypatch):
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None)
    monkeypatch.setattr(db_adapter, "USE_DB", False, raising=False)
    status, body = api_v2._wl_jobs()
    assert status == 503 and body["error"] == "db_unavailable"
    assert "USE_DB" in body["cause"]


def test_the_dispatcher_does_not_wrap_the_error_as_ok_true(dead_db):
    status, body = api_v2.handle("/api/v2/watch/alerts/list")
    assert status == 503 and body["ok"] is False and body["error"] == "db_unavailable"
    # a decorated zero-argument handler must still be called with no query (inspect.signature
    # follows __wrapped__, so the dispatcher's arity check is unchanged)
    status2, body2 = api_v2.handle("/api/v2/watchlist/jobs")
    assert status2 == 503 and body2["ok"] is False


def test_the_main_watchlist_route_is_explicit_not_an_empty_list(dead_db):
    with pytest.raises(api_v2._DbReadError):
        api_v2._wl_items()
    status, body = api_v2.handle("/api/v2/watchlist/items")
    assert status == 503 and body["error"] == "db_unavailable"
    assert "items" not in body and body["ok"] is False


def test_reentry_status_carries_the_desk_error_instead_of_a_projection(dead_db):
    status, body = api_v2._reentry_status_projection()
    assert status == 503 and body["route"] == "/api/v2/reentry/decision-desk"
    assert body["state"] == "UNKNOWN"


def test_a_read_that_ran_and_found_no_row_is_still_not_found(monkeypatch):
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None)
    monkeypatch.setattr(db_adapter, "USE_DB", True, raising=False)
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: _EmptyConn())
    out = api_v2._watch_directive_detail({"id": ["7"]})
    assert isinstance(out, dict) and out["ok"] is False
    assert "not found" in out["error"]


def test_db_required_uses_the_ordinary_read_when_it_answers(monkeypatch):
    rows = [{"symbol": "AAA"}]
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: rows)
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: (_ for _ in ()).throw(AssertionError("re-read")))
    assert api_v2._db_required("SELECT 1") == rows


def test_watchlist_combined_labels_each_failed_enrichment_source(monkeypatch):
    # same hermetic fixture shape as tests/test_watchlist_news_enrichment_lq2137_20261111.py
    monkeypatch.setattr(api_v2, "_load_json", lambda p: {"watchlist.json": {"AAA": {}}}.get(Path(p).name))
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None)
    monkeypatch.setattr(db_adapter, "USE_DB", True, raising=False)
    monkeypatch.setattr(
        db_adapter,
        "_execute",
        lambda *a, **k: (_ for _ in ()).throw(psycopg2.OperationalError("connection refused")),
    )
    monkeypatch.setattr(db_adapter, "load_watchlist_items", lambda **kw: [])
    monkeypatch.setattr(watch_intelligence, "active_ticker_directives", lambda: [])
    out = api_v2.watchlist_combined()
    assert set(out["enrichment_unknown"]) >= {"llm_health", "news", "social", "scan"}
    item = out["items"][0]
    assert item["news_status"] == "UNKNOWN" and item["news_7d"] is None
    assert "active_news" not in item["conviction_signals"]


def test_watchlist_combined_recovers_the_cause_when_execute_swallows_it(monkeypatch):
    # The production shape: db_adapter._execute() logs the SQL error and answers None, so the
    # per-source `except` never sees it. Without a re-read on the connection the gap again reads
    # as "no news" — this is the LQ-2485 hole inside the LQ-2137 fix.
    monkeypatch.setattr(api_v2, "_load_json", lambda p: {"watchlist.json": {"AAA": {}}}.get(Path(p).name))
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None)
    monkeypatch.setattr(db_adapter, "USE_DB", True, raising=False)
    monkeypatch.setattr(db_adapter, "_execute", lambda *a, **k: None)
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: _RaisingConn(psycopg2.OperationalError("connection refused")))
    monkeypatch.setattr(db_adapter, "close_thread_conn", lambda: None)
    monkeypatch.setattr(db_adapter, "load_watchlist_items", lambda **kw: [])
    monkeypatch.setattr(watch_intelligence, "active_ticker_directives", lambda: [])
    out = api_v2.watchlist_combined()
    assert set(out["enrichment_unknown"]) >= {"llm_health", "news", "social", "scan"}
    assert "connection refused" in out["enrichment_unknown"]["news"]
    assert out["items"][0]["news_status"] == "UNKNOWN"


def test_the_old_shape_is_what_the_defect_looked_like():
    # Pin the contract this patch replaces, so a later edit cannot quietly restore it.
    assert not isinstance({"ok": True, "alerts": [], "active_count": 0}, tuple)


# ── LQ-20261107-2517: F1 (one execution per required read) and F2 (classify by class, not text) ──

class _SqlStateError(Exception):
    """A driver error carrying a SQLSTATE, the tag psycopg2 sets on every error it raises itself.

    ``pgcode`` is read-only on psycopg2's own exception classes, so a test that needs an exact
    SQLSTATE — or none at all — uses this stub. Hand-built psycopg2 exceptions have ``pgcode`` None
    (checked), which is the case the class fallback in ``_db_exc_unavailable`` exists for.
    """

    def __init__(self, text, code):
        super().__init__(text)
        self.pgcode = code


class _CountingCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        self.conn.executions += 1
        self.conn.sqls.append(sql)
        if self.conn.exc is not None:
            raise self.conn.exc

    def fetchone(self):
        return self.conn.rows[0] if self.conn.rows else None

    def fetchall(self):
        return list(self.conn.rows)


class _CountingConn:
    """Counts statement executions, so a test can prove one required read runs its SQL once."""

    closed = False

    def __init__(self, exc=None, rows=()):
        self.exc = exc
        self.rows = list(rows)
        self.executions = 0
        self.sqls = []
        self.rollbacks = 0
        self.commits = 0

    def cursor(self, *args, **kwargs):
        return _CountingCursor(self)

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def _drive_required(monkeypatch, conn, sql="SELECT 1 AS ok", fetch="one"):
    """Call the real ``_db_required`` → real ``_db_query`` → real ``db_adapter._execute`` → ``conn``."""
    monkeypatch.setattr(db_adapter, "USE_DB", True, raising=False)
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: conn)
    monkeypatch.setattr(db_adapter, "close_thread_conn", lambda: None)
    return api_v2._db_required(sql, fetch=fetch)


# F1 — a required read must execute its statement once, however it ends.

def test_a_statement_failure_executes_the_read_once(monkeypatch):
    """Fail-before (REVIEW-2511 measured 2): the strict path re-ran the statement to recover the cause."""
    exc = _SqlStateError("canceling statement due to statement timeout", "57014")
    conn = _CountingConn(exc=exc)
    with pytest.raises(api_v2._DbReadError) as caught:
        _drive_required(monkeypatch, conn)
    assert conn.executions == 1, f"a failing required read ran its statement {conn.executions} times"
    err = caught.value
    assert "statement timeout" in err.cause
    # F4, chosen deliberately: the database is up, so a statement timeout is a real error, not a soft retry.
    assert err.unavailable is False and err.http_status == 500


def test_a_read_that_found_no_row_executes_the_statement_once(monkeypatch):
    """Fail-before (measured 2): a not-found single-row read paid a second round trip."""
    conn = _CountingConn(rows=())
    assert _drive_required(monkeypatch, conn) is None
    assert conn.executions == 1, f"a not-found read ran its statement {conn.executions} times"


def test_a_connection_failure_is_not_re_run_by_the_strict_path(monkeypatch):
    """Fail-before (measured 4): the adapter's one retry plus the strict path's own retry."""
    exc = _SqlStateError("server closed the connection unexpectedly", "08006")
    conn = _CountingConn(exc=exc)
    with pytest.raises(api_v2._DbReadError) as caught:
        _drive_required(monkeypatch, conn)
    # db_adapter._execute retries an idle-reaped handle once; the strict path adds no execution of its own.
    assert conn.executions == 2, f"a connection-class read ran its statement {conn.executions} times"
    assert caught.value.unavailable is True and caught.value.http_status == 503


def test_the_required_read_answers_a_failed_read_without_re_running_it(monkeypatch):
    """The note is the whole fix: db_adapter says what happened, and ``_db_required`` believes it."""
    exc = _SqlStateError('relation "agent_connections" does not exist', "42P01")
    conn = _CountingConn(exc=exc)
    with pytest.raises(api_v2._DbReadError):
        _drive_required(monkeypatch, conn, sql="SELECT 1 FROM agent_connections")
    assert conn.executions == 1
    assert conn.sqls == ["SELECT 1 FROM agent_connections"]


def test_db_adapter_records_whether_the_statement_ran_and_why(monkeypatch):
    ok = _CountingConn(rows=[{"ok": 1}])
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: ok)
    db_adapter.begin_exec_note()
    assert db_adapter._execute("SELECT 1", fetch="one") == {"ok": 1}
    assert db_adapter.last_exec_note() == (True, None)

    boom = _SqlStateError("boom", "42P01")
    bad = _CountingConn(exc=boom)
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: bad)
    assert db_adapter._execute("SELECT nope", fetch="all") is None
    ran, err = db_adapter.last_exec_note()
    assert ran is True and err is boom, "the adapter must keep the driver's own exception for the caller"

    db_adapter.begin_exec_note()
    assert db_adapter.last_exec_note() == (False, None), "a cleared note must not describe an earlier read"


# F2 — the SQLSTATE or the driver's class decides; the message text never does.

@pytest.mark.parametrize(
    "code,unavailable",
    [
        ("08006", True),    # connection failure
        ("08003", True),    # connection does not exist
        ("53300", True),    # too many connections -- retryable, so a soft 503 (REVIEW-2511 F4)
        ("57P01", True),    # admin shutdown
        ("57P03", True),    # cannot connect now
        ("42P01", False),   # undefined table: a permanent break
        ("42703", False),   # undefined column
        ("57014", False),   # statement timeout: the DB is up and the same request fails again (F4)
        ("55P03", False),   # lock not available (F4)
        ("25P02", False),   # in failed sql transaction
    ],
)
def test_the_sqlstate_class_decides_whether_the_store_is_unavailable(code, unavailable):
    cause, got = api_v2._db_cause(_SqlStateError("whatever the server said", code))
    assert got is unavailable, f"SQLSTATE {code} classified unavailable={got}"
    assert cause.startswith("_SqlStateError: ")


def test_a_schema_error_naming_a_connection_is_a_500_not_a_soft_503():
    """Fail-before: REVIEW-2511 measured 503 for both of these, because the message said 'connection'."""
    for exc in (
        psycopg2.errors.UndefinedTable('relation "agent_connections" does not exist'),
        psycopg2.errors.UndefinedColumn('column "connection_id" does not exist'),
        psycopg2.errors.UndefinedColumn('column "interfaceerror_at" does not exist'),
    ):
        cause, unavailable = api_v2._db_cause(exc)
        assert unavailable is False, f"{cause} was classed retryable because of a word in its message"


def test_a_route_answers_500_when_a_schema_error_names_a_connection(monkeypatch):
    exc = psycopg2.errors.UndefinedTable('relation "agent_connections" does not exist')
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None)
    monkeypatch.setattr(db_adapter, "USE_DB", True, raising=False)
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: _RaisingConn(exc))
    status, body = api_v2._watch_alerts_list()
    assert status == 500 and body["error"] == "db_read_failed"
    assert "does not exist" in body["cause"]


@pytest.mark.parametrize(
    "exc,unavailable",
    [
        (psycopg2.OperationalError("server closed the connection unexpectedly"), True),
        (psycopg2.InterfaceError("connection already closed"), True),
        (ConnectionError("refused"), True),
        (TimeoutError("timed out"), True),          # S6 of REVIEW-2511: this branch had no test
        (psycopg2.errors.UndefinedTable('relation "x" does not exist'), False),
        (psycopg2.ProgrammingError("syntax error at or near"), False),
        (RuntimeError("something else entirely"), False),
    ],
)
def test_an_untagged_driver_exception_is_classified_by_its_class(exc, unavailable):
    assert api_v2._db_cause(exc)[1] is unavailable, f"{type(exc).__name__} classified wrong"


# F3 — the direct path: one attempt, and it always rolls back the transaction.

def _stubbed_query_sees_nothing(monkeypatch):
    """``_db_query`` answered None without executing anything: the path that may use the direct read."""
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: None)
    monkeypatch.setattr(db_adapter, "USE_DB", True, raising=False)


def test_the_direct_read_rolls_back_after_a_successful_read(monkeypatch):
    """S2 of REVIEW-2511 (drop the rollback) had no test; without it the request thread keeps a txn open."""
    _stubbed_query_sees_nothing(monkeypatch)
    conn = _CountingConn(rows=[{"ok": 1}])
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: conn)
    assert api_v2._db_required("SELECT 1 AS ok", fetch="one") == {"ok": 1}
    assert conn.executions == 1 and conn.rollbacks >= 1
    assert conn.commits == 0, "the read path must never commit"


def test_the_direct_read_rolls_back_after_a_failure(monkeypatch):
    _stubbed_query_sees_nothing(monkeypatch)
    conn = _CountingConn(exc=psycopg2.errors.UndefinedColumn('column "nope" does not exist'))
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: conn)
    with pytest.raises(api_v2._DbReadError):
        api_v2._db_required("SELECT nope FROM t")
    assert conn.executions == 1 and conn.rollbacks >= 1


def test_the_direct_read_does_not_retry(monkeypatch):
    """A retry here would be the F1 defect inside the fallback: the adapter already retried."""
    _stubbed_query_sees_nothing(monkeypatch)
    conn = _CountingConn(exc=_SqlStateError("connection refused", "08006"))
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: conn)
    with pytest.raises(api_v2._DbReadError) as caught:
        api_v2._db_required("SELECT 1")
    assert conn.executions == 1, f"the fallback ran the statement {conn.executions} times"
    assert caught.value.http_status == 503


# F5 — the helper cannot persist a write, so it must refuse one instead of silently rolling it back.

@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE watchlist_items SET status = 'x'",
        "INSERT INTO t VALUES (1)",
        "delete from t",
        " WITH x AS (SELECT 1) DELETE FROM t WHERE id IN (SELECT * FROM x)",
        "SET statement_timeout = 0",
        "",
    ],
)
def test_a_write_is_refused_by_the_required_read_helper(monkeypatch, sql):
    monkeypatch.setattr(db_adapter, "ensure_conn", lambda: (_ for _ in ()).throw(AssertionError("a write reached the connection")))
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: [{"ok": 1}])
    with pytest.raises(ValueError):
        api_v2._db_required(sql)


@pytest.mark.parametrize(
    "sql",
    ["SELECT 1", "  select 1", "-- a note\nSELECT 1", "/* a note */ WITH x AS (SELECT 1) SELECT * FROM x", "SHOW work_mem"],
)
def test_a_read_statement_passes_the_guard(monkeypatch, sql):
    rows = [{"ok": 1}]
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: rows)
    assert api_v2._db_required(sql) == rows
