"""`attach_telegram_message_id` must actually issue the UPDATE.

WHY THESE TESTS LOOK PARANOID
-----------------------------
On 2026-09-21 six separate checks in this codebase reported success while
exercising nothing: a CI gate green over a 0% production condition, a dry run
previewing a truncated body, a PR watch reporting "settled" mid-run, a guard
validating row count instead of row content, a COVERS pin that stopped matching
its own call site, and a firing test that satisfied the ratchet while sitting
outside the gate list.

So these tests do not assert that the function exists or that it returns a
truthy value. They assert that it REACHES THE DATABASE LAYER with the right SQL
and the right parameters -- and `test_the_detector_would_catch_a_no_op` proves
the suite fails if the body were replaced with `return True`.

There is no database in CI, so asserting on the call to `_db_write` is the
honest substitute for a round trip. It is a weaker claim than "the column was
written", and it is labelled as such rather than dressed up as end-to-end.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def writer(monkeypatch):
    """Load the writer and capture every _db_write call."""
    import importlib.util

    path = ROOT / "scripts" / "alert_event_writer.py"
    spec = importlib.util.spec_from_file_location("_writer_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # loaded by explicit path: a sibling test importing this module from another
    # tree must not decide which copy we assert against (see
    # test_no_shadowed_module_imports_20260921 for why that matters).
    assert module.__file__ == str(path)

    calls: list[tuple] = []

    def _fake_db_write(sql, params=None):
        calls.append((sql, params))
        return (4242,)  # a row was updated

    monkeypatch.setattr(module, "_db_write", _fake_db_write)
    module._captured = calls
    return module


def test_it_issues_an_update_against_alert_events(writer):
    """The whole point: the id must reach the database layer."""
    assert writer.attach_telegram_message_id(4242, "99001") is True

    assert writer._captured, "no DB call was made at all"
    sql, params = writer._captured[0]
    assert "UPDATE alert_events" in sql
    assert "telegram_message_id = %s" in sql
    assert "telegram_sent_at" in sql, "an id with no timestamp is half a record"
    assert params == ("99001", 4242)


def test_it_refuses_to_overwrite_an_id_already_set(writer):
    """Mirrors the COALESCE in save_alert_event's ON CONFLICT.

    Two sends for one row would otherwise silently relabel which message the
    operator acknowledged.
    """
    writer.attach_telegram_message_id(4242, "99001")
    sql, _ = writer._captured[0]
    assert "telegram_message_id IS NULL" in sql


def test_falsy_input_makes_no_db_call(writer):
    """A missing id must not burn a connection or write a NULL."""
    for bad in ((0, "99001"), (4242, ""), (None, None), (4242, None)):
        assert writer.attach_telegram_message_id(*bad) is False
    assert writer._captured == [], "a falsy argument reached the database"


def test_a_failed_write_reports_false(writer, monkeypatch):
    """_db_write returns None on error AND on 'no row matched'.

    Both mean "not stamped", and the caller must be able to tell.
    """
    monkeypatch.setattr(writer, "_db_write", lambda *a, **k: None)
    assert writer.attach_telegram_message_id(4242, "99001") is False


def test_the_detector_would_catch_a_no_op(writer, monkeypatch):
    """Positive control: a stub implementation must FAIL this suite.

    A test that cannot fail is not a test -- the same rule the alarm-firing
    ratchet applies to alerts.
    """
    monkeypatch.setattr(writer, "attach_telegram_message_id",
                        lambda *a, **k: True)
    writer._captured.clear()
    result = writer.attach_telegram_message_id(4242, "99001")
    assert result is True  # the stub "works"
    assert writer._captured == [], "stub made no DB call, as expected"
    # ...and that absence is exactly what test_it_issues_an_update detects.


def test_send_telegram_bool_contract_is_untouched():
    """Guard the decision not to change send_telegram's return type.

    Measured 2026-09-21: >=36 files read its return value in a boolean context,
    and telegram_alert.py itself claims 182 call sites across 150 files. The id
    is reachable via last_message_id()/send_telegram_with_id(), which already
    exist -- so nothing here needs that signature to change.
    """
    src = (ROOT / "scripts" / "telegram_alert.py")
    if not src.is_file():
        pytest.skip("telegram_alert.py not in this tree")
    text = src.read_text(encoding="utf-8")
    assert "def send_telegram_with_id" in text, "the id-returning variant vanished"
    assert "def last_message_id" in text, "last_message_id() vanished"
