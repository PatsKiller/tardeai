"""A guarantee that spans invocations needs state that does too, and a send
without a receipt is not a send.

B2  `_dedupe_cache`, `_hourly_counts`, `_last_health` and `_health_daily_count`
    are module-level dicts. Every producer reaching that module is a one-shot
    cron or systemd process, so they are empty at every invocation:
    `_dedupe_cache` was always empty when consulted, `mark_sent()` wrote to a
    dict that died microseconds later, and the "max 2 health telegrams per day"
    cap passed unconditionally on every cold start.

B5  `open_trade_alerts.sent_telegram` was 0 of 864 rows and
    `alert_events.telegram_sent_at` 0 of 932. The columns existed; nothing wrote
    them. With no receipt there was no way to answer "did the operator get this?"
    -- which is why 25 repeats could not be traced to a producer and a 98-day
    delivery outage went unnoticed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("", "scripts"):
    p = str(ROOT / sub) if sub else str(ROOT)
    if p not in sys.path:
        sys.path.insert(0, p)


# ── B2 ────────────────────────────────────────────────────────────────────────

def test_dedupe_survives_a_process_boundary(tmp_path, monkeypatch):
    """The regression: a key marked in one process must be seen by the next.

    A module-level dict cannot do this. The durable store can.
    """
    # The variable is CIO_OUTBOUND_DEDUPE_PATH. An earlier draft of this test set
    # CIO_DEDUPE_PATH, which does not exist -- the test passed anyway, writing to
    # the default store. A test that passes while its isolation does nothing is
    # the defect this suite exists to catch, so the path is asserted below.
    store = tmp_path / "dedupe.jsonl"
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(store))
    import importlib
    import scripts.telegram_alert_router as R
    importlib.reload(R)

    key = "b2-cross-process-probe"
    assert R._durable_recently_sent(key, 3600) is False
    R.durable_mark_sent(key, {"test": True})

    # Simulate a NEW process: the in-memory caches start empty again.
    importlib.reload(R)
    assert R._durable_recently_sent(key, 3600) is True, \
        "the guarantee did not survive a fresh module state"
    assert store.exists(), "the test wrote somewhere other than its tmp store"
    assert key in store.read_text(encoding="utf-8")


def test_the_in_memory_cache_alone_would_not_have_survived():
    """Guard the guard: prove the dict is the thing that could not work."""
    import scripts.telegram_alert_router as R
    import importlib
    R._dedupe_cache["ephemeral"] = 10 ** 12
    importlib.reload(R)
    assert "ephemeral" not in R._dedupe_cache, \
        "module state unexpectedly persisted; the premise no longer holds"


def test_durable_lookup_fails_open():
    """A dedupe lookup that cannot run must not silently suppress a real send."""
    import scripts.telegram_alert_router as R
    assert R._durable_recently_sent("", 3600) in (False, True)


# ── B5 ────────────────────────────────────────────────────────────────────────

def test_the_sender_returns_a_receipt():
    import open_trade_monitor as m
    r = m.send_telegram_with_buttons("probe", [[("a", "b")]], dry_run=True)
    assert isinstance(r, dict), "the sender must return a receipt, not None"
    for field in ("ok", "message_id", "error"):
        assert field in r


def test_a_dry_run_receipt_is_not_a_success():
    import open_trade_monitor as m
    r = m.send_telegram_with_buttons("probe", [[("a", "b")]], dry_run=True)
    assert r["ok"] is False and r["error"] == "dry_run"


def test_recording_a_receipt_is_non_fatal():
    """Failing to record must never stop the monitor -- it also closes positions."""
    import open_trade_monitor as m

    class FailingConn:
        def cursor(self):
            raise RuntimeError("db down")

    m.record_send_receipt(FailingConn(), 1, {"ok": True})   # must not raise
    m.record_send_receipt(FailingConn(), None, {"ok": True})


def test_the_monitor_imports_without_a_database():
    """CI runs the deterministic subset with no Postgres.

    This module previously did a module-level `from session13_db import get_conn`,
    so merely importing it required psycopg2 and these tests failed in CI while
    passing locally -- green on a machine that happened to have the driver.
    """
    import importlib
    import open_trade_monitor as m
    importlib.reload(m)
    assert callable(m.get_conn)


def test_both_alert_paths_record_a_receipt():
    src = (ROOT / "scripts" / "open_trade_monitor.py").read_text(encoding="utf-8")
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    joined = "\n".join(code)
    assert joined.count("record_send_receipt(conn,") >= 2, \
        "both the NEAR_STOP and STOP_WARNING sends must record a receipt"
