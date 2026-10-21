"""n8n llm lanes on the governed bridge, batch 2 (2026-10-15; AGENTS.md §23.4, §23.18, §23.25; operator D10).

Lanes: portfolio-lookthrough-themes, hermes-analyst-coverage, hermes-usefulness-backfill, proposal-llm-review-worker,
defense-weekly-paid-review, generate-analyst-reports-autonomous-weekly / -full (process SET analyst_report_editorial +
analyst_report_critique). Same pins as batch 1 (tests/test_n8n_llm_bridge_routes_b1_20261015.py, whose fixtures this
file reuses): both route maps + bridge-acceptable registry row + n8n_oauth_first routing row; with the executor's
binding the lane calls ONLY the governed bridge (provider modules are recording poison); a refusal is no output and no
fallback; the dry run makes no model call. Extra: the cron line's own bridge process (hermes_usefulness_score) keeps
its DeepSeek-only routing row; the metered Claude arbiter and the paid defense seat are never reachable on the n8n path.

Hermetic: fake _call_bridge (no socket), fake DB cursors, stub modules. No network, DB, key or model call.
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
    Cur,
    Poison,
    bind,
    bridge,
    poison,
    route,
)

import defense_oversight as do  # noqa: E402
import defense_weekly_paid_review as dwr  # noqa: E402
import generate_analyst_reports_autonomous as gara  # noqa: E402
import hermes_analyst_coverage as hac  # noqa: E402
import hermes_external_feedback_loop as hefl  # noqa: E402
import portfolio_lookthrough_themes as plt  # noqa: E402
import proposal_llm_reviewer as plr  # noqa: E402
import report_oversight as ro  # noqa: E402
import reporting_engine as reng  # noqa: E402

from scripts.lib import governed_process_routes as R  # noqa: E402

ANALYST_SET = {"via": "cio-governed-bridge", "process_ids": ["analyst_report_editorial", "analyst_report_critique"]}
PROCESSES = {
    "portfolio_lookthrough_themes": route("portfolio_lookthrough_themes"),
    "hermes_analyst_coverage": route("hermes_analyst_coverage"),
    "hermes_usefulness_score_n8n": route("hermes_usefulness_score_n8n"),
    "proposal_llm_review": route("proposal_llm_review"),
    "defense_weekly_oversight": route("defense_weekly_oversight"),
    "analyst_report_editorial": ANALYST_SET,
    "analyst_report_critique": ANALYST_SET,
}


# ── registration ──────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("pid", sorted(PROCESSES))
def test_routed_on_both_sides_with_a_bridge_acceptable_row(pid):
    from scripts.lib import cio_governed_model_bridge as B
    from scripts.lib.consumption_run_manual import validate_paid_cap_config

    assert R.route_for_process(pid) == ("advisory_desk", pid)
    assert B.resolve_caller("advisory_desk", pid) == pid
    row = REGISTRY[pid]
    validate_paid_cap_config(row)
    assert row["tools_allowed"] is False and row["advisory_only"] is True and row["reasoning_tier"] == "standard"
    rr = ROUTING[pid]
    assert [rr[k]["provider"] for k in ("primary", "secondary", "fallback")] == ["grok", "chatgpt", "deepseek"]
    assert rr["route_profile"] == B.OAUTH_FIRST_PROFILE and rr["transport_failover"] is True


@pytest.mark.parametrize("pid", sorted(PROCESSES))
def test_the_lane_route_validates_and_binds(pid):
    entry = {"lane_id": "x", "env_names": [], "llm_route": PROCESSES[pid]}
    assert (
        X.validate_entry(
            {
                **entry,
                "command": ["$PY", "x.py"],
                "lock": "/tmp/x.lock",
                "timeout_s": 60,
                "dry_run_arg": ["--dry-run"],
                "live_arg": None,
                "market_gate": False,
                "output_signal": None,
            }
        )
        is None
    )
    env, _ = X.build_child_env({"PATH": "/usr/bin"}, "x", entry)
    assert env[X.LLM_BRIDGE_ENV] == "1"


def test_the_cron_lines_own_bridge_process_keeps_its_route():
    """hermes_usefulness_score is called through the bridge by the CRON line today (advisory_desk/usefulness_score):
    its DeepSeek-only row must not move. The n8n path has its own id."""
    row = ROUTING["hermes_usefulness_score"]
    assert row["primary"]["provider"] == "deepseek" and "route_profile" not in row
    assert R.route_for_process("hermes_usefulness_score") == ("advisory_desk", "usefulness_score")


# ── portfolio-lookthrough-themes ──────────────────────────────────────────────────────────────────────────────────

LT = {"portfolio_total": 1000.0, "themes": {"AI": {"pct": 30.0}}, "top_underlying": [{"symbol": "NVDA", "pct": 9.0}]}


def test_lookthrough_via_bridge(bridge, poison, monkeypatch):
    bind(monkeypatch, PROCESSES["portfolio_lookthrough_themes"])
    bridge.reply = '{"text": "Concentrated in AI."}'
    assert plt.grok_narrative(LT) == "Concentrated in AI."
    adv = plt.agent_advisories(LT)
    assert [a["agent"] for a in adv] == ["CIO", "Risk Agent", "Steph · Allocation"]
    assert {a["model"] for a in adv} == {"governed-bridge"}
    assert {c["process_id"] for c in bridge.calls} == {"portfolio_lookthrough_themes"} and len(bridge.calls) == 4


def test_lookthrough_refusal_is_empty(bridge, poison, monkeypatch):
    bind(monkeypatch, PROCESSES["portfolio_lookthrough_themes"])
    bridge.refuse = True
    assert plt.grok_narrative(LT) == "" and plt.agent_advisories(LT) == [] and len(bridge.calls) == 4


def test_lookthrough_dry_run_makes_no_model_call(bridge, poison, monkeypatch, capsys):
    bind(monkeypatch, PROCESSES["portfolio_lookthrough_themes"])
    assert plt.main(["--dry-run", "--grok"]) == 0 and bridge.calls == []


# ── hermes-analyst-coverage ───────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def coverage(monkeypatch):
    conn = Conn()
    conn.cursor = lambda *a, **k: Cur(conn.log)
    monkeypatch.setattr(hac, "_conn", lambda: conn)
    monkeypatch.setattr(
        hac,
        "_candidates",
        lambda cur, limit, thin, symbols=None: [
            {"symbol": "MRLN", "description_1s": "Marlin Inc.", "industry": "biotech"}
        ],
    )
    # Required CI has no psycopg2: stand in for the package too (per test, so nothing leaks to later modules).
    _extras = types.SimpleNamespace(RealDictCursor=object)
    if "psycopg2" not in sys.modules:
        monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(extras=_extras))
    elif not hasattr(sys.modules["psycopg2"], "extras"):  # another module's stand-in (e.g. seed-sync tests)
        monkeypatch.setattr(sys.modules["psycopg2"], "extras", _extras, raising=False)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", _extras)
    return conn


def test_analyst_coverage_via_bridge(coverage, bridge, poison, monkeypatch):
    bind(monkeypatch, PROCESSES["hermes_analyst_coverage"])
    bridge.reply = json.dumps({"coverage_found": True, "consensus_label": "buy", "mean_target": 12, "ratings": []})
    assert hac.run(apply=True) == 0
    assert [c["process_id"] for c in bridge.calls] == ["hermes_analyst_coverage"]
    assert coverage.writes()[0].startswith("INSERT INTO analyst_consensus_history")


def test_analyst_coverage_refusal_inserts_nothing_and_tries_no_other_lane(coverage, bridge, poison, monkeypatch):
    bind(monkeypatch, PROCESSES["hermes_analyst_coverage"])
    bridge.refuse = True
    assert hac.run(apply=True) == 1 and coverage.writes() == [] and len(bridge.calls) == 1


def test_analyst_coverage_dry_run_makes_no_model_call(coverage, bridge, poison, monkeypatch):
    bind(monkeypatch, PROCESSES["hermes_analyst_coverage"])
    assert hac.run(apply=False) == 0 and bridge.calls == []
    assert hac.main(["--dry-run", "--limit", "8", "--apply"]) == 0 and bridge.calls == []


# ── hermes-usefulness-backfill ────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def failover(monkeypatch):
    calls = []
    import hermes_llm_failover as real

    stub = types.SimpleNamespace(
        _extract_json_text=real._extract_json_text, chat_json=lambda *a, **k: calls.append(k) or {"content": "{}"}
    )
    monkeypatch.setitem(sys.modules, "hermes_llm_failover", stub)
    return calls


def test_usefulness_via_bridge_uses_the_n8n_process_not_the_cron_one(failover, bridge, poison, monkeypatch):
    bind(monkeypatch, PROCESSES["hermes_usefulness_score_n8n"])
    bridge.reply = '```json\n{"usefulness": 0.7, "rationale": "specific"}\n```'
    u, why, pack = hefl._rate("q", "rec", "d", None)
    assert (u, why, pack["provider"]) == (0.7, "specific", "governed_bridge")
    assert [c["process_id"] for c in bridge.calls] == ["hermes_usefulness_score_n8n"] and failover == []


def test_usefulness_refusal_is_terminal(failover, bridge, poison, monkeypatch):
    bind(monkeypatch, PROCESSES["hermes_usefulness_score_n8n"])
    bridge.refuse = True
    with pytest.raises(Exception) as exc:
        hefl._rate("q", "rec", "d", None)
    assert hefl._is_terminal(str(exc.value)) and failover == []


def test_usefulness_cron_path_unchanged(failover, bridge, monkeypatch):
    for name in (X.LLM_BRIDGE_ENV, X.LLM_PROCESS_ENV, X.LLM_PROCESS_SET_ENV):
        monkeypatch.delenv(name, raising=False)
    sys.modules["hermes_llm_failover"].chat_json = lambda *a, **k: (
        failover.append(k) or {"content": '{"usefulness": 0.4}', "provider": "bridge_flash", "model": "deepseek-flash"}
    )
    assert hefl._rate("q", "rec", "d", None)[0] == 0.4
    assert failover == [{"cloud_timeout_s": 120, "task_type": "usefulness_score"}] and bridge.calls == []


def test_usefulness_dry_run_makes_no_model_call(bridge, poison, monkeypatch):
    bind(monkeypatch, PROCESSES["hermes_usefulness_score_n8n"])
    monkeypatch.setattr(hefl, "_load_env", lambda: pytest.fail("dry run loaded env"))
    assert hefl.main(["--dry-run", "--apply"]) == 0 and bridge.calls == []


# ── proposal-llm-review-worker ────────────────────────────────────────────────────────────────────────────────────

PROPOSAL_COLS = [
    "id",
    "symbol",
    "strategy_id",
    "proposed_entry",
    "proposed_stop",
    "proposed_target1",
    "proposed_shares",
    "proposed_rr",
    "rvol",
    "float_m",
    "gap_pct",
    "catalyst",
    "catalyst_verified",
    "catalyst_confidence",
    "critic_verdict",
    "critic_confidence",
    "critic_reasoning",
    "sector",
    "proposed_account",
    "technical_context",
    "backtest_summary",
    "stock_history_summary",
]


@pytest.fixture
def proposal(monkeypatch):
    conn = Conn()

    class PCur(Cur):
        description = [(c,) for c in PROPOSAL_COLS]

        def fetchone(self):
            return tuple([7, "AAA"] + [None] * (len(PROPOSAL_COLS) - 2))

    conn.cursor = lambda *a, **k: PCur(conn.log)
    for fn in (
        "_build_data_summary",
        "_build_analysis_prompt",
        "_build_decision_prompt",
        "_build_risk_prompt",
        "_build_catalyst_prompt",
    ):
        monkeypatch.setattr(plr, fn, lambda *a, **k: "PROMPT")
    return conn


def test_proposal_review_via_bridge(proposal, bridge, poison, monkeypatch):
    bind(monkeypatch, PROCESSES["proposal_llm_review"])
    bridge.reply = json.dumps({"decision": "CAUTIOUS_TEST", "confidence_score": 55, "summary": "s"})
    out = plr.review_proposal(proposal, 7)
    assert out["success"] and out["model"] == "governed-bridge"
    assert [c["process_id"] for c in bridge.calls] == ["proposal_llm_review"] * 4


def test_proposal_refusal_writes_no_deterministic_stand_in(proposal, bridge, poison, monkeypatch):
    bind(monkeypatch, PROCESSES["proposal_llm_review"])
    bridge.refuse = True
    monkeypatch.setattr(plr, "_deterministic_review", lambda *a: pytest.fail("deterministic stand-in written"))
    out = plr.review_proposal(proposal, 7)
    assert out["error"].startswith("BRIDGE_ROUTE_REFUSED") and proposal.writes() == [] and len(bridge.calls) == 1


def test_proposal_worker_dry_run_and_no_local_warmup_on_the_bridge_path(bridge, poison, monkeypatch):
    import proposal_llm_review_worker as w

    bind(monkeypatch, PROCESSES["proposal_llm_review"])
    assert w.main(["--dry-run", "--run"]) == 0 and bridge.calls == []
    src = (ROOT / "scripts/proposal_llm_review_worker.py").read_text()
    assert src.index("TRADEAI_LLM_VIA_BRIDGE") < src.index("from local_llm import warmup_ollama")


# ── defense-weekly-paid-review ────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def defense(monkeypatch):
    log = []

    class DCur(Cur):
        def __init__(self):
            super().__init__(log)
            self.connection = types.SimpleNamespace(commit=lambda: None)
            self.n = 0

        def fetchone(self):
            self.n += 1
            return None if self.n == 1 else (0,)

    monkeypatch.setattr(do, "ensure_tables", lambda cur: None)
    monkeypatch.setattr(
        do,
        "build_oversight_brief",
        lambda: {"build_hash": "h1", "token_estimate": 10, "markdown": "brief", "brief": {"cards": [{"id": "c1"}]}},
    )
    return DCur, log


REVIEW = {
    "cards": [{"id": "c1", "verdict": "CONCUR", "reason": "ok", "missed_risk": None}],
    "memo": {"top_concerns": [], "incoherences": [], "blind_spots": [], "strongest_objection": "none"},
}


def test_defense_weekly_seat_via_bridge(defense, bridge, poison, monkeypatch):
    DCur, log = defense
    bind(monkeypatch, PROCESSES["defense_weekly_oversight"])
    bridge.reply = json.dumps(REVIEW)
    out = do.run_free_critiques(DCur(), force=True, seats=["chatgpt"])
    assert out["seats"] == {"chatgpt": "ok"} and bridge.max_tokens == 4096
    assert [c["process_id"] for c in bridge.calls] == ["defense_weekly_oversight"]


def test_defense_refusal_is_an_unavailable_status_row(defense, bridge, poison, monkeypatch):
    DCur, log = defense
    bind(monkeypatch, PROCESSES["defense_weekly_oversight"])
    bridge.refuse = True
    assert do.run_free_critiques(DCur(), force=True, seats=["chatgpt"])["seats"] == {"chatgpt": "unavailable"}
    assert len(bridge.calls) == 1


def test_defense_paid_seat_and_dry_run_on_the_bridge_path(bridge, poison, monkeypatch, capsys):
    bind(monkeypatch, PROCESSES["defense_weekly_oversight"])
    assert dwr.main(["--apply-paid"], do=Poison("do"), get_conn=lambda: pytest.fail("conn")) == 2
    assert dwr.main(["--dry-run"], do=Poison("do"), get_conn=lambda: pytest.fail("conn")) == 0
    assert bridge.calls == []


# ── generate-analyst-reports-autonomous-weekly / -full ────────────────────────────────────────────────────────────


def _report():
    return {
        "meta": {"symbol": "AAA", "kpis": {}},
        "sections": [
            {"id": "executive_summary", "content": "AAA holds up."},
            {"id": "recommendation", "content": "Hold."},
        ],
    }


def test_editorial_via_bridge_and_refusal(bridge, poison, monkeypatch):
    bind(monkeypatch, ANALYST_SET)
    bridge.reply = json.dumps({"executive_summary": "AAA remains resilient.", "editor_notes": "tightened"})
    rep = reng.apply_grok_editorial(_report())
    assert rep["meta"]["grok_editorial"]["applied"] is True and rep["meta"]["grok_editorial"]["lane"] == "bridge"
    assert rep["sections"][0]["content"] == "AAA remains resilient."
    bridge.refuse = True
    rep = reng.apply_grok_editorial(_report())
    assert rep["meta"]["grok_editorial"]["applied"] is False and rep["sections"][0]["content"] == "AAA holds up."
    assert [c["process_id"] for c in bridge.calls] == ["analyst_report_editorial"] * 2


def test_critique_is_one_bridge_request_and_claude_never_runs(bridge, poison, monkeypatch):
    bind(monkeypatch, ANALYST_SET)
    monkeypatch.setitem(sys.modules, "hermes_external_researcher", Poison("hermes_external_researcher"))
    bridge.reply = json.dumps({"fabrications": ["x"]})
    crit = ro.free_lane_critique(_report(), {"price": 1}, "bridge")
    assert crit["available"] and crit["fabrications"] == ["x"]
    assert ro._call_lane("claude", "p") == "" and ro._call_lane("grok", "p") == ""
    assert ro._should_run_claude(_report(), [crit], requested=True, cadence="monthly") == (
        False,
        "governed_bridge_no_claude_lane",
    )
    assert [c["process_id"] for c in bridge.calls] == ["analyst_report_critique"]
    assert sys.modules["hermes_external_researcher"].touched == []


def test_critique_refusal_is_no_critique(bridge, poison, monkeypatch):
    bind(monkeypatch, ANALYST_SET)
    bridge.refuse = True
    crit = ro.free_lane_critique(_report(), {}, "bridge")
    assert crit["fabrications"] == [] and crit["section_grades"] == {} and len(bridge.calls) == 1


def test_analyst_reports_dry_run_makes_no_model_call(bridge, poison, monkeypatch, capsys):
    bind(monkeypatch, ANALYST_SET)
    for mode in ("weekly", "full"):
        assert gara.main(["--mode", mode, "--dry-run"]) == 0
    assert bridge.calls == []


def test_registered_in_the_cio_hardening_gates():
    text = (ROOT / "scripts" / "run_cio_hardening_ci.py").read_text(encoding="utf-8")
    assert "tests/test_n8n_llm_bridge_routes_b2_20261015.py" in text
