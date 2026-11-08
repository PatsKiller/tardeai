"""LQ-20261107-1104: the governed bridge's daily cap is a quota wait, not a broken lane.

Measured 2026-11-08: from 13:40 ET every due-diligence-questions run hit the bridge's daily request cap
(``COST_CAP_EXCEEDED: daily request cap (HTTP 429)``), asked again for every remaining change, and exited 1 with
``all_model_calls_failed`` -- three runs dead-lettered in 40 minutes while the bridge behaved exactly as configured.

The rule (the same as LQ-20261107-1010's 429): a cap refusal stops the run at the FIRST refusal, the run exits 0
with ``empty_reason="rate_limited"`` and ``outcome_reason="ok_rate_limited: <code>"`` -- no exit 1, so no dead
letter. A refusal for any other reason is still a failure, and so is a real failure that precedes the cap.

Hermetic: the DB, DDL guard, dossier, persist and router are stubs; the bridge transport (``_call_bridge``) returns
the two shapes the live bridge sends for a cap. No DB, provider, network or live state.
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

import lib.llm_bridge_route as route_mod  # noqa: E402 -- after the sys.path set-up above

#: The live 429 body (logs/cio_governed_bridge.log, 2026-11-08 13:40:13 ET).
CAP_429 = {"error": {"code": "COST_CAP_EXCEEDED", "status": 429, "message": "daily request cap"},
           "governance_pass": False}
#: The second live shape of the same cap (lib/cio_research_fail_policy.py): a 500 that is not a server fault.
CAP_500 = {"error": {"code": "RESERVATION_FAILED", "status": 500,
                     "message": "COST_CAP_EXCEEDED: daily request cap"}, "governance_pass": False}
PROVIDER_DOWN = {"error": {"code": "PROVIDER_HTTP_ERROR", "status": 502, "message": "bad gateway"},
                 "governance_pass": False}


def _ok_answer() -> dict:
    return {"choices": [{"message": {"content": json.dumps({"narrative": [], "questions": []})}}],
            "_tradeai": {"governance_pass": True, "process_id": "due_diligence_questions", "reservation_id": "r-1"}}


def _load() -> types.ModuleType:
    path = ROOT / "scripts" / "due_diligence_questions.py"
    mod = types.ModuleType("ddq_lq1104_under_test")
    mod.__file__ = str(path)
    exec(compile(path.read_text(encoding="utf-8"), mod.__file__, "exec"), mod.__dict__)
    return mod


class _Cur:
    rowcount = 0

    def execute(self, *a, **k):
        return None

    def fetchone(self):
        return (1,)

    def fetchall(self):
        return []


class _Conn:
    def cursor(self, *a, **k):
        return _Cur()

    def commit(self):
        return None

    def close(self):
        return None


def _changes(n: int) -> list[dict]:
    return [{"subject_guid": f"g-{i}", "change_guid": f"c-{i}", "symbol": f"S{i}", "kind": "news",
             "magnitude": 1, "observed_value": 2, "baseline": 1, "observed_at": "2026-11-08T18:00:00Z"}
            for i in range(n)]


@pytest.fixture
def wired(tmp_path, monkeypatch):
    """A DDQ module on the bridge path whose transport replies from a script; returns (mod, calls, script)."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TRADEAI_LLM_VIA_BRIDGE", "bridge")
    stub = types.ModuleType("scripts.lib.ddl_guard")
    stub.apply_ddl = lambda cur, ddl: None
    monkeypatch.setitem(sys.modules, "scripts.lib.ddl_guard", stub)

    calls: list[str] = []
    script: list[dict] = []

    def _call_bridge(messages, **kw):
        calls.append(kw["process_id"])
        return script.pop(0) if script else CAP_429

    monkeypatch.setattr(route_mod, "_call_bridge", _call_bridge)
    monkeypatch.setattr(route_mod, "process_admitted", lambda pid: True)

    mod = _load()
    mod._db = _Conn
    mod._usable = lambda conn, cur: (conn, cur)
    mod.cap_env_warning = lambda: None
    mod.reconcile_answers = lambda cur, apply=True: {}
    mod.dossier = lambda cur, guid: [{"id": "d-1", "date": "2026-11-06", "text": "linked in the corpus"}]
    mod.evidence_subjects = lambda cur, guids: {str(g) for g in guids}
    mod.route = lambda cur, limit: {"routed": 0}
    mod.ground = lambda parsed, items: ([], [{"question": "q?"}], {})
    mod.persist = lambda cur, ch, narrative, questions, meta, n: ("n", 1)
    return mod, calls, script


def _receipt(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "state" / "data" / "runtime" / "due-diligence-questions_last.json").read_text())


