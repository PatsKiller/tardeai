"""An n8n-triggered lane-failure diagnosis is served by DeepSeek whenever DeepSeek is the selected lane (2026-10-15).

Operator question 2026-10-15: "is DeepSeek working with n8n". Measured in the provider journal: 117 of 119 completed
n8n_lane_failure_diagnosis calls (2026-10-11T19:33Z..2026-10-15T00:34Z) were served by DeepSeek although the routing row
is grok OAuth -> chatgpt OAuth -> deepseek FAST. Cause: the bridge only reaches an OAuth lane the host enabled
(CIO_BRIDGE_OAUTH_TRANSPORTS); until the 60-oauth-transports drop-in (2026-10-14 ~21:26 ET) none was, so the
transport_failover walk skipped grok/chatgpt (no_bridge_transport) and DeepSeek served. Intended order and behaviour now
agree; DeepSeek stays the working fallback.

End to end, in process: n8n_failure_diagnosis.main --apply -> n8n_model_job.run_model_job -> the REAL
cio_governed_model_bridge.execute_governed_call (route walk, governance envelope) -> a fake DeepSeek provider. Pins:
1. OAuth lanes enabled but both failing -> DeepSeek serves and the diagnosis records provider deepseek;
2. OAuth transports not enabled on the host (the pre-2026-10-14 config) -> DeepSeek serves, grok/chatgpt never called.

Hermetic: the bridge test module's autouse fixture (tmp journal/audit paths, canary bind with fake transports, health
snapshot stubbed) and its `governed` ledger patches; OAuth proxies are fake HTTP; no network, DB, key or token store.
"""
from __future__ import annotations

import json

from scripts.lib import n8n_failure_diagnosis as D

from tests.test_bridge_oauth_llm_step_20261014 import (  # noqa: F401 — `hermetic` is autouse: it must be in scope
    FakeDeepSeek,
    FakeResp,
    Proxy,
    bridge,
    governed,
    hermetic,
    ot,
    wire,
)
from tests.test_n8n_llm_remediation_20261010 import (  # noqa: F401 — shared diagnoser doubles + env fixture
    FakeDB,
    FakeStore,
    _answer,
    _receipt,
    _run,
    _siem_row,
    env,
)


def _in_process_bridge(seen: list):
    """n8n_model_job's governed_call contract, served by the real bridge pipeline in process (not loopback HTTP)."""

    def call(messages, *, process_id, response_format=None, request_id=None, task_type=None, **kw):
        seen.append({"process_id": process_id, "task_type": task_type})
        return bridge.execute_governed_call(messages, process_id=process_id, response_format=response_format,
                                            request_id=request_id, max_tokens=1024)

    return call


def _diagnose_once(monkeypatch, env, grok, chat, ds):
    wire(monkeypatch, grok, chat, ds)
    seen: list = []
    with governed(monkeypatch):
        assert _run(env, ["--apply"], db=FakeDB([_siem_row()]), call=_in_process_bridge(seen), store=FakeStore()) == 0
    assert seen == [{"process_id": D.PROCESS_ID, "task_type": "lane_failure_diagnosis"}]
    return _receipt(env)["results"][0]


def test_deepseek_serves_the_diagnosis_when_oauth_lanes_fail(monkeypatch, env):
    grok, chat = Proxy("grok", FakeResp(502)), Proxy("chatgpt", FakeResp(500))
    ds = FakeDeepSeek(json.dumps(_answer(action="suggest_only", conf=0.9)))
    res = _diagnose_once(monkeypatch, env, grok, chat, ds)
    assert len(grok.calls) == 1 and len(chat.calls) == 1 and len(ds.calls) == 1
    assert res["model_job_state"] == "ARTIFACT_WRITTEN", res.get("model_job_reason")
    assert res["provider"] == "deepseek" and res["outcome"] == "diagnosed"
    assert res["verdict"]["cause"] and res["verdict"]["confidence"] == 0.9


def test_deepseek_serves_when_no_oauth_transport_is_enabled(monkeypatch, env):
    monkeypatch.delenv(ot.ENABLE_ENV, raising=False)
    grok, chat = Proxy("grok", FakeResp(502)), Proxy("chatgpt", FakeResp(500))
    ds = FakeDeepSeek(json.dumps(_answer(action="suggest_only", conf=0.9)))
    res = _diagnose_once(monkeypatch, env, grok, chat, ds)
    assert grok.calls == [] and chat.calls == [] and len(ds.calls) == 1
    assert res["provider"] == "deepseek" and res["outcome"] == "diagnosed"
