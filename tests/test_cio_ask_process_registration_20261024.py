"""Ask-CIO registration through real bridge/cap logic, fake transports and ledger.

COVERS = ["config/llm_process_registry.json", "config/llm_routing_policy.json",
          "scripts/lib/cio_governed_model_bridge.py", "scripts/lib/governed_process_routes.py",
          "scripts/sync_cio_process_caps.py", "scripts/lib/n8n_model_job.py"]
"""
from __future__ import annotations

import io
import json
import sys
import types
import urllib.request
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from tests.test_bridge_oauth_llm_step_20261014 import (
    FakeDeepSeek, FakeResp, Proxy, REGISTRY, ROOT, bridge, hermetic, ok_body, wire,
)
from lib import llm_consumption as lc
from scripts.lib import governed_process_routes as routes
from scripts import sync_cio_process_caps as sync

PID = "cio_ask_deep_research"
DEPTH = "cio_ask_deep_research_depth"
ANSWER = '{"summary":"No sourced merger evidence."}'


@contextmanager
def ledger(monkeypatch, *, projected=0.02, process_spent=0.0, global_spent=0.0):
    """Inject only persistence/pricing boundaries; execute the real cap checker."""
    calls = {"reserve": MagicMock(return_value=4242), "settle": MagicMock(), "log": MagicMock()}

    def config(pid):
        row = dict(REGISTRY.get(pid) or {})
        return dict(row, process_id=pid, registered=bool(row), mode=row.get("default_mode"))

    monkeypatch.setattr(lc, "get_process_config", config)
    monkeypatch.setattr(lc, "ledger_paid_usd_today", lambda pid, **kw: global_spent if pid is None else process_spent)
    monkeypatch.setattr(lc, "reserve_projected_cost", calls["reserve"])
    monkeypatch.setattr(lc, "settle_reservation", calls["settle"])
    monkeypatch.setattr(lc, "log_call", calls["log"])
    monkeypatch.setattr(lc, "calibrated_projected_usd", lambda *a, **kw: {"projected_usd": projected, "basis": "fixture"})
    monkeypatch.setattr("lib.consumption_run_manual.projected_max_cost_usd", lambda **kw: projected)
    monkeypatch.setattr("scripts.lib.llm_lane_reservation.load_lane_floors", lambda: {})
    monkeypatch.setenv("LLM_GLOBAL_DAILY_USD_CAP", "2.0")
    monkeypatch.setattr(bridge, "GLOBAL_DAILY_USD_CAP", "2.0")
    yield calls


def call(**kw):
    return bridge.execute_governed_call(
        [{"role": "user", "content": "Public sourced evidence only."}],
        process_id=PID, response_format={"type": "json_object"},
        request_id="ask-fixture-answer-v1", max_tokens=512, **kw,
    )


def transports(monkeypatch, grok_status=200, chat_status=200):
    grok = Proxy("grok", FakeResp(grok_status, ok_body(ANSWER, "grok-fixture")))
    chat = Proxy("chatgpt", FakeResp(chat_status, ok_body(ANSWER, "chatgpt-fixture")))
    ds = FakeDeepSeek(ANSWER)
    wire(monkeypatch, grok, chat, ds)
    return grok, chat, ds


def test_registration_is_narrow_manual_and_both_maps_share_one_process():
    row = REGISTRY[PID]
    assert row["default_mode"] == "manual"
    assert row["daily_cost_cap_usd"] == 5.0 and row["daily_soft_cap"] == 30
    assert row["deepseek_allowed_policies"] == ["FAST", "PRO_THINK"]
    assert set(row["allowed_lanes"]) == {"grok", "chatgpt", "fast", "deepseek-flash", "pro_think"}
    assert row["tools_allowed"] is False and row["advisory_only"] is True
    assert sync.CAPS[PID] == (5.0, 30)
    for task in (PID, DEPTH):
        assert bridge.resolve_caller("advisory_desk", task_type=task) == PID
        assert routes.CALLER_TASK_PROCESS_MAP["advisory_desk"][task] == PID
    assert routes.route_for_process(PID) == ("advisory_desk", PID)
    policy = json.loads((ROOT / "config/llm_routing_policy.json").read_text())["policies"]["default"]["processes"][PID]
    assert policy["route_profile"] == "n8n_oauth_first"
    assert [policy[k]["provider"] for k in ("primary", "secondary", "fallback")] == ["grok", "chatgpt", "deepseek"]
    assert [policy[k]["policy"] for k in ("primary", "secondary", "fallback")] == ["FAST"] * 3
    assert policy["reasoning_lane"] == {"provider": "deepseek", "policy": "PRO_THINK"}
    assert policy["cost_ceiling_usd"] == 0.5


