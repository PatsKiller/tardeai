"""LQ-20261107-2565 ADDENDUM 2 — provider-exhausted breaker and automatic reroute.

Operator requirement (2026-11-12): "the system must know on its own that Grok is out and reroute to the
next provider." Measured before this: xAI answered 403 ``personal-team-blocked:spending-limit`` from
2026-11-10 10:35 ET; the proxy folded it into 502; nothing classified it; 2,284 calls failed over 54 h
(324 in the last 8 h, zero successes) because every caller retried into the same wall on its own.

Pins, in order:

* the shared breaker: N consecutive quota/5xx failures exhaust a provider; a timeout does not; a success
  clears it; the expiry is the probe (after it the provider is tried once more, and failing again
  re-exhausts it);
* ``gate_and_generate`` — the funnel every ``log_call`` caller reaches — skips an exhausted provider and
  routes to the next one in ``grok -> chatgpt -> deepseek``, logging requested vs executed provider;
* DeepSeek is only a candidate inside the operator's paid window; outside it, no DeepSeek call;
* with no provider left the call raises ``NO_PROVIDER_LEFT`` (UNKNOWN/error), never a fabricated answer;
* the grok proxy names an entitlement wall as 402/``entitlement_exhausted`` instead of an anonymous 502,
  and ``llm_lane`` keeps that body in the raised error so it reaches the ledger.

Hermetic: no database, no network, no proxy, no .env. The breaker state lives in a tmp file
(``PROVIDER_BREAKER_PATH``), the ledger is a dict, and every provider call is a stub.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import llm_lane  # noqa: E402
import scripts.lib.llm_consumption as lc  # noqa: E402
from lib import provider_breaker as pb  # noqa: E402
from lib import oauth_lane_status as ols  # noqa: E402

#: The ``lib.*`` submodules this file bound at import. A neighbour that drops ``lib.*`` from ``sys.modules`` at its
#: module teardown (test_lane_repair_ri_hermes_litmus_20261015) would otherwise make the code under test
#: re-import fresh copies at call time, so the ``ols``/``pb`` patches below would miss it (LQ-20261107-2704, D3).
#: The ``lib`` package itself is NOT pinned: ``import lib.x as y`` binds through the package attribute, and a stale
#: package would hand a test an old ``lib.x`` while the code under test resolves the current one.
_LIB_MODULES = {n: m for n, m in sys.modules.items() if n.startswith("lib.")}


@pytest.fixture(autouse=True)
def _pin_lib_modules(monkeypatch):
    for name, mod in _LIB_MODULES.items():
        monkeypatch.setitem(sys.modules, name, mod)

ET = ZoneInfo("America/New_York")
PROCESS = "topic_curator"  # registry lane_policy "either": grok + chatgpt
CFG = {
    "process_id": PROCESS, "process_name": "Topic Curator", "category": "Research",
    "mode": "automated", "allowed_lanes": ["grok", "chatgpt"],
    "deepseek_allowed_policies": [], "max_input_tokens": None, "max_output_tokens": None,
    "daily_soft_cap": None, "daily_cost_cap_usd": None, "registered": True,
    "anthropic_first": False, "local_only": False, "tools_allowed": False,
    "fallback_allowed": False, "advisory_only": True,
}
QUOTA_502 = "GROK_PROXY_402: Grok lane entitlement exhausted — spending-limit (out of credits)"


@pytest.fixture
def state(tmp_path, monkeypatch):
    """A private breaker file, so a test can never exhaust the host's real providers — and a private
    lane-cooldown file, so a simulated entitlement wall never hides the real grok lane."""
    p = tmp_path / "provider_breaker.json"
    monkeypatch.setenv("PROVIDER_BREAKER_PATH", str(p))
    monkeypatch.setattr(ols, "_COOLDOWN_FILE", tmp_path / "oauth_lane_cooldown.json")
    return p


# ── the breaker itself ────────────────────────────────────────────────────────────────────────────────


def test_three_consecutive_quota_failures_exhaust_the_provider(state):
    for i in range(3):
        pb.note_result("grok", ok=False, error=QUOTA_502, now=1000.0 + i)
    assert pb.is_exhausted("grok", now=1003.0) is True
    assert pb.is_exhausted("chatgpt", now=1003.0) is False  # one provider's wall is not another's
    entry = pb.read_state()["grok"]
    assert entry["kind"] == "quota" and entry["streak"] == 3
    assert entry["exhausted_until"] == pytest.approx(1002.0 + pb._probe_s(), abs=1.0)


def test_a_success_clears_the_provider(state):
    for i in range(2):
        pb.note_result("grok", ok=False, error="HTTP 502 Bad Gateway", now=1000.0 + i)
    assert pb.is_exhausted("grok", now=1002.0) is False  # below the threshold
    pb.note_result("grok", ok=True, now=1003.0)
    assert pb.read_state() == {}  # a success is proof: nothing is held against the provider
    pb.note_result("grok", ok=False, error="HTTP 502 Bad Gateway", now=1004.0)
    assert pb.is_exhausted("grok", now=1005.0) is False  # the streak restarted from one
    assert pb.read_state()["grok"]["streak"] == 1


def test_a_caller_timeout_does_not_exhaust_a_live_provider(state):
    for i in range(5):
        pb.note_result("grok", ok=False, error="HTTPSConnectionPool: Read timed out. (read timeout=40)",
                       now=1000.0 + i)
    assert pb.read_state() == {}  # LQ-20261107-978: a caller deadline is not a dead provider


def test_the_probe_window_reopens_the_provider_and_a_second_failure_re_exhausts_it(state):
    for i in range(3):
        pb.note_result("grok", ok=False, error=QUOTA_502, now=1000.0 + i)
    expiry = pb.exhausted_until("grok", now=1003.0)
    assert expiry is not None
    assert pb.is_exhausted("grok", now=expiry + 1) is False      # the probe is due: try it once
    pb.note_result("grok", ok=False, error=QUOTA_502, now=expiry + 1)
    assert pb.is_exhausted("grok", now=expiry + 2) is True       # still out: another full window


def test_a_probe_that_succeeds_clears_it(state):
    for i in range(3):
        pb.note_result("grok", ok=False, error=QUOTA_502, now=1000.0 + i)
    pb.note_result("grok", ok=True, now=5000.0)
    assert pb.read_state() == {}


def test_deepseek_candidates_use_the_operator_paid_window():
    assert pb.deepseek_in_window(datetime(2026, 11, 12, 10, 0, tzinfo=ET)) is True    # Thu 10:00 ET
    assert pb.deepseek_in_window(datetime(2026, 11, 12, 22, 0, tzinfo=ET)) is False   # Thu 22:00 ET
    assert pb.deepseek_in_window(datetime(2026, 11, 12, 8, 59, tzinfo=ET)) is False   # before 09:00
    assert pb.deepseek_in_window(datetime(2026, 11, 14, 3, 0, tzinfo=ET)) is True     # Sat: operator rule


# ── routing, through the real gate ───────────────────────────────────────────────────────────────────


def _wire(monkeypatch, *, generate, available=("grok", "chatgpt"), cfg=None):
    logged: dict = {}
    monkeypatch.setattr(lc, "should_call", lambda *a, **k: {"allow": True, "mode": "automated"})
    monkeypatch.setattr(lc, "get_process_config", lambda pid: dict(cfg or CFG))
    monkeypatch.setattr(lc, "check_cost_cap", lambda *a, **k: {"allow": True})
    monkeypatch.setattr(lc, "log_call", lambda **kw: logged.update(kw))
    monkeypatch.setattr(ols, "lane_available", lambda lane: lane in available)
    monkeypatch.setitem(sys.modules, "memory_ring2",
                        types.SimpleNamespace(check=lambda *a, **k: {"decision": "ALLOW"},
                                              research_class=lambda *a, **k: False))
    monkeypatch.setitem(sys.modules, "model_chooser", types.SimpleNamespace(apply=lambda *a, **k: (None, {})))
    try:
        promo = __import__("lib.anthropic_routing", fromlist=["active"])
        monkeypatch.setattr(promo, "anthropic_only", lambda *a, **k: False)
        monkeypatch.setattr(promo, "active", lambda *a, **k: False)
    except Exception:  # noqa: BLE001
        pass
    monkeypatch.setattr(llm_lane, "generate", generate)
    return logged


def _call(lane="grok", *, manual_trigger=False, metadata=None):
    return lc.gate_and_generate("Q?", lane=lane, process_id=PROCESS, task_summary="t",
                                timeout=1, max_tokens=16, metadata=metadata or {},
                                manual_trigger=manual_trigger)


def test_after_n_grok_failures_the_next_call_goes_to_chatgpt(state, monkeypatch):
    lanes: list[str] = []

    def generate(prompt, lane="grok", **kw):
        lanes.append(lane)
        if lane == "grok":
            raise RuntimeError(QUOTA_502)
        return "chatgpt answered"

    logged = _wire(monkeypatch, generate=generate)
    for _ in range(pb._threshold()):
        with pytest.raises(RuntimeError, match="GROK_PROXY_402"):
            _call("grok")
    assert lanes == ["grok"] * pb._threshold()

    assert _call("grok") == "chatgpt answered"
    assert lanes[-1] == "chatgpt"
    # requested vs executed provider on the row the consumption page reads
    assert logged["lane"] == "chatgpt"
    assert logged["requested_policy"] == "grok"
    assert logged["executed_policy"] == "chatgpt"
    rr = logged["metadata"]["reroute"]
    assert rr["requested_provider"] == "grok" and rr["executed_provider"] == "chatgpt"
    assert "exhausted" in rr["reason"]


def test_the_reroute_is_logged_once_per_served_call_not_per_failed_one(state, monkeypatch):
    rows: list[dict] = []

    def generate(prompt, lane="grok", **kw):
        if lane == "grok":
            raise RuntimeError(QUOTA_502)
        return "ok"

    _wire(monkeypatch, generate=generate)
    monkeypatch.setattr(lc, "log_call", lambda **kw: rows.append(kw))
    for _ in range(pb._threshold()):
        with pytest.raises(RuntimeError):
            _call("grok")
    assert sum(1 for r in rows if r["lane"] == "grok" and not r["success"]) == pb._threshold()
    assert _call("grok") == "ok"
    assert len(rows) == pb._threshold() + 1 and rows[-1]["lane"] == "chatgpt"


def test_no_deepseek_call_outside_the_operator_window(state, monkeypatch):
    cfg = dict(CFG, allowed_lanes=["grok", "chatgpt", "deepseek-flash"])
    lanes: list[str] = []

    def generate(prompt, lane="grok", **kw):
        lanes.append(lane)
        return "x"

    _wire(monkeypatch, generate=generate, available=("grok",), cfg=cfg)  # grok out, chatgpt down
    for i in range(3):
        pb.note_result("grok", ok=False, error=QUOTA_502, now=1000.0 + i)
    monkeypatch.setattr(pb.time, "time", lambda: 1004.0)
    monkeypatch.setattr(pb, "deepseek_in_window", lambda now=None: False)  # weekday 22:00 ET

    with pytest.raises(RuntimeError, match="NO_PROVIDER_LEFT") as exc:
        _call("grok")
    assert lanes == []
    assert "09:00-21:00 ET" in str(exc.value)


def test_with_no_provider_left_the_call_raises_and_never_returns_output(state, monkeypatch):
    cfg = dict(CFG, allowed_lanes=["grok", "chatgpt"])
    _wire(monkeypatch, generate=lambda *a, **k: "should never run", available=(), cfg=cfg)
    for i in range(3):
        pb.note_result("grok", ok=False, error=QUOTA_502, now=1000.0 + i)
    monkeypatch.setattr(pb.time, "time", lambda: 1004.0)

    with pytest.raises(RuntimeError, match="NO_PROVIDER_LEFT") as exc:
        _call("grok")
    assert "Nothing was sent and nothing is fabricated" in str(exc.value)
    # the refusal is counted where a monitor can see it, without a row per refused call
    refusals = pb.read_state()["_refusals"]
    assert list(refusals.values())[0]["count"] == 1


def test_once_the_window_expires_grok_is_tried_again(state, monkeypatch):
    lanes: list[str] = []

    def generate(prompt, lane="grok", **kw):
        lanes.append(lane)
        return f"{lane} answered"

    _wire(monkeypatch, generate=generate)
    for i in range(3):
        pb.note_result("grok", ok=False, error=QUOTA_502, now=1000.0 + i)
    expiry = pb.exhausted_until("grok", now=1003.0)
    monkeypatch.setattr(pb.time, "time", lambda: expiry + 1)
    assert _call("grok") == "grok answered"
    assert lanes == ["grok"]


def test_a_normal_call_is_untouched(state, monkeypatch):
    logged = _wire(monkeypatch, generate=lambda *a, **k: "plain")
    assert _call("grok") == "plain"
    assert logged["lane"] == "grok" and logged["requested_policy"] is None
    assert "reroute" not in logged["metadata"]
    assert pb.read_state() == {}


def test_a_model_pinned_call_is_never_rerouted(state, monkeypatch):
    """An exact model is provider-specific and reaches the proxy verbatim (llm_lane: model or
    "grok-3-mini"). Swapping the lane under a pinned model would ask chatgpt for a grok model — a 4xx
    the breaker would then read as a chatgpt server error. A pinned caller keeps its own provider."""
    lanes: list[str] = []

    def generate(prompt, lane="grok", **kw):
        lanes.append(lane)
        raise RuntimeError(QUOTA_502)

    _wire(monkeypatch, generate=generate)
    for _ in range(pb._threshold()):
        pb.note_result("grok", ok=False, error=QUOTA_502)
    assert pb.is_exhausted("grok") is True
    with pytest.raises(RuntimeError, match="GROK_PROXY_402"):
        lc.gate_and_generate("Q?", lane="grok", process_id=PROCESS, task_summary="t", timeout=1,
                             max_tokens=16, metadata={}, model="grok-3-mini")
    assert lanes == ["grok"]  # the breaker never touched this call


# ── the cause reaches the caller (proxy 402 + llm_lane body) ─────────────────────────────────────────


def test_the_proxy_names_an_entitlement_wall_as_402_not_an_anonymous_502(monkeypatch):
    import grok_oauth_proxy as gop

    status, body = gop._failure_response(RuntimeError("ENTITLEMENT_EXHAUSTED: Error code: 403 - "
                                                      "{'code': 'personal-team-blocked:spending-limit'}"))
    assert status == 402
    assert body["error"]["type"] == "entitlement_exhausted"
    assert "run out of credits" in body["error"]["message"]
    assert "re-login will not help" in body["error"]["message"]

    assert gop._failure_response(RuntimeError("RATE_LIMITED: 429"))[0] == 429
    assert gop._failure_response(RuntimeError("AUTH_EXPIRED"))[0] == 401
    assert gop._failure_response(RuntimeError("GROK_RUN_FAILED: boom"))[0] == 502


def test_health_stops_claiming_to_serve_once_the_bucket_is_empty(monkeypatch):
    import grok_oauth_proxy as gop

    monkeypatch.setattr(gop, "_xai_token_state", lambda: (True, False))
    monkeypatch.setattr(gop, "_LAST_UPSTREAM", {"state": "unknown", "at": None, "detail": ""})
    assert gop._health_body()["serving"] is True  # nothing known yet
    gop._note_upstream("entitlement_exhausted", "spending-limit")
    body = gop._health_body()
    assert body["serving"] is False
    assert body["last_upstream"]["state"] == "entitlement_exhausted"
    assert "no entitlement" in body["note"] and "re-login will not help" in body["note"]
    gop._note_upstream("ok")
    assert gop._health_body()["serving"] is True


def test_run_grok_classifies_the_403_as_entitlement(monkeypatch):
    import subprocess

    import grok_oauth_proxy as gop

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 1, stdout="", stderr="Error code: 403 - {'code': 'personal-team-blocked:spending-limit', "
                                "'error': 'You have run out of credits'}"))
    with pytest.raises(RuntimeError, match="ENTITLEMENT_EXHAUSTED") as exc:
        gop._run_grok("prompt", "grok-3-mini")
    assert "spending-limit" in str(exc.value)
    assert gop._LAST_UPSTREAM["state"] == "entitlement_exhausted"


def test_llm_lane_keeps_the_proxy_body_in_the_raised_error(monkeypatch):
    import requests

    class _Resp:
        status_code = 402
        ok = False
        text = ""

        def json(self):
            return {"error": {"message": "Grok lane entitlement exhausted — spending-limit", "type": "x"}}

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp())
    monkeypatch.delenv("TRADEAI_LLM_VIA_BRIDGE", raising=False)
    with pytest.raises(RuntimeError) as exc:
        llm_lane.generate("hi", lane="grok", process_id=None, timeout=1)
    assert str(exc.value).startswith("GROK_PROXY_402:")
    assert "spending-limit" in str(exc.value)


# ── the classification that starts the breaker ───────────────────────────────────────────────────────


def test_an_entitlement_wall_is_its_own_cooldown_class(tmp_path, monkeypatch):
    monkeypatch.setattr(ols, "_COOLDOWN_FILE", tmp_path / "cd.json")
    assert ols.classify_failure(QUOTA_502) == "entitlement"
    assert ols.classify_failure("429 Too Many Requests") == "rate_limited"   # rate wins, as before
    assert ols.classify_failure("INPUT_LIMIT_EXCEEDED") is None
    entry = ols.note_failure("grok", QUOTA_502, now=1000.0)
    assert entry["kind"] == "entitlement"
    assert entry["until"] == 1000.0 + ols.COOLDOWN_BASE_S["entitlement"]
    monkeypatch.setattr(ols, "lane_status", lambda lane, **k: {"ready": True})
    monkeypatch.setattr(ols.time, "time", lambda: 1001.0)
    assert ols.lane_available("grok") is False
    assert "entitlement" in (ols.lane_blocked_reason("grok") or "")


# ── F2 (REVIEW-2589): a requested DeepSeek lane off the paid window keeps its deferral path ──────────


def _deepseek_cfg():
    return dict(CFG, allowed_lanes=["grok", "chatgpt", "deepseek-flash"],
                daily_cost_cap_usd=5.0, daily_soft_cap=10,
                max_input_tokens=1000, max_output_tokens=100)


def _free_lanes_out(monkeypatch):
    """grok exhausted, chatgpt unauthenticated, and it is 22:00 ET: the ADDENDUM-2 wall today."""
    for i in range(3):
        pb.note_result("grok", ok=False, error=QUOTA_502, now=1000.0 + i)
    monkeypatch.setattr(pb.time, "time", lambda: 1004.0)
    monkeypatch.setattr(pb, "deepseek_in_window", lambda now=None: False)


def test_a_deepseek_request_off_window_defers_instead_of_raising(state, monkeypatch):
    """F2: the breaker used to refuse a caller that explicitly asked for DeepSeek at night, even with the
    off-peak queue armed and ready to defer it. The window gates an automatic *hop*, not the caller's lane."""
    import lib.llm_deferral as deferral

    lanes: list[str] = []

    def generate(prompt, lane="grok", **kw):
        lanes.append(lane)
        return "should never be sent"

    _wire(monkeypatch, generate=generate, available=(), cfg=_deepseek_cfg())
    _free_lanes_out(monkeypatch)
    monkeypatch.setenv("LLM_DEFER_OFFPEAK", "1")
    monkeypatch.setattr(deferral, "resolve_tier", lambda pid: "standard")
    monkeypatch.setattr(deferral, "is_scheduled_deepseek_window", lambda now=None: False)
    monkeypatch.setattr(deferral, "enqueue", lambda **kw: "req-1")

    with pytest.raises(deferral.DeferredToOffPeak) as exc:
        _call("deepseek-flash")
    assert "DEFERRED_TO_OFFPEAK" in str(exc.value)
    assert lanes == []  # nothing was sent and nothing was spent
    assert "_refusals" not in pb.read_state()  # a deferral is not a refusal


