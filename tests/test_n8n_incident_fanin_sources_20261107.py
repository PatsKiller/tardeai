"""Fan-in sources `runs` and `dlq_recovery` (LQ-20261107-61): the 2 s wall-clock cut-off interrupted the
recovery scan and a PARTIAL projection dropped the runs source, so 256 incidents never recovered.
Synthetic ledgers only."""

from __future__ import annotations

import inspect
import sqlite3
from datetime import datetime, timezone

from scripts import n8n_incident_fanin as fanin
from scripts.lib import n8n_coordination_projection as proj
from scripts.lib import n8n_dlq_disposition as DD
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

NOW = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)


def _ledger(tmp_path, lanes=("lane-a", "lane-b")):
    path = tmp_path / "ledger.sqlite"
    ledger = CoordinationLedger(path)
    store = LedgerRunStore(ledger)
    for lane in lanes:
        rid = f"ok-{lane}"
        store.request(run_id=rid, lane_id=lane, mode="live", requested_by="f", caller_id="f", now=NOW.timestamp() - 600)
        store.claim_next(now=NOW.timestamp() - 590)
        receipt = {
            "schema": "RunReceipt@v3", "run_id": rid, "lane_id": lane, "mode": "live", "state": "RUN_DONE",
            "exit_code": 0, "finished_at": datetime.fromtimestamp(NOW.timestamp() - 500, timezone.utc).isoformat(),
            "output_verdict": {"verdict": "produced", "contract_id": lane},
        }
        store.finish(rid, state="RUN_DONE", receipt=receipt, now=NOW.timestamp() - 500)
    ledger.close()
    return path


def test_successful_runs_reads_only_the_requested_lanes(tmp_path):
    path = _ledger(tmp_path)
    got = DD.successful_runs(path, now=NOW, lanes={"lane-a"})
    assert {k[0] for k in got} == {"lane-a"}
    assert {k[0] for k in DD.successful_runs(path, now=NOW)} == {"lane-a", "lane-b"}


def test_an_interrupted_lane_is_a_gap_and_does_not_fail_the_others(tmp_path, monkeypatch):
    path = _ledger(tmp_path)
    real = sqlite3.connect

    class Conn:
        def __init__(self, c):
            object.__setattr__(self, "_c", c)

        def __setattr__(self, n, v):
            setattr(self._c, n, v)

        def execute(self, sql, *a):
            if a and a[0] and a[0][0] == "lane-a":
                raise sqlite3.OperationalError("interrupted")
            return self._c.execute(sql, *a)

        def __getattr__(self, n):
            return getattr(self._c, n)

    class Shim:
        OperationalError = sqlite3.OperationalError
        Row = sqlite3.Row

        @staticmethod
        def connect(*a, **k):
            return Conn(real(*a, **k))

    monkeypatch.setattr(DD, "sqlite3", Shim)
    gaps: list[str] = []
    got = DD.successful_runs(path, now=NOW, lanes={"lane-a", "lane-b"}, gaps=gaps)
    assert gaps == ["lane-a"] and {k[0] for k in got} == {"lane-b"}


def test_project_runs_takes_a_budget_and_keeps_the_ui_default():
    p = inspect.signature(proj.project_runs).parameters["budget_s"]
    assert p.default == 2.0 and fanin.RUNS_READ_BUDGET_S > 2.0


def test_a_partial_projection_still_feeds_the_runs_source(tmp_path, monkeypatch):
    from scripts.lib import lane_registry as LR

    reg = {"schema": "LaneRegistry@v1", "lanes": [{"lane_id": "n8n-x", "state": "ACTIVE", "expected_cadence_hours": 1.0,
                                                  "scheduler": {"kind": "n8n", "expression": "wf"}}]}
    monkeypatch.setattr(LR, "load_registry", lambda path=None: reg)
    monkeypatch.setenv("TRADEAI_FANIN_LANE_REGISTRY", "0")
    monkeypatch.delenv("TRADEAI_FANIN_RUNS", raising=False)
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return {"status": "PARTIAL", "coverage": {"invalid_detail_rows": 3}, "items": [
            {"lane_id": "n8n-x", "state": "RUN_FAILED", "run_id": "r1", "mode": "live", "exit_code": 2,
             "finished_at": "2026-10-24T21:00:00+00:00"}]}

    monkeypatch.setattr(proj, "project_runs", lambda **kw: fake(**kw))
    found = fanin._runs_findings(tmp_path, NOW)
    assert [f["item"] for f in found] == ["n8n-x:RUN_FAILED"]
    assert fanin.NOTES["runs_source"].startswith("ok:") and "unparsable_receipts=3" in fanin.NOTES["runs_source"]
    assert seen["budget_s"] == fanin.RUNS_READ_BUDGET_S


def test_an_unavailable_projection_still_marks_the_source_unavailable(tmp_path, monkeypatch):
    from scripts.lib import lane_registry as LR

    reg = {"schema": "LaneRegistry@v1", "lanes": [{"lane_id": "n8n-x", "state": "ACTIVE", "expected_cadence_hours": 1.0,
                                                  "scheduler": {"kind": "n8n", "expression": "wf"}}]}
    monkeypatch.setattr(LR, "load_registry", lambda path=None: reg)
    monkeypatch.delenv("TRADEAI_FANIN_RUNS", raising=False)
    monkeypatch.setattr(proj, "project_runs", lambda **kw: {"status": "UNAVAILABLE", "note": "ledger missing"})
    assert fanin._runs_findings(tmp_path, NOW) == []
    assert fanin.NOTES["runs_source"].startswith("unavailable:RuntimeError")