@pytest.mark.parametrize("grok_status,chat_status,provider", [(200, 200, "grok"), (500, 200, "chatgpt"), (500, 500, "deepseek")])
def test_registered_process_walks_existing_route_with_real_cap_check(monkeypatch, grok_status, chat_status, provider):
    grok, chat, ds = transports(monkeypatch, grok_status, chat_status)
    with ledger(monkeypatch) as seen:
        out = call()
    assert "error" not in out, out.get("error")
    meta = out["_tradeai"]
    assert meta["process_id"] == PID and meta["provider"] == provider
    assert meta["governance_pass"] is True and meta["reservation_id"] == 4242
    assert meta["reasoning_tier"] == "standard"
    assert len(grok.calls) == 1
    assert len(chat.calls) == (provider != "grok")
    assert len(ds.calls) == (provider == "deepseek")
    assert seen["reserve"].call_args.args[0] == PID
    assert seen["settle"].call_count == 1


def test_server_depth_uses_declared_reasoning_lane_and_same_bucket(monkeypatch):
    grok, chat, ds = transports(monkeypatch)
    with ledger(monkeypatch) as seen:
        out = call(**bridge.caller_reasoning_options("advisory_desk", DEPTH))
    assert "error" not in out, out.get("error")
    assert out["_tradeai"]["provider"] == "deepseek"
    assert out["_tradeai"]["reasoning_tier"] == "high"
    assert out["_tradeai"]["routing_decision"]["requested_policy"] == "PRO_THINK"
    assert len(ds.calls) == 1 and grok.calls == [] and chat.calls == []
    assert seen["reserve"].call_args.args[0] == PID


@pytest.mark.parametrize("params,scope", [({"process_spent": 4.99}, "process"), ({"global_spent": 1.99}, "global")])
def test_process_and_unchanged_global_cap_refuse_before_any_provider(monkeypatch, params, scope):
    grok, chat, ds = transports(monkeypatch)
    with ledger(monkeypatch, **params) as seen:
        decision = lc.check_cost_cap(PID, projected_usd=0.02, global_cap=2.0)
        out = call()
    assert decision["allow"] is False and decision["scope"] == scope
    assert out["error"]["code"] == "COST_CAP_EXCEEDED"
    assert seen["reserve"].call_count == 0
    assert grok.calls == [] and chat.calls == [] and ds.calls == []


@pytest.mark.parametrize("projected,budget", [(0.51, None), (0.02, {"cost_ceiling_usd": 0.01})])
def test_per_call_ceiling_and_narrower_question_remainder_refuse_before_reservation(monkeypatch, projected, budget):
    grok, chat, ds = transports(monkeypatch)
    with ledger(monkeypatch, projected=projected) as seen:
        out = call(budget=budget)
    assert out["error"]["code"] == "COST_CEILING_EXCEEDED"
    assert seen["reserve"].call_count == 0
    assert grok.calls == [] and chat.calls == [] and ds.calls == []


def test_manual_intent_and_request_counter_remain_separate_from_dollar_caps(monkeypatch):
    with ledger(monkeypatch):
        assert lc.should_call(PID, "grok")["reason"] == "manual_mode"
        assert lc.should_call(PID, "grok", manual_trigger=True)["allow"] is True
        assert lc.should_call(PID, "pro", manual_trigger=True)["reason"] == "POLICY_NOT_ALLOWED"
        assert lc.should_call("unregistered-ask-fixture", "grok", manual_trigger=True)["reason"] == "PROCESS_NOT_REGISTERED"
        monkeypatch.setattr(lc, "calls_today", lambda pid: 30)
        assert lc.over_daily_cap(PID) is True
        monkeypatch.setattr(lc, "calls_today", lambda pid: 29)
        assert lc.over_daily_cap(PID) is False


def test_unknown_process_and_forbidden_tools_never_reach_reservation(monkeypatch):
    grok, chat, ds = transports(monkeypatch)
    with ledger(monkeypatch) as seen:
        unknown = bridge.execute_governed_call(
            [{"role": "user", "content": "Public fact"}], process_id="unregistered-ask-fixture",
        )
        tools = call(tools=[{"type": "function", "function": {"name": "external_tool"}}])
    assert unknown["error"]["code"] == "PROCESS_NOT_REGISTERED"
    assert tools["error"]["code"] == "TOOL_NOT_ALLOWED"
    assert seen["reserve"].call_count == 0
    assert grok.calls == [] and chat.calls == [] and ds.calls == []


