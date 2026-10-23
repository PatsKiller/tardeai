"""grok_stop_review on the LLM spend gate (2026-10-22, incident SPCX resume).

Operator 2026-10-22: keep crontab L497 paused until grok_stop_review is registered with the spend gate, then
"switch on after your fix". Before this change the script called llm_lane.generate(prompt, lane="grok", timeout=90)
with no process_id, so lib.llm_consumption.gate_and_generate never ran. These tests pin:

* every Grok call names the registered process ``grok_stop_review`` and reaches gate_and_generate;
* the registry row allows grok only, no fallback, with count caps (12 stops/run, 30 calls/day);
* over the daily cap or on a gate refusal the run stops before sending anything;
* a failed call is an error on that stop and nothing is sent on another lane;
* the bridge map, governed routes, routing row and caps sync carry the process (AGENTS.md §9.2);
* ``--plan`` calls no model.

Hermetic: no database, no network, no .env. Grok, the stop scan and the DB connection are stubbed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import grok_stop_review as gsr  # noqa: E402
import llm_lane  # noqa: E402
from lib import llm_consumption as lc  # noqa: E402

PID = "grok_stop_review"
GOOD = json.dumps({"grade": "B", "rr_assessment": "ok", "recommendation": "keep",
                   "suggested_action": "hold", "should_trail": False, "confidence": 0.6})


class _Cur:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return None


class _Conn:
    def __init__(self):
        self.c = _Cur()

    def cursor(self):
        return self.c

    def commit(self):
        pass


def _stops(n):
    return [{"symbol": f"S{i}", "account": "acct", "broker": "schwab", "held_qty": 10, "qty": 10,
             "stop_price": 9.0, "current_price": 10.0, "order_type": "STOP"} for i in range(n)]


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.delenv("TRADEAI_LLM_VIA_BRIDGE", raising=False)
    conn = _Conn()
    monkeypatch.setattr(gsr, "_conn", lambda: conn)
    monkeypatch.setattr(gsr, "_latest_thesis", lambda cur, sym: None)
    monkeypatch.setattr(gsr, "_hermes_finding", lambda cur, s, p: None)
    monkeypatch.setattr(gsr, "_held_stops", lambda: _stops(3))
    monkeypatch.setattr(lc, "over_daily_cap", lambda pid, extra=0: False)
    return conn


def _registry_row():
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text())
    rows = [p for p in reg["processes"] if p.get("id") == PID]
    assert len(rows) == 1
    return rows[0]


# ── the call goes through the gate ────────────────────────────────────────────────────────────────────


def test_every_call_names_the_registered_process(harness, monkeypatch):
    calls = []

    def fake_generate(prompt, lane="grok", timeout=90, **kw):
        calls.append({"lane": lane, **kw})
        return GOOD

    monkeypatch.setattr(llm_lane, "generate", fake_generate)
    out = gsr.run(apply=False)
    assert len(calls) == 3
    assert all(c["process_id"] == PID and c["lane"] == "grok" for c in calls)
    assert out["errors"] == 0 and out["refused"] is None


def test_llm_lane_routes_the_call_through_gate_and_generate(harness, monkeypatch):
    seen = []

    def fake_gate(prompt, **kw):
        seen.append(kw)
        return GOOD

    monkeypatch.setattr(lc, "gate_and_generate", fake_gate)
    out = gsr.run(apply=False)
    assert len(seen) == 3
    assert {k["process_id"] for k in seen} == {PID}
    assert {k["lane"] for k in seen} == {"grok"}
    assert len(out["reviewed"]) == 3


# ── budget refusals stop the run before anything is sent ─────────────────────────────────────────────


def test_over_daily_call_cap_refuses_before_sending(harness, monkeypatch):
    sent = []
    monkeypatch.setattr(llm_lane, "generate", lambda *a, **k: sent.append(1) or GOOD)
    monkeypatch.setattr(lc, "over_daily_cap", lambda pid, extra=0: pid == PID)
    out = gsr.run(apply=True)
    assert sent == []
    assert out["refused"].startswith("DAILY_CALL_CAP")
    assert out["reviewed"] == []
    assert harness.c.executed[1:] == []  # only the CREATE TABLE ran; no review row written


def test_daily_cap_counts_logged_calls_against_the_registry_soft_cap(monkeypatch):
    row = _registry_row()
    cfg = {"registered": True, "allowed_lanes": ["grok"], "daily_soft_cap": row["daily_soft_cap"]}
    monkeypatch.setattr(lc, "get_process_config", lambda pid: cfg)
    monkeypatch.setattr(lc, "calls_today", lambda pid: row["daily_soft_cap"] - 1)
    assert lc.over_daily_cap(PID) is False
    monkeypatch.setattr(lc, "calls_today", lambda pid: row["daily_soft_cap"])
    assert lc.over_daily_cap(PID) is True


def test_gate_cost_cap_refusal_ends_the_run(harness, monkeypatch):
    sent = []

    def refusing_gate(prompt, **kw):
        sent.append(kw)
        raise RuntimeError("COST_CAP_EXCEEDED: {'scope': 'process'}")

    monkeypatch.setattr(lc, "gate_and_generate", refusing_gate)
    out = gsr.run(apply=True)
    assert len(sent) == 1  # first refusal stops the run; the other two stops are not attempted
    assert out["refused"].startswith("COST_CAP_EXCEEDED")
    assert out["errors"] == 0


def test_gate_refuses_unregistered_and_other_lanes(monkeypatch):
    """should_call over the committed row: grok allowed, chatgpt/deepseek refused (no DB: config stubbed)."""
    row = _registry_row()
    cfg = {"registered": True, "allowed_lanes": lc._allowed_lanes_from_registry(row), "mode": "automated"}
    monkeypatch.setattr(lc, "get_process_config", lambda pid: cfg)
    assert lc.should_call(PID, "grok")["allow"] is True
    for other in ("chatgpt", "deepseek-flash", "fast", "local"):
        assert lc.should_call(PID, other) == {"allow": False, "reason": "POLICY_NOT_ALLOWED",
                                              "mode": "automated", "process_id": PID}


# ── no fallback model ────────────────────────────────────────────────────────────────────────────────


def test_failure_is_logged_and_nothing_goes_to_another_lane(harness, monkeypatch, capsys):
    lanes = []

    def failing(prompt, lane="grok", timeout=90, **kw):
        lanes.append(lane)
        raise RuntimeError("grok OAuth lane unavailable — check grok-oauth-proxy")

    monkeypatch.setattr(llm_lane, "generate", failing)
    out = gsr.run(apply=True)
    assert lanes == ["grok", "grok", "grok"]
    assert out["errors"] == 3 and out["refused"] is None
    assert all(r["status"].startswith("error:") for r in out["reviewed"])
    assert "no fallback" in capsys.readouterr().err
    assert harness.c.executed[1:] == []


# ── per-run cap and plan ─────────────────────────────────────────────────────────────────────────────


def test_limit_is_clamped_to_max_stops_per_run(harness, monkeypatch):
    monkeypatch.setattr(gsr, "_held_stops", lambda: _stops(40))
    monkeypatch.setattr(llm_lane, "generate", lambda *a, **k: GOOD)
    out = gsr.run(apply=False, limit=50)
    assert out["per_run_cap"] == 12
    assert len(out["reviewed"]) == 12
    assert out["skipped_over_per_run_cap"] == 28


def test_plan_calls_no_model(harness, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("plan must not call a model")

    monkeypatch.setattr(llm_lane, "generate", boom)
    monkeypatch.setattr(lc, "gate_and_generate", boom)
    monkeypatch.setattr(gsr, "budget_state", lambda: {"registered": True, "calls_today": 28, "daily_call_cap": 30})
    out = gsr.plan()
    assert out["mode"] == "PLAN"
    assert out["would_send_calls"] == 2  # 30 - 28 remaining today
    assert out["refused"] is None


# ── registry, routing, bridge map, caps sync (AGENTS.md §9.2) ────────────────────────────────────────


def test_registry_row_is_grok_only_capped_and_advisory():
    row = _registry_row()
    assert row["allowed_lanes"] == ["grok"]
    assert row["fallback_allowed"] is False and row["advisory_only"] is True and row["tools_allowed"] is False
    assert row["daily_soft_cap"] == 30 and row["max_stops_per_run"] == 12
    assert row["daily_cost_cap_usd"] > 0
    assert row["default_mode"] == "automated"


def test_routing_row_has_no_fallback_lane():
    pol = json.loads((ROOT / "config" / "llm_routing_policy.json").read_text())
    r = pol["policies"]["default"]["processes"][PID]
    # The routing schema needs three lanes; every one is grok, so no other model can answer.
    assert {r[k]["provider"] for k in ("primary", "secondary", "fallback")} == {"grok"}
    assert "reasoning_lane" not in r and "transport_failover" not in r
    assert r["on_health_unknown"] == "refuse"


def test_bridge_maps_and_caps_sync_carry_the_process():
    from lib import governed_process_routes as gpr
    assert gpr.route_for_process(PID) == ("advisory_desk", PID)
    src = (ROOT / "scripts" / "lib" / "cio_governed_model_bridge.py").read_text()
    assert f'"{PID}": "{PID}",' in src
    caps = (ROOT / "scripts" / "sync_cio_process_caps.py").read_text()
    assert f'"{PID}": (0.05, 30),' in caps


def test_resume_packet_marker_is_in_the_script():
    """resume-operator.sh resumes L497 only when the served release's script carries this exact line."""
    src = (ROOT / "scripts" / "grok_stop_review.py").read_text()
    assert 'PROCESS_ID = "grok_stop_review"' in src
    assert "process_id=PROCESS_ID" in src
    assert "lane=lane, timeout=90)" not in src  # the ungated call is gone
