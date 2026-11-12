"""LQ-20261107-2620 — due-diligence routing sent every question to a dead DIRECT-OAuth label.

MEASURED 2026-11-12 18:20 ET, read-only, from the lane's own receipt and the runs ledger:

    RESULT: {..., "rows_produced": 11,
             "routed": {"routed": 0, "failed": 2, "lanes_ranked": ["chatgpt"],
                        "detail": ["BE:chatgpt gated before attempting — next lane", ...]}}

Three faults, and each one alone keeps routed=0:

1. THE BRIDGE PATH TRIMMED THE POLICY TO A DEAD LABEL. `route()` ranked lanes by 30-day DIRECT-provider
   success and kept only `lanes[:1]`. chatgpt was the only rankable lane; its breaker was open from
   direct OAuth failures (status unavailable/auth_pending), so every question exited 75 — once, which is
   all the list had. On the bridge path the BRIDGE picks the provider (grok -> chatgpt -> deepseek,
   config/llm_routing_policy.json), so the order must come from the policy, not from a direct-route
   ranking that can also empty the list.

2. THE PER-LANE BREAKER GATED THE BRIDGE ROUTE. The breaker is a fact about the label's direct provider
   client (HTTP 401/403, unavailable). The bridge call never touches that client, so its breaker must not
   refuse the call before the healthy bridge is asked.

3. A RUN THAT SELECTED QUESTIONS AND ROUTED NONE STILL WROTE `ok`/`nothing_due`. selected=2, failed=2,
   routed=0 advanced ok_at every 20 minutes (routed=0 since 2026-11-11 19:40 ET). A selected question
   that could not be sent is a standing gap, not an empty lane — the run is failed.

No database, no network, no model call, no live lane run.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load() -> types.ModuleType:
    """The lane script as its own module object (the receipt suite's pattern): no DB, no import side effects."""
    path = ROOT / "scripts" / "due_diligence_questions.py"
    mod = types.ModuleType("ddq_lq2620_under_test")
    mod.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), mod.__file__, "exec"), mod.__dict__)
    return mod


@pytest.fixture(scope="module")
def ddq():
    return pytest.importorskip("due_diligence_questions")


@pytest.fixture(scope="module")
def researcher():
    return pytest.importorskip("hermes_external_researcher")


# ── route(): the bridge path takes its order from the policy ─────────────────────────────────────────

class _Cur:
    """route(): one SELECT ... FOR UPDATE, then one row lookup per lane attempt, then UPDATEs."""

    def __init__(self, questions, found_rows):
        self.questions = questions
        self.found = list(found_rows)
        self.sql = []
        self._last = ""

    def execute(self, sql, params=None):
        self._last = sql
        self.sql.append(sql)

    def fetchall(self):
        return self.questions if "FOR UPDATE" in self._last else []

    def fetchone(self):
        return self.found.pop(0) if self.found else None


class _Proc:
    def __init__(self, rc, stderr=""):
        self.returncode, self.stderr, self.stdout = rc, stderr, ""


def _route(ddq, monkeypatch, *, rc, found, lanes, bridge, order=None):
    cur = _Cur([("q1", "NVDA", "Q?")], found)
    monkeypatch.setattr(ddq, "rank_research_lanes", lambda _c: lanes)
    monkeypatch.setattr(ddq, "via_bridge", lambda: bridge)
    if order is not None:
        monkeypatch.setattr(ddq, "bridge_lane_order", lambda *a, **k: order)
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd[cmd.index("--lane") + 1])
        return _Proc(rc)

    monkeypatch.setattr(ddq.subprocess, "run", fake_run)
    return ddq.route(cur, 2), seen


def test_bridge_path_labels_the_call_with_the_policy_primary(ddq, monkeypatch):
    """Measured: lanes_ranked=['chatgpt'], --lane chatgpt, exit 75. The policy primary is grok."""
    out, seen = _route(ddq, monkeypatch, rc=0, found=[(1,)], lanes=[("chatgpt", 0.9, 2.0)], bridge=True)
    assert seen == ["grok"], seen
    assert out["routed"] == 1 and out["failed"] == 0, out
    assert out["lanes_ranked"] == ["grok"], out


def test_bridge_path_routes_when_the_measured_gate_admits_no_lane(ddq, monkeypatch):
    """The direct-route success gate cannot empty the bridge path: unmeasured is not unusable there.

    Before: rank_research_lanes -> [] (grok unmeasured, chatgpt below/without a window) returned
    routed=0 with 'no research lane met the minimum success rate' and never asked the bridge.
    """
    out, seen = _route(ddq, monkeypatch, rc=0, found=[(1,)], lanes=[], bridge=True)
    assert seen == ["grok"], seen
    assert out["routed"] == 1, out


