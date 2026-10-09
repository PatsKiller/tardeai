"""Bridge + n8n executor hardening (guardrail audit B, 2026-10-09: findings H1, H2, M1, M2).

H1  a streamed bridge request makes exactly one provider call, one reservation, one settlement, one cost
    event; the SSE text is the governed result, never a second provider answer.
H2  caller authentication: off | report (default) | enforce. Report never refuses and records one line per
    caller per hour; enforce answers a typed 401 before any reservation or provider call; a key value is
    never logged, returned or written.
M1  the executor unit carries every behaviour-affecting crontab-wide variable the cron-side lanes rely on.
M2  a lane spawned by the executor inherits no n8n secret, and still sees TRADEAI_STATE_ROOT and PY.

Hermetic: tmp_path ledgers/receipts, patched consumption ledger, fake providers, loopback port 0.
Never reads the live crontab, ledger, token store or key material.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
import threading
from contextlib import contextmanager
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import cio_governed_model_bridge as bridge  # noqa: E402

GOVERNED_TEXT = "Governed  answer:\nhold the line, trim 10%  "
KEY = "k" * 40          # fixture key material; asserted absent from every output below
PREVIOUS_KEY = "p" * 40
CALLER = "alex"
KEY_ENV = "TRADEAI_BRIDGE_CALLER_KEY_ALEX"


# ── shared bridge harness ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("TRADEAI_LLM_PROVIDER_HEALTH", str(tmp_path / "absent-health.json"))
    monkeypatch.setenv("TRADEAI_DEEPSEEK_BALANCE_HISTORY", str(tmp_path / "absent-balance.jsonl"))
    monkeypatch.setenv("CIO_PROVIDER_REQUEST_JOURNAL_JSONL", str(tmp_path / "journal.jsonl"))
    monkeypatch.setenv("TRADEAI_BRIDGE_CALLER_AUTH_REPORT", str(tmp_path / "caller_auth_report.jsonl"))
    monkeypatch.delenv("TRADEAI_LLM_ROUTING_POLICY", raising=False)
    monkeypatch.delenv("TRADEAI_BRIDGE_CALLER_AUTH", raising=False)
    for name in [n for n in list(__import__("os").environ) if n.startswith(bridge.CALLER_KEY_ENV_PREFIX)]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(bridge, "BIND_MODE", "mock")
    bridge._reset_circuit()
    bridge._reset_caller_auth()

    def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    for target in ("model_chooser.apply", "scripts.lib.model_chooser.apply"):
        try:
            monkeypatch.setattr(target, _noop)
        except (AttributeError, ModuleNotFoundError, ImportError):
            continue
    yield tmp_path
    bridge._reset_circuit()
    bridge._reset_caller_auth()


def _registered(process_id: str) -> dict:
    return {
        "process_id": process_id,
        "registered": True,
        "mode": "automated",
        "deepseek_allowed_policies": ["PRO", "PRO_THINK", "FAST", "FAST_THINK"],
        "max_input_tokens": 32000,
        "max_output_tokens": 16384,
        "daily_soft_cap": 40,
        "daily_cost_cap_usd": 1.0,
    }


@contextmanager
def _governed(monkeypatch: pytest.MonkeyPatch):
    """Patch the consumption path so nothing reserves against the live ledger; return the counters."""
    ledger = {
        "reserve": MagicMock(return_value=4242),
        "settle": MagicMock(return_value=None),
        "log_call": MagicMock(return_value=None),
    }
    monkeypatch.setattr("lib.llm_consumption.get_process_config", lambda pid: _registered(pid))
    monkeypatch.setattr("lib.llm_consumption.reserve_projected_cost", ledger["reserve"])
    monkeypatch.setattr("lib.llm_consumption.settle_reservation", ledger["settle"])
    monkeypatch.setattr("lib.llm_consumption.check_cost_cap", lambda *a, **k: {"allow": True})
    monkeypatch.setattr(
        "lib.llm_consumption.calibrated_projected_usd",
        lambda *_a, **_k: {"projected_usd": 0.002, "basis": "test"},
    )
    monkeypatch.setattr("lib.llm_consumption.log_call", ledger["log_call"])
    monkeypatch.setattr("lib.llm_model_registry.reject_legacy_model_id", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "lib.llm_model_registry.estimate_usd_cost",
        lambda *_a, **_k: {
            "estimated_cost_usd": 0.0005,
            "cost_basis": "provider_usage_x_registry_snapshot",
            "pricing_effective_at": "2026-10-09",
        },
    )
    monkeypatch.setattr("lib.consumption_run_manual.validate_paid_cap_config", lambda *_a, **_k: None)
    monkeypatch.setattr("lib.consumption_run_manual.projected_max_cost_usd", lambda *_a, **_k: 0.002)
    yield ledger


class CountingProvider:
    """Stands in for RealProvider: one generate = one provider call = one cost event (as RealProvider emits)."""

    def __init__(self, cost_events: list) -> None:
        self.calls = 0
        self.stream_calls = 0
        self._cost_events = cost_events

    def generate(self, messages, model_id, **_kwargs):
        self.calls += 1
        usage = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
        bridge._emit_bridge_cost(outcome="success", model=model_id, usage=usage, request_sent=True)
        return {
            "id": f"prov-{self.calls}",
            "object": "chat.completion",
            "created": 1_791_000_000,
            "model": model_id,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": GOVERNED_TEXT},
                         "finish_reason": "stop"}],
            "usage": usage,
            "_tradeai": {"provider_request_id": f"provider-{self.calls}"},
        }

    def generate_stream(self, *_a, **_k):
        self.stream_calls += 1
        raise AssertionError("the stream path must not ask the provider for a stream")


def _fake_provider(monkeypatch: pytest.MonkeyPatch, *, canary: bool) -> tuple[CountingProvider, list]:
    cost_events: list = []
    monkeypatch.setattr(bridge, "_emit_bridge_cost", lambda **kw: cost_events.append(kw))
    provider = CountingProvider(cost_events)
    if canary:
        monkeypatch.setattr(bridge, "BIND_MODE", "canary")
        monkeypatch.setattr(bridge.RealProvider, "instance", classmethod(lambda cls: provider))
        monkeypatch.setattr(bridge.MockProvider, "instance", classmethod(lambda cls: (_ for _ in ()).throw(
            AssertionError("mock provider in canary"))))
    else:
        monkeypatch.setattr(bridge.MockProvider, "instance", classmethod(lambda cls: provider))
        monkeypatch.setattr(bridge.RealProvider, "instance", classmethod(lambda cls: (_ for _ in ()).throw(
            AssertionError("real provider in mock mode"))))
    return provider, cost_events


def _post(body: dict, headers: dict[str, str]) -> tuple[int, str, bytes]:
    server = bridge.start_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", int(server.server_address[1]), timeout=10)
        conn.request("POST", "/v1/chat/completions", body=json.dumps(body).encode("utf-8"),
                     headers={"Content-Type": "application/json", **headers})
        resp = conn.getresponse()
        raw = resp.read()
        ctype = resp.getheader("Content-Type") or ""
        conn.close()
        return resp.status, ctype, raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _sse_events(raw: bytes) -> list:
    out = []
    for block in raw.decode("utf-8").split("\n\n"):
        if not block.startswith("data: "):
            continue
        payload = block[len("data: "):]
        out.append(payload if payload == "[DONE]" else json.loads(payload))
    return out


def _streamed_text(events: list) -> str:
    return "".join(
        (e["choices"][0]["delta"].get("content") or "") for e in events if isinstance(e, dict) and e.get("choices")
    )


BODY = {"messages": [{"role": "user", "content": "review"}]}


# ── H1: one provider call per streamed request ─────────────────────────────

@pytest.mark.parametrize("canary", [True, False], ids=["canary", "mock"])
def test_stream_makes_exactly_one_provider_call_reservation_settlement_and_cost_event(monkeypatch, canary):
    provider, cost_events = _fake_provider(monkeypatch, canary=canary)
    with _governed(monkeypatch) as ledger:
        status, ctype, raw = _post({**BODY, "stream": True}, {"X-TradeAI-Agent": CALLER})
    assert status == 200, raw[:400]
    assert ctype.startswith("text/event-stream")
    events = _sse_events(raw)
    assert events[-1] == "[DONE]"
    assert provider.calls == 1
    assert provider.stream_calls == 0
    assert ledger["reserve"].call_count == 1
    assert ledger["settle"].call_count == 1
    assert ledger["log_call"].call_count == 1
    assert len(cost_events) == 1
    assert _streamed_text(events) == GOVERNED_TEXT
    final = events[-2]
    assert final["choices"][0]["finish_reason"] == "stop"
    assert final["usage"]["total_tokens"] == 18
    assert final["_tradeai"]["governance_pass"] is True
    assert final["_tradeai"]["reservation_id"] == 4242


def test_stream_text_equals_the_non_stream_governed_result(monkeypatch):
    provider, _ = _fake_provider(monkeypatch, canary=True)
    with _governed(monkeypatch):
        _, _, plain = _post(BODY, {"X-TradeAI-Agent": CALLER})
        bridge._reset_circuit()
        _, _, streamed = _post({**BODY, "stream": True}, {"X-TradeAI-Agent": CALLER})
    assert provider.calls == 2  # one per request, never two for the streamed one
    governed = json.loads(plain)["choices"][0]["message"]["content"]
    assert _streamed_text(_sse_events(streamed)) == governed == GOVERNED_TEXT


def test_sse_chunks_are_pure_and_carry_tool_calls():
    result = {
        "id": "r1", "created": 1, "model": "m",
        "choices": [{"message": {"role": "assistant", "content": None,
                                 "tool_calls": [{"id": "t1", "type": "function",
                                                 "function": {"name": "f", "arguments": "{}"}}]}}],
        "usage": {"total_tokens": 3},
    }
    events = _sse_events("".join(bridge.governed_result_sse_chunks(result)).encode("utf-8"))
    assert events[-1] == "[DONE]"
    assert events[0]["choices"][0]["delta"]["role"] == "assistant"
    tool = [e for e in events[:-1] if e["choices"][0]["delta"].get("tool_calls")]
    assert tool and tool[0]["choices"][0]["delta"]["tool_calls"][0]["function"]["name"] == "f"
    assert events[-2]["choices"][0]["finish_reason"] == "tool_calls"


def test_stream_handler_no_longer_calls_a_provider_in_source():
    src = (ROOT / "scripts" / "lib" / "cio_governed_model_bridge.py").read_text(encoding="utf-8")
    body = src.split("def _send_stream", 1)[1].split("\n    def ", 1)[0].split("\n# ", 1)[0]
    assert "generate" not in body and "resolve_model_policy" not in body and "Provider" not in body


# ── H2: caller authentication modes ────────────────────────────────────────

def test_verdicts(monkeypatch):
    assert bridge.caller_key_env_name("n8n_model_job") == "TRADEAI_BRIDGE_CALLER_KEY_N8N_MODEL_JOB"
    assert bridge.caller_auth_verdict(CALLER, f"Bearer {KEY}") == "no_key_configured"
    monkeypatch.setenv(KEY_ENV, "short")
    assert bridge.caller_auth_verdict(CALLER, "Bearer short") == "no_key_configured"  # weak keys do not count
    monkeypatch.setenv(KEY_ENV, KEY)
    assert bridge.caller_auth_verdict(CALLER, None) == "unsigned"
    assert bridge.caller_auth_verdict(CALLER, KEY) == "unsigned"
    assert bridge.caller_auth_verdict(CALLER, "Bearer ") == "unsigned"
    assert bridge.caller_auth_verdict(CALLER, "Bearer " + "x" * 40) == "bad_key"
    assert bridge.caller_auth_verdict(CALLER, f"Bearer {KEY}") == "verified"
    assert bridge.caller_auth_verdict(CALLER, f"bearer {KEY}") == "verified"
    assert bridge.caller_auth_verdict(CALLER, f"Bearer {PREVIOUS_KEY}") == "bad_key"
    monkeypatch.setenv(KEY_ENV + "_PREVIOUS", PREVIOUS_KEY)
    assert bridge.caller_auth_verdict(CALLER, f"Bearer {PREVIOUS_KEY}") == "verified"  # rotation overlap
    assert bridge.caller_auth_verdict("maria", f"Bearer {KEY}") == "no_key_configured"  # keys are per caller


def test_mode_defaults_to_report_and_unknown_values_fall_back_to_report(monkeypatch):
    assert bridge.caller_auth_mode() == "report"
    for raw, want in (("off", "off"), ("ENFORCE", "enforce"), (" report ", "report"), ("bogus", "report")):
        monkeypatch.setenv("TRADEAI_BRIDGE_CALLER_AUTH", raw)
        assert bridge.caller_auth_mode() == want


def _report_lines(tmp_path: Path) -> list[dict]:
    path = tmp_path / "caller_auth_report.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize("auth", [None, "Bearer " + "x" * 40], ids=["unsigned", "wrong-key"])
def test_report_mode_serves_unverified_callers_and_records_one_line_per_caller_per_hour(
    monkeypatch, hermetic, auth
):
    provider, _ = _fake_provider(monkeypatch, canary=True)
    monkeypatch.setenv(KEY_ENV, KEY)
    headers = {"X-TradeAI-Agent": CALLER, **({"Authorization": auth} if auth else {})}
    with _governed(monkeypatch) as ledger:
        for _ in range(3):
            status, _, raw = _post(BODY, headers)
            assert status == 200, raw[:300]
            bridge._reset_circuit()
    assert provider.calls == 3 and ledger["reserve"].call_count == 3
    lines = _report_lines(hermetic)
    assert len(lines) == 1
    line = lines[0]
    assert line["schema"] == "BridgeCallerAuthReport@v1"
    assert line["caller"] == CALLER and line["process_id"] == "alex_cio_synthesis"
    assert line["verdict"] == ("unsigned" if auth is None else "bad_key")
    assert line["mode"] == "report" and line["served"] is True
    assert line["key_env"] == KEY_ENV and line["key_configured"] is True
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}", line["hour"])
    snap = bridge.caller_auth_snapshot()
    assert snap["mode"] == "report"
    assert snap["counts"][CALLER][line["verdict"]] == 3


def test_report_mode_records_callers_without_any_key_configured(monkeypatch, hermetic):
    _fake_provider(monkeypatch, canary=False)
    with _governed(monkeypatch):
        status, _, _ = _post(BODY, {"X-TradeAI-Agent": CALLER})
    assert status == 200
    (line,) = _report_lines(hermetic)
    assert line["verdict"] == "no_key_configured" and line["key_configured"] is False


def test_report_mode_does_not_record_a_verified_caller(monkeypatch, hermetic):
    _fake_provider(monkeypatch, canary=False)
    monkeypatch.setenv(KEY_ENV, KEY)
    with _governed(monkeypatch):
        status, _, _ = _post(BODY, {"X-TradeAI-Agent": CALLER, "Authorization": f"Bearer {KEY}"})
    assert status == 200
    assert _report_lines(hermetic) == []
    assert bridge.caller_auth_snapshot()["counts"][CALLER] == {"verified": 1}


def test_off_mode_checks_nothing_and_records_nothing(monkeypatch, hermetic):
    _fake_provider(monkeypatch, canary=False)
    monkeypatch.setenv("TRADEAI_BRIDGE_CALLER_AUTH", "off")
    monkeypatch.setenv(KEY_ENV, KEY)
    with _governed(monkeypatch):
        status, _, _ = _post(BODY, {"X-TradeAI-Agent": CALLER, "Authorization": "Bearer wrong"})
    assert status == 200
    assert _report_lines(hermetic) == []
    assert bridge.caller_auth_snapshot()["counts"] == {}


@pytest.mark.parametrize(
    "key_set,auth,code",
    [
        (False, None, "CALLER_AUTH_REQUIRED"),
        (True, None, "CALLER_AUTH_REQUIRED"),
        (True, "Bearer " + "x" * 40, "CALLER_AUTH_INVALID"),
    ],
    ids=["no-key-configured", "unsigned", "wrong-key"],
)
def test_enforce_refuses_with_typed_401_before_any_reservation_or_provider_call(monkeypatch, key_set, auth, code):
    provider, cost_events = _fake_provider(monkeypatch, canary=True)
    monkeypatch.setenv("TRADEAI_BRIDGE_CALLER_AUTH", "enforce")
    if key_set:
        monkeypatch.setenv(KEY_ENV, KEY)
    ring2 = MagicMock(side_effect=AssertionError("ring 2 must not run before caller auth"))
    for target in ("memory_ring2.check", "scripts.lib.memory_ring2.check", "lib.memory_ring2.check"):
        try:
            monkeypatch.setattr(target, ring2)
        except (AttributeError, ModuleNotFoundError, ImportError):
            continue
    headers = {"X-TradeAI-Agent": CALLER, **({"Authorization": auth} if auth else {})}
    with _governed(monkeypatch) as ledger:
        status, ctype, raw = _post({**BODY, "stream": True}, headers)
    payload = json.loads(raw)
    assert status == 401 and ctype == "application/json"
    assert payload["error"]["code"] == code and payload["error"]["status"] == 401
    assert payload["caller_auth"]["mode"] == "enforce"
    assert payload["caller_auth"]["key_env"] == KEY_ENV
    assert payload["governance_pass"] is False
    assert ledger["reserve"].call_count == 0 and ledger["settle"].call_count == 0
    assert provider.calls == 0 and cost_events == []


def test_enforce_serves_a_verified_caller(monkeypatch):
    provider, _ = _fake_provider(monkeypatch, canary=True)
    monkeypatch.setenv("TRADEAI_BRIDGE_CALLER_AUTH", "enforce")
    monkeypatch.setenv(KEY_ENV, KEY)
    with _governed(monkeypatch):
        status, _, _ = _post(BODY, {"X-TradeAI-Agent": CALLER, "Authorization": f"Bearer {KEY}"})
    assert status == 200 and provider.calls == 1


def test_no_key_value_is_ever_logged_returned_or_written(monkeypatch, hermetic, caplog):
    _fake_provider(monkeypatch, canary=False)
    monkeypatch.setenv(KEY_ENV, KEY)
    monkeypatch.setenv(KEY_ENV + "_PREVIOUS", PREVIOUS_KEY)
    wrong = "w" * 40
    seen: list[bytes] = []
    caplog.set_level(logging.DEBUG)
    with _governed(monkeypatch):
        for mode in ("report", "enforce"):
            monkeypatch.setenv("TRADEAI_BRIDGE_CALLER_AUTH", mode)
            bridge._reset_caller_auth()
            for auth in (f"Bearer {KEY}", f"Bearer {wrong}", None):
                headers = {"X-TradeAI-Agent": CALLER, **({"Authorization": auth} if auth else {})}
                seen.append(_post(BODY, headers)[2])
                bridge._reset_circuit()
    report = (hermetic / "caller_auth_report.jsonl").read_text(encoding="utf-8")
    haystacks = [report, caplog.text, json.dumps(bridge.caller_auth_snapshot())] + [s.decode() for s in seen]
    for secret in (KEY, PREVIOUS_KEY, wrong):
        for text in haystacks:
            assert secret not in text


def test_health_exposes_the_counter_without_key_values(monkeypatch):
    monkeypatch.setenv(KEY_ENV, KEY)
    bridge.record_caller_auth(CALLER, "alex_cio_synthesis", "unsigned", "report")
    server = bridge.start_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", int(server.server_address[1]), timeout=5)
        conn.request("GET", "/health")
        body = conn.getresponse().read().decode("utf-8")
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    doc = json.loads(body)
    assert doc["caller_auth"] == {"mode": "report", "counts": {CALLER: {"unsigned": 1}}}
    assert KEY not in body


# ── M1: crontab-wide env parity for the executor unit ──────────────────────

#: Measured 2026-10-09 from the live crontab header (`crontab -l | sed -n '1,30p'`): the only lines without a
#: schedule are SHELL (2), PROJ (3), PY (4), LLM_DEFER_OFFPEAK (9), TRADEAI_ENV (11), BLIND_REVIEW_LANES (13).
#: Path values are written in systemd specifiers (%h home, %t runtime dir); scalars must match exactly.
CRONTAB_WIDE_LANE_ENV: dict[str, str] = {
    "PROJ": "%h/trade-ai-releases/portfolio-server/CURRENT",
    "PY": "%h/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python",
    "LLM_DEFER_OFFPEAK": "1",                       # off-peak deferral of scheduled paid LLM work (2026-09-20)
    "TRADEAI_ENV": "%t/tradeai/env",
    "BLIND_REVIEW_LANES": "deepseek-flash,grok,chatgpt",
}
#: Deliberately NOT in the unit, with the reason.
CRONTAB_VARS_EXCLUDED: dict[str, str] = {
    "SHELL": "cron's command interpreter; the executor spawns argv directly with no shell",
    "CIO_DUAL_CHATGPT_CAP": "position-scoped (set at crontab line ~506, applies only to the lines after it; "
                            "earlier lanes rely on the script default), so it is not crontab-wide",
}


def _unit_environment() -> dict[str, str]:
    unit = (ROOT / "config" / "systemd" / "user" / "tradeai-n8n-run-executor.service").read_text(encoding="utf-8")
    env: dict[str, str] = {}
    for line in unit.splitlines():
        if line.startswith("Environment="):
            name, _, value = line[len("Environment="):].partition("=")
            env[name] = value
    return env


def test_executor_unit_carries_every_crontab_wide_lane_variable():
    env = _unit_environment()
    for name, value in CRONTAB_WIDE_LANE_ENV.items():
        assert env.get(name) == value, name
    for name in CRONTAB_VARS_EXCLUDED:
        assert name not in env, name
    assert env["PY"] == env["TRADEAI_VENV_PYTHON"]
    unit = (ROOT / "config" / "systemd" / "user" / "tradeai-n8n-run-executor.service").read_text(encoding="utf-8")
    assert "/home/" not in unit


def test_crontab_wide_variables_reach_the_lane_child_env():
    env = {**_unit_environment(), "PATH": "/usr/bin:/bin"}
    child = X.child_env(env, "generate-analyst-daily-digest")
    for name in CRONTAB_WIDE_LANE_ENV:
        assert name in child
    assert child["LLM_DEFER_OFFPEAK"] == "1"


# ── M2: lanes inherit no n8n secret ────────────────────────────────────────

N8N_SECRETS = {
    "TRADEAI_N8N_GATEWAY_HMAC_KEY": "a" * 40,
    "TRADEAI_N8N_GATEWAY_HMAC_KEY_PREVIOUS": "b" * 40,
    "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N": "c" * 40,
    "TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N_PREVIOUS": "d" * 40,
    "TRADEAI_N8N_RELAY_BEARER": "e" * 40,
    "TRADEAI_N8N_RELAY_BEARER_PREVIOUS": "f" * 40,
    "N8N_ENCRYPTION_KEY_ESCROW": "g" * 40,
}
NEVER_PASSED = set(N8N_SECRETS) - {X.GATEWAY_DISPATCH_KEY_ENV}


@pytest.fixture
def env_bench(tmp_path, monkeypatch):
    code = tmp_path / "code"
    (code / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "safe_flock.sh", code / "scripts" / "safe_flock.sh")
    (code / "scripts" / "dump_env.py").write_text(
        "import json, os, pathlib, sys\n"
        "out = pathlib.Path(os.environ['TRADEAI_STATE_ROOT']) / ('env_' + sys.argv[1] + '.json')\n"
        "out.write_text(json.dumps(dict(os.environ)))\n"
    )
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "locks").mkdir()
    env = {
        "PATH": "/usr/bin:/bin",
        "TRADEAI_STATE_ROOT": str(state),
        "TRADEAI_VENV_PYTHON": sys.executable,
        "PY": sys.executable,
        "SAFE_FLOCK_LOG_DIR": str(tmp_path / "flock-logs"),
        "TRADEAI_N8N_GATEWAY_URL": "http://127.0.0.1:18091",
        **N8N_SECRETS,
    }
    return {"code": code, "state": state, "locks": tmp_path / "locks", "env": env}


def _run_lane(bench, lane_id: str) -> dict:
    entry = {
        "lane_id": lane_id,
        "command": ["$PY", "scripts/dump_env.py"],
        "lock": str(bench["locks"] / f"{lane_id}.lock"),
        "timeout_s": 20,
        "dry_run_arg": [lane_id],
        "live_arg": [lane_id],
    }
    row = {"run_id": f"run-{lane_id}-0000000000", "lane_id": lane_id, "mode": "dry_run"}
    receipt = X.execute(row, entry, env=bench["env"], state_root=bench["state"], code_root=bench["code"])
    assert receipt["state"] == "RUN_DONE", receipt
    for secret in N8N_SECRETS.values():
        assert secret not in json.dumps(receipt)
    return json.loads((bench["state"] / f"env_{lane_id}.json").read_text(encoding="utf-8"))


def test_a_lane_sees_no_n8n_secret_but_keeps_state_root_and_py(env_bench):
    seen = _run_lane(env_bench, "fake-lane")
    for name in N8N_SECRETS:
        assert name not in seen, name
    assert not [k for k in seen if k.startswith(("TRADEAI_N8N_", "N8N_")) and k not in X.CHILD_ENV_N8N_NON_SECRET]
    assert seen["TRADEAI_STATE_ROOT"] == str(env_bench["state"])
    assert seen["PY"] == sys.executable
    assert seen["TRADEAI_N8N_GATEWAY_URL"] == "http://127.0.0.1:18091"  # non-secret routing value


def test_gateway_client_lanes_get_only_the_dispatch_key(env_bench):
    seen = _run_lane(env_bench, "n8n-pilot-dispatch")
    assert seen[X.GATEWAY_DISPATCH_KEY_ENV] == N8N_SECRETS[X.GATEWAY_DISPATCH_KEY_ENV]
    for name in NEVER_PASSED:
        assert name not in seen, name


def test_passthrough_table_never_admits_relay_previous_or_n8n_keys():
    admitted = set().union(*X.CHILD_ENV_LANE_PASSTHROUGH.values()) | set(X.CHILD_ENV_N8N_NON_SECRET)
    assert admitted & NEVER_PASSED == set()
    for name in X.CHILD_ENV_N8N_NON_SECRET:
        assert not re.search(r"KEY|BEARER|TOKEN|SECRET", name)
    # the gateway-client lanes named here are real allowlisted lanes, so the table cannot silently drift
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))
    lanes = {e["lane_id"] for e in allow["lanes"]}
    assert set(X.CHILD_ENV_LANE_PASSTHROUGH) <= lanes


def test_child_env_does_not_mutate_the_executor_env(env_bench):
    before = dict(env_bench["env"])
    X.child_env(env_bench["env"], "fake-lane")
    assert env_bench["env"] == before
