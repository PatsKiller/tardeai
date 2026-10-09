"""Bridge-side n8n Agent preconditions (AGENTS.md 3.0.0 §23.3, §23.4, §23.10 P4, P5, P6, P21).

P4   the single egress sanitiser sanitise_for_external() (§2A): every category is caught; a forbidden field
     cannot pass in enforce; report mode (default) sends unchanged and records counts only; it runs for
     every process, before any provider call.
P5   per-process tool allowlist at the bridge: typed 400 before reservation for a request tool outside the
     row's `tools_allowed`; a model tool_call outside it (or hitting FORBIDDEN_ROUTE_TOKENS) is refused
     typed, never dropped; rows with tools_allowed true keep today's pass-through; no current caller sends
     tools.
P6   n8n_* outputs: schema + behaviour-field scan (cio_instrument_record.BEHAVIOR_FIELDS) -> typed refusal;
     other processes unaffected.
P21  routing policy cost_ceiling_usd refuses before reservation; latency_budget_ms is the provider deadline;
     advisory_only stamps READ_ONLY_ADVISORY (n8n_*: recommendation NONE).
Routing: n8n_* rows are Grok -> ChatGPT -> DeepSeek (§23.4 decision 2); the live transport walks to DeepSeek.

Hermetic: fake providers, patched consumption ledger, tmp report files, no network, no key material.
Fixture secrets are assembled at runtime and asserted absent from every report.
"""

from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_governed_model_bridge as bridge  # noqa: E402
from lib import bridge_agent_preconditions as gate  # noqa: E402
from lib import cio_egress_sanitiser as egress  # noqa: E402

DIGEST = "n8n_material_digest_draft"
OPS = "n8n_ops_summary_draft"
VALID_DIGEST = {"headline": "two material changes", "items": [{"symbol": "AMC", "change_guid": "d13460e0",
                "summary": "8-K filed"}], "sources_cited": ["sec.gov"], "confidence_note": "artifact only",
                "recommendation": "NONE"}

# Fixture values, assembled so no literal credential sits in the repository.
FAKE_SK = "sk-" + "Zq7" * 10
FAKE_BEARER = "Bearer " + "abc123XYZ" * 3
FAKE_ENV = "DEEPSEEK_API_KEY=" + "v" * 24
FAKE_ACCT = "account number: 8765" + "4321"
FAKE_EMAIL = "someone" + "@" + "example.org"
FAKE_SSN = "123-" + "45-" + "6789"
FAKE_HOME = "/" + "home" + "/" + "operator/trade-ai/.env"
FAKE_TS = "100." + "66.1.2"
FAKE_POS = '"market_value": 48250.75'
SAMPLES = {
    "credential": [FAKE_SK, FAKE_BEARER],
    "env_contents": [FAKE_ENV],
    "account_number": [FAKE_ACCT],
    "personal_identifier": [FAKE_EMAIL, FAKE_SSN],
    "internal_host_path": [FAKE_HOME, FAKE_TS],
    "position_dollars": [FAKE_POS],
}
PERMITTED = "NVDA thesis: AI capex cycle intact; last price 182.50, forward P/E 45, sector weight discussed in aggregate."


