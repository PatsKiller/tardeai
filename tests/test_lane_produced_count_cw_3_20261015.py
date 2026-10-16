"""CW1 lanes (batch 3) write LaneRunReceipt@v2 produced_count and opt into the executor output verdict (2026-10-15).

Lanes: identity-sweep-stage0, journal-tilt-morning-hook, material-change-detector-stage1,
materialize-watchlist-strategy-cards, proposal-backtest-engine, sec-data-ingest, source-attribution-monitor,
update-agent-performance.

For each lane the REAL entry point runs inside a fake n8n attempt with its DB / provider work stubbed; the test reads
the immutable per-attempt receipt and applies the executor's output verdict with the committed contract and allowlist
entry: ``produced`` for a run that wrote, ``empty_allowed`` for an allowed empty run (where the rule allows one),
RUN_FAILED ``empty_output`` for a fatal skip. Three of these lanes keep an established receipt file name that differs
from the n8n lane id; the tests pin that the file stays where it was and the attempt copy lands under the lane id.
Hermetic (tests/support/lane_produced_count.py).
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

from tests.support import lane_produced_count as H

LANES = (
    "identity-sweep-stage0",
    "journal-tilt-morning-hook",
    "material-change-detector-stage1",
    "materialize-watchlist-strategy-cards",
    "proposal-backtest-engine",
    "sec-data-ingest",
    "source-attribution-monitor",
    "update-agent-performance",
)


@pytest.mark.parametrize("lane", LANES)
def test_lane_is_opted_in_with_code_that_writes_produced_count(lane):
    H.assert_opted_in(lane)


class _Cur:
    description = ()

    def __init__(self, rows=(), one=None):
        self._rows, self._one = list(rows), one

    def execute(self, *a, **k):
        return None

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._one

    def close(self):
        pass


class _Conn:
    def __init__(self, rows=(), one=None):
        self._rows, self._one = rows, one

    def cursor(self, *a, **k):
        return _Cur(self._rows, self._one)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def set_session(self, **k):
        pass


def _boom(*a, **k):
    raise RuntimeError("db down")


def _driver_stub(monkeypatch):
    """CI has no psycopg2; the lane modules import it at module level. Stub it only when it is absent (no test here
    opens a connection: every _db/_get_conn is replaced)."""
    try:
        import psycopg2  # noqa: F401
        import psycopg2.extras  # noqa: F401
    except ImportError:
        fake = types.ModuleType("psycopg2")
        extras = types.ModuleType("psycopg2.extras")
        extras.RealDictCursor = object
        fake.extras = extras
        fake.connect = _boom
        monkeypatch.setitem(sys.modules, "psycopg2", fake)
        monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)


def _last(tmp_path, name):
    return json.loads((tmp_path / "data" / "runtime" / f"{name}_last.json").read_text())


# ── identity-sweep-stage0 ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def bsi(monkeypatch):
    import backfill_subject_identity as m

    monkeypatch.setattr(m, "_db", lambda: _Conn())
    return m


@pytest.mark.parametrize("stamped,expect", [(3, "produced"), (0, "empty_allowed")])
def test_identity_sweep_stage0(bsi, monkeypatch, tmp_path, stamped, expect):
    run_id = H.attempt_env(monkeypatch, tmp_path, "identity-sweep-stage0")
    monkeypatch.setattr(bsi, "backfill", lambda cur, t, col, apply, limit: {
        "table": t, "symbols_seen": 2, "resolved": 1, "unresolved": 1, "not_applicable": 0, "rows_stamped": stamped})
    monkeypatch.setattr(bsi, "classify_remainder", lambda cur, t, col, apply: {
        "topics": 0, "topic_rows": 0, "unresolvable_rows": 1})
    assert bsi.main(["--all", "--apply"]) == 0
    tables = len(bsi.TARGETS)
    doc = H.attempt_receipt(tmp_path, "identity-sweep-stage0", run_id)
    assert doc["skipped_reasons"]["unresolvable_rows"] == tables
    H.check(tmp_path, "identity-sweep-stage0", run_id, produced=stamped * tables, expect=expect)


def test_identity_sweep_stage0_db_failure_is_a_fatal_skip(bsi, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "identity-sweep-stage0")
    monkeypatch.setattr(bsi, "_db", _boom)
    with pytest.raises(RuntimeError):
        bsi.main(["--all", "--apply"])
    H.check(tmp_path, "identity-sweep-stage0", run_id, produced=0, expect="empty_output")


# ── journal-tilt-morning-hook ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("outcome,produced,expect", [("queued", 1, "produced"), ("not_needed", 0, "empty_allowed"),
                                                     ("already_queued", 0, "empty_allowed")])
def test_journal_tilt_morning_hook(monkeypatch, tmp_path, outcome, produced, expect):
    import journal_tilt_morning_hook as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "journal-tilt-morning-hook")
    monkeypatch.setattr(m, "run", lambda dry_run=False: {"outcome": outcome, "review_item_id": "x"})
    assert m.main([]) == 0
    assert _last(tmp_path, "journal_tilt_morning_hook")["ok_at"]  # established receipt path kept
    H.check(tmp_path, "journal-tilt-morning-hook", run_id, produced=produced, expect=expect)


def test_journal_tilt_morning_hook_failure_is_a_fatal_skip(monkeypatch, tmp_path):
    import journal_tilt_morning_hook as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "journal-tilt-morning-hook")
    monkeypatch.setattr(m, "run", _boom)
    assert m.main([]) == 1
    H.check(tmp_path, "journal-tilt-morning-hook", run_id, produced=0, expect="empty_output")


# ── material-change-detector-stage1 ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "summary,expect",
    [
        ({"universe": 40, "changes_found": 3, "attempted": 3, "written": 2, "already_present": 1,
          "disposition": "PARTIAL_NEW"}, "produced"),
        ({"universe": 40, "changes_found": 3, "attempted": 3, "written": 0, "already_present": 3,
          "disposition": "ALL_ALREADY_PRESENT"}, "empty_allowed"),
        ({"universe": 0, "changes_found": 0, "attempted": 0, "written": 0, "already_present": 0,
          "disposition": "NOTHING_DETECTED"}, "empty_output"),
        ({"universe": 40, "changes_found": 2, "attempted": 2, "written": 0, "already_present": 0,
          "disposition": "WROTE_NOTHING_UNEXPLAINED"}, "empty_output"),
    ],
)
def test_material_change_detector_stage1(monkeypatch, tmp_path, summary, expect):
    import material_change_detector as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "material-change-detector-stage1")

    def fake_run(args):
        m.LAST_SUMMARY = dict(summary)
        return 0

    monkeypatch.setattr(m, "_run", fake_run)
    monkeypatch.setattr(m, "LAST_SUMMARY", {})
    assert m.main(["--apply"]) == 0
    H.check(tmp_path, "material-change-detector-stage1", run_id, produced=summary["written"], expect=expect)


# ── materialize-watchlist-strategy-cards ──────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("n,expect", [(4, "produced"), (0, "empty_output")])
def test_materialize_watchlist_strategy_cards(monkeypatch, tmp_path, n, expect):
    import materialize_watchlist_strategy_cards as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "materialize-watchlist-strategy-cards")
    row = {"symbol": "NOC", "strategy_type": "swing", "latest_price": 1, "support": 1, "resistance": 2,
           "stop_loss": 1, "target_price": 2, "risk_reward": 1, "needs_iteration": False}
    monkeypatch.setattr(m, "materialize", lambda syms, dry_run=False: [dict(row)] * n)
    monkeypatch.setattr(sys, "argv", ["materialize_watchlist_strategy_cards.py"])
    assert m.cli() == 0
    assert _last(tmp_path, "materialize_watchlist_strategy_cards")["summary"]["cards"] == n  # established path
    out = H.check(tmp_path, "materialize-watchlist-strategy-cards", run_id, produced=n, expect=expect)
    if not n:
        assert out["output_verdict"]["fatal"] == ["universe_empty_unexpected"]


def test_materialize_watchlist_strategy_cards_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    import materialize_watchlist_strategy_cards as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "materialize-watchlist-strategy-cards")
    monkeypatch.setattr(m, "materialize", _boom)
    monkeypatch.setattr(sys, "argv", ["materialize_watchlist_strategy_cards.py"])
    with pytest.raises(RuntimeError):
        m.cli()
    H.check(tmp_path, "materialize-watchlist-strategy-cards", run_id, produced=0, expect="empty_output")


# ── proposal-backtest-engine ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ids,expect", [((7, 8), "produced"), ((), "empty_allowed")])
def test_proposal_backtest_engine(monkeypatch, tmp_path, ids, expect):
    import proposal_backtest_engine as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "proposal-backtest-engine")
    monkeypatch.setattr(m, "get_conn", lambda: _Conn(rows=[(i,) for i in ids]))
    monkeypatch.setattr(m, "backtest_proposal", lambda conn, pid, persist=True: {
        "symbol": "NOC", "backtest_quality": "ok", "sample_size": 5, "persisted": True})
    monkeypatch.setattr(m, "_write_strategy_backtest_result", lambda conn, result: True)
    assert m.main(["--all-pending", "--apply"]) == 0
    H.check(tmp_path, "proposal-backtest-engine", run_id, produced=len(ids), expect=expect)


def test_proposal_backtest_engine_db_failure_is_a_fatal_skip(monkeypatch, tmp_path):
    import proposal_backtest_engine as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "proposal-backtest-engine")
    monkeypatch.setattr(m, "get_conn", _boom)
    with pytest.raises(RuntimeError):
        m.main(["--all-pending", "--apply"])
    H.check(tmp_path, "proposal-backtest-engine", run_id, produced=0, expect="empty_output")


# ── sec-data-ingest ───────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "res,expect",
    [
        ({"symbols_scanned": 10, "new_filings": 3, "fetch_failed": 0, "insert_errors": 0, "insert_attempts": 9},
         "produced"),
        ({"symbols_scanned": 10, "new_filings": 0, "fetch_failed": 0, "insert_errors": 0, "insert_attempts": 9},
         "empty_allowed"),
        ({"symbols_scanned": 0, "new_filings": 0, "fetch_failed": 0, "insert_errors": 0, "insert_attempts": 0},
         "empty_output"),
    ],
)
def test_sec_data_ingest(monkeypatch, tmp_path, res, expect):
    import sec_data_ingest as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "sec-data-ingest")
    monkeypatch.setattr(m, "ingest_form4", lambda symbols=None, limit=5: dict(res))
    assert m.main(["--all"]) == 0
    out = H.check(tmp_path, "sec-data-ingest", run_id, produced=res["new_filings"], expect=expect)
    if expect == "empty_output":
        assert out["output_verdict"]["fatal"] == ["universe_empty_unexpected"]


def test_sec_data_ingest_crash_is_a_fatal_skip(monkeypatch, tmp_path):
    import sec_data_ingest as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "sec-data-ingest")
    monkeypatch.setattr(m, "ingest_form4", _boom)
    with pytest.raises(RuntimeError):
        m.main(["--all"])
    H.check(tmp_path, "sec-data-ingest", run_id, produced=0, expect="empty_output")


# ── source-attribution-monitor ────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def sam(monkeypatch, tmp_path):
    """The module reads <checkout>/.env at import; import it with that read stubbed (no credential file is read)."""
    _driver_stub(monkeypatch)
    if "source_attribution_monitor" not in sys.modules:
        real = Path.read_text

        def read_text(self, *a, **k):
            return "" if self.name == ".env" else real(self, *a, **k)

        monkeypatch.setattr(Path, "read_text", read_text)
        importlib.import_module("source_attribution_monitor")
        monkeypatch.setattr(Path, "read_text", real)
    m = sys.modules["source_attribution_monitor"]
    monkeypatch.setattr(m, "HIST", tmp_path / "hist" / "source_attribution_history.json")
    monkeypatch.setattr(m, "MATURITY", tmp_path / "hist" / "source_maturity_latest.json")
    monkeypatch.setattr(m, "_db", lambda: _Conn(one=(10, 8, 5, 2, 1, 3)))
    return m


def test_source_attribution_monitor_appends_a_snapshot(sam, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "source-attribution-monitor")
    monkeypatch.setattr(sys, "argv", ["source_attribution_monitor.py"])
    sam.main()
    assert len(json.loads(sam.HIST.read_text())["snapshots"]) == 1
    H.check(tmp_path, "source-attribution-monitor", run_id, produced=1, expect="produced")


def test_source_attribution_monitor_dry_run_writes_nothing(sam, monkeypatch, tmp_path):
    H.attempt_env(monkeypatch, tmp_path, "source-attribution-monitor")
    monkeypatch.setattr(sys, "argv", ["source_attribution_monitor.py", "--dry-run"])
    sam.main()
    assert not sam.HIST.exists() and not (tmp_path / "data" / "runtime").exists()


def test_source_attribution_monitor_db_failure_writes_no_success(sam, monkeypatch, tmp_path):
    """A DB failure raises before the snapshot: no attempt receipt -> the executor's verdict is unverifiable."""
    run_id = H.attempt_env(monkeypatch, tmp_path, "source-attribution-monitor")
    monkeypatch.setattr(sam, "_db", _boom)
    monkeypatch.setattr(sys, "argv", ["source_attribution_monitor.py"])
    with pytest.raises(RuntimeError):
        sam.main()
    out = H.verdict(tmp_path, "source-attribution-monitor", run_id)
    assert out["state"] == "RUN_FAILED" and out["reason"] == "output_unverifiable"