def test_a_manual_deepseek_trigger_off_window_runs(state, monkeypatch):
    """F2, operator half: manual_trigger outranks the off-peak rule. With the queue armed and the free
    providers out, the requested DeepSeek call runs — it must not become NO_PROVIDER_LEFT."""
    import lib.llm_deferral as deferral

    lanes: list[str] = []

    def generate(prompt, lane="grok", **kw):
        lanes.append(lane)
        return "deepseek answered"

    _wire(monkeypatch, generate=generate, available=(), cfg=_deepseek_cfg())
    _free_lanes_out(monkeypatch)
    monkeypatch.setenv("LLM_DEFER_OFFPEAK", "1")
    monkeypatch.setattr(deferral, "resolve_tier", lambda pid: "standard")
    monkeypatch.setattr(deferral, "is_scheduled_deepseek_window", lambda now=None: False)
    monkeypatch.setattr(lc, "cost_persistence_available", lambda: True)
    monkeypatch.setattr(lc, "reserve_projected_cost", lambda *a, **k: "res-1")
    monkeypatch.setattr(lc, "settle_reservation", lambda *a, **k: None)
    monkeypatch.setenv("LLM_GLOBAL_DAILY_USD_CAP", "5")

    assert _call("deepseek-flash", manual_trigger=True) == "deepseek answered"
    assert lanes == ["deepseek-flash"]