@pytest.fixture(autouse=True)
def hermetic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("TRADEAI_LLM_PROVIDER_HEALTH", str(tmp_path / "absent-health.json"))
    monkeypatch.setenv("TRADEAI_DEEPSEEK_BALANCE_HISTORY", str(tmp_path / "absent-balance.jsonl"))
    monkeypatch.setenv("CIO_PROVIDER_REQUEST_JOURNAL_JSONL", str(tmp_path / "journal.jsonl"))
    monkeypatch.setenv("TRADEAI_BRIDGE_CALLER_AUTH_REPORT", str(tmp_path / "caller_auth.jsonl"))
    monkeypatch.setenv(egress.REPORT_ENV, str(tmp_path / "egress_report.jsonl"))
    for name in ("TRADEAI_LLM_ROUTING_POLICY", "TRADEAI_BRIDGE_CALLER_AUTH", egress.MODE_ENV, egress.POLICY_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(bridge, "BIND_MODE", "mock")
    bridge._reset_circuit()
    bridge._reset_caller_auth()
    egress.reset()
    for target in ("model_chooser.apply", "scripts.lib.model_chooser.apply"):
        try:
            monkeypatch.setattr(target, lambda *a, **k: None)
        except (AttributeError, ModuleNotFoundError, ImportError):
            continue
    yield tmp_path
    bridge._reset_circuit()
    egress.reset()
    bridge.set_call_latency_budget(None)


@contextmanager
def _governed(monkeypatch: pytest.MonkeyPatch, projected: float = 0.002):
    ledger = {"reserve": MagicMock(return_value=4242), "settle": MagicMock(), "log_call": MagicMock()}

    def cfg(pid):
        return {"process_id": pid, "registered": True, "mode": "automated",
                "deepseek_allowed_policies": ["PRO", "PRO_THINK", "FAST", "FAST_THINK"],
                "max_input_tokens": 16000, "max_output_tokens": 2048, "daily_soft_cap": 40, "daily_cost_cap_usd": 1.0}
    monkeypatch.setattr("lib.llm_consumption.get_process_config", cfg)
    monkeypatch.setattr("lib.llm_consumption.reserve_projected_cost", ledger["reserve"])
    monkeypatch.setattr("lib.llm_consumption.settle_reservation", ledger["settle"])
    monkeypatch.setattr("lib.llm_consumption.check_cost_cap", lambda *a, **k: {"allow": True})
    monkeypatch.setattr("lib.llm_consumption.calibrated_projected_usd",
                        lambda *_a, **_k: {"projected_usd": projected, "basis": "test"})
    monkeypatch.setattr("lib.llm_consumption.log_call", ledger["log_call"])
    monkeypatch.setattr("lib.llm_model_registry.reject_legacy_model_id", lambda *_a, **_k: None)
    monkeypatch.setattr("lib.llm_model_registry.estimate_usd_cost",
                        lambda *_a, **_k: {"estimated_cost_usd": 0.0005, "cost_basis": "test"})
    monkeypatch.setattr("lib.consumption_run_manual.validate_paid_cap_config", lambda *_a, **_k: None)
    monkeypatch.setattr("lib.consumption_run_manual.projected_max_cost_usd", lambda *_a, **_k: projected)
    yield ledger


class FakeProvider:
    """Records what reached the provider; answers with `content` and optional `tool_calls`."""

    def __init__(self, content=None, tool_calls=None):
        self.calls: list[dict] = []
        self.content = content
        self.tool_calls = tool_calls

    def generate(self, messages, model_id, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs,
                           "deadline_s": bridge.effective_upstream_deadline_s()})
        msg = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return {"id": "prov", "object": "chat.completion", "created": 1, "model": model_id,
                "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}, "_tradeai": {}}


def _use(monkeypatch, provider, *, canary=False):
    if canary:
        monkeypatch.setattr(bridge, "BIND_MODE", "canary")
        monkeypatch.setattr(bridge.RealProvider, "instance", classmethod(lambda cls: provider))
    else:
        monkeypatch.setattr(bridge.MockProvider, "instance", classmethod(lambda cls: provider))
    return provider


def _report(tmp_path: Path) -> list[dict]:
    path = tmp_path / "egress_report.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def _all_samples() -> str:
    return "\n".join(s for group in SAMPLES.values() for s in group)


# ── P4: egress sanitiser ───────────────────────────────────────────────────

@pytest.mark.parametrize("category", sorted(SAMPLES))
def test_each_2a_category_is_caught_and_cannot_pass(category):
    for sample in SAMPLES[category]:
        out = egress.sanitise_for_external([{"role": "user", "content": f"context:\n{sample}\nend"}], "any_process")
        text = out["messages"][0]["content"]
        assert out["counts"].get(category, 0) >= 1, (category, out["counts"])
        assert sample not in text and f"[REDACTED:{category}]" in text


def test_permitted_working_set_passes_untouched_and_input_is_not_mutated():
    msgs = [{"role": "system", "content": PERMITTED}, {"role": "user", "content": [{"type": "text", "text": PERMITTED}]}]
    before = json.dumps(msgs)
    out = egress.sanitise_for_external(msgs, "alex_cio_synthesis")
    assert out["total"] == 0 and out["messages"] == msgs and json.dumps(msgs) == before
    # token-count prose is not a credential
    assert egress.sanitise_for_external([{"role": "user", "content": "max_tokens: 2048, prompt_tokens=120"}], "p")["total"] == 0


def test_content_parts_and_tool_call_arguments_are_scanned():
    msgs = [{"role": "user", "content": [{"type": "text", "text": FAKE_EMAIL}]},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function",
             "function": {"name": "runs_last", "arguments": json.dumps({"note": FAKE_SK})}}]}]
    out = egress.sanitise_for_external(msgs, "p")
    blob = json.dumps(out["messages"])
    assert FAKE_EMAIL not in blob and FAKE_SK not in blob and out["total"] == 2