# ── update-agent-performance ──────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("n,expect", [(2, "produced"), (0, "empty_allowed")])
def test_update_agent_performance(monkeypatch, tmp_path, n, expect):
    import update_agent_performance as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "update-agent-performance")
    rows = [{"agent": f"a{i}", "total": 3, "accuracy_pct": 50.0, "avg_confidence": 0.5, "overrides": 0}
            for i in range(n)]
    monkeypatch.setattr(m, "_get_conn", lambda: _Conn())
    monkeypatch.setattr(m, "score", lambda cur: {"outcomes": 9, "matched": 3, "rows": rows,
                                                 "period_start": "2026-10-08", "period_end": "2026-10-15"})
    monkeypatch.setattr(m, "_write_rows", lambda cur, scored: [{"id": i, **r} for i, r in enumerate(scored["rows"])])
    assert m.run() == 0
    assert _last(tmp_path, "update_agent_performance")["summary"]["agents_scored"] == n  # established path
    H.check(tmp_path, "update-agent-performance", run_id, produced=n, expect=expect)


def test_update_agent_performance_db_failure_is_a_fatal_skip(monkeypatch, tmp_path):
    import update_agent_performance as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "update-agent-performance")
    monkeypatch.setattr(m, "_get_conn", lambda: _Conn())
    monkeypatch.setattr(m, "score", _boom)
    with pytest.raises(RuntimeError):
        m.run()
    H.check(tmp_path, "update-agent-performance", run_id, produced=0, expect="empty_output")
