"""Refactor wave 2, bucket V2 (cron -> n8n, 2026-10-10): the advisory LLM lanes.

- watchlist_entry_planner.py (cron L473 watchlist, L474 --scope proposals): --dry-run selects the
  candidates on a READ ONLY session and returns before price bars (yfinance / Alpaca data + its
  credentials), the cloud LLM, the plan INSERT and the Telegram alert; a scheduled real run writes
  watchlist_entry_planner[_proposals]_last.json, exits 1 only when every candidate failed.
- health_agent_llm_review.py (cron L337): --dry-run returns before the local LLM and both INSERTs on a
  READ ONLY session; a real run exits 1 (receipt failed, ok_at kept) when no review was stored.
- hermes_top20_external_intel.py (cron L453): --dry-run (wins over --apply) appends no accounting
  events, writes no skip ledger and starts no researcher subprocess; receipt + honest exit on --apply.
Hermetic: fake DB connections, TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import inspect
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import health_agent_llm_review as har  # noqa: E402
import hermes_top20_external_intel as top20  # noqa: E402
import watchlist_entry_planner as wep  # noqa: E402
from lib import lane_last_receipt as llr  # noqa: E402


def _forbid(monkeypatch, obj, name):
    def boom(*a, **k):
        raise AssertionError(f"dry run reached {name}")

    monkeypatch.setattr(obj, name, boom)


class FakeConn:
    """Answers SQL by substring; records every statement, commit and session change."""

    def __init__(self, answers=(), one=None):
        self.answers = list(answers)  # (substring, rows)
        self.one = one or {}  # substring -> fetchone row
        self.log: list = []

    def cursor(self, *a, **k):
        conn = self

        class C:
            description = [("symbol",)]

            def execute(self, sql, params=None):
                flat = " ".join(sql.split())
                conn.log.append(("execute", flat))
                self._rows = next((rows for sub, rows in conn.answers if sub in flat), [])
                self._one = next((row for sub, row in conn.one.items() if sub in flat), None)

            def fetchall(self):
                return list(self._rows)

            def fetchone(self):
                if self._one is not None:
                    return self._one
                return self._rows[0] if self._rows else None

            def close(self):
                pass

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


@pytest.fixture(autouse=True)
def _state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    return tmp_path / "state"


def _receipt(name):
    return json.loads(llr.receipt_path(name).read_text())


# ── watchlist_entry_planner (L473 / L474) ─────────────────────────────────────────────


def _planner_dry(monkeypatch, cands):
    import db_adapter

    conn = FakeConn()
    monkeypatch.setattr(db_adapter, "_get_conn", lambda: conn)
    seen = {}

    def fake_candidates(cur, limit, symbols, scope, cap):
        seen.update(limit=limit, symbols=symbols, scope=scope, cap=cap)
        return cands

    monkeypatch.setattr(wep, "_candidates", fake_candidates)
    for name in ("_bars", "_bars_alpaca", "_alpaca_creds", "_alert", "_analyst", "_live"):
        _forbid(monkeypatch, wep, name)
    fake_llm = types.ModuleType("llm_lane")
    fake_llm.generate = lambda *a, **k: (_ for _ in ()).throw(AssertionError("dry run reached the LLM"))
    fake_llm.available = lambda *a, **k: (_ for _ in ()).throw(AssertionError("dry run probed a lane"))
    monkeypatch.setitem(sys.modules, "llm_lane", fake_llm)
    return conn, seen


def test_planner_dry_run_lists_candidates_and_reaches_nothing(monkeypatch, capsys):
    cands = [{"symbol": "AAA"}, {"symbol": "BBB", "_buy_rated": True}]
    conn, seen = _planner_dry(monkeypatch, cands)
    rep = wep.preview(limit=60, buy_rated_cap=400, scope="watchlist")
    assert rep["dry_run"] is True and rep["candidates"] == 2 and rep["buy_rated"] == 1
    assert rep["symbols"] == ["AAA", "BBB"] and rep["would_call_llm"] == 2
    assert seen == {"limit": 60, "symbols": None, "scope": "watchlist", "cap": 400}
    assert ("set_session", {"readonly": True}) in conn.log
    assert conn.writes() == [] and ("commit",) not in conn.log
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["candidates"] == 2
    assert not llr.receipt_path("watchlist_entry_planner").exists()


def test_planner_dry_run_report_varies_with_state(monkeypatch):
    _planner_dry(monkeypatch, [])
    assert wep.preview()["candidates"] == 0
    _planner_dry(monkeypatch, [{"symbol": s} for s in ("A", "B", "C")])
    assert wep.preview(alert=False)["candidates"] == 3


def test_planner_preview_source_never_names_a_side_effect():
    src = inspect.getsource(wep.preview)
    for token in ("_bars(", "generate(", "INSERT INTO", "UPDATE watchlist", "_alert(", "commit("):
        assert token not in src, token
    assert src.index("enforce_readonly") < src.index("_candidates(")


def test_planner_scheduled_receipt_names_and_honest_exit(monkeypatch):
    monkeypatch.setattr(
        wep, "run", lambda **kw: {"candidates": 5, "planned": 3, "failed": 2, "alerts": 0, "lane": "grok"}
    )
    assert wep._scheduled_run({"scope": "watchlist"}) == 0
    r = _receipt("watchlist_entry_planner")
    assert r["status"] == "ok" and r["ok_at"] and r["summary"]["failed"] == 2
    monkeypatch.setattr(
        wep, "run", lambda **kw: {"candidates": 0, "planned": 0, "failed": 0, "alerts": 0, "lane": "grok"}
    )
    assert wep._scheduled_run({"scope": "proposals"}) == 0  # an empty queue is not a failure
    assert _receipt("watchlist_entry_planner_proposals")["status"] == "ok"


def test_planner_all_failed_or_raise_is_exit_1_and_keeps_ok_at(monkeypatch):
    monkeypatch.setattr(
        wep, "run", lambda **kw: {"candidates": 1, "planned": 1, "failed": 0, "alerts": 0, "lane": "grok"}
    )
    assert wep._scheduled_run({"scope": "watchlist"}) == 0
    first_ok = _receipt("watchlist_entry_planner")["ok_at"]
    monkeypatch.setattr(
        wep, "run", lambda **kw: {"candidates": 4, "planned": 0, "failed": 4, "alerts": 0, "lane": "grok"}
    )
    assert wep._scheduled_run({"scope": "watchlist"}) == 1
    r = _receipt("watchlist_entry_planner")
    assert r["status"] == "failed" and r["ok_at"] == first_ok

    def boom(**kw):
        raise RuntimeError("CLOUD_LANES_UNAVAILABLE: entry planning failed closed")

    monkeypatch.setattr(wep, "run", boom)
    assert wep._scheduled_run({"scope": "watchlist"}) == 1
    assert _receipt("watchlist_entry_planner")["error"] == "RuntimeError"  # helper scrubs to the type


def test_planner_cli_dry_run_wins_and_symbols_run_writes_no_receipt():
    src = inspect.getsource(wep)
    main_src = src[src.index('if __name__ == "__main__":') :]
    assert main_src.index("if a.dry_run:") < main_src.index("if a.symbols:") < main_src.index("_scheduled_run(kw)")


# ── health_agent_llm_review (L337) ────────────────────────────────────────────────────


def _health_conn():
    return FakeConn(one={"FROM pipeline_runs": (0, 3), "FROM paper_trades": (2, 0, 0)})


def test_health_dry_run_returns_before_llm_and_inserts(monkeypatch):
    conn = _health_conn()
    monkeypatch.setattr(har, "_get_conn", lambda: conn)
    _forbid(monkeypatch, har, "_call_local_llm")
    res = har.run_review(dry_run=True)
    assert res["status"] == "dry_run" and res["prompt_chars"] > 100 and res["pipeline_failed"] == 0
    assert ("set_session", {"readonly": True}) in conn.log
    assert conn.writes() == [] and ("commit",) not in conn.log
    assert har.main(["--dry-run"]) == 0  # CLI form: same fake, still no LLM, no receipt
    assert not llr.receipt_path("health_agent_llm_review").exists()


def test_health_dry_run_source_order():
    src = inspect.getsource(har.run_review)
    assert src.index("if dry_run:\n        log.info") < src.index("_call_local_llm(prompt)") < src.index("INSERT")


def test_health_real_run_receipt_and_exit(monkeypatch):
    monkeypatch.setattr(har, "run_review", lambda dry_run=False: {"status": "stored", "response_chars": 9})
    assert har.main([]) == 0
    r = _receipt("health_agent_llm_review")
    assert r["status"] == "ok" and r["ok_at"]
    for status in ("no_response", "store_failed", "no_db"):
        monkeypatch.setattr(har, "run_review", lambda dry_run=False, s=status: {"status": s})
        assert har.main([]) == 1
        r2 = _receipt("health_agent_llm_review")
        assert r2["status"] == "failed" and r2["ok_at"] == r["ok_at"] and r2["error"] == status


def test_health_real_run_stores_and_reports_stored(monkeypatch):
    conn = _health_conn()
    monkeypatch.setattr(har, "_get_conn", lambda: conn)
    monkeypatch.setattr(har, "_call_local_llm", lambda prompt: "HEALTH GRADE: B")
    res = har.run_review(dry_run=False)
    assert res["status"] == "stored"
    assert len(conn.writes()) == 2 and ("commit",) in conn.log


# ── hermes_top20_external_intel (L453) ────────────────────────────────────────────────


def _top20_setup(monkeypatch, rows, recent_symbols=()):
    conn = FakeConn()
    monkeypatch.setattr(top20, "_conn", lambda: conn)
    monkeypatch.setattr(top20, "_top", lambda c, n: rows)
    monkeypatch.setattr(
        top20, "_trigger_context", lambda c: {"holdings": set(), "proposals": set(), "directive": set()}
    )
    monkeypatch.setattr(top20, "_recent", lambda c, sym, lane: sym in recent_symbols)
    guard = types.ModuleType("hermes_research_budget_guard")
    guard._load_policy = lambda: {"trigger_source_tier": {}}
    guard.decide = lambda **kw: {"decision": "DEFER" if kw["dedup_fresh"] else "ALLOW"}
    monkeypatch.setitem(sys.modules, "hermes_research_budget_guard", guard)
    # Recorded, not raised: run() wraps each of these in try/except Exception, which would swallow a raise.
    conn.side_effects = []
    monkeypatch.setattr(top20, "append_call_event", lambda *a, **k: conn.side_effects.append("accounting"))
    monkeypatch.setattr(top20.subprocess, "run", lambda *a, **k: conn.side_effects.append("subprocess"))
    ledger = types.ModuleType("lib.research_skip_ledger")
    ledger.log_mapped_reason = lambda *a, **k: conn.side_effects.append("skip_ledger")
    monkeypatch.setitem(sys.modules, "lib.research_skip_ledger", ledger)
    return conn


ROWS = [
    {
        "symbol": "AAA",
        "hermes_rank": 1,
        "hermes_composite_score": 80,
        "hermes_score_components": {},
        "rsi": 50,
        "trend": "up",
    },
    {
        "symbol": "BBB",
        "hermes_rank": 2,
        "hermes_composite_score": 75,
        "hermes_score_components": {},
        "rsi": 40,
        "trend": "down",
    },
]


def test_top20_dry_run_wins_over_apply_and_writes_nothing(monkeypatch):
    conn = _top20_setup(monkeypatch, ROWS, recent_symbols={"BBB"})
    rep = top20.run(top=20, lanes=("grok", "chatgpt"), apply=True, dry_run=True)
    assert rep["would_call"] == 2 and rep["deferred"] == 2 and rep["called"] == 0
    assert ("set_session", {"readonly": True}) in conn.log and conn.writes() == []
    assert conn.side_effects == []
    assert not llr.receipt_path("hermes_top20_external_intel").exists()


def test_top20_main_dry_run_flag_never_receipts(monkeypatch):
    fake = _top20_setup(monkeypatch, ROWS)
    monkeypatch.setattr(sys, "argv", ["x"])
    lib_mod = sys.modules["lib"]
    monkeypatch.setattr(lib_mod, "assert_single_import_identity", lambda: None, raising=False)
    assert top20.main(["--apply", "--dry-run"]) == 0
    assert fake.side_effects == []
    assert not llr.receipt_path("hermes_top20_external_intel").exists()


def test_top20_apply_receipt_and_honest_exit(monkeypatch):
    lib_mod = sys.modules["lib"]
    monkeypatch.setattr(lib_mod, "assert_single_import_identity", lambda: None, raising=False)
    base = {"top": 2, "called": 2, "call_errors": 0, "skipped": 0, "metadata_only": 0, "deferred": 4448, "blocked": 0}
    monkeypatch.setattr(top20, "run", lambda **kw: dict(base))
    assert top20.main(["--apply"]) == 0
    r = _receipt("hermes_top20_external_intel")
    assert r["status"] == "ok" and r["summary"]["deferred"] == 4448  # deferrals are findings
    monkeypatch.setattr(top20, "run", lambda **kw: {**base, "called": 0, "call_errors": 3})
    assert top20.main(["--apply"]) == 1
    r2 = _receipt("hermes_top20_external_intel")
    assert r2["status"] == "failed" and r2["ok_at"] == r["ok_at"]


def test_top20_holdings_path_resolves_served_state(monkeypatch, tmp_path):
    import lib.persistent_state_root as psr

    monkeypatch.setattr(psr, "resolve_durable_dir", lambda rel, root=None: tmp_path / rel)
    assert top20._holdings_path() == tmp_path / "data/portfolios/state/holdings.json"
