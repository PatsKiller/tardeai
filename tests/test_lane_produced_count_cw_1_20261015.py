"""CW1 lanes write LaneRunReceipt@v2 produced_count and opt into the executor output verdict (batch 1 of the
cutover-wave produced_count work, 2026-10-15).

Lanes: agent-outcome-linker, catalyst-graph, catalyst-symbol-impact, classify-instruments,
document-mentions-backfill, etf-analyst-enrich, etf-performance-enrich, feedback-loop-processor.

For each lane the REAL ``main()`` runs inside a fake n8n attempt with its DB / provider work stubbed; the test reads
the immutable per-attempt receipt and applies the executor's output verdict with the committed contract and
allowlist entry: ``produced`` for a run that wrote rows, ``empty_allowed`` for an allowed empty run (where the rule
allows one), RUN_FAILED ``empty_output`` for a fatal skip. Hermetic (tests/support/lane_produced_count.py).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from tests.support import lane_produced_count as H

LANES = (
    "agent-outcome-linker",
    "catalyst-graph",
    "catalyst-symbol-impact",
    "classify-instruments",
    "document-mentions-backfill",
    "etf-analyst-enrich",
    "etf-performance-enrich",
    "feedback-loop-processor",
)


@pytest.mark.parametrize("lane", LANES)
def test_lane_is_opted_in_with_code_that_writes_produced_count(lane):
    H.assert_opted_in(lane)


class _Cur:
    description = ()

    def execute(self, *a, **k):
        return None

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class _Conn:
    def cursor(self, *a, **k):
        return _Cur()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _boom(*a, **k):
    raise RuntimeError("db down")


# ── agent-outcome-linker ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def aol(monkeypatch):
    import agent_outcome_linker as m

    monkeypatch.setattr(m, "_get_conn", lambda: _Conn())
    monkeypatch.setattr(sys, "argv", ["agent_outcome_linker.py", "--apply"])
    return m


@pytest.mark.parametrize("n,expect", [(3, "produced"), (0, "empty_allowed")])
def test_agent_outcome_linker(aol, monkeypatch, tmp_path, n, expect):
    run_id = H.attempt_env(monkeypatch, tmp_path, "agent-outcome-linker")
    links = [{"outcome_type": "trade"}] * n
    monkeypatch.setattr(aol, "link_to_proposals", lambda c: links)
    monkeypatch.setattr(aol, "link_to_trades", lambda c: [])
    monkeypatch.setattr(aol, "save_links", lambda c, ls, dry_run=True: len(ls))
    assert aol.main() == 0
    out = H.check(tmp_path, "agent-outcome-linker", run_id, produced=n, expect=expect)
    if not n:
        assert out["output_verdict"]["empty_reason"] == "no_new_input"


def test_agent_outcome_linker_db_failure_is_a_fatal_skip(aol, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "agent-outcome-linker")
    monkeypatch.setattr(aol, "link_to_proposals", _boom)
    with pytest.raises(RuntimeError):
        aol.main()
    H.check(tmp_path, "agent-outcome-linker", run_id, produced=0, expect="empty_output")


# ── catalyst-graph ────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("catalysts,nodes,expect", [(5, 3, "produced"), (0, 0, "empty_output"), (4, 0, "empty_output")])
def test_catalyst_graph(monkeypatch, tmp_path, catalysts, nodes, expect):
    import build_catalyst_graph as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "catalyst-graph")
    monkeypatch.setattr(m, "_state_root", lambda: tmp_path)
    monkeypatch.setattr(m, "load_registry", lambda: {})
    monkeypatch.setattr(m, "fetch_catalysts", lambda limit: [{"id": i} for i in range(catalysts)])
    graph = {"node_count": nodes, "trace_count": nodes, "bound_by_type": {}, "skipped": {}, "nodes": [], "traces": []}
    monkeypatch.setattr(m, "build_graph", lambda cats, reg: dict(graph))
    monkeypatch.setattr(sys, "argv", ["build_catalyst_graph.py", "--apply"])
    assert m.main() == 0
    assert (tmp_path / "data/cio/catalyst_graph_latest.json").is_file()  # the projection is still written
    out = H.check(tmp_path, "catalyst-graph", run_id, produced=1 if nodes else 0, expect=expect)
    if expect == "empty_output" and not catalysts:
        assert out["output_verdict"]["fatal"] == ["no_input_unexpected"]


def test_catalyst_graph_dry_run_writes_no_receipt(monkeypatch, tmp_path):
    import build_catalyst_graph as m

    H.attempt_env(monkeypatch, tmp_path, "catalyst-graph")
    monkeypatch.setattr(m, "load_registry", lambda: {})
    monkeypatch.setattr(m, "fetch_catalysts", lambda limit: [])
    monkeypatch.setattr(m, "build_graph", lambda c, r: {"node_count": 0, "trace_count": 0, "bound_by_type": {},
                                                        "skipped": {}})
    monkeypatch.setattr(m, "write_lane_receipt", _boom)
    monkeypatch.setattr(sys, "argv", ["build_catalyst_graph.py"])
    assert m.main() == 0
    assert not (tmp_path / "data/runtime/lane_attempts").exists()


# ── catalyst-symbol-impact ────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def csi(monkeypatch, tmp_path):
    import catalyst_symbol_impact_writer as m

    monkeypatch.setattr(m, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(m, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(m, "_conn", lambda: _Conn())
    monkeypatch.setattr(sys, "argv", ["catalyst_symbol_impact_writer.py", "--apply"])
    return m


def _csi_row(i):
    return {"catalyst_event_id": i, "symbol": "NOC", "strategy_type": None, "price_at_event": 1.0,
            "expected_direction": "UP", "expected_magnitude": None, "portfolio_impact_pct": 0.0, "_type": "x",
            "_ts": "2026-10-15"}


@pytest.mark.parametrize("n,expect", [(2, "produced"), (0, "empty_allowed")])
def test_catalyst_symbol_impact(csi, monkeypatch, tmp_path, n, expect):
    run_id = H.attempt_env(monkeypatch, tmp_path, "catalyst-symbol-impact")
    monkeypatch.setattr(csi, "plan_rows", lambda cur, days, w: [_csi_row(i) for i in range(n)])
    assert csi.main() == 0
    assert (tmp_path / "data/runtime/catalyst_symbol_impact_last_run.json").is_file()  # legacy receipt unchanged
    H.check(tmp_path, "catalyst-symbol-impact", run_id, produced=n, expect=expect)


def test_catalyst_symbol_impact_db_failure_is_a_fatal_skip(csi, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "catalyst-symbol-impact")
    monkeypatch.setattr(csi, "_conn", _boom)
    with pytest.raises(RuntimeError):
        csi.main()
    H.check(tmp_path, "catalyst-symbol-impact", run_id, produced=0, expect="empty_output")


# ── classify-instruments ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("written,expect", [(1, "produced"), (0, "empty_output")])
def test_classify_instruments(monkeypatch, tmp_path, written, expect):
    import classify_instruments as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "classify-instruments")
    monkeypatch.setattr(m, "_get_conn", lambda: _Conn())
    monkeypatch.setattr(m, "OUT", tmp_path / "instrument_types_latest.json")
    monkeypatch.setattr(m, "ROOT", tmp_path)  # holdings.json absent -> the step is skipped as today
    monkeypatch.setattr(
        m, "upsert_profile", lambda *a, **k: SimpleNamespace(rows_written=written, rows_rejected=1 - written)
    )
    assert m.main(["--no-fetch"]) == 0
    universe = len(__import__("json").loads(m.UNIVERSE.read_text())["instruments"])
    doc = H.attempt_receipt(tmp_path, "classify-instruments", run_id)
    assert doc["attempted_count"] == universe and doc["produced_count"] == written * universe
    H.check(tmp_path, "classify-instruments", run_id, produced=written * universe, expect=expect)


def test_classify_instruments_db_failure_is_a_fatal_skip(monkeypatch, tmp_path):
    import classify_instruments as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "classify-instruments")
    monkeypatch.setattr(m, "_get_conn", _boom)
    with pytest.raises(RuntimeError):
        m.main([])
    H.check(tmp_path, "classify-instruments", run_id, produced=0, expect="empty_output")


# ── document-mentions-backfill ────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def bdm(monkeypatch, tmp_path):
    import backfill_document_mentions as m

    monkeypatch.setattr(m, "watermark_path", lambda: tmp_path / "state" / "document_mentions_watermark.json")
    return m


def _bdm_stat(table, written, offered):
    return {"table": table, "documents": offered, "subject": offered, "mentioned": 0, "undecided_docs": 1,
            "no_mention": 2, "written": written, "multi": 0, "scanned": offered + 3, "max_id": 10,
            "budget_hit": False, "offered": offered}


@pytest.mark.parametrize("written,expect", [(2, "produced"), (0, "empty_allowed")])
def test_document_mentions_backfill(bdm, monkeypatch, tmp_path, written, expect):
    run_id = H.attempt_env(monkeypatch, tmp_path, "document-mentions-backfill")
    monkeypatch.setattr(bdm, "run", lambda t, limit, apply, **k: _bdm_stat(t, written, 2))
    assert bdm.main(["--all", "--limit", "4000", "--apply"]) == 0
    tables = len(__import__("lib.document_mentions", fromlist=["SOURCES"]).SOURCES)
    doc = H.attempt_receipt(tmp_path, "document-mentions-backfill", run_id)
    assert doc["attempted_count"] == 2 * tables and doc["skipped_reasons"]["no_mention_docs"] == 2 * tables
    H.check(tmp_path, "document-mentions-backfill", run_id, produced=written * tables, expect=expect)


def test_document_mentions_backfill_failure_is_a_fatal_skip(bdm, monkeypatch, tmp_path):
    run_id = H.attempt_env(monkeypatch, tmp_path, "document-mentions-backfill")
    monkeypatch.setattr(bdm, "run", _boom)
    with pytest.raises(RuntimeError):
        bdm.main(["--all", "--apply"])
    H.check(tmp_path, "document-mentions-backfill", run_id, produced=0, expect="empty_output")


def test_document_mentions_run_counts_offered_rows(monkeypatch):
    """run() counts the decided mention rows it offers persist(): attempted >= written by construction."""
    import backfill_document_mentions as m

    class Cur(_Cur):
        def fetchall(self):
            return [(1, "NOC", "x"), (2, "NOC", "y")]

    class Conn(_Conn):
        def cursor(self, *a, **k):
            return Cur()

    from lib import document_mentions as DM
    from lib import research_identity as RI

    monkeypatch.setattr(m, "_conn", lambda: Conn())
    monkeypatch.setattr(RI, "load_registry", lambda: {})
    found = [{"role": "subject", "role_source": "own"}, {"role": "mentioned", "role_source": "x"}]
    monkeypatch.setattr(DM, "extract", lambda text, **k: list(found))
    monkeypatch.setattr(DM, "persist", lambda conn, **k: 1)
    table = sorted(DM.SOURCES)[0]
    monkeypatch.setitem(DM.SOURCES, table, {**DM.SOURCES[table], "subject_is_own_symbol": False})
    stat = m.run(table, 10, True, mark=5)
    assert stat["offered"] == 4 and stat["written"] == 2


# ── etf-analyst-enrich / etf-performance-enrich ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "res,produced,expect",
    [
        ({"ok": True, "etfs_funds": 9, "etfs_with_holdings": 4, "etfs_with_direct_target": 1,
          "constituents_needed": 0, "constituents_fetched": 0, "with_analyst_view": 3}, 3, "produced"),
        ({"ok": True, "etfs_funds": 0, "etfs_with_holdings": 0, "etfs_with_direct_target": 0,
          "constituents_needed": 0, "constituents_fetched": 0, "with_analyst_view": 0}, 0, "empty_output"),
    ],
)
def test_etf_analyst_enrich(monkeypatch, tmp_path, res, produced, expect):
    import etf_analyst_enrich as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "etf-analyst-enrich")
    monkeypatch.setattr(m, "enrich", lambda: dict(res))
    assert m.main([]) == 0
    out = H.check(tmp_path, "etf-analyst-enrich", run_id, produced=produced, expect=expect)
    if expect == "empty_output":
        assert out["output_verdict"]["fatal"] == ["universe_empty_unexpected"]


def test_etf_analyst_enrich_failure_is_a_fatal_skip(monkeypatch, tmp_path):
    import etf_analyst_enrich as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "etf-analyst-enrich")
    monkeypatch.setattr(m, "enrich", _boom)
    with pytest.raises(RuntimeError):
        m.main([])
    H.check(tmp_path, "etf-analyst-enrich", run_id, produced=0, expect="empty_output")


@pytest.mark.parametrize(
    "res,expect",
    [
        ({"symbols": 5, "attempted": 5, "updated": 4, "rejected": 0, "errors": 1, "empty": 0}, "produced"),
        ({"symbols": 0, "attempted": 0, "updated": 0, "rejected": 0, "errors": 0, "empty": 0}, "empty_output"),
    ],
)
def test_etf_performance_enrich(monkeypatch, tmp_path, res, expect):
    import etf_performance_enrich as m

    monkeypatch.setenv("DB_PASSWORD", "not-a-secret")  # _load_env never reads a .env
    run_id = H.attempt_env(monkeypatch, tmp_path, "etf-performance-enrich")
    monkeypatch.setattr(m, "enrich", lambda: dict(res))
    assert m.main([]) == 0
    out = H.check(tmp_path, "etf-performance-enrich", run_id, produced=res["updated"], expect=expect)
    if expect == "empty_output":
        assert out["output_verdict"]["fatal"] == ["universe_empty_unexpected"]


# ── feedback-loop-processor ───────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("counts,expect", [((2, 0, 1, 0, 0, 0), "produced"), ((0,) * 6, "empty_allowed")])
def test_feedback_loop_processor(monkeypatch, tmp_path, counts, expect):
    import feedback_loop_processor as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "feedback-loop-processor")
    monkeypatch.setattr(m, "_get_conn", lambda: _Conn())
    steps = tuple((k, label, (lambda n: lambda conn, dry_run=False: n)(n)) for (k, label, _), n in zip(m.STEPS, counts))
    monkeypatch.setattr(m, "STEPS", steps)
    assert m.main([]) == 0
    H.check(tmp_path, "feedback-loop-processor", run_id, produced=sum(counts), expect=expect)


def test_feedback_loop_processor_failure_is_a_fatal_skip(monkeypatch, tmp_path):
    import feedback_loop_processor as m

    run_id = H.attempt_env(monkeypatch, tmp_path, "feedback-loop-processor")
    monkeypatch.setattr(m, "_get_conn", _boom)
    with pytest.raises(RuntimeError):
        m.main([])
    H.check(tmp_path, "feedback-loop-processor", run_id, produced=0, expect="empty_output")