def test_counter_refusal_at_reservation_stays_typed_and_spends_nothing(monkeypatch):
    grok, chat, ds = transports(monkeypatch)
    with ledger(monkeypatch) as seen:
        seen["reserve"].side_effect = RuntimeError("COST_CAP_EXCEEDED: request count reached")
        out = call(**bridge.caller_reasoning_options("advisory_desk", DEPTH))
    assert out["error"]["code"] == "COST_CAP_EXCEEDED" and out["error"]["status"] == 429
    assert seen["reserve"].call_args.args[0] == PID
    assert seen["settle"].call_count == 0
    assert grok.calls == [] and chat.calls == [] and ds.calls == []


def test_cap_sync_dry_run_never_imports_database(monkeypatch, capsys):
    sentinel = types.ModuleType("db_adapter")
    sentinel._execute = lambda *a, **kw: pytest.fail("dry run reached DB")
    monkeypatch.setitem(sys.modules, "db_adapter", sentinel)
    assert sync.main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert f"would upsert {PID}: cost=5.0 soft=30" in output
    assert "Ask-CIO new-row mode=manual; existing-row mode unchanged" in output


def test_cap_sync_new_process_is_manual_without_changing_conflict_mode(monkeypatch):
    writes = []
    fake = types.ModuleType("db_adapter")

    def execute(sql, params=None, **kw):
        writes.append((sql, params, kw))
        return []

    fake._execute = execute
    monkeypatch.setitem(sys.modules, "db_adapter", fake)
    assert sync.main([]) == 0  # Only this injected object receives SQL; no driver exists in this fixture.
    inserts = [(sql, params) for sql, params, kw in writes if sql.lstrip().startswith("INSERT")]
    row = next((sql, params) for sql, params in inserts if params[0] == PID)
    assert row[1][3:6] == ("manual", 30, 5.0)
    assert "mode =" not in row[0].split("ON CONFLICT", 1)[1]
    assert all(params[3] == "automated" for _, params in inserts if params[0] != PID)
    assert writes[-1][1] == (list(sync.CAPS),) and writes[-1][2] == {"fetch": "all"}


def test_selected_sync_touches_only_ask_and_reads_back_only_ask(monkeypatch):
    writes = []
    fake = types.ModuleType("db_adapter")
    fake._execute = lambda sql, params=None, **kw: writes.append((sql, params, kw)) or []
    monkeypatch.setitem(sys.modules, "db_adapter", fake)
    assert sync.main(["--process-id", PID]) == 0
    assert len(writes) == 2
    assert writes[0][0].lstrip().startswith("INSERT")
    assert writes[0][1][0] == PID and writes[0][1][3:6] == ("manual", 30, 5.0)
    assert writes[1][0].lstrip().startswith("SELECT")
    assert writes[1][1] == ([PID],) and writes[1][2] == {"fetch": "all"}


def test_selected_dry_run_is_one_row_and_no_db(monkeypatch, capsys):
    fake = types.ModuleType("db_adapter")
    fake._execute = lambda *a, **kw: pytest.fail("selected dry run reached DB")
    monkeypatch.setitem(sys.modules, "db_adapter", fake)
    assert sync.main(["--dry-run", "--process-id", PID]) == 0
    out = capsys.readouterr().out
    assert out.count("would upsert") == 1 and f"would upsert {PID}" in out
    assert "mode=manual" in out


def test_unknown_selected_process_refuses_before_db(monkeypatch):
    fake = types.ModuleType("db_adapter")
    fake._execute = lambda *a, **kw: pytest.fail("unknown process reached DB")
    monkeypatch.setitem(sys.modules, "db_adapter", fake)
    with pytest.raises(SystemExit) as err:
        sync.main(["--process-id", "unregistered-ask-fixture"])
    assert err.value.code == 2


