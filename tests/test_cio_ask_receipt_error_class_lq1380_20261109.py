"""ANCHOR: CIO_ASK_RECEIPT_ERROR_CLASS_LQ1380_20261109 — a failed material source names its cause in the receipt.

2026-11-08, 22:29:59 ET: the ``trade_ai`` role password was changed out of band; the tmpfs secret render still
carried the previous value until 22:47:06. ``cio-ask-material-events`` failed slots 22:30/22:35/22:40 (exit 1)
and its breaker opened at 22:40:06 — and every surface that could have named the cause had flattened it. The
lane summary said ``material_changes:OperationalError`` (auth rejection, statement timeout and a dead server
are the same string), and the receipt's own ``error`` field said just ``material_changes``, because
``lane_last_receipt._scrub_error`` truncated *any* ``identifier:`` head. This gate pins the shape that makes
triage one read: the read-only DB boundary classifies its own failure (auth / slots / query timeout / connect
timeout / unreachable), the lifecycle carries that class in ``source_errors``, and the receipt keeps
``<source>:<ExceptionType>[:<class>]`` whole. Synthetic fixtures only; no DB, no network, no secret is read.
"""

import sys
import types

import pytest

from scripts.lib import cio_ask_material_sources as src
from scripts.lib.cio_ask_material_sources import MaterialChangesTable, SourceReadError
from scripts.lib.lane_last_receipt import _scrub_error, build_receipt
from tests.test_cio_ask_hourly_20261026 import fixture, provider, run


# ── 1. the receipt keeps "<source>:<ExceptionType>" ───────────────────────────────────────────────────────────────
def test_an_exception_head_still_loses_its_message():
    assert _scrub_error("OSError: No space left on device") == "OSError"
    assert _scrub_error("sqlite3.OperationalError: ledger_missing") == "sqlite3.OperationalError"
    assert _scrub_error("  ReadTimeout: handshake") == "ReadTimeout"
    assert _scrub_error("SystemExit: 2") == "SystemExit"


def test_a_source_tag_is_not_an_exception_type_and_is_kept_whole():
    # the deployed receipt said exactly "material_changes" for an auth rejection (2026-11-08 22:40 slot)
    assert _scrub_error("material_changes:OperationalError") == "material_changes:OperationalError"
    assert _scrub_error("sec_filing_events:FileNotFoundError") == "sec_filing_events:FileNotFoundError"
    assert _scrub_error("material_changes:OperationalError:db_auth_failed") == (
        "material_changes:OperationalError:db_auth_failed"
    )


def test_other_strings_are_still_length_capped():
    assert _scrub_error("x" * 400) == "x" * 300
    assert _scrub_error(None) is None
    assert _scrub_error(7) == 7


def test_the_receipt_error_field_carries_the_source_and_the_type():
    doc = build_receipt(
        "cio-ask-material-events",
        ok=False,
        error="material_changes:OperationalError:db_auth_failed",
        summary={"ok": False, "source_errors": ["material_changes:OperationalError:db_auth_failed"]},
    )
    assert doc["error"] == "material_changes:OperationalError:db_auth_failed"
    assert doc["status"] == "failed"
    # source_errors is a list under a plural key: the per-value scrubber never touches it
    assert doc["summary"]["source_errors"] == ["material_changes:OperationalError:db_auth_failed"]


# ── 2. the DB boundary classifies the failure ─────────────────────────────────────────────────────────────────────
class _FakePgError(Exception):
    def __init__(self, message, pgcode=None):
        super().__init__(message)
        self.pgcode = pgcode


@pytest.mark.parametrize(
    "exc, expected",
    [
        (_FakePgError("anything", pgcode="28P01"), src.DB_AUTH_FAILED),
        (_FakePgError('FATAL:  password authentication failed for user "trade_ai"'), src.DB_AUTH_FAILED),
        (_FakePgError("no password supplied"), src.DB_AUTH_FAILED),
        (_FakePgError("FATAL: sorry, too many clients already", pgcode="53300"), src.DB_SLOTS_EXHAUSTED),
        (_FakePgError("connection slot exhausted"), src.DB_SLOTS_EXHAUSTED),
        (_FakePgError("canceling statement due to statement timeout", pgcode="57014"), src.DB_QUERY_TIMEOUT),
        (_FakePgError("canceling statement due to statement timeout"), src.DB_QUERY_TIMEOUT),
        (_FakePgError("connection to server at \"localhost\", port 5432 failed: timeout expired"), src.DB_CONNECT_TIMEOUT),
        (_FakePgError("server closed the connection unexpectedly"), src.DB_UNREACHABLE),
        (_FakePgError("could not connect to server"), src.DB_UNREACHABLE),
        (_FakePgError("odd driver failure"), src.DB_ERROR),
    ],
)
def test_read_failure_reason_classifies_by_sqlstate_then_wording(exc, expected):
    assert src._read_failure_reason(exc) == expected
    assert expected in src.DB_FAILURE_REASONS