def test_non_bridge_path_still_uses_the_measured_ranking(ddq, monkeypatch):
    """The cron path has no bridge to choose for it; its measured ranking is unchanged."""
    out, seen = _route(ddq, monkeypatch, rc=0, found=[(1,)],
                       lanes=[("chatgpt", 0.9, 2.0), ("grok", 0.8, 1.0)], bridge=False)
    assert seen == ["chatgpt"], seen
    assert out["routed"] == 1, out


def test_an_unreadable_policy_keeps_the_measured_ranking_on_the_bridge_path(ddq, monkeypatch):
    """An unreadable policy is not permission to invent an order: fall back, do not crash."""
    out, seen = _route(ddq, monkeypatch, rc=0, found=[(1,)],
                       lanes=[("chatgpt", 0.9, 2.0)], bridge=True, order=[])
    assert seen == ["chatgpt"], seen
    assert out["routed"] == 1, out


def test_bridge_order_is_the_n8n_llm_order(ddq):
    """config/llm_routing_policy.json process due_diligence_questions: grok, chatgpt, deepseek."""
    assert ddq.bridge_lane_order() == ["grok", "chatgpt", "deepseek"]
    doc = json.loads((ROOT / "config" / "llm_routing_policy.json").read_text(encoding="utf-8"))
    row = doc["policies"][doc.get("default_policy_id", "default")]["processes"]["due_diligence_questions"]
    assert [row[s]["provider"] for s in ("primary", "secondary", "fallback")] == ["grok", "chatgpt", "deepseek"]


# ── the live allowlist must bind BOTH processes the lane calls ──────────────────────────────────────

def _ddq_allowlist_entry(ddq) -> dict:
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
    return next(e for e in allow["lanes"] if e.get("lane_id") == ddq.LANE_ID)


def test_the_lane_binds_both_bridge_processes(ddq):
    """Curation calls due_diligence_questions; the --route child calls hermes_external_research.

    A single-process binding refuses the child's bridge call in the CLIENT as PROCESS_NOT_ADMITTED before
    the bridge is asked. Measured: every DDQ research row since 2026-11-07 is that refusal (115 rows,
    last 2026-11-12 17:27 ET) — and the lane still wrote routed=0 / RUN_DONE over them.
    """
    assert _ddq_allowlist_entry(ddq)["llm_route"] == {
        "via": "cio-governed-bridge",
        "process_ids": ["due_diligence_questions", "hermes_external_research"],
    }


def test_the_executor_binds_the_declared_process_set(ddq):
    """The executor's own validator + binder accept the entry and export the SET the child inherits."""
    import n8n_run_executor as X

    entry = _ddq_allowlist_entry(ddq)
    assert X.validate_entry(entry) is None
    env = X._bind_llm_route({}, entry)
    assert env["TRADEAI_LLM_PROCESS_IDS"] == "due_diligence_questions,hermes_external_research"
    assert "TRADEAI_LLM_PROCESS_ID" not in env


# ── the run's verdict: selected and not sent is a failed run ─────────────────────────────────────────

def test_route_verdict_fails_a_run_that_routed_none_of_what_it_selected(ddq):
    routed = {"routed": 0, "failed": 2, "lanes_ranked": ["grok"],
              "detail": ["BE:grok gated before attempting — next lane", "HOOD:grok gated before attempting — next lane"]}
    assert ddq._route_verdict(routed) == (False, 1, "all_route_attempts_failed")


def test_route_verdict_leaves_a_working_route_alone(ddq):
    assert ddq._route_verdict({"routed": 2, "failed": 0}) == (True, 0, None)
    assert ddq._route_verdict({"routed": 1, "failed": 1}) == (True, 0, None)


def test_route_verdict_leaves_an_empty_backlog_alone(ddq):
    """Nothing selected is `nothing_due`, not a fault: no question existed to send."""
    assert ddq._route_verdict({"routed": 0, "failed": 0}) == (True, 0, None)
    assert ddq._route_verdict(None) == (True, 0, None)


# ---- receipt-level: main() must not write ok / nothing_due over routed=0 failed=2 -------------------

def _receipt(tmp_path: Path) -> Path:
    return tmp_path / "state" / "data" / "runtime" / "due-diligence-questions_last.json"


class _Conn:
    def cursor(self, *a, **k):
        return _RCur()

    def commit(self):
        return None

    def close(self):
        return None

    def rollback(self):
        return None


class _RCur:
    rowcount = 0

    def execute(self, *a, **k):
        return None

    def fetchone(self):
        return (1,)

    def fetchall(self):
        return []

    def set_session(self, **k):
        return None