# --- the refusal says what it was ----------------------------------------------------------------------


@pytest.mark.parametrize("body", [CAP_429, CAP_500], ids=["http429", "reservation_failed_500"])
def test_a_cap_refusal_is_flagged_and_keeps_the_refused_prefix(monkeypatch, body):
    monkeypatch.setattr(route_mod, "_call_bridge", lambda messages, **kw: body)
    monkeypatch.setattr(route_mod, "process_admitted", lambda pid: True)
    with pytest.raises(route_mod.BridgeRouteRefused) as ei:
        route_mod.require_text_via_bridge("due_diligence_questions", "p")
    assert str(ei.value).startswith(f"{route_mod.REFUSED}: governed bridge returned no text"), ei.value
    assert ei.value.cap_exceeded is True
    assert ei.value.code == body["error"]["code"]


def test_any_other_refusal_is_not_a_cap(monkeypatch):
    monkeypatch.setattr(route_mod, "_call_bridge", lambda messages, **kw: PROVIDER_DOWN)
    monkeypatch.setattr(route_mod, "process_admitted", lambda pid: True)
    with pytest.raises(route_mod.BridgeRouteRefused) as ei:
        route_mod.require_text_via_bridge("due_diligence_questions", "p")
    assert ei.value.cap_exceeded is False and ei.value.code == "PROVIDER_HTTP_ERROR"


def test_text_via_bridge_still_returns_plain_text_or_none(monkeypatch):
    monkeypatch.setattr(route_mod, "process_admitted", lambda pid: True)
    monkeypatch.setattr(route_mod, "_call_bridge", lambda messages, **kw: CAP_429)
    assert route_mod.text_via_bridge("due_diligence_questions", "p") is None
    monkeypatch.setattr(route_mod, "_call_bridge", lambda messages, **kw: _ok_answer())
    assert route_mod.text_via_bridge("due_diligence_questions", "p") == json.dumps({"narrative": [], "questions": []})


# --- the lane: stop at the first cap, exit 0, no dead letter ------------------------------------------------


@pytest.mark.parametrize("body", [CAP_429, CAP_500], ids=["http429", "reservation_failed_500"])
def test_a_cap_on_the_first_change_stops_asking_and_exits_zero(wired, tmp_path, body):
    mod, calls, script = wired
    mod.pending_changes = lambda cur, limit: _changes(5)
    script[:] = [body] * 5

    assert mod.main(["--apply"]) == 0

    assert len(calls) == 1, f"the run kept asking a capped bridge: {len(calls)} requests"
    doc = _receipt(tmp_path)
    assert doc["status"] == "ok" and doc["exit"] == 0, doc
    assert doc["ok_at"] == doc["finished_at"], doc
    assert doc["produced_count"] == 0, doc
    assert doc["empty_reason"] == "rate_limited", doc
    assert doc["outcome_reason"].startswith("ok_rate_limited"), doc
    assert not doc.get("error"), doc


def test_work_written_before_the_cap_is_counted(wired, tmp_path):
    mod, calls, script = wired
    mod.pending_changes = lambda cur, limit: _changes(5)
    script[:] = [_ok_answer(), _ok_answer(), CAP_429]

    assert mod.main(["--apply"]) == 0

    assert len(calls) == 3, calls
    doc = _receipt(tmp_path)
    assert doc["status"] == "ok" and doc["exit"] == 0, doc
    assert doc["produced_count"] == 2, doc
    assert doc["outcome"] == "ok", doc
    assert doc["outcome_reason"].startswith("ok_rate_limited"), doc


def test_a_real_failure_before_the_cap_is_still_a_failed_run(wired, tmp_path):
    """The cap rule must not launder a broken route: one provider error, then the cap, nothing written."""
    mod, calls, script = wired
    mod.pending_changes = lambda cur, limit: _changes(5)
    script[:] = [PROVIDER_DOWN, CAP_429]

    assert mod.main(["--apply"]) == 1

    assert len(calls) == 2, calls
    doc = _receipt(tmp_path)
    assert doc["status"] == "failed" and doc["exit"] == 1, doc
    assert doc["error"] == "all_model_calls_failed", doc


def test_a_non_cap_refusal_on_every_call_is_still_all_model_calls_failed(wired, tmp_path):
    mod, calls, script = wired
    mod.pending_changes = lambda cur, limit: _changes(3)
    script[:] = [PROVIDER_DOWN] * 3

    assert mod.main(["--apply"]) == 1

    assert len(calls) == 3, calls
    doc = _receipt(tmp_path)
    assert doc["status"] == "failed" and doc["error"] == "all_model_calls_failed", doc
