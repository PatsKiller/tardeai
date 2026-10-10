"""Refactor wave 2, bucket V2 (cron -> n8n, 2026-10-10): the Hermes source-maturity tick (cron L431).

The cron line is ``bash -c "attribution && maturity && ladder"``. scripts/source_maturity_chain.py is the
single-argv form of it. Each step's --dry-run was a flag tested AFTER the write was already in the same
loop; now each step has a read-only compute and a separate writer the dry path cannot reach:
- source_outcome_attribution: compute() / write_rows();
- source_maturity: compute() / write_out() (data/runtime via the persistent-state resolver);
- source_vetting_ladder: plan() / apply_plan() (INSERT/UPDATE research_sources, actions file, policy
  cache invalidation and hermes_source_auto_approval).
The chain stops at the first failed step like `&&`, and its dry run feeds the ladder the maturity
document it just computed in memory. Hermetic: fake DB connections, tmp files, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Required CI has no psycopg2 (these tests use fake connections only). Install a minimal stand-in ONLY when the real
# driver is absent, so the dry-run safety tests still run in CI instead of being skipped by importorskip.
try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    import types as _types

    _pg = _types.ModuleType("psycopg2")
    _pg_extras = _types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: tests must use fake connections")

    _pg.connect = _no_connect
    _pg.Error = Exception
    _pg.OperationalError = Exception
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import source_maturity as sm  # noqa: E402
import source_maturity_chain as chain  # noqa: E402
import source_outcome_attribution as soa  # noqa: E402
import source_vetting_ladder as svl  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402


def _forbid(monkeypatch, obj, name):
    def boom(*a, **k):
        raise AssertionError(f"dry run reached {name}")

    monkeypatch.setattr(obj, name, boom)


class FakeConn:
    def __init__(self, answers=()):
        self.answers = list(answers)
        self.log: list = []

    def cursor(self, *a, **k):
        conn = self

        class C:
            def execute(self, sql, params=None):
                flat = " ".join(sql.split())
                conn.log.append(("execute", flat, params))
                self._rows = next((rows for sub, rows in conn.answers if sub in flat), [])

            def fetchall(self):
                return list(self._rows)

            def fetchone(self):
                return self._rows[0] if self._rows else None

        return C()

    def commit(self):
        self.log.append(("commit",))

    def rollback(self):
        self.log.append(("rollback",))

    def set_session(self, **kw):
        self.log.append(("set_session", kw))

    def close(self):
        self.log.append(("close",))

    def writes(self):
        return [e for e in self.log if e[0] == "execute" and e[1].split()[0].upper() in ("INSERT", "UPDATE", "DELETE")]


NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def _soa_conn():
    return FakeConn(
        [
            (
                "FROM news_articles WHERE",
                [("finviz", "AAA", NOW, 30), ("finviz", "BBB", NOW, 10), ("rss", "AAA", NOW, 5)],
            ),
            ("FROM trade_ai_scans", [("AAA",)]),
            ("FROM paper_trades pt", [("finviz", 1, "closed", 50.0, 2.0), ("finviz", 2, "closed", -20.0, -1.0)]),
        ]
    )


def _sm_conn():
    return FakeConn(
        [
            (
                "FROM source_performance",
                [
                    {"source_id": "finviz", "total_signals": 40, "go_signals": 10, "trades_matched": 6, "win_rate": 60},
                    {"source_id": "rss", "total_signals": 200, "go_signals": 0, "trades_matched": 0, "win_rate": None},
                ],
            ),
            ("FROM source_learning_scores", []),
            ("FROM data_source_health", []),
            ("FROM research_sources", [{"source_name": "finviz", "credibility_score": 0.9, "notes": None}]),
        ]
    )


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setattr(sm, "OUT", tmp_path / "runtime" / "source_maturity_latest.json")
    monkeypatch.setattr(svl, "MATURITY", tmp_path / "runtime" / "source_maturity_latest.json")
    monkeypatch.setattr(svl, "ACTIONS", tmp_path / "runtime" / "source_vetting_actions_latest.json")
    return tmp_path


# ── step 1: attribution ───────────────────────────────────────────────────────────────


def test_attribution_dry_run_is_read_only(monkeypatch):
    conn = _soa_conn()
    monkeypatch.setattr(soa, "_db", lambda: conn)
    _forbid(monkeypatch, soa, "write_rows")
    rep = soa.run(dry_run=True)
    assert rep["dry_run"] is True and rep["would_upsert"] == 2 and rep["upserted"] == 0
    assert ("set_session", {"readonly": True}) in conn.log
    assert conn.writes() == [] and ("commit",) not in conn.log


def test_attribution_live_upserts_same_rows(monkeypatch):
    conn = _soa_conn()
    monkeypatch.setattr(soa, "_db", lambda: conn)
    rep = soa.run(dry_run=False)
    assert rep["upserted"] == 2 and len(conn.writes()) == 2 and ("commit",) in conn.log
    finviz = next(e for e in conn.writes() if e[2][0] == "finviz")
    # (source, total_signals, go_signals, trades_matched, wins, win_rate, avg_pnl_pct, scar, losses, last)
    assert finviz[2][:6] == ("finviz", 40, 1, 2, 1, 50.0) and finviz[2][7] == 0.4 and finviz[2][8] == 1


def test_attribution_receipt_and_exit(monkeypatch):
    monkeypatch.setattr(soa, "run", lambda dry_run=False: {"sources": 2, "upserted": 2, "with_matched_trades": 1})
    assert soa.main([]) == 0
    assert json.loads(llr.receipt_path("source_outcome_attribution").read_text())["status"] == "ok"

    def boom(dry_run=False):
        raise RuntimeError("db down")

    monkeypatch.setattr(soa, "run", boom)
    assert soa.main([]) == 1
    assert json.loads(llr.receipt_path("source_outcome_attribution").read_text())["status"] == "failed"


# ── step 2: maturity ──────────────────────────────────────────────────────────────────


def test_maturity_dry_run_writes_no_file(monkeypatch):
    conn = _sm_conn()
    monkeypatch.setattr(sm, "_db", lambda: conn)
    _forbid(monkeypatch, sm, "write_out")
    doc = sm.run(dry_run=True)
    assert doc["source_count"] == 2 and doc["tier_counts"].get("demoted") == 1
    assert ("set_session", {"readonly": True}) in conn.log
    assert not sm.OUT.exists()


def test_maturity_live_writes_out(monkeypatch):
    monkeypatch.setattr(sm, "_db", lambda: _sm_conn())
    sm.run(dry_run=False)
    assert json.loads(sm.OUT.read_text())["source_count"] == 2


def test_maturity_runtime_dir_uses_persistent_resolver(monkeypatch, tmp_path):
    import lib.persistent_state_root as psr

    monkeypatch.setattr(psr, "resolve_durable_dir", lambda rel, root=None: tmp_path / "persist" / rel)
    assert sm.runtime_dir() == tmp_path / "persist" / "data/runtime"


# ── step 3: ladder ────────────────────────────────────────────────────────────────────

DOC = {
    "sources": [
        {
            "source": "finviz",
            "tier": "core",
            "maturity_score": 75.0,
            "go_rate": 0.25,
            "outcome_proven": True,
            "total_signals": 40,
        },
        {
            "source": "newsrc",
            "tier": "trusted",
            "maturity_score": 55.0,
            "go_rate": 0.1,
            "outcome_proven": False,
            "total_signals": 30,
        },
    ]
}


def test_ladder_dry_run_reaches_no_writer(monkeypatch):
    conn = FakeConn([("FROM research_sources", [("finviz", False, "")])])
    monkeypatch.setattr(svl, "_db", lambda: conn)
    _forbid(monkeypatch, svl, "apply_plan")
    rep = svl.run(dry_run=True, maturity=DOC)
    assert rep["registered_new_candidates"] == 1 and rep["tier_updates"] == 1 and rep["vetting_actions"] == 2
    assert rep["would_run_auto_approval"] is True
    assert ("set_session", {"readonly": True}) in conn.log and conn.writes() == []
    assert not svl.ACTIONS.exists()


def test_ladder_live_applies_same_plan(monkeypatch):
    conn = FakeConn([("FROM research_sources", [("finviz", False, "")])])
    monkeypatch.setattr(svl, "_db", lambda: conn)
    called = {}
    import types

    mod = types.ModuleType("hermes_source_auto_approval")
    mod.run_auto_approval = lambda **kw: called.update(kw) or {"applied": 0}
    monkeypatch.setitem(sys.modules, "hermes_source_auto_approval", mod)
    svl.MATURITY.parent.mkdir(parents=True, exist_ok=True)
    svl.MATURITY.write_text(json.dumps(DOC))
    rep = svl.run(dry_run=False)
    kinds = [e[1].split()[0] for e in conn.writes()]
    assert kinds == ["INSERT", "UPDATE"] and ("commit",) in conn.log
    assert len(json.loads(svl.ACTIONS.read_text())["actions"]) == 2
    assert called == {"apply": True, "max_actions": 15, "use_llm": True} and rep["auto_approval"] == {"applied": 0}


def test_ladder_source_order():
    src = inspect.getsource(svl.run)
    assert "None if dry_run else apply_plan(c, p)" in src
    assert src.index("set_session(readonly=True)") < src.index("plan(mat, existing)")


# ── the chain (single argv for the allowlist) ─────────────────────────────────────────


def test_chain_dry_run_end_to_end_writes_nothing(monkeypatch):
    c1, c2 = _soa_conn(), _sm_conn()
    c3 = FakeConn([("FROM research_sources", [])])
    monkeypatch.setattr(soa, "_db", lambda: c1)
    monkeypatch.setattr(sm, "_db", lambda: c2)
    monkeypatch.setattr(svl, "_db", lambda: c3)
    _forbid(monkeypatch, soa, "write_rows")
    _forbid(monkeypatch, sm, "write_out")
    _forbid(monkeypatch, svl, "apply_plan")
    res = chain.run_chain(dry_run=True)
    assert res["ok"] is True
    # the ladder planned from the in-memory maturity doc (no file exists to read)
    assert not svl.MATURITY.exists()
    assert res["steps"]["source_vetting_ladder"]["registered_new_candidates"] == 2
    for c in (c1, c2, c3):
        assert c.writes() == [] and ("set_session", {"readonly": True}) in c.log
    assert chain.main(["--dry-run"]) == 0
    assert not llr.receipt_path("source_maturity_chain").exists()


def test_chain_stops_at_first_failure_like_and_and(monkeypatch):
    calls = []
    monkeypatch.setattr(soa, "run", lambda dry_run=False: calls.append("soa") or {"sources": 1})

    def bad(dry_run=False):
        calls.append("sm")
        raise RuntimeError("source_performance missing")

    monkeypatch.setattr(sm, "run", bad)
    monkeypatch.setattr(svl, "run", lambda **kw: calls.append("svl") or {})
    assert chain.main([]) == 1
    assert calls == ["soa", "sm"]
    r = json.loads(llr.receipt_path("source_maturity_chain").read_text())
    assert r["status"] == "failed" and r["ok_at"] is None and r["summary"]["failed_step"] == "source_maturity"


def test_chain_live_success_receipt(monkeypatch):
    monkeypatch.setattr(soa, "run", lambda dry_run=False: {"sources": 3, "upserted": 3, "with_matched_trades": 1})
    monkeypatch.setattr(sm, "run", lambda dry_run=False: {"source_count": 3, "tier_counts": {"core": 1}})
    seen = {}
    monkeypatch.setattr(
        svl,
        "run",
        lambda dry_run=False, maturity=None: (
            seen.update(maturity=maturity) or {"registered_new_candidates": 0, "tier_updates": 3, "vetting_actions": 0}
        ),
    )
    assert chain.main([]) == 0
    assert seen["maturity"] is None  # live ladder reads the file step 2 just wrote, as cron did
    r = json.loads(llr.receipt_path("source_maturity_chain").read_text())
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["steps"]["source_maturity"]["source_count"] == 3
