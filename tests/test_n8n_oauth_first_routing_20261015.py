"""n8n LLM processes route OAuth first; DeepSeek on failure or when the answer needs higher reasoning (2026-10-15).

Operator decision 2026-10-15, verbatim: "in terms of n8n, then, we should try OAuth first. And if OAuth fails or if
the answer needs higher reasoning, then we go to DeepSeek."

Pinned here, through the REAL cio_governed_model_bridge.execute_governed_call (route walk, output gate, caps,
reservation, settlement) with fake transports:
  * OAuth success -> no DeepSeek call; grok fails -> chatgpt; both OAuth fail -> DeepSeek; OAuth not enabled on the
    host -> DeepSeek (grok/chatgpt recorded no_transport, never called);
  * a schema-invalid or empty OAuth answer is a failed lane: the walk moves on and DeepSeek serves;
  * reasoning_tier high (registry row, or a template's tier in process) -> the DeepSeek reasoning lane (PRO_THINK,
    thinking on) first, OAuth as its fallback; a rejected paid answer is still metered;
  * a schema-valid OAuth answer below escalate_below_confidence -> exactly ONE DeepSeek escalation on the same
    request lineage (<rid>:esc1), its own reservation; over the daily cap or the per-call ceiling -> the OAuth answer
    returns flagged escalation_skipped_cap; never a second escalation, even when the escalated answer is low too;
  * the route decision lands in the llm_step audit row and the model-job receipt;
  * registry allowed_lanes and the routing policy agree for every N8nCoordination process and hermes_tag_engine.

Hermetic: the fixtures of tests/test_bridge_oauth_llm_step_20261014.py (tmp journal/audit paths, canary bind with
fake transports, health stubbed, ledger patched). No network, DB, key, token store or paid call.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from tests.test_bridge_oauth_llm_step_20261014 import (  # noqa: F401 — `hermetic` is autouse: it must be in scope
    DIAG,
    REGISTRY,
    ROOT,
    VALID,
    FakeDeepSeek,
    FakeResp,
    Proxy,
    audit_rows,
    bridge,
    hermetic,
    ok_body,
    ot,
    step,
    step_request,
    wire,
)

from lib import n8n_model_job as mj  # noqa: E402

LOW = dict(VALID, confidence=0.3)
DEEP = dict(VALID, confidence=0.95, cause="reasoned cause")
ROUTING = json.loads((ROOT / "config" / "llm_routing_policy.json").read_text())["policies"]["default"]["processes"]
N8N_PROCESSES = sorted(r["id"] for r in REGISTRY.values() if r.get("category") == "N8nCoordination")
FABRIC_PROCESSES = ["hermes_tag_engine"]


@contextmanager
def ledger(monkeypatch, *, cap_allow=None, projected=0.002, reg_override=None):
    """The consumption ledger, patched. `cap_allow(n)` answers the n-th check_cost_cap (1 = the first call)."""
    led = {"reserve": MagicMock(side_effect=[4242, 4343, 4444]), "settle": MagicMock(), "log_call": MagicMock()}
    caps = {"n": 0}

    def cfg(pid):
        row = REGISTRY.get(pid) or {}
        return {
            "process_id": pid,
            "registered": bool(row),
            "mode": "automated",
            "allowed_lanes": row.get("allowed_lanes"),
            "deepseek_allowed_policies": [str(x).upper() for x in row.get("deepseek_allowed_policies") or []],
            "max_input_tokens": 12000,
            "max_output_tokens": 1024,
            "daily_soft_cap": 40,
            "daily_cost_cap_usd": 0.1,
        }

    def check(*_a, **_k):
        caps["n"] += 1
        ok = True if cap_allow is None else bool(cap_allow(caps["n"]))
        return {"allow": ok, "reason": None if ok else "PROCESS_DAILY_CAP"}

    monkeypatch.setattr("lib.llm_consumption.get_process_config", cfg)
    monkeypatch.setattr("lib.llm_consumption.reserve_projected_cost", led["reserve"])
    monkeypatch.setattr("lib.llm_consumption.settle_reservation", led["settle"])
    monkeypatch.setattr("lib.llm_consumption.check_cost_cap", check)
    monkeypatch.setattr(
        "lib.llm_consumption.calibrated_projected_usd", lambda *_a, **_k: {"projected_usd": projected, "basis": "t"}
    )
    monkeypatch.setattr("lib.llm_consumption.log_call", led["log_call"])
    monkeypatch.setattr("lib.llm_model_registry.reject_legacy_model_id", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "lib.llm_model_registry.estimate_usd_cost", lambda *_a, **_k: {"estimated_cost_usd": 0.0005, "cost_basis": "t"}
    )
    monkeypatch.setattr("lib.consumption_run_manual.validate_paid_cap_config", lambda *_a, **_k: None)
    monkeypatch.setattr("lib.consumption_run_manual.projected_max_cost_usd", lambda *_a, **_k: projected)
    if reg_override is not None:
        real = bridge.agent_gate.registry_row
        monkeypatch.setattr(
            bridge.agent_gate,
            "registry_row",
            lambda pid: dict(real(pid) or {}, **reg_override) if pid == DIAG else real(pid),
        )
    led["caps"] = caps
    yield led


class ScriptedDeepSeek(FakeDeepSeek):
    """FakeDeepSeek answering each call with the next scripted content (the last one repeats)."""

    def __init__(self, *contents: str) -> None:
        super().__init__(contents[0])
        self.contents = list(contents)

    def generate(self, messages, model_id, **kwargs):
        self.content = self.contents.pop(0) if len(self.contents) > 1 else self.contents[0]
        return super().generate(messages, model_id, **kwargs)


def grok_ok(answer) -> Proxy:
    body = answer if isinstance(answer, str) else json.dumps(answer)
    return Proxy("grok", FakeResp(200, ok_body(body, "grok-3-mini")))


def call(process_id: str = DIAG, request_id: str = "rid-n8n-1", **kw):
    return bridge.execute_governed_call(
        [{"role": "user", "content": "evidence"}],
        process_id=process_id,
        response_format={"type": "json_object"},
        max_tokens=512,
        request_id=request_id,
        **kw,
    )


def receipts(out) -> list[dict]:
    return (out.get("_tradeai") or {}).get("route_receipts") or (out.get("error") or {}).get("route_receipts") or []


def outcomes(out) -> list[tuple[str, str]]:
    return [(r["provider"], r["outcome"]) for r in receipts(out)]


def answer(out) -> dict:
    return json.loads(out["choices"][0]["message"]["content"])


# ── 1. default order: OAuth first ───────────────────────────────────────────────────────────────────────────────


def test_oauth_success_makes_no_deepseek_call(monkeypatch):
    grok, chat, ds = grok_ok(VALID), Proxy("chatgpt", FakeResp(500)), FakeDeepSeek("unused")
    wire(monkeypatch, grok, chat, ds)
    with ledger(monkeypatch) as led:
        out = call()
    assert "error" not in out, out.get("error")
    assert outcomes(out) == [("grok", "ok")] and chat.calls == [] and ds.calls == []
    meta = out["_tradeai"]
    assert meta["provider"] == "grok" and meta["escalation"] is None and meta["escalation_skipped_cap"] is False
    assert meta["reasoning_tier"] == "standard" and meta["routing_decision"]["route_profile"] == "n8n_oauth_first"
    # OAuth is $0 on its receipt; the reservation settles at its projection (spend accounting unchanged)
    assert meta["route_receipts"][0]["cost_basis"] == "free_oauth_unmetered"
    assert led["reserve"].call_count == 1 and led["settle"].call_args.args[1] is None


def test_grok_failure_falls_to_chatgpt(monkeypatch):
    grok = Proxy("grok", FakeResp(429, {}, {"Retry-After": "30"}))
    chat = Proxy("chatgpt", FakeResp(200, ok_body(json.dumps(VALID), "gpt-6.1-sol")))
    ds = FakeDeepSeek("unused")
    wire(monkeypatch, grok, chat, ds)
    with ledger(monkeypatch):
        out = call()
    assert outcomes(out) == [("grok", "rate_limited"), ("chatgpt", "ok")] and ds.calls == []
    assert out["_tradeai"]["provider"] == "chatgpt"


@pytest.mark.parametrize("grok_status,chat_status", [(401, 403), (502, 500)])
def test_both_oauth_lanes_fail_then_deepseek_serves(monkeypatch, grok_status, chat_status):
    grok, chat = Proxy("grok", FakeResp(grok_status)), Proxy("chatgpt", FakeResp(chat_status))
    ds = FakeDeepSeek(json.dumps(VALID))
    wire(monkeypatch, grok, chat, ds)
    with ledger(monkeypatch):
        out = call()
    assert "error" not in out, out.get("error")
    assert [p for p, _ in outcomes(out)] == ["grok", "chatgpt", "deepseek"] and outcomes(out)[-1][1] == "ok"
    if grok_status == 401:
        assert outcomes(out)[:2] == [("grok", "auth_failure"), ("chatgpt", "auth_failure")]
    assert len(ds.calls) == 1 and out["_tradeai"]["provider"] == "deepseek"
    assert out["_tradeai"]["route_receipts"][-1]["cost_usd"] == 0.0005  # DeepSeek metered


def test_oauth_not_enabled_on_host_goes_to_deepseek_without_error(monkeypatch):
    monkeypatch.delenv(ot.ENABLE_ENV, raising=False)
    grok, chat, ds = (
        grok_ok(VALID),
        Proxy("chatgpt", FakeResp(200, ok_body("{}", "c"))),
        FakeDeepSeek(json.dumps(VALID)),
    )
    wire(monkeypatch, grok, chat, ds)
    with ledger(monkeypatch):
        out = call()
    assert "error" not in out, out.get("error")
    assert outcomes(out) == [("grok", "no_transport"), ("chatgpt", "no_transport"), ("deepseek", "ok")]
    assert grok.calls == [] and chat.calls == [] and len(ds.calls) == 1


# ── 2. invalid OAuth output is a failed lane ───────────────────────────────────────────────────────────────────


def test_schema_invalid_oauth_answer_falls_to_deepseek(monkeypatch):
    grok = grok_ok({"cause": "missing every other key"})
    chat = Proxy("chatgpt", FakeResp(200, ok_body("not json at all", "gpt-6.1-sol")))
    ds = FakeDeepSeek(json.dumps(VALID))
    wire(monkeypatch, grok, chat, ds)
    with ledger(monkeypatch) as led:
        out = call()
    assert "error" not in out, out.get("error")
    assert outcomes(out) == [("grok", "output_invalid"), ("chatgpt", "output_invalid"), ("deepseek", "ok")]
    rs = receipts(out)
    assert rs[0]["detail"].startswith("OUTPUT_SCHEMA_INVALID") and rs[1]["detail"].startswith("OUTPUT_INVALID_JSON")
    assert rs[0]["cost_basis"] == "free_oauth_unmetered" and len(ds.calls) == 1
    assert answer(out) == VALID and led["settle"].call_args.args[1] == 0.0005


def test_empty_oauth_answer_falls_through(monkeypatch):
    grok, chat = grok_ok(""), Proxy("chatgpt", FakeResp(500))
    ds = FakeDeepSeek(json.dumps(VALID))
    wire(monkeypatch, grok, chat, ds)
    with ledger(monkeypatch):
        out = call()
    # the OAuth transport already types an empty body (invalid_response); either way the lane failed and the walk moved on
    assert outcomes(out)[0] in (("grok", "invalid_response"), ("grok", "output_invalid"))
    assert outcomes(out)[-1] == ("deepseek", "ok")


def test_walk_output_check_refuses_an_empty_answer():
    empty = {"choices": [{"message": {"role": "assistant", "content": ""}}]}
    assert bridge.walk_output_refusal(DIAG, empty, REGISTRY[DIAG])["code"] == "OUTPUT_EMPTY"
    assert bridge.walk_output_refusal(DIAG, {"choices": []}, REGISTRY[DIAG])["code"] == "OUTPUT_EMPTY"
    ok = {"choices": [{"message": {"role": "assistant", "content": json.dumps(VALID)}}]}
    assert bridge.walk_output_refusal(DIAG, ok, REGISTRY[DIAG]) is None


def test_every_lane_invalid_is_still_a_typed_output_refusal(monkeypatch):
    bad = json.dumps({"cause": "x"})
    wire(monkeypatch, grok_ok(bad), Proxy("chatgpt", FakeResp(200, ok_body(bad, "c"))), FakeDeepSeek(bad))
    with ledger(monkeypatch):
        out = call()
    assert out["error"]["code"] == "OUTPUT_SCHEMA_INVALID"
    walked = out["routing_decision"]["route_receipts"]
    assert [r["outcome"] for r in walked] == ["output_invalid"] * 3


# ── 3a. declared reasoning tier ────────────────────────────────────────────────────────────────────────────────


def test_reasoning_tier_high_routes_deepseek_reasoning_first(monkeypatch):
    grok, chat, ds = grok_ok(VALID), Proxy("chatgpt", FakeResp(500)), FakeDeepSeek(json.dumps(DEEP))
    wire(monkeypatch, grok, chat, ds)
    with ledger(monkeypatch, reg_override={"reasoning_tier": "high"}):
        out = call()
    assert "error" not in out, out.get("error")
    assert outcomes(out) == [("deepseek", "ok")] and grok.calls == [] and chat.calls == []
    meta = out["_tradeai"]
    assert meta["reasoning_tier"] == "high" and meta["requested_policy"] == "PRO_THINK"
    assert meta["routing_decision"]["reason"] == "reasoning_tier_high" and receipts(out)[0]["lane"] == "reasoning"
    assert ds.calls[0]["thinking"] == "enabled" and ds.calls[0]["reasoning_effort"] == "high"


def test_reasoning_tier_high_falls_back_to_oauth(monkeypatch):
    grok, chat, ds = grok_ok(VALID), Proxy("chatgpt", FakeResp(500)), FakeDeepSeek(json.dumps({"cause": "x"}))
    wire(monkeypatch, grok, chat, ds)
    with ledger(monkeypatch, reg_override={"reasoning_tier": "high"}) as led:
        out = call()
    assert "error" not in out, out.get("error")
    assert outcomes(out)[:2] == [("deepseek", "output_invalid"), ("grok", "ok")]
    # the rejected DeepSeek answer was billed: metered on its receipt and settled, OAuth stays $0
    assert receipts(out)[0]["cost_usd"] == 0.0005 and led["settle"].call_args.args[1] == 0.0005
    # a paid lane is never tried twice in one call: the DeepSeek FAST fallback is not attempted
    assert len(ds.calls) == 1


def test_template_tier_high_is_honoured_in_process(monkeypatch):
    grok, ds = grok_ok(VALID), FakeDeepSeek(json.dumps(DEEP))
    wire(monkeypatch, grok, Proxy("chatgpt", FakeResp(500)), ds)
    with ledger(monkeypatch):
        out = call(reasoning_tier="high")
    assert outcomes(out) == [("deepseek", "ok")] and grok.calls == []
    with ledger(monkeypatch):
        out = call(
            request_id="rid-n8n-2", reasoning_tier="bogus"
        )  # an unknown tier is ignored: the registry's standard tier applies
    assert outcomes(out)[0][0] == "grok"


# ── 3b. escalation of a low-confidence OAuth answer ────────────────────────────────────────────────────────────


def test_low_confidence_oauth_answer_escalates_exactly_once(monkeypatch):
    grok, chat, ds = grok_ok(LOW), Proxy("chatgpt", FakeResp(500)), FakeDeepSeek(json.dumps(DEEP))
    wire(monkeypatch, grok, chat, ds)
    with ledger(monkeypatch) as led:
        out = call()
    assert "error" not in out, out.get("error")
    assert len(grok.calls) == 1 and chat.calls == [] and len(ds.calls) == 1
    assert ds.calls[0]["client_request_id"] == "rid-n8n-1:esc1" and ds.calls[0]["thinking"] == "enabled"
    meta = out["_tradeai"]
    esc = meta["escalation"]
    assert esc["schema"] == "BridgeEscalation@v1" and esc["outcome"] == "escalated"
    assert esc["reason"] == "low_confidence:confidence=0.3<0.7" and esc["parent_request_id"] == "rid-n8n-1"
    assert esc["oauth_answer"]["provider"] == "grok" and esc["reservation_id"] == 4343
    assert meta["provider"] == "deepseek" and meta["requested_policy"] == "PRO_THINK" and answer(out) == DEEP
    assert meta["cost_estimate"] == 0.0005 and meta["routing_decision"]["served_lane"] == "reasoning"
    assert [(r["provider"], r["outcome"], r.get("attempt")) for r in receipts(out)] == [
        ("grok", "ok", None),
        ("deepseek", "ok", "escalation"),
    ]
    # two reservations: the OAuth call's (settled at projection) and the escalation's (metered)
    assert led["reserve"].call_count == 2
    assert led["reserve"].call_args_list[1].kwargs["metadata"]["request_id"] == "rid-n8n-1:esc1"
    assert [c.args[1] for c in led["settle"].call_args_list] == [None, 0.0005]


def test_confident_oauth_answer_is_not_escalated(monkeypatch):
    ds = FakeDeepSeek("unused")
    wire(monkeypatch, grok_ok(dict(VALID, confidence=0.7)), Proxy("chatgpt", FakeResp(500)), ds)
    with ledger(monkeypatch):
        out = call()
    assert ds.calls == [] and out["_tradeai"]["escalation"] is None


def test_never_more_than_one_escalation(monkeypatch):
    ds = ScriptedDeepSeek(json.dumps(dict(LOW, confidence=0.1)), json.dumps(DEEP))
    wire(monkeypatch, grok_ok(LOW), Proxy("chatgpt", FakeResp(500)), ds)
    with ledger(monkeypatch) as led:
        out = call()
    assert len(ds.calls) == 1 and led["reserve"].call_count == 2
    assert out["_tradeai"]["escalation"]["outcome"] == "escalated" and answer(out)["confidence"] == 0.1


def test_escalation_over_daily_cap_returns_oauth_answer_flagged(monkeypatch):
    ds = FakeDeepSeek(json.dumps(DEEP))
    wire(monkeypatch, grok_ok(LOW), Proxy("chatgpt", FakeResp(500)), ds)
    with ledger(monkeypatch, cap_allow=lambda n: n == 1) as led:
        out = call()
    assert "error" not in out, out.get("error")
    meta = out["_tradeai"]
    assert ds.calls == [] and led["reserve"].call_count == 1
    assert meta["escalation_skipped_cap"] is True and meta["escalation"]["outcome"] == "escalation_skipped_cap"
    assert meta["escalation"]["detail"].startswith("daily_cap") and meta["provider"] == "grok"
    assert answer(out) == LOW


def test_escalation_over_per_call_ceiling_is_skipped(monkeypatch):
    # The escalation's projection (0.06) is over the diagnosis row's per-call cost_ceiling_usd (0.05).
    ds = FakeDeepSeek(json.dumps(DEEP))
    wire(monkeypatch, grok_ok(LOW), Proxy("chatgpt", FakeResp(500)), ds)
    real = bridge.agent_gate.cost_ceiling_refusal
    seen = {"n": 0}

    def ceiling(policy, projected):
        seen["n"] += 1  # the 1st check is the main call's (passes), the 2nd the escalation's (refused)
        return real(policy, 0.06 if seen["n"] >= 2 else projected)

    with ledger(monkeypatch):
        monkeypatch.setattr(bridge.agent_gate, "cost_ceiling_refusal", ceiling)
        out = call()
    assert ds.calls == [] and out["_tradeai"]["escalation"]["detail"] == "per_call_ceiling"
    assert out["_tradeai"]["escalation_skipped_cap"] is True


def test_reservation_cap_refusal_is_skipped_cap(monkeypatch):
    ds = FakeDeepSeek(json.dumps(DEEP))
    wire(monkeypatch, grok_ok(LOW), Proxy("chatgpt", FakeResp(500)), ds)
    with ledger(monkeypatch) as led:
        led["reserve"].side_effect = [4242, RuntimeError("COST_CAP_EXCEEDED: count cap")]
        out = call()
    assert ds.calls == [] and out["_tradeai"]["escalation"]["outcome"] == "escalation_skipped_cap"


def test_failed_escalation_keeps_the_oauth_answer(monkeypatch):
    ds = FakeDeepSeek(json.dumps({"cause": "invalid"}))
    wire(monkeypatch, grok_ok(LOW), Proxy("chatgpt", FakeResp(500)), ds)
    with ledger(monkeypatch) as led:
        out = call()
    assert "error" not in out, out.get("error")
    esc = out["_tradeai"]["escalation"]
    assert esc["outcome"] == "escalation_failed" and esc["detail"] == "output_invalid" and len(ds.calls) == 1
    assert out["_tradeai"]["provider"] == "grok" and answer(out) == LOW
    # the rejected escalation was billed and settled at its metered cost
    assert led["settle"].call_args_list[-1].args[1] == 0.0005


def test_typed_flag_escalates(monkeypatch):
    ds = FakeDeepSeek(json.dumps(DEEP))
    wire(monkeypatch, grok_ok(VALID), Proxy("chatgpt", FakeResp(500)), ds)
    with ledger(monkeypatch, reg_override={"escalate_on_values": {"action_id": ["suggest_only", "reap_orphan_run"]}}):
        out = call()
    assert len(ds.calls) == 1 and out["_tradeai"]["escalation"]["reason"] == "flag:action_id=reap_orphan_run"


def test_unit_escalation_reason():
    row = {"escalate_below_confidence": 0.7, "escalate_on_values": {"needs_escalation": ["higher_reasoning"]}}

    def resp(obj):
        return {"choices": [{"message": {"content": json.dumps(obj)}}]}

    assert bridge.escalation_reason(resp({"confidence": 0.69}), row) == "low_confidence:confidence=0.69<0.7"
    assert bridge.escalation_reason(resp({"confidence": 0.7}), row) is None
    assert bridge.escalation_reason(resp({"confidence": True}), row) is None
    assert bridge.escalation_reason(resp({"needs_escalation": "higher_reasoning"}), row) == (
        "flag:needs_escalation=higher_reasoning"
    )
    assert bridge.escalation_reason(resp({"confidence": 0.1}), {"escalate_below_confidence": None}) is None


# ── 4. the route decision is audited ───────────────────────────────────────────────────────────────────────────


def test_llm_step_audit_records_lanes_and_escalation(monkeypatch, hermetic):
    grok = grok_ok(dict(LOW, recommendation="NONE"))
    ds = FakeDeepSeek(json.dumps(DEEP))
    wire(monkeypatch, grok, Proxy("chatgpt", FakeResp(500)), ds)
    with ledger(monkeypatch):
        out = step.execute_llm_step(
            step_request(execution_id="exec-oauth-first-1"),
            allowed_processes=bridge.llm_step_processes_for("n8n_model_job"),
            governed_call=bridge.execute_governed_call,
        )
    assert out["status"] == "ok", out["refusal"]
    route = out["route"]
    assert route["escalated"] is True and route["escalation"]["reason"].startswith("low_confidence")
    assert [(lane["provider"], lane["outcome"]) for lane in route["lanes"]] == [("grok", "ok"), ("deepseek", "ok")]
    assert route["route_profile"] == "n8n_oauth_first" and route["reasoning_tier"] == "standard"
    rows = audit_rows(hermetic)
    assert len(rows) == 1 and rows[0]["route"] == route and rows[0]["provider"] == "deepseek"


def test_llm_step_passes_a_template_tier(monkeypatch, hermetic):
    tpls = mj.load_templates()
    tpls["lane_failure_diagnosis.v1"] = dict(tpls["lane_failure_diagnosis.v1"], reasoning_tier="high")
    ds = FakeDeepSeek(json.dumps(DEEP))
    grok = grok_ok(VALID)
    wire(monkeypatch, grok, Proxy("chatgpt", FakeResp(500)), ds)
    with ledger(monkeypatch):
        out = step.execute_llm_step(
            step_request(execution_id="exec-oauth-first-2"),
            allowed_processes=bridge.llm_step_processes_for("n8n_model_job"),
            governed_call=bridge.execute_governed_call,
            templates=tpls,
        )
    assert out["status"] == "ok", out["refusal"]
    assert grok.calls == [] and out["route"]["reasoning_tier"] == "high" and out["provider"] == "deepseek"


def test_template_tier_must_be_known():
    row = dict(mj.load_templates()["lane_failure_diagnosis.v1"], reasoning_tier="ultra")
    assert mj._template_problem(row) == "reasoning_tier must be standard or high"


# ── 5. registry and routing policy agree ───────────────────────────────────────────────────────────────────────


def test_n8n_processes_are_listed_and_route_oauth_first():
    assert N8N_PROCESSES == ["n8n_lane_failure_diagnosis", "n8n_material_digest_draft", "n8n_ops_summary_draft"]
    for pid in N8N_PROCESSES + FABRIC_PROCESSES:
        row = ROUTING[pid]
        assert [row[k]["provider"] for k in ("primary", "secondary", "fallback")] == ["grok", "chatgpt", "deepseek"]
        assert row["transport_failover"] is True and row["route_profile"] == "n8n_oauth_first", pid
        lane = row["reasoning_lane"]
        assert lane["provider"] == "deepseek" and lane["policy"] == "PRO_THINK"
        assert bridge.POLICY_RESOLUTION[lane["policy"]]["thinking"] == "enabled"
        reg = REGISTRY[pid]
        assert reg["reasoning_tier"] in bridge.REASONING_TIERS
        if reg.get("allowed_lanes") is not None:
            assert {"grok", "chatgpt", "fast", "deepseek-flash"} <= set(reg["allowed_lanes"]), pid
        if reg.get("deepseek_allowed_policies"):
            assert {"FAST", "PRO_THINK"} <= set(reg["deepseek_allowed_policies"]), pid
    assert REGISTRY[DIAG]["escalate_below_confidence"] == 0.7  # = n8n_failure_diagnosis.CONFIDENCE_MIN (V9 §6.4)


def test_registry_and_routing_agree_through_the_route_plan(monkeypatch):
    """No n8n row skips an OAuth lane for registry_lane_not_allowed (the #1755 finding for digest / ops summary)."""
    import lib.llm_consumption as lc

    for pid in N8N_PROCESSES + FABRIC_PROCESSES:
        cfg = {"allowed_lanes": lc._allowed_lanes_from_registry(REGISTRY[pid])}
        policy = {"provider": "grok", "requested_policy": "FAST", "routing_decision": {"lane_chosen": "primary"}}
        pols = [str(x).upper() for x in REGISTRY[pid].get("deepseek_allowed_policies") or []]
        plan = bridge.route_plan(pid, None, policy, pols, cfg)
        assert [(c["provider"], c["skip"]) for c in plan] == [("grok", None), ("chatgpt", None), ("deepseek", None)]
        high = bridge.route_plan(pid, None, policy, pols, cfg, reasoning_tier="high")
        assert [(c["lane"], c["policy_name"], c["skip"]) for c in high][0] == ("reasoning", "PRO_THINK", None)


def test_model_job_receipt_carries_the_route(monkeypatch, tmp_path):
    """The model-job path (n8n_model_job.run_model_job) records the bridge's route decision on its receipt."""
    store = tmp_path / "data" / "runtime"
    store.mkdir(parents=True)
    (store / "pack.json").write_text(json.dumps({"lane": "x"}))
    wire(monkeypatch, grok_ok(LOW), Proxy("chatgpt", FakeResp(500)), FakeDeepSeek(json.dumps(DEEP)))

    def governed_call(messages, *, process_id, response_format=None, request_id=None, task_type=None, **kw):
        return bridge.execute_governed_call(
            messages, process_id=process_id, response_format=response_format, request_id=request_id, max_tokens=512
        )

    job = {
        "correlation_id": "corr-oauth-first-1",
        "process_id": DIAG,
        "output_schema_id": "lane_failure_diagnosis/v1",
        "deadline": "2099-01-01T00:00:00+00:00",
        "artifact_ref": {"store": "data/runtime", "ref": "pack.json"},
        "template_id": "lane_failure_diagnosis.v1",
    }
    with ledger(monkeypatch):
        receipt = mj.run_model_job(job, governed_call=governed_call, root=tmp_path)
    assert receipt["state"] == "ARTIFACT_WRITTEN", (receipt["reason"], receipt["detail"])
    route = receipt["route"]
    assert route["escalated"] is True and route["served_provider"] == "deepseek"
    assert [(lane["provider"], lane["outcome"]) for lane in route["lanes"]] == [("grok", "ok"), ("deepseek", "ok")]
    assert route["escalation"]["request_id"] == "corr-oauth-first-1:esc1"
