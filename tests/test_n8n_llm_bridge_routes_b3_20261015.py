"""n8n llm lanes on the governed bridge, batch 3 (2026-10-15; AGENTS.md §23.4, §23.18, §23.25; operator D10).

Lanes: hermes-top20-external-intel and due-diligence-questions (through hermes_external_researcher's bridge mode,
process hermes_external_research; DDQ curation as process due_diligence_questions), llm-deferred-drain (bridge drain of
the bound process SET only), shadow-batch-generator-at-15-10 (blind first pass, process blind_review_runner).
Same pins as batches 1-2 (fixtures from tests/test_n8n_llm_bridge_routes_b1_20261015.py): routes on both sides,
bridge-acceptable rows, n8n_oauth_first rows; bridge only (provider modules poisoned); refusal = no output, no
fallback; dry run = no model call. Extra: the caller never picks a provider on the bridge, so per-lane fan-outs
(top20 --lanes, DDQ route ranking, blind pass lanes) collapse to ONE request; the paid claude researcher lane and the
DDQ operator escalation are unreachable on that path; the drain never honours a row's stored lane/model.

Hermetic: fake _call_bridge (no socket), fake DB, stub modules; no network, DB, subprocess, key or model call.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.test_n8n_llm_bridge_routes_b1_20261015 import (  # noqa: E402,F401 -- fixtures must be in scope
    REGISTRY,
    ROUTING,
    X,
    Conn,
    Poison,
    bind,
    bridge,
    poison,
    route,
)

import blind_review_runner as brr  # noqa: E402
import drain_llm_deferred as dld  # noqa: E402
import due_diligence_questions as ddq  # noqa: E402
import hermes_external_researcher as her  # noqa: E402
import hermes_top20_external_intel as top20  # noqa: E402

from scripts.lib import governed_process_routes as R  # noqa: E402

DDQ_SET = {"via": "cio-governed-bridge", "process_ids": ["due_diligence_questions", "hermes_external_research"]}
PROCESSES = ("hermes_external_research", "due_diligence_questions", "blind_review_runner")


@pytest.mark.parametrize("pid", PROCESSES)
def test_routed_on_both_sides_with_a_bridge_acceptable_row(pid):
    from scripts.lib import cio_governed_model_bridge as B
    from scripts.lib.consumption_run_manual import validate_paid_cap_config

    assert R.route_for_process(pid) == ("advisory_desk", pid)
    assert B.resolve_caller("advisory_desk", pid) == pid
    row = REGISTRY[pid]
    validate_paid_cap_config(row)
    assert row["tools_allowed"] is False and row["advisory_only"] is True
    assert {"grok", "chatgpt"} <= set(row["allowed_lanes"])
    rr = ROUTING[pid]
    assert [rr[k]["provider"] for k in ("primary", "secondary", "fallback")] == ["grok", "chatgpt", "deepseek"]
    assert rr["route_profile"] == B.OAUTH_FIRST_PROFILE


def test_blind_review_row_keeps_the_cron_calls_refused():
    assert REGISTRY["blind_review_runner"]["default_mode"] == "manual"


@pytest.mark.parametrize(
    "route_",
    [
        route("hermes_external_research"),
        DDQ_SET,
        route("blind_review_runner"),
        {"via": "cio-governed-bridge", "process_ids": ["hermes_external_research"]},
    ],
)
def test_lane_routes_validate(route_):
    entry = {
        "lane_id": "x",
        "command": ["$PY", "x.py"],
        "lock": "/tmp/x.lock",
        "timeout_s": 60,
        "dry_run_arg": ["--dry-run"],
        "live_arg": None,
        "market_gate": False,
        "output_signal": None,
        "env_names": [],
        "llm_route": route_,
    }
    assert X.validate_entry(entry) is None


# ── hermes_external_researcher bridge mode (top20 + DDQ --route child) ────────────────────────────────────────────


@pytest.fixture
def no_providers(monkeypatch):
    hits = []
    for name in ("call_codex_cli", "call_xai_proxy", "call_governed_deepseek", "_get_key", "urlopen_retry"):
        monkeypatch.setattr(her, name, lambda *a, _n=name, **k: hits.append(_n) or pytest.fail(f"{_n} reached"))
    return hits


@pytest.mark.parametrize("lane", ["chatgpt", "grok", "deepseek", "claude"])
def test_researcher_call_external_is_the_bridge_whatever_the_lane(lane, bridge, poison, no_providers, monkeypatch):
    bind(monkeypatch, route("hermes_external_research"))
    bridge.reply = '{"recommendation": "r"}'
    assert her.call_external(lane, "m", "prompt", max_tokens=1234) == '{"recommendation": "r"}'
    assert bridge.calls[0]["process_id"] == "hermes_external_research" and bridge.max_tokens == 1234
    assert no_providers == []


def test_researcher_refusal_raises_and_reaches_no_provider(bridge, poison, no_providers, monkeypatch):
    bind(monkeypatch, DDQ_SET)
    bridge.refuse = True
    with pytest.raises(Exception, match="BRIDGE_ROUTE_REFUSED"):
        her.call_external("grok", "m", "prompt")
    assert len(bridge.calls) == 1 and no_providers == []


def test_researcher_refuses_the_paid_claude_lane_on_the_bridge(bridge, poison, no_providers, monkeypatch):
    bind(monkeypatch, route("hermes_external_research"))
    events = []
    monkeypatch.setattr(her, "append_call_event", lambda event, **kw: events.append((event, kw.get("reason"))))
    monkeypatch.setattr(her, "_load_env", lambda: pytest.fail("env loaded"))
    monkeypatch.setattr(sys, "argv", ["her", "--lane", "claude", "--question", "q", "--apply"])
    her.main()
    assert ("SKIP_GATED", "CLAUDE_NOT_ON_GOVERNED_BRIDGE") in events and bridge.calls == []


# ── hermes-top20-external-intel ───────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def top(monkeypatch):
    spawned = []
    monkeypatch.setattr(top20, "_conn", lambda: Conn())
    monkeypatch.setattr(top20, "_top", lambda conn, n: [{"symbol": "AAA"}, {"symbol": "BBB"}])
    monkeypatch.setattr(top20, "_question", lambda r: "q?")
    monkeypatch.setattr(top20, "_trigger_context", lambda conn: {})
    monkeypatch.setattr(top20, "_trigger_for", lambda r, ctx: ("held", True))
    monkeypatch.setattr(top20, "_recent", lambda conn, sym, lane: False)
    monkeypatch.setattr(top20, "append_call_event", lambda *a, **k: None)
    monkeypatch.setitem(
        sys.modules,
        "hermes_research_budget_guard",
        types.SimpleNamespace(
            decide=lambda **k: {"decision": "ALLOW"}, _load_policy=lambda: {"trigger_source_tier": {}}
        ),
    )
    monkeypatch.setattr(
        top20.subprocess, "run", lambda argv, **k: spawned.append((argv, k)) or types.SimpleNamespace(returncode=0)
    )
    return spawned


def test_top20_fans_out_once_per_symbol_on_the_bridge(top, bridge, poison, monkeypatch):
    bind(monkeypatch, route("hermes_external_research"))
    rep = top20.run(lanes=("chatgpt", "grok"), apply=True)
    assert rep["lanes"] == ["chatgpt"] and rep["called"] == 2 and len(top) == 2
    for argv, kw in top:
        assert "env" not in kw  # the child inherits the executor's bridge binding
        assert argv[argv.index("--lane") + 1] == "chatgpt"


def test_top20_cron_fan_out_unchanged(top, bridge, monkeypatch):
    for name in (X.LLM_BRIDGE_ENV, X.LLM_PROCESS_ENV, X.LLM_PROCESS_SET_ENV):
        monkeypatch.delenv(name, raising=False)
    rep = top20.run(lanes=("chatgpt", "grok"), apply=True)
    assert rep["lanes"] == ["chatgpt", "grok"] and len(top) == 4


def test_top20_dry_run_starts_no_researcher(top, bridge, poison, monkeypatch):
    bind(monkeypatch, route("hermes_external_research"))
    assert top20.main(["--dry-run", "--apply"]) == 0 and top == [] and bridge.calls == []


# ── due-diligence-questions ───────────────────────────────────────────────────────────────────────────────────────

CHANGE = {
    "symbol": "AOUT",
    "kind": "news_spike",
    "observed_value": 64,
    "baseline": 4,
    "magnitude": 16,
    "observed_at": "2026-10-15",
}
ITEMS = [{"id": "n1", "date": "2026-10-14", "text": "item"}]


def test_ddq_curation_is_one_bridge_request(bridge, poison, no_providers, monkeypatch):
    bind(monkeypatch, DDQ_SET)
    monkeypatch.setitem(sys.modules, "lib.llm_escalation", Poison("lib.llm_escalation"))
    bridge.reply = json.dumps({"narrative": [{"sentence": "s", "cites": ["n1"]}], "questions": []})
    got = ddq.ask_model(CHANGE, ITEMS)
    assert got["lane"] == "bridge" and got["parsed"]["narrative"][0]["cites"] == ["n1"]
    assert [c["process_id"] for c in bridge.calls] == ["due_diligence_questions"]
    assert sys.modules["lib.llm_escalation"].touched == []


def test_ddq_refusal_raises_no_ladder_no_escalation(bridge, poison, no_providers, monkeypatch):
    bind(monkeypatch, DDQ_SET)
    monkeypatch.setitem(sys.modules, "lib.llm_escalation", Poison("lib.llm_escalation"))
    monkeypatch.setattr(ddq, "_curate_via_deepseek", lambda *a: pytest.fail("flash ladder reached"))
    monkeypatch.setattr(ddq, "_curate_via_oauth", lambda *a: pytest.fail("oauth ladder reached"))
    bridge.refuse = True
    with pytest.raises(Exception, match="BRIDGE_ROUTE_REFUSED"):
        ddq.ask_model(CHANGE, ITEMS)
    assert len(bridge.calls) == 1 and sys.modules["lib.llm_escalation"].touched == []


def test_ddq_route_asks_the_researcher_once_per_question(bridge, poison, monkeypatch):
    bind(monkeypatch, DDQ_SET)
    spawned = []

    class RCur:
        def __init__(self):
            self.q = []

        def execute(self, sql, params=None):
            self.q.append(" ".join(sql.split())[:40])

        def fetchall(self):
            return [("g1", "AOUT", "what changed?")]

        def fetchone(self):
            return (1,)

    monkeypatch.setattr(ddq, "rank_research_lanes", lambda cur: [("chatgpt", 0.9, 0.8), ("grok", 0.8, 0.7)])
    monkeypatch.setattr(
        ddq.subprocess,
        "run",
        lambda cmd, **k: spawned.append((cmd, k)) or types.SimpleNamespace(returncode=0, stderr=""),
    )
    out = ddq.route(RCur(), 2)
    assert out["lanes_ranked"] == ["chatgpt"] and out["routed"] == 1 and len(spawned) == 1
    assert "env" not in spawned[0][1]


def test_ddq_dry_run_makes_no_model_call(bridge, poison, monkeypatch):
    bind(monkeypatch, DDQ_SET)
    monkeypatch.setattr(ddq, "_db", lambda: pytest.fail("db opened"))
    assert ddq.main(["--dry-run", "--apply", "--route"]) == 0 and bridge.calls == []


# ── llm-deferred-drain ────────────────────────────────────────────────────────────────────────────────────────────

DRAIN_SET = {"via": "cio-governed-bridge", "process_ids": ["hermes_external_research"]}


@pytest.fixture
def queue(monkeypatch):
    q = types.SimpleNamespace(claims=[], completed=[])

    def claim_due(limit=25, now=None, process_ids=None):
        q.claims.append(process_ids)
        return [
            {
                "id": "u1",
                "process_id": "hermes_external_research",
                "lane": "deepseek-pro",
                "prompt": "deferred prompt",
                "payload": {"model": "deepseek-pro", "max_tokens": 900},
            }
        ]

    fake = types.SimpleNamespace(
        reclaim_stale=lambda: {"returned": 0},
        expire_stale=lambda: 0,
        queue_summary=lambda: {"pending": 1},
        claim_due=claim_due,
        complete=lambda rid, ok, error=None: q.completed.append((rid, ok, error)),
    )
    lib_mod = sys.modules.get("lib") or __import__("lib")
    monkeypatch.setattr(lib_mod, "llm_deferral", fake, raising=False)
    monkeypatch.setitem(sys.modules, "lib.llm_deferral", fake)
    monkeypatch.setitem(
        sys.modules, "lib.deepseek_offpeak", types.SimpleNamespace(is_scheduled_deepseek_window=lambda: True)
    )
    monkeypatch.setitem(sys.modules, "lib.llm_consumption", Poison("lib.llm_consumption"))
    monkeypatch.setattr(dld, "_receipt", lambda *a, **k: None)
    monkeypatch.setattr(dld, "_write_heartbeat", lambda payload: None)
    return q


def test_drain_on_the_bridge_leases_only_the_bound_set_and_ignores_the_rows_lane(queue, bridge, poison, monkeypatch):
    bind(monkeypatch, DRAIN_SET)
    bridge.reply = "answer"
    assert dld.main([]) == 0
    assert queue.claims == [["hermes_external_research"]]
    assert bridge.calls == [{"process_id": "hermes_external_research", "timeout_s": 180, "prompt": "deferred prompt"}]
    assert bridge.max_tokens == 900 and queue.completed == [("u1", True, None)]
    assert sys.modules["lib.llm_consumption"].touched == []  # gate_and_generate never imported


def test_drain_refusal_fails_the_row_only(queue, bridge, poison, monkeypatch):
    bind(monkeypatch, DRAIN_SET)
    bridge.refuse = True
    assert dld.main([]) == 1
    assert queue.completed[0][:2] == ("u1", False) and "BRIDGE_ROUTE_REFUSED" in queue.completed[0][2]
    assert sys.modules["lib.llm_consumption"].touched == []


def test_drain_dry_run_claims_nothing(queue, bridge, poison, monkeypatch):
    bind(monkeypatch, DRAIN_SET)
    assert dld.main(["--dry-run"]) == 0 and queue.claims == [] and bridge.calls == []


def test_claim_due_filter_is_opt_in(monkeypatch):
    from lib import llm_deferral as real

    seen = []
    monkeypatch.setattr(real, "ensure_schema", lambda: None)
    monkeypatch.setitem(
        sys.modules,
        "db_adapter",
        types.SimpleNamespace(
            _execute=lambda sql, params, fetch=None: seen.append((" ".join(sql.split()), params)) or []
        ),
    )
    real.claim_due(limit=3)
    real.claim_due(limit=3, process_ids=["b", "a", "a"])
    assert "process_id = ANY" not in seen[0][0] and len(seen[0][1]) == 3
    assert "process_id = ANY(%s)" in seen[1][0] and seen[1][1][2] == ["a", "b"]


# ── shadow-batch-generator-at-15-10 (blind first pass) ────────────────────────────────────────────────────────────


@pytest.fixture
def blind(monkeypatch):
    monkeypatch.setattr(brr.br, "assert_blind", lambda facts: None)
    monkeypatch.setattr(brr.br, "build_blind_prompt", lambda facts: "BLIND PROMPT")
    monkeypatch.setattr(brr.br, "measure_agreement", lambda completed: {"dimensions": {}})
    monkeypatch.setattr(brr.br, "consensus_badge", lambda agreement, blind=True: "badge")
    monkeypatch.setattr(brr, "_sanitise", lambda parsed: parsed)


def test_blind_pass_is_one_bridge_request_and_single_lane(blind, bridge, poison, monkeypatch):
    bind(monkeypatch, route("blind_review_runner"))
    bridge.reply = json.dumps({"thesis": "up"})
    out = brr.run_blind_pass({"symbol": "AAA"}, lanes=("deepseek-flash", "grok", "chatgpt"))
    assert out["lanes_requested"] == ["bridge"] and out["mode"] == "SINGLE_LANE"
    assert [c["process_id"] for c in bridge.calls] == ["blind_review_runner"]


def test_blind_refusal_is_unavailable(blind, bridge, poison, monkeypatch):
    bind(monkeypatch, route("blind_review_runner"))
    bridge.refuse = True
    out = brr.run_blind_pass({"symbol": "AAA"})
    assert out["mode"] == "UNAVAILABLE" and out["lanes_completed"] == [] and len(bridge.calls) == 1


def test_shadow_batch_dry_run_spends_nothing(bridge, poison, monkeypatch, capsys):
    import shadow_batch_generator as sbg

    bind(monkeypatch, route("blind_review_runner"))
    monkeypatch.setattr(sbg, "run", lambda **k: pytest.fail("dry run reached run"))
    monkeypatch.setattr(sbg, "select_targets", lambda *a, **k: pytest.fail("dry run selected targets"))
    assert sbg.main(["--dry-run", "--run", "--top", "100"]) == 0 and bridge.calls == []
    assert "DRY-RUN shadow-batch-generator-at-15-10" in capsys.readouterr().out


def test_registered_in_the_cio_hardening_gates():
    from scripts.lib import ci_gates  # gates: one file per gate under config/ci_gates/ (2026-10-21)
    text = ci_gates.registry_text(ROOT)
    assert "tests/test_n8n_llm_bridge_routes_b3_20261015.py" in text