def _fake_psycopg2(monkeypatch, connect):
    mod = types.ModuleType("psycopg2")
    extras = types.ModuleType("psycopg2.extras")
    extras.RealDictCursor = object
    mod.extras = extras
    mod.Error = _FakePgError
    mod.connect = connect
    monkeypatch.setitem(sys.modules, "psycopg2", mod)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)


def test_a_rejected_connect_becomes_a_classified_source_error(monkeypatch):
    def connect(**_kw):
        raise _FakePgError('FATAL:  password authentication failed for user "trade_ai"', pgcode="28P01")

    _fake_psycopg2(monkeypatch, connect)
    with pytest.raises(SourceReadError) as info:
        src._read_query("SELECT 1", ())
    assert info.value.reason == src.DB_AUTH_FAILED
    assert str(info.value) == src.DB_AUTH_FAILED          # the driver text is not copied into the reason
    assert isinstance(info.value.cause, _FakePgError)     # ...but the original is still reachable


def test_a_failed_execute_closes_the_connection_and_classifies(monkeypatch):
    closed = []

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def execute(self, *_a):
            raise _FakePgError("canceling statement due to statement timeout", pgcode="57014")

        def fetchall(self):
            return []

    class _Conn:
        def set_session(self, **_kw):
            pass

        def cursor(self, **_kw):
            return _Cur()

        def close(self):
            closed.append(True)

    _fake_psycopg2(monkeypatch, lambda **_kw: _Conn())
    with pytest.raises(SourceReadError) as info:
        src._read_query("SELECT 1", ())
    assert info.value.reason == src.DB_QUERY_TIMEOUT
    assert closed == [True]


def test_a_non_select_is_still_a_programming_error(monkeypatch):
    _fake_psycopg2(monkeypatch, lambda **_kw: pytest.fail("must not connect"))
    with pytest.raises(ValueError, match="MATERIAL_READ_ONLY"):
        src._read_query("DELETE FROM material_changes", ())


# ── 3. the lane carries the class into its summary ────────────────────────────────────────────────────────────────
def _auth_failing_query(_sql, _params):
    raise SourceReadError(src.DB_AUTH_FAILED)


def test_the_material_source_carries_the_class_into_source_errors(tmp_path):
    d = fixture(tmp_path, provider=provider([]))
    result = run(d, events_only=True, event_sources=[MaterialChangesTable(db_query=_auth_failing_query)])
    assert result["ok"] is False
    assert result["source_errors"] == ["material_changes:SourceReadError:db_auth_failed"]


def test_an_unclassified_source_keeps_its_old_two_part_shape(tmp_path):
    d = fixture(tmp_path, provider=provider([]))

    def boom(_g, _s):
        raise RuntimeError("feed down")

    result = run(
        d,
        events_only=True,
        event_sources=[types.SimpleNamespace(name="sec_filing_events", fetch=boom)],
    )
    assert result["source_errors"] == ["sec_filing_events:RuntimeError"]


def test_the_receipt_built_from_that_summary_names_the_class(tmp_path):
    d = fixture(tmp_path, provider=provider([]))
    summary = run(d, events_only=True, event_sources=[MaterialChangesTable(db_query=_auth_failing_query)])
    doc = build_receipt(
        "cio-ask-material-events",
        ok=bool(summary["ok"]),
        error="; ".join(summary["source_errors"])[:400] or None,
        summary=summary,
    )
    assert doc["error"] == "material_changes:SourceReadError:db_auth_failed"
    assert doc["summary"]["source_errors"] == ["material_changes:SourceReadError:db_auth_failed"]