def test_report_mode_is_default_sends_unchanged_and_records_counts_only(monkeypatch, hermetic):
    assert egress.egress_mode() == "report"
    provider = _use(monkeypatch, FakeProvider(content="ok"))
    msgs = [{"role": "user", "content": _all_samples()}]
    with _governed(monkeypatch):
        out = bridge.execute_governed_call(msgs, process_id="alex_cio_synthesis", request_id="req-report-1")
    assert "error" not in out, out.get("error")
    assert provider.calls[0]["messages"] == msgs                     # unchanged
    rows = _report(hermetic)
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == "EgressSanitiserReport@v1" and row["action"] == "reported" and row["sent_unchanged"] is True
    assert row["process_id"] == "alex_cio_synthesis" and row["request_id"] == "req-report-1"
    assert set(row["counts"]) == set(SAMPLES) and row["total"] >= len(SAMPLES)
    raw = (hermetic / "egress_report.jsonl").read_text()
    for sample in (s for group in SAMPLES.values() for s in group):
        assert sample not in raw                                     # no matched value
    assert "content" not in row and "messages" not in row
    assert out["_tradeai"]["egress_sanitiser"] == {"mode": "report", "action": "reported", "total": row["total"]}
    assert egress.snapshot()["by_process"]["alex_cio_synthesis"]["with_matches"] == 1


def test_enforce_mode_redacts_before_the_provider_and_records(monkeypatch, hermetic):
    monkeypatch.setenv(egress.MODE_ENV, "enforce")
    provider = _use(monkeypatch, FakeProvider(content="ok"))
    with _governed(monkeypatch):
        out = bridge.execute_governed_call([{"role": "user", "content": _all_samples()}], process_id="maria_research_critique")
    assert "error" not in out
    sent = json.dumps(provider.calls[0]["messages"])
    for sample in (s for group in SAMPLES.values() for s in group):
        assert sample not in sent
    assert _report(hermetic)[0]["action"] == "redacted" and _report(hermetic)[0]["sent_unchanged"] is False


def test_sanitiser_runs_for_every_process_including_n8n(monkeypatch, hermetic):
    _use(monkeypatch, FakeProvider(content=json.dumps(VALID_DIGEST)))
    with _governed(monkeypatch):
        for pid in (DIGEST, "alex_cio_synthesis", "advisory_desk_opinion"):
            out = bridge.execute_governed_call([{"role": "user", "content": FAKE_EMAIL}], process_id=pid)
            assert "error" not in out, (pid, out.get("error"))
    assert {r["process_id"] for r in _report(hermetic)} == {DIGEST, "alex_cio_synthesis", "advisory_desk_opinion"}


def test_off_mode_does_not_scan_and_clean_calls_write_nothing(monkeypatch, hermetic):
    _use(monkeypatch, FakeProvider(content="ok"))
    with _governed(monkeypatch):
        bridge.execute_governed_call([{"role": "user", "content": PERMITTED}], process_id="alex_cio_synthesis")
        monkeypatch.setenv(egress.MODE_ENV, "off")
        out = bridge.execute_governed_call([{"role": "user", "content": FAKE_SK}], process_id="alex_cio_synthesis")
    assert _report(hermetic) == []
    assert out["_tradeai"]["egress_sanitiser"]["action"] == "not_scanned"


def test_missing_policy_fails_closed_in_enforce_and_open_in_report(monkeypatch, hermetic):
    monkeypatch.setenv(egress.POLICY_ENV, str(hermetic / "absent-policy.json"))
    provider = _use(monkeypatch, FakeProvider(content="ok"))
    with _governed(monkeypatch) as ledger:
        served = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id="alex_cio_synthesis")
        assert "error" not in served and len(provider.calls) == 1
        monkeypatch.setenv(egress.MODE_ENV, "enforce")
        refused = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id="alex_cio_synthesis")
    assert refused["error"]["code"] == "EGRESS_POLICY_UNAVAILABLE" and refused["error"]["status"] == 503
    assert len(provider.calls) == 1                                   # nothing sent in enforce
    assert ledger["settle"].call_args.kwargs.get("ok") is False
    assert [r["action"] for r in _report(hermetic)] == ["policy_unavailable", "policy_unavailable"]