def _stub_ddl_guard(monkeypatch):
    stub = types.ModuleType("scripts.lib.ddl_guard")
    stub.apply_ddl = lambda cur, ddl: None
    monkeypatch.setitem(sys.modules, "scripts.lib.ddl_guard", stub)


_CHANGE = {"subject_guid": "g-1", "change_guid": "c-1", "symbol": "AAA", "kind": "news", "magnitude": 1}


def _wire(mod, monkeypatch, *, changes, routed):
    _stub_ddl_guard(monkeypatch)
    mod._db = _Conn
    mod.cap_env_warning = lambda: None
    mod.reconcile_answers = lambda cur, apply=True: {}
    mod.pending_changes = lambda cur, limit: changes
    mod.dossier = lambda cur, guid: [{"id": "d-1", "date": "2026-11-06", "text": "linked in the corpus"}]
    mod.ask_model = lambda ch, items: {"parsed": {}, "lane": "bridge"}
    mod.persist = lambda cur, ch, narrative, questions, meta, n: ("n", 0)
    mod.route = lambda cur, limit: routed


def test_a_run_that_selected_questions_and_routed_none_is_failed(tmp_path, monkeypatch):
    """Measured receipt: produced_count=11, status ok, empty_reason null, routed=0 failed=2, ok_at advanced."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))
    mod = _load()
    _wire(mod, monkeypatch, changes=[dict(_CHANGE)],
          routed={"routed": 0, "failed": 2, "lanes_ranked": ["grok"], "detail": []})

    assert mod.main(["--apply", "--route"]) == 1

    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "failed", doc
    assert doc["exit"] == 1, doc
    assert doc["error"] == "all_route_attempts_failed", doc
    assert doc.get("empty_reason") is None, f"a routing failure reported an empty lane: {doc}"
    assert not doc.get("ok_at"), f"a routing failure advanced ok_at: {doc}"


def test_a_run_that_routed_its_selection_stays_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))
    mod = _load()
    _wire(mod, monkeypatch, changes=[dict(_CHANGE)], routed={"routed": 2, "failed": 0})

    assert mod.main(["--apply", "--route"]) == 0

    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "ok" and doc["exit"] == 0, doc
    assert doc["ok_at"] == doc["finished_at"], doc


def test_the_same_rule_covers_the_no_changes_branch(tmp_path, monkeypatch):
    """The backlog is routed even when no NEW change arrived; a gated backlog is a failed run there too."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))
    mod = _load()
    _wire(mod, monkeypatch, changes=[], routed={"routed": 0, "failed": 2, "lanes_ranked": ["grok"], "detail": []})

    assert mod.main(["--apply", "--route"]) == 1

    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "failed" and doc["exit"] == 1, doc
    assert doc["error"] == "all_route_attempts_failed", doc
    assert not doc.get("ok_at"), doc


def test_an_empty_backlog_without_changes_stays_nothing_due(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))
    mod = _load()
    _wire(mod, monkeypatch, changes=[], routed={"routed": 0, "failed": 0, "lanes_ranked": ["grok"], "detail": []})

    assert mod.main(["--apply", "--route"]) == 0

    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "ok" and doc["exit"] == 0, doc
    assert doc["empty_reason"] == "nothing_due", doc


# ── researcher: the direct-route breaker does not gate the bridge route ─────────────────────────────

def test_the_lane_breaker_does_not_gate_the_bridge_route(researcher, monkeypatch):
    """Before: chatgpt's breaker exited 75 before the bridge was asked; the bridge is a different route."""
    def _explode(_lane):
        raise AssertionError("the direct-route breaker was queried on the bridge path")

    monkeypatch.setattr(researcher, "via_bridge", lambda: True)
    monkeypatch.setattr(researcher, "lane_circuit_open", _explode)
    assert researcher.lane_breaker_gates("chatgpt") == (False, "governed_bridge_chooses_the_provider")


def test_the_lane_breaker_still_gates_the_direct_route(researcher, monkeypatch):
    monkeypatch.setattr(researcher, "via_bridge", lambda: False)
    monkeypatch.setattr(researcher, "lane_circuit_open", lambda _lane: True)
    assert researcher.lane_breaker_gates("chatgpt") == (True, "lane_circuit_open")
    monkeypatch.setattr(researcher, "lane_circuit_open", lambda _lane: False)
    assert researcher.lane_breaker_gates("chatgpt") == (False, "")


def test_main_asks_the_gate_function_not_the_raw_breaker(researcher):
    """Pins the call site: a future edit that restores `if lane_circuit_open(args.lane)` re-breaks the bridge."""
    src = (ROOT / "scripts" / "hermes_external_researcher.py").read_text(encoding="utf-8")
    assert "lane_breaker_gates(args.lane)" in src
    assert "if lane_circuit_open(args.lane)" not in src