def handler_request(monkeypatch, task, body):
    """Real HTTP handler parsing with in-memory streams, no socket/auth/DB/store."""
    ring = types.ModuleType("memory_ring2")
    ring.check = lambda *a, **kw: None
    ring.research_class = lambda *a: False
    ring.MemoryContextRequired = type("MemoryContextRequired", (Exception,), {})
    monkeypatch.setitem(sys.modules, "memory_ring2", ring)
    seen = []
    monkeypatch.setattr(bridge, "execute_governed_call", lambda messages, **kw: seen.append(kw) or {"choices": []})
    handler = object.__new__(bridge.GovernedBridgeHandler)
    raw = json.dumps(body).encode()
    handler.path = "/v1/chat/completions"
    handler.headers = {bridge.AUTH_HEADER: "advisory_desk", "X-TradeAI-Task-Type": task, "Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    handler._caller_auth_admits = lambda *a: True
    responses = []
    handler._send_json = lambda status, payload: responses.append((status, payload))
    handler._send_error = lambda status, code, detail: responses.append((status, {"error": code}))
    handler.do_POST()
    return seen, responses


@pytest.mark.parametrize("task,tier", [(PID, None), (DEPTH, "high")])
def test_only_server_mapped_task_controls_depth_not_client_overrides(monkeypatch, task, tier):
    seen, responses = handler_request(monkeypatch, task, {
        "messages": [{"role": "user", "content": "Public fact"}], "request_id": "ask-http-fixture",
        "model": "arbitrary-client-model", "provider": "arbitrary-client-provider",
        "policy": "PRO", "reasoning_tier": "high" if tier is None else "standard",
    })
    assert responses[0][0] == 200 and len(seen) == 1
    assert seen[0]["process_id"] == PID and seen[0].get("reasoning_tier") == tier
    assert "model" not in seen[0] and "provider" not in seen[0] and "policy" not in seen[0]


def test_client_process_injection_is_rejected_and_unrelated_task_has_no_depth(monkeypatch):
    seen, responses = handler_request(monkeypatch, DEPTH, {
        "messages": [{"role": "user", "content": "Public fact"}], "process_id": "another-process",
    })
    assert responses == [(403, {"error": "PROCESS_ID_REJECTED"})] and seen == []
    assert bridge.caller_reasoning_options("advisory_desk", "operator_reply") == {}
    assert bridge.caller_reasoning_options("maria", DEPTH) == {}


def test_existing_client_helper_emits_only_server_task_and_stable_identity(monkeypatch):
    from lib.n8n_model_job import bridge_governed_call
    captured = []
    payload = {"_tradeai": {"governance_pass": True, "process_id": PID, "provider": "deepseek", "reservation_id": 4242}}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def fake_open(req, **kw):
        captured.append(req)
        return Response(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    out = bridge_governed_call(
        [{"role": "user", "content": "Public fact"}], process_id=PID, caller="advisory_desk",
        task_type=DEPTH, request_id="ask-answer-fixture", max_tokens=1500, timeout_s=1,
        context_id="ctx_0123456789abcdef",
    )
    assert out == payload
    req = captured[0]
    headers = {k.lower(): v for k, v in req.header_items()}
    assert headers["x-tradeai-task-type"] == DEPTH and headers["x-tradeai-agent"] == "advisory_desk"
    assert headers["x-tradeai-context-id"] == "ctx_0123456789abcdef"
    body = json.loads(req.data)
    assert body["request_id"] == "ask-answer-fixture" and body["model"] == "tradeai_governed"
    assert not {"process_id", "reasoning_tier", "provider", "context_id"} & body.keys()


@pytest.mark.parametrize("context", [None, {"context_id": "ctx_fedcba9876543210"}])
def test_helper_inherits_existing_context_or_keeps_it_missing(monkeypatch, context):
    from lib import intelligence_client as ic
    from lib.n8n_model_job import bridge_governed_call

    captured = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def fake_open(req, **kw):
        captured.append(req)
        return Response(b'{}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    token = ic._CURRENT_CTX.set(context)
    try:
        bridge_governed_call([], process_id=PID, caller="advisory_desk", task_type=PID)
    finally:
        ic._CURRENT_CTX.reset(token)
    headers = {k.lower(): v for k, v in captured[0].header_items()}
    if context is None:
        assert "x-tradeai-context-id" not in headers
    else:
        assert headers["x-tradeai-context-id"] == context["context_id"]


@pytest.mark.parametrize("context", ["", "ctx_safe\r\nX-Forged: yes", "x" * 257, {"context_id": "bad"}])
def test_unsafe_context_never_reaches_transport(monkeypatch, context):
    from lib.n8n_model_job import bridge_governed_call

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: pytest.fail("unsafe context reached transport"))
    out = bridge_governed_call([], process_id=PID, caller="advisory_desk", task_type=PID, context_id=context)
    assert out["error"]["code"] == "MEMORY_CONTEXT_INVALID"
    assert out["governance_pass"] is False


def test_failed_context_reader_does_not_forge_id_or_hide_refusal(monkeypatch):
    from lib import intelligence_client as ic
    from lib.n8n_model_job import bridge_governed_call

    def failed():
        raise RuntimeError("sensitive internal detail")

    monkeypatch.setattr(ic, "current_context_id", failed)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: pytest.fail("unavailable context reached transport"))
    out = bridge_governed_call([], process_id=PID, caller="advisory_desk", task_type=PID)
    assert out["error"]["code"] == "MEMORY_CONTEXT_UNAVAILABLE"
    assert out["governance_pass"] is False and "sensitive" not in json.dumps(out)