def test_policy_is_data_and_names_the_2a_permitted_set():
    doc = json.loads((ROOT / "config" / "egress_sanitiser_policy.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "EgressSanitiserPolicy@v1"
    assert {c["id"] for c in doc["categories"]} == set(SAMPLES)
    assert "symbol" in doc["permitted_to_external_provider"]
    pending = [c["id"] for c in doc["categories"] if c["class"] == "PENDING_OPERATOR_DECISION"]
    assert pending == ["position_dollars"]


def test_report_schema_is_classified():
    doc = json.loads((ROOT / "config" / "cio_surface_classification.json").read_text(encoding="utf-8"))
    entry = next(e for e in doc["entries"] if e["name"] == "schema:EgressSanitiserReport@v1")
    assert entry["classification"] == "NOT_OPERATOR_RELEVANT" and entry["reason"]


# ── P5: tool allowlist ─────────────────────────────────────────────────────

def _tool(name):
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object"}}}


def _call(fn_name, args=None):
    return [{"id": "c1", "type": "function", "function": {"name": fn_name, "arguments": json.dumps(args or {})}}]


def test_tools_false_refuses_request_tools_before_reservation(monkeypatch):
    provider = _use(monkeypatch, FakeProvider(content=json.dumps(VALID_DIGEST)))
    with _governed(monkeypatch) as ledger:
        out = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id=DIGEST, tools=[_tool("runs_last")])
    assert out["error"]["code"] == "TOOL_NOT_ALLOWED" and out["error"]["status"] == 400
    assert out["error"]["tools_refused"] == [{"name": "runs_last", "reason": "tools_not_allowed_for_process"}]
    assert ledger["reserve"].call_count == 0 and provider.calls == []


def test_allowlist_admits_named_tools_and_refuses_others_and_forbidden(monkeypatch):
    row = {"id": "n8n_agent_x", "tools_allowed": ["runs_last", "ledger_runs_read"], "advisory_only": True,
           "output_schema_id": "material_change_digest_draft/v1"}
    monkeypatch.setattr(gate, "registry_row", lambda pid: row)
    assert gate.request_tools_refusal("p", [_tool("runs_last")], "auto", row) is None
    bad = gate.request_tools_refusal("p", [_tool("runs_last"), _tool("explain_everything")], None, row)
    assert bad["code"] == "TOOL_NOT_ALLOWED" and bad["extra"]["tools_refused"][0]["reason"] == "not_in_allowlist"
    forb = gate.request_tools_refusal("p", [_tool("send_telegram")], None, row)
    assert forb["code"] == "TOOL_FORBIDDEN" and forb["extra"]["tools_refused"][0]["reason"] == "forbidden_token:send"
    choice = gate.request_tools_refusal("p", [_tool("runs_last")], {"type": "function", "function": {"name": "place_order"}}, row)
    assert choice["code"] == "TOOL_FORBIDDEN"
    # forbidden tokens win even if a row lists the name
    assert gate.request_tools_refusal("p", [_tool("broker_positions")], None, {"tools_allowed": ["broker_positions"]})["code"] == "TOOL_FORBIDDEN"


def test_model_tool_calls_outside_the_allowlist_are_refused_typed_not_dropped(monkeypatch):
    row = {"id": DIGEST, "tools_allowed": ["runs_last"], "advisory_only": True,
           "output_schema_id": "material_change_digest_draft/v1"}
    monkeypatch.setattr(gate, "registry_row", lambda pid: row)
    with _governed(monkeypatch) as ledger:
        _use(monkeypatch, FakeProvider(content=None, tool_calls=_call("postgres_query")))
        out = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id=DIGEST, tools=[_tool("runs_last")])
        assert out["error"]["code"] == "TOOL_CALL_REFUSED" and out["error"]["status"] == 422
        assert out["error"]["tool_calls_refused"][0]["name"] == "postgres_query"
        assert out["error"]["billed_cost_estimate"] == 0.0005 and ledger["settle"].call_count == 1
        _use(monkeypatch, FakeProvider(content=None, tool_calls=_call("runs_last", {"lane_id": "n8n-pilot-dispatch"})))
        ok = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id=DIGEST, tools=[_tool("runs_last")])
    assert "error" not in ok, ok.get("error")
    assert ok["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "runs_last"


def test_tools_true_rows_keep_todays_passthrough(monkeypatch):
    provider = _use(monkeypatch, FakeProvider(content=None, tool_calls=_call("get_financial_data")))
    with _governed(monkeypatch):
        out = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id="alex_cio_synthesis",
                                           tools=[_tool("get_financial_data")], tool_choice="auto")
    assert "error" not in out
    assert provider.calls[0]["kwargs"]["tools"] == [_tool("get_financial_data")]


