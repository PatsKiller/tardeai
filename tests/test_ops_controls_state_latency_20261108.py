"""LQ-20261107-509: ``GET /api/v2/ops/controls/state`` must not wait on its two expensive sub-reads.

Measured on the host 2026-11-08, read-only: ``bin/guard show`` 6.3-7.3 s (it re-reads the grant ledger once per tier
per field — ``grant_expires``/``grant_left``/``grant_reason`` in ``.cursor/hooks/guard-lib.sh``, ~68 ``python3`` starts
for 22 tiers) and the n8n outcomes fan-out 2.1 s warm / 9.4 s cold over the ~200 MB coordination ledger. A whole state
load cost 8.3 s cold and 7.5 s on every load.

Both reads now run in a background thread and are served with their age (contract: docs/ops/OPS_CONTROLS_API.md §3,
"Two sections are served from a background cache"). These tests pin that with fakes that are deliberately slow: a
regression that puts either read back on the request path fails the first one by seconds, not by a stopwatch wobble.
"""

import time

from scripts.lib import ops_controls_api as API
from scripts.lib import ops_controls_n8n_outcomes as NO
from tests.test_ops_controls_20261022 import env, get  # noqa: F401 — the hermetic ops-controls env (fakes only)

SLOW_S = 1.0     # each stubbed sub-read
BUDGET_S = 0.5   # a state load must stay far below the 2 s target even with both stubs sleeping SLOW_S


def _slow_guard(rows, delay: float = SLOW_S):
    """A stand-in for ``bin/guard show`` that costs what the real one costs."""
    def call(_ctx):
        time.sleep(delay)
        return list(rows)
    return call


def test_a_slow_guard_and_ledger_never_hold_the_state_load(env, monkeypatch):
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(env.tmp))
    monkeypatch.setattr(API, "_guard_snapshot",
                        _slow_guard([{"tier": "db-write", "uses": "3", "minutes_left": 100, "grant_id8": "g" * 8,
                                      "grant_id": "g" * 8 + "0" * 10, "reason": "test"}]))
    monkeypatch.setattr(NO, "read_ledger", lambda *a, **k: time.sleep(SLOW_S) or {})

    t0 = time.perf_counter()
    st, state = get(env, "/state")
    elapsed = time.perf_counter() - t0
    assert st == 200
    # The two reads are each sleeping SLOW_S; the old code ran both on the request thread (2.08 s measured).
    assert elapsed < BUDGET_S, f"the state load waited {elapsed:.2f}s on its background reads"

    # Nothing has been read yet: the sections say so. They do not present an empty list as "no grants", nor a row as
    # "never ran" — being able to tell WARMING from a failure is the point.
    g, n = state["grants"], state["n8n"]
    assert g["state"] == "UNAVAILABLE" and g["cache"]["state"] == "WARMING" and g["active"] == []
    assert "being read" in g["reason"]
    assert n["outcomes_state"] == "UNAVAILABLE" and n["cache"]["state"] == "WARMING"
    assert "being read" in n["outcomes_reason"]
    assert all(r["outcome"]["health"] == "UNKNOWN" for r in n["rows"])

    # A page poll is the production equivalent of this drain; the next load carries both values, still fast.
    API._drain_slow_reads()
    t0 = time.perf_counter()
    st, state = get(env, "/state")
    elapsed = time.perf_counter() - t0
    assert st == 200 and elapsed < BUDGET_S, f"the warm load took {elapsed:.2f}s"
    g, n = state["grants"], state["n8n"]
    assert g["state"] == "OK" and g["cache"]["state"] == "OK" and g["active"][0]["tier"] == "db-write"
    assert g["cache"]["age_s"] is not None and g["cache"]["ttl_s"] == 60
    assert n["outcomes_state"] == "OK" and n["cache"]["state"] == "OK" and len(n["rows"]) == 2


def test_a_changed_guard_ledger_makes_the_snapshot_due_without_blocking(env, monkeypatch, tmp_path):
    """Every grant, revocation and consumed use rewrites the guard ledger. The snapshot is stamped with
    ``(mtime_ns, size)``, so a change makes it due at once — and still off the request thread."""
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(tmp_path))
    ledger = tmp_path / "grants.json"
    ledger.write_text('{"active": {}}')
    monkeypatch.setattr(API, "_guard_snapshot", _slow_guard([{"tier": "db-write"}], delay=0.6))

    st, state = get(env, "/state")           # WARMING: starts the first read
    assert state["grants"]["cache"]["state"] == "WARMING"
    API._drain_slow_reads()
    st, state = get(env, "/state")           # a poll lands: OK, stamped
    assert state["grants"]["cache"]["state"] == "OK" and state["grants"]["active"] == [{"tier": "db-write"}]

    ledger.write_text('{"active": {"db-write": {}}}')   # a grant landed (size, so mtime_ns too, changed)
    t0 = time.perf_counter()
    st, state = get(env, "/state")
    assert time.perf_counter() - t0 < BUDGET_S
    cache = state["grants"]["cache"]
    assert cache["state"] == "STALE" and cache["refreshing"] is True, cache
    assert state["grants"]["active"] == [{"tier": "db-write"}]   # the last good value, not an empty list


def test_a_failed_refresh_keeps_the_last_good_value_and_says_so(env, monkeypatch, tmp_path):
    monkeypatch.setenv("GUARD_APPROVALS_DIR", str(tmp_path))
    ledger = tmp_path / "grants.json"
    ledger.write_text('{"active": {}}')
    calls = {"n": 0}

    def flaky(_ctx):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"tier": "db-write"}]
        raise API.C.OpsError("GUARD_SHOW_FAILED", "rc 2", 503)

    monkeypatch.setattr(API, "_guard_snapshot", flaky)
    get(env, "/state")
    API._drain_slow_reads()
    st, state = get(env, "/state")
    assert state["grants"]["cache"]["state"] == "OK" and state["grants"]["active"] == [{"tier": "db-write"}]

    ledger.write_text('{"active": {"db-write": {"uses": 2}}}')   # the ledger moved: the snapshot is due
    get(env, "/state")                                          # serves the old value, start the refresh
    API._drain_slow_reads()                                     # the refresh failed
    st, state = get(env, "/state")
    cache = state["grants"]["cache"]
    assert "GUARD_SHOW_FAILED" in (cache["refresh_error"] or "")     # the failure is reported…
    assert state["grants"]["active"] == [{"tier": "db-write"}]       # …and the last good value is kept
