"""LQ-20261107-816 — a sibling lane's ledger write must not dead-letter the comms-intent slot.

The 2026-11-08 05:45 ET run of lane ``n8n-comms-intent-consumer`` exited 1 with
``sqlite3.OperationalError: database is locked`` and the executor dead-lettered it on attempt 1
(``d:n8n-comms-intent-consumer:live:20261108T0545``) out of ``max_attempts`` 3 and a 60 s lane
budget. The coordination ledger has one writer at a time (WAL + ``BEGIN IMMEDIATE``): at that
slot disk-usage-monitor (~22.4 s of run time) and n8n-incident-fanin (~24.5 s) held the write
lock, and the consumer began ~10.7 s into the slot with ~16.4 s of contention still to go.

The shared ``connect_rw`` (scripts/lib/n8n_comms_intent_consumption.py) sets
``PRAGMA busy_timeout=5000``, so the consumer gave up at 5.0 s of its 60 s — a healthy slot
killed by a neighbour's write. The lane now opens its own connection with a wider busy timeout
(30 s): still well inside the lane budget, wider than every sibling write measured on the slot.

This suite pins the value, the wiring (the apply path opens through it), that it is wider than
the shared default and still fits the lane budget, and reproduces the incident with a real
cross-connection write lock: the shared path raises ``database is locked`` at ~5 s, the lane's
waits it out and proceeds.

The *classification* half of the queue item (``database is locked`` is retryable, not terminal)
is LQ-20261107-684, delivered on ``wt/livefix-cc-deepseek-4-lq684`` head ``73749a7db``
(``DB_LOCK`` in config/n8n_executor.json + the ``SQLITE_LOCK_RE`` rail in
scripts/lib/n8n_retry_policy.py) and not yet folded into main; this branch does not duplicate it
and main still classifies the lock as terminal (asserted as a fact below, so the follower who
folds only one branch sees why both matter).

COVERS = ["scripts/n8n_comms_intent_consumer.py", "config/n8n_run_allowlist.json"]
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import n8n_comms_intent_consumer as CLI  # noqa: E402
from scripts.lib import n8n_comms_intent_consumption as C  # noqa: E402

LANE = "n8n-comms-intent-consumer"
ROUTES = ROOT / "config" / "n8n_comms_intent_routes.json"
#: The incident: the consumer started ~10.7 s into the 05:45 slot with ~16.4 s of sibling write left.
INCIDENT_REMAINING_MS = 16_400
#: How long a sibling lane holds the write lock in the reproduction — past the shared 5 s default.
HOLD_S = 6.5
NOW = datetime(2026, 11, 8, 10, 45, tzinfo=timezone.utc)


def _busy_timeout(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA busy_timeout").fetchone()[0])


def _ledger(path: Path) -> Path:
    """A ledger in the shape the gateway writes (file present, schema, WAL), as a fixture."""
    sqlite3.connect(str(path)).close()  # the gateway creates the file; a consumer never does
    C.connect_rw(path).close()
    conn = sqlite3.connect(str(path), timeout=5, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()
    return path


@contextmanager
def _sibling_write_lock(path: Path, seconds: float):
    """A second connection holding the ledger's write lock, like the fan-in sharing the :45 slot.

    Yields a dict filled when the holder returns; ``ok`` is True only if it wrote and committed."""
    held: dict = {"ok": False, "error": None, "started": False}
    acquired = threading.Event()

    def hold() -> None:
        try:
            conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)
            try:
                conn.execute("BEGIN IMMEDIATE")
                held["started"] = True
                acquired.set()
                time.sleep(seconds)
                conn.execute("COMMIT")
                held["ok"] = True
            finally:
                conn.close()
        except BaseException as exc:  # noqa: BLE001 — the test asserts on what went wrong
            held["error"] = f"{type(exc).__name__}: {exc}"
            acquired.set()

    t = threading.Thread(target=hold, name="sibling-lane", daemon=True)
    t.start()
    assert acquired.wait(10), "the sibling never acquired the write lock"
    try:
        yield held
    finally:
        t.join(seconds + 30)


def _allow_entry() -> dict:
    doc = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
    return {e["lane_id"]: e for e in doc["lanes"]}[LANE]


# --- the value, and why it is this one -------------------------------------------------------


def test_the_lane_connection_carries_the_widened_busy_timeout(tmp_path: Path) -> None:
    path = _ledger(tmp_path / "ledger.sqlite")
    shared = C.connect_rw(path)
    try:
        assert _busy_timeout(shared) == 5_000, "the shared default this lane no longer relies on"
    finally:
        shared.close()
    lane = CLI._connect_ledger_rw(path)
    try:
        assert CLI.LEDGER_BUSY_TIMEOUT_MS == 30_000
        assert _busy_timeout(lane) == CLI.LEDGER_BUSY_TIMEOUT_MS
    finally:
        lane.close()


def test_the_timeout_covers_the_incident_and_fits_the_lane_budget() -> None:
    budget_ms = int(_allow_entry()["timeout_s"]) * 1000
    assert budget_ms == 60_000, "the lane budget moved; re-derive LEDGER_BUSY_TIMEOUT_MS against it"
    assert CLI.LEDGER_BUSY_TIMEOUT_MS > 5_000, "wider than the shared connect_rw default, or this is a no-op"
    assert CLI.LEDGER_BUSY_TIMEOUT_MS > INCIDENT_REMAINING_MS, "the 05:45 slot's contention would still fail"
    assert CLI.LEDGER_BUSY_TIMEOUT_MS < budget_ms, "must give up and answer inside the lane's own deadline"


def test_the_apply_path_opens_the_widened_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wiring: the run path applies through the widened connection, and the run still completes."""
    ledger, state = _ledger(tmp_path / "ledger.sqlite"), tmp_path / "state"
    state.mkdir()
    seen: dict = {}
    real_apply = CLI.C.apply

    def spy(conn: sqlite3.Connection, *a, **kw):
        seen["busy_timeout"] = _busy_timeout(conn)
        return real_apply(conn, *a, **kw)

    monkeypatch.setattr(CLI.C, "apply", spy)
    rc = CLI.run(
        ledger=ledger,
        state_root=state,
        apply=True,
        max_intents=5,
        now=NOW,
        routes_path=ROUTES,
        receipt=state / "receipt.json",
    )
    assert rc == 0
    assert seen.get("busy_timeout") == CLI.LEDGER_BUSY_TIMEOUT_MS
    receipt = json.loads((state / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["lane_id"] == LANE
    assert receipt["status"] == "ok" and receipt["ok_at"], "a completed run advances ok_at"


# --- the incident itself, reproduced ---------------------------------------------------------


def test_a_write_lock_past_five_seconds_fails_the_shared_path_and_is_waited_out_by_the_lane(
    tmp_path: Path,
) -> None:
    """The incident's shape: shared ``connect_rw`` raises at ~5 s; the lane's connection waits and proceeds."""
    path = _ledger(tmp_path / "ledger.sqlite")
    with _sibling_write_lock(path, HOLD_S) as held:
        shared = C.connect_rw(path)
        try:
            t0 = time.monotonic()
            with pytest.raises(sqlite3.OperationalError) as caught:
                shared.execute("BEGIN IMMEDIATE")
            shared_wait = time.monotonic() - t0
        finally:
            shared.close()
        assert "database is locked" in str(caught.value), str(caught.value)
        assert 4.0 <= shared_wait < HOLD_S + 5.0, f"the shared path did not sit out its 5 s: {shared_wait:.2f}s"

        t0 = time.monotonic()
        lane = CLI._connect_ledger_rw(path)
        try:
            lane.execute("BEGIN IMMEDIATE")
            lane.execute("ROLLBACK")
        finally:
            lane.close()
        lane_wait = time.monotonic() - t0
        assert lane_wait < 5.0, f"the lane still gave up at the shared deadline: {lane_wait:.2f}s"
    assert held["ok"], held["error"]


# --- the classification half, as it stands on main --------------------------------------------


def _lane_policy():
    from scripts.lib import n8n_retry_policy as RP

    rows = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]
    name = {r["lane_id"]: r for r in rows}[LANE]["dispatch"]["retry_policy"]
    return RP, RP.load_policies().policies[name]


def test_the_incident_reason_is_terminal_on_this_base_until_lq684_folds() -> None:
    """The classification half of the queue item is LQ-684 (`73749a7db`), not yet folded.

    Until it lands, the lane's own ``transient-2`` policy reads ``database is locked`` as terminal —
    which is why the 05:45 slot dead-lettered on attempt 1 with max_attempts 3. Both halves matter:
    the wider timeout keeps a sibling's write from failing the run, and the classification keeps a
    failure that does happen from being called terminal. Skips (loudly) once LQ-684 is folded."""
    RP, policy = _lane_policy()
    assert policy.name == "transient-2"
    got = RP.verdict("RUN_FAILED", 1, "OperationalError: database is locked", policy)
    if got == RP.VERDICT_RETRYABLE:
        pytest.skip("LQ-684 (73749a7db) has landed: the lock is classified retryable at this base")
    assert got == RP.VERDICT_TERMINAL, got