def test_no_current_bridge_caller_sends_tools():
    """Every Python client that names itself to the bridge (X-TradeAI-Agent) sends no `tools`: the
    tools_allowed=false rows they map to (advisory_desk, cio_*, hermes_*, n8n_*) lose nothing."""
    clients = []
    for path in (ROOT / "scripts").rglob("*.py"):
        if path.name == "cio_governed_model_bridge.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "X-TradeAI-Agent" in text:
            clients.append(path)
            assert not re.search(r"""["']tools["']\s*:""", text), path
            assert "tool_choice" not in text, path
    assert len(clients) >= 5
    reg = {p["id"]: p for p in json.loads((ROOT / "config" / "llm_process_registry.json").read_text())["processes"]}
    mapped = set(bridge.CALLER_PROCESS_MAP.values()) | {p for m in bridge.CALLER_TASK_PROCESS_MAP.values() for p in m.values()}
    for pid in mapped:
        mode, _ = gate.tool_policy(reg.get(pid))
        caller_openclaw = pid in {"alex_cio_synthesis", "maria_research_critique", "steph_allocation_review",
                                  "guardian_risk_critique", "ledger_tax_critique", "morgan_wealth_synthesis"}
        assert mode == ("passthrough" if caller_openclaw else "none"), (pid, mode)


# ── P6: n8n output validation ──────────────────────────────────────────────

@pytest.mark.parametrize("content,code", [
    ("Here is the digest you asked for.", "OUTPUT_INVALID_JSON"),
    (json.dumps(["not", "an", "object"]), "OUTPUT_INVALID_JSON"),
    (json.dumps({k: v for k, v in VALID_DIGEST.items() if k != "headline"}), "OUTPUT_SCHEMA_INVALID"),
    (json.dumps({**VALID_DIGEST, "items": [{**VALID_DIGEST["items"][0], "qty": 100}]}), "OUTPUT_BEHAVIOUR_FIELD"),
    (json.dumps({**VALID_DIGEST, "Stop": 41.2}), "OUTPUT_BEHAVIOUR_FIELD"),
    (json.dumps({**VALID_DIGEST, "buy": True}), "OUTPUT_BEHAVIOUR_FIELD"),
    (json.dumps({**VALID_DIGEST, "recommendation": "BUY"}), "OUTPUT_RECOMMENDATION_FORBIDDEN"),
])
def test_n8n_output_is_schema_and_behaviour_checked(monkeypatch, content, code):
    _use(monkeypatch, FakeProvider(content=content))
    with _governed(monkeypatch) as ledger:
        out = bridge.execute_governed_call([{"role": "user", "content": "digest"}], process_id=DIGEST)
    assert out["error"]["code"] == code and out["error"]["status"] == 422, out["error"]
    assert out["error"]["output_schema_id"] == "material_change_digest_draft/v1"
    assert out["governance_pass"] is False and ledger["settle"].call_count == 1
    assert ledger["log_call"].call_args.kwargs["success"] is False


def test_valid_n8n_output_passes_and_is_stamped_advisory(monkeypatch):
    _use(monkeypatch, FakeProvider(content=json.dumps(VALID_DIGEST)))
    with _governed(monkeypatch):
        out = bridge.execute_governed_call([{"role": "user", "content": "digest"}], process_id=DIGEST)
    assert "error" not in out, out.get("error")
    meta = out["_tradeai"]
    assert meta["authority"] == "READ_ONLY_ADVISORY" and meta["recommendation"] == "NONE"
    assert meta["output_schema_id"] == "material_change_digest_draft/v1" and meta["output_validated"] is True