# ── F1 (REVIEW-2589): generate_cloud names the provider that actually answered ──────────────────────


def test_generate_cloud_reports_the_lane_that_answered_not_the_one_it_asked(monkeypatch):
    """F1: the gate may execute another lane; the returned label is persisted by the callers, so it must
    come from the gate's provenance rather than the lane this loop requested."""
    import lib.llm_consumption as gatelib
    from lib.governed_cloud_generation import generate_cloud

    calls: list[dict] = []

    def fake_gate(prompt, *, lane, process_id, task_summary, timeout, max_tokens,
                  response_json, manual_trigger, return_provenance=False, **_kw):
        calls.append({"lane": lane, "return_provenance": return_provenance})
        answer = "chatgpt answered"
        if not return_provenance:
            return answer
        return answer, {
            "reroute": {"requested": "grok", "executed": "chatgpt",
                        "requested_provider": "grok", "executed_provider": "chatgpt",
                        "reason": "provider exhausted (1800s left before the probe)"},
        }

    monkeypatch.setattr(gatelib, "gate_and_generate", fake_gate)
    monkeypatch.setattr(gatelib, "_registry_process", lambda pid: {})
    monkeypatch.setattr(llm_lane, "available", lambda lane: lane == "grok")

    text, lane = generate_cloud("Q?", process_id=PROCESS, task_summary="t", timeout=1)
    assert text == "chatgpt answered"
    assert lane == "chatgpt", "a rerouted answer must not be persisted under the requested provider"
    assert calls and calls[0]["return_provenance"] is True


