"""DRAIN-COST-CAP-LQ2162: a per-process daily cost cap refusal must DEFER the queued request
(back to pending, next window), not kill it as 'failed', and must not turn the lane red.
Synthetic queue only."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

CAP = "RuntimeError: COST_CAP_EXCEEDED: process cap"


def _drain():
    spec = importlib.util.spec_from_file_location("drain_lq2162", ROOT / "scripts" / "drain_llm_deferred.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeQ:
    def __init__(self, rows, attempts_max=3):
        self.rows = rows
        self.state = {}
        self.calls = []

    def reclaim_stale(self):
        return {"requeued": 0, "retired": 0}

    def expire_stale(self):
        return 0

    def queue_summary(self):
        return {"pending": 0}

    def claim_due(self, limit=25, **_):
        return self.rows

    def complete(self, rid, ok, error=None):
        self.state[rid] = ("done" if ok else "failed", error)

    def release(self, rid, error=None):
        self.state[rid] = ("pending" if int(next(r for r in self.rows if str(r["id"]) == rid)["attempts"]) < 3 else "failed", error)
        return self.state[rid][0]


def _run(monkeypatch, rows, outcomes):
    d = _drain()
    q = FakeQ(rows)
    import lib.deepseek_offpeak as off
    import lib.llm_deferral as real
    monkeypatch.setattr(off, "is_scheduled_deepseek_window", lambda *a, **k: True)
    for name in ("reclaim_stale", "expire_stale", "queue_summary", "claim_due", "complete"):
        monkeypatch.setattr(real, name, getattr(q, name))
    monkeypatch.setattr(real, "release", q.release, raising=False)
    called = []
    def run_one(row):
        called.append(row["id"])
        return outcomes[row["id"]]
    monkeypatch.setattr(d, "_run_one", run_one)
    receipts = []
    monkeypatch.setattr(d, "_receipt", lambda ok, rc, s: receipts.append((ok, rc, s)))
    monkeypatch.setattr(d, "_write_heartbeat", lambda p: None)
    rc = d.main(["--limit", "25"])
    return rc, q, called, receipts


def _row(i, attempts=1, pid="hermes_external_research"):
    return {"id": f"r{i}", "process_id": pid, "lane": "deepseek", "prompt": "p", "attempts": attempts}


def test_cost_cap_refusal_defers_not_fails(monkeypatch):
    rows = [_row(1), _row(2), _row(3)]
    rc, q, called, receipts = _run(monkeypatch, rows, {"r1": (False, CAP), "r2": (False, CAP), "r3": (False, CAP)})
    assert all(v[0] == "pending" for v in q.state.values()), q.state
    assert rc == 0 and receipts[-1][0] is True
    assert receipts[-1][2]["deferred_cost_cap"] == 3


def test_capped_process_is_not_called_again_in_the_batch(monkeypatch):
    rows = [_row(1), _row(2), _row(3), _row(4, pid="other_proc")]
    out = {"r1": (False, CAP), "r4": (True, None)}
    rc, q, called, _ = _run(monkeypatch, rows, out)
    assert called == ["r1", "r4"], "after the first cap refusal the process makes no more paid attempts"
    assert q.state["r2"][0] == "pending" and q.state["r3"][0] == "pending"
    assert q.state["r4"][0] == "done"


def test_exhausted_attempts_still_fail_loudly(monkeypatch):
    rows = [_row(1, attempts=3)]
    rc, q, _, receipts = _run(monkeypatch, rows, {"r1": (False, CAP)})
    assert q.state["r1"][0] == "failed"
    assert rc == 1 and receipts[-1][0] is False


def test_real_errors_still_fail(monkeypatch):
    rc, q, _, _ = _run(monkeypatch, [_row(1)], {"r1": (False, "ValueError: boom")})
    assert q.state["r1"][0] == "failed" and rc == 1