def test_ops_summary_uses_its_own_schema(monkeypatch):
    ops = {"headline": "ops", "sections": [{"area": "lanes", "summary": "ok"}], "open_items": [],
           "sources_cited": ["x"], "confidence_note": "stub", "recommendation": "NONE"}
    _use(monkeypatch, FakeProvider(content=json.dumps(ops)))
    with _governed(monkeypatch):
        assert "error" not in bridge.execute_governed_call([{"role": "user", "content": "o"}], process_id=OPS)
        _use(monkeypatch, FakeProvider(content=json.dumps(VALID_DIGEST)))
        assert bridge.execute_governed_call([{"role": "user", "content": "o"}], process_id=OPS)["error"]["code"] == "OUTPUT_SCHEMA_INVALID"


def test_other_processes_are_not_output_validated(monkeypatch):
    _use(monkeypatch, FakeProvider(content="Prose answer with qty and stop words, not JSON."))
    with _governed(monkeypatch):
        out = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id="alex_cio_synthesis")
    assert "error" not in out and "recommendation" not in out["_tradeai"]
    assert out["_tradeai"]["authority"] == "READ_ONLY_ADVISORY"     # registry advisory_only true


def test_n8n_row_without_schema_or_advisory_is_refused_before_reservation(monkeypatch):
    provider = _use(monkeypatch, FakeProvider(content=json.dumps(VALID_DIGEST)))
    with _governed(monkeypatch) as ledger:
        monkeypatch.setattr(gate, "registry_row", lambda pid: {"id": pid, "advisory_only": True, "tools_allowed": False})
        a = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id=DIGEST)
        monkeypatch.setattr(gate, "registry_row", lambda pid: {"id": pid, "advisory_only": False,
                                                               "output_schema_id": "ops_summary_draft/v1"})
        b = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id=DIGEST)
    assert a["error"]["code"] == "OUTPUT_SCHEMA_UNKNOWN" and b["error"]["code"] == "PROCESS_NOT_ADVISORY"
    assert ledger["reserve"].call_count == 0 and provider.calls == []


def test_behaviour_list_is_the_instrument_record_list():
    from lib.cio_instrument_record import BEHAVIOR_FIELDS
    assert gate.BEHAVIOR_FIELDS is BEHAVIOR_FIELDS
    for key in ("qty", "order", "stop", "limit", "trade", "size_usd", "target_weight_pct"):
        assert gate.behaviour_hits({"a": [{key: 1}]})


def test_registry_n8n_rows_declare_schema_and_advisory():
    reg = {p["id"]: p for p in json.loads((ROOT / "config" / "llm_process_registry.json").read_text())["processes"]}
    schemas = gate.load_output_schemas()
    for pid in (DIGEST, OPS):
        assert reg[pid]["advisory_only"] is True and reg[pid]["tools_allowed"] is False
        assert reg[pid]["output_schema_id"] in schemas


# ── P21: cost ceiling, latency budget ──────────────────────────────────────

def test_cost_ceiling_refuses_before_reservation(monkeypatch):
    provider = _use(monkeypatch, FakeProvider(content=json.dumps(VALID_DIGEST)))
    with _governed(monkeypatch, projected=0.25) as ledger:                 # n8n ceiling is 0.10
        out = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id=DIGEST)
    assert out["error"]["code"] == "COST_CEILING_EXCEEDED" and out["error"]["status"] == 429
    assert out["error"]["cost_ceiling_usd"] == 0.1 and out["error"]["retry"]["retryable"] is False
    assert ledger["reserve"].call_count == 0 and provider.calls == []


def test_latency_budget_is_the_provider_deadline(monkeypatch, hermetic):
    doc = json.loads((ROOT / "config" / "llm_routing_policy.json").read_text())
    doc["policies"]["default"]["processes"]["alex_cio_synthesis"]["latency_budget_ms"] = 5000
    path = hermetic / "routing.json"
    path.write_text(json.dumps(doc))
    monkeypatch.setenv("TRADEAI_LLM_ROUTING_POLICY", str(path))
    provider = _use(monkeypatch, FakeProvider(content="ok"))
    with _governed(monkeypatch):
        bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id="alex_cio_synthesis")
    assert provider.calls[0]["deadline_s"] == 5.0
    # the deadline the body reader uses when not told one
    bridge.set_call_latency_budget({"latency_budget_ms": 5000})

    class Resp:
        def iter_content(self, chunk_size=8192):
            yield b"x"

        def close(self):
            pass
    with pytest.raises(bridge.UpstreamDeadlineExceeded):
        bridge.read_body_with_deadline(Resp(), 0.0, clock=lambda: 6.0)
    bridge.set_call_latency_budget(None)
    assert bridge.read_body_with_deadline(Resp(), 0.0, clock=lambda: 6.0) == b"x"


