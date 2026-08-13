"""Phase 5 — lock/contention remediation under full promote load (dry tests).

Deterministic, in-memory proofs that the drain path no longer:
  * double-claims a staging row across concurrent workers (FOR UPDATE SKIP LOCKED),
  * silently drops a lead when a promote errors under lock contention (terminal-only
    `drained` marking + retry),
  * lets one contention abort poison the whole run (savepoint isolation), and
  * commits ~5x per promote (single caller-owned transaction).

No live database, broker, or LLM.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from lib import two_way_curation as tc  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# fake cursor that records every statement + returns controlled rows
# ─────────────────────────────────────────────────────────────────────────────
class RecordingCursor:
    def __init__(self, staged_rows):
        self._staged = list(staged_rows)
        self._claimed = False
        self.sql = []  # list of (sql_upper_nospace, raw_sql, params)
        self._next_id = 900
        self.updates = []  # UPDATE statements issued
        self.savepoints = []
        self.rollbacks = []
        self.releases = []

    def execute(self, sql, params=None):
        raw = sql
        norm = raw.upper().replace(" ", "")
        self.sql.append((norm, raw, params))
        if norm.startswith("SAVEPOINT"):
            self.savepoints.append(params if params is not None else raw.split()[-1])
        elif norm.startswith("ROLLBACKTOSAVEPOINT"):
            self.rollbacks.append(raw)
        elif norm.startswith("RELEASESAVEPOINT"):
            self.releases.append(raw)
        elif norm.startswith("UPDATE") and "DRAINED=TRUE" in norm:
            self.updates.append(params)

    def fetchall(self):
        # only the FIRST claim SELECT returns rows (one source has staged work);
        # subsequent sources see an empty queue — realistic, and keeps per-source
        # counters exact.
        if "DRAINED=FALSE" in self.sql[-1][0] and not self._claimed:
            self._claimed = True
            return list(self._staged)
        return []

    def fetchone(self):
        norm = self.sql[-1][0]
        if "RETURNINGID" in norm:
            self._next_id += 1
            return {"id": self._next_id}
        return None


def _staged_row(sym="NVDA", source_detail=None, did=None):
    sd = source_detail or {
        "directive_kind": "ticker",
        "directive_label": f"Advisory ADD — {sym}",
        "spec": {"symbol": sym},
        "thesis": f"Advisory ADD: {sym}",
        "rationale": "test",
    }
    return {"id": 1, "directive_id": did, "symbol": sym, "thesis": "t",
            "source_detail": sd}


def _run(sym, status="PROMOTED", resolve=None):
    staged = [_staged_row(sym)]
    cur = RecordingCursor(staged)
    report = {}

    def evaluate(s, did, reason, source, auto):
        return {"status": status, "symbol": s}

    tc.drain_curation_sources(
        cur, dry=False, report=report, evaluate=evaluate,
        resolve_fn=resolve or (lambda d: [d["spec"]["symbol"]]),
    )
    return cur, report


# ─────────────────────────────────────────────────────────────────────────────
# claim isolation — FOR UPDATE SKIP LOCKED
# ─────────────────────────────────────────────────────────────────────────────

def test_claim_select_uses_for_update_skip_locked():
    cur, _ = _run("NVDA")
    select = [s for s in cur.sql if "DRAINED=FALSE" in s[0] and "SELECT" in s[0]]
    assert select, "drain must issue a claim SELECT"
    assert "FORUPDATESKIPLOCKED" in select[0][0]


def test_terminal_status_marks_drained():
    cur, report = _run("NVDA", status="PROMOTED")
    assert report["curation_drained"] == 1
    assert report["curation_retry"] == 0
    # the staged row's id=1 is marked drained
    assert any(p == (1,) or (isinstance(p, tuple) and p and p[0] == 1) for p in cur.updates)


def test_error_status_leaves_undrained_and_retries():
    cur, report = _run("NVDA", status="ERROR")
    assert report["curation_drained"] == 0
    assert report["curation_retry"] == 1
    assert report["curation_errors"] == 1
    # no UPDATE drained=true was issued for this row
    assert cur.updates == []


def test_error_status_rolls_back_savepoint():
    cur, _ = _run("NVDA", status="ERROR")
    assert cur.savepoints, "promote must be savepoint-isolated"
    assert cur.rollbacks, "a failed promote must ROLLBACK TO SAVEPOINT to clear aborted txn"
    assert cur.releases


def test_success_status_releases_savepoint_without_rollback():
    cur, _ = _run("NVDA", status="PROMOTED")
    assert cur.savepoints and cur.releases
    assert cur.rollbacks == []


def test_evaluate_exception_rolls_back_and_is_not_dropped():
    staged = [_staged_row("NVDA")]
    cur = RecordingCursor(staged)
    report = {}

    def evaluate(s, did, reason, source, auto):
        raise RuntimeError("lock timeout")

    tc.drain_curation_sources(
        cur, dry=False, report=report, evaluate=evaluate,
        resolve_fn=lambda d: [d["spec"]["symbol"]],
    )
    assert report["curation_retry"] == 1
    assert report["curation_errors"] == 1
    assert cur.rollbacks


def test_unresolved_directive_leaves_undrained():
    staged = [_staged_row("NVDA")]
    cur = RecordingCursor(staged)
    report = {}

    def evaluate(s, did, reason, source, auto):
        raise AssertionError("must not evaluate without a directive id")

    tc.drain_curation_sources(
        cur, dry=False, report=report, evaluate=evaluate,
        resolve_fn=lambda d: [d["spec"]["symbol"]],
    )
    # directive mint returns None (fetchone None) → row not terminal → retry
    assert report["curation_retry"] == 1
    assert report["curation_drained"] == 0
    assert cur.updates == []


# ─────────────────────────────────────────────────────────────────────────────
# promote_directive_lead — single caller-owned transaction
# ─────────────────────────────────────────────────────────────────────────────

class FakeConn:
    def __init__(self):
        self.commits = 0
        self._cur = self._Cursor(self)

    class _Cursor:
        def __init__(self, conn):
            self.conn = conn
            self.rowcount = 1

        def execute(self, sql, params=None):
            return None

        def fetchone(self):
            return None

    def cursor(self):
        return self._cur

    def commit(self):
        self.commits += 1


def _patch_promotion(monkeypatch):
    import directive_promotion as dp
    monkeypatch.setattr(dp, "get_source_tier", lambda *a, **k: "trusted")
    monkeypatch.setattr(dp, "get_divergence_status", lambda *a, **k: "aligned")
    monkeypatch.setattr(dp, "enrich_symbol_on_demand", lambda *a, **k: {"price": 100.0, "rsi": 55})
    monkeypatch.setattr(dp, "classify_tradeable", lambda *a, **k: [])
    return dp


def test_promote_defers_commit_on_shared_conn(monkeypatch):
    dp = _patch_promotion(monkeypatch)
    conn = FakeConn()
    res = dp.promote_directive_lead("AAPL", 1, "x", "advisory", conn=conn, auto=True)
    assert res["status"] == "MONITORED_NO_QUALIFY"
    # caller owns the transaction → promote must NOT commit internally
    assert conn.commits == 0


def test_promote_explicit_commit_true_commits(monkeypatch):
    dp = _patch_promotion(monkeypatch)
    conn = FakeConn()
    dp.promote_directive_lead("AAPL", 1, "x", "advisory", conn=conn, auto=True, commit=True)
    assert conn.commits == 1


def test_promote_staged_path_defers_commit(monkeypatch):
    import directive_promotion as dp
    monkeypatch.setattr(dp, "get_source_tier", lambda *a, **k: "candidate")
    monkeypatch.setattr(dp, "get_divergence_status", lambda *a, **k: "divergent")
    conn = FakeConn()
    res = dp.promote_directive_lead("AAPL", 1, "x", "advisory", conn=conn, auto=False)
    assert res["status"] == "STAGED_FOR_REVIEW"
    assert conn.commits == 0


# ─────────────────────────────────────────────────────────────────────────────
# benchmark harness — the fixed policy is strictly better on every metric
# ─────────────────────────────────────────────────────────────────────────────

def test_benchmark_fixed_policy_has_no_double_claims_or_drops():
    sys.path.insert(0, str(ROOT / "scripts" / "ops"))
    import benchmark_drain_contention as bc
    fixed = bc.simulate_contention("fixed")
    legacy = bc.simulate_contention("legacy")
    assert fixed["double_claims"] == 0
    assert fixed["dropped_leads"] == 0
    assert fixed["commits_per_item"] == 1.0
    # legacy is strictly worse on contention + data-loss axes
    assert legacy["double_claims"] > 0
    assert legacy["dropped_leads"] > 0
    assert legacy["commits_per_item"] > fixed["commits_per_item"]