# ── guards the REVIEW-2589 mutants P9 / P11 found uncovered ──────────────────────────────────────────


def test_a_reroute_never_leaves_the_process_allowlist(state, monkeypatch):
    cfg = dict(CFG, allowed_lanes=["grok"])  # chatgpt is up but this process may not use it
    lanes: list[str] = []
    _wire(monkeypatch, generate=lambda p, lane="grok", **k: lanes.append(lane) or "x", cfg=cfg)
    for i in range(3):
        pb.note_result("grok", ok=False, error=QUOTA_502, now=1000.0 + i)
    monkeypatch.setattr(pb.time, "time", lambda: 1004.0)
    with pytest.raises(RuntimeError, match="NO_PROVIDER_LEFT"):
        _call("grok")
    assert lanes == []


def test_a_provider_pinned_call_is_never_rerouted(state, monkeypatch):
    lanes: list[str] = []
    _wire(monkeypatch, generate=lambda p, lane="grok", **k: lanes.append(lane) or "ok")
    for i in range(3):
        pb.note_result("grok", ok=False, error=QUOTA_502, now=1000.0 + i)
    monkeypatch.setattr(pb.time, "time", lambda: 1004.0)
    assert _call("grok", metadata={"provider_pinned": True}) == "ok"
    assert lanes == ["grok"]