def test_todays_latency_budgets_do_not_move_any_deadline():
    doc = json.loads((ROOT / "config" / "llm_routing_policy.json").read_text())
    for pid, row in doc["policies"]["default"]["processes"].items():
        bridge.set_call_latency_budget(row)
        assert bridge.effective_upstream_deadline_s() == bridge.UPSTREAM_DEADLINE_S, pid
        assert float(row["cost_ceiling_usd"]) > 0, pid
    bridge.set_call_latency_budget(None)
    assert bridge.effective_upstream_deadline_s() == bridge.UPSTREAM_DEADLINE_S


# ── Routing: n8n rows Grok -> ChatGPT -> DeepSeek ──────────────────────────

def test_only_n8n_rows_route_grok_chatgpt_deepseek_with_transport_failover():
    rows = json.loads((ROOT / "config" / "llm_routing_policy.json").read_text())["policies"]["default"]["processes"]
    for pid, row in rows.items():
        if pid.startswith("n8n_"):
            assert [row[k]["provider"] for k in ("primary", "secondary", "fallback")] == ["grok", "chatgpt", "deepseek"]
            assert row["transport_failover"] is True
        else:
            assert "transport_failover" not in row, pid


def test_canary_n8n_call_walks_to_deepseek_and_records_why(monkeypatch):
    provider = _use(monkeypatch, FakeProvider(content=json.dumps(VALID_DIGEST)), canary=True)
    with _governed(monkeypatch):
        out = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id=DIGEST)
    assert "error" not in out, out.get("error")
    decision = out["_tradeai"]["routing_decision"]
    assert out["_tradeai"]["provider"] == "deepseek" and decision["lane_chosen"] == "fallback"
    assert decision["reason"] == "transport_failover_fallback"
    assert [(s["provider"], s["reason"]) for s in decision["skipped_lanes"]] == [
        ("grok", "no_bridge_transport"), ("chatgpt", "no_bridge_transport")]
    assert len(provider.calls) == 1


def test_canary_non_opt_in_grok_row_keeps_provider_not_configured(monkeypatch):
    provider = _use(monkeypatch, FakeProvider(content="ok"), canary=True)
    with _governed(monkeypatch):
        out = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id="portfolio_ai_analyst")
    assert out["error"]["code"] == "provider_not_configured" and provider.calls == []


def test_canary_n8n_with_deepseek_indicted_refuses(monkeypatch, hermetic):
    health = hermetic / "health.json"
    health.write_text(json.dumps({"worst_severity": "CRITICAL", "findings": [
        {"lane": "deepseek", "kind": "BILLING", "severity": "CRITICAL"}]}))
    monkeypatch.setenv("TRADEAI_LLM_PROVIDER_HEALTH", str(health))
    provider = _use(monkeypatch, FakeProvider(content=json.dumps(VALID_DIGEST)), canary=True)
    with _governed(monkeypatch) as ledger:
        out = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id=DIGEST)
    assert out["error"]["code"] == "provider_not_configured" and provider.calls == []
    assert ledger["reserve"].call_count == 0


def test_policy_primary_is_grok_and_mock_receipt_names_the_live_provider(monkeypatch):
    policy = bridge.resolve_model_policy(DIGEST)
    assert policy["provider"] == "grok" and policy["requested_policy"] == "FAST"
    _use(monkeypatch, FakeProvider(content=json.dumps(VALID_DIGEST)))
    with _governed(monkeypatch):
        out = bridge.execute_governed_call([{"role": "user", "content": "x"}], process_id=DIGEST)
    assert out["_tradeai"]["provider"] == "deepseek" and out["_tradeai"]["mock"] is True
    assert out["_tradeai"]["routing_decision"]["reason"] == "transport_failover_fallback"
