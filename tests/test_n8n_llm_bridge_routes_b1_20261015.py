"""n8n llm lanes on the governed bridge, batch 1 (2026-10-15; AGENTS.md §23.4, §23.18, §23.25; operator D10).

Operator D10 (verbatim): "in terms of n8n, then, we should try OAuth first. And if OAuth fails or if the answer needs
higher reasoning, then we go to DeepSeek."

Pins, per lane (watchlist-entry-planner-limit/-scope, holdings-llm-refresh, hermes-cross-source-synthesizer,
incubator-llm-screener, directive-keyword-enhancer, journal-review-builder, run-research-intelligence-overnight):
  * the process has a cio-governed-bridge route on BOTH sides (governed_process_routes + the bridge's server map),
    a registry row the bridge accepts (daily_cost_cap_usd + daily_soft_cap, tools_allowed false, advisory_only) and
    an n8n_oauth_first routing row (grok -> chatgpt -> DeepSeek FAST; reasoning lane DeepSeek PRO_THINK);
  * with the executor's binding (TRADEAI_LLM_VIA_BRIDGE=1 + the bound process / process SET) the lane calls ONLY the
    governed bridge: llm_lane (every provider client) is never touched;
  * a bridge refusal is NO output (no UPDATE / INSERT / write) and never a fallback to an in-process provider,
    another lane or a local model;
  * the dry run makes no model call; without the flag the cron path is the unchanged in-process path.
Infrastructure: a compound lane declares llm_route.process_ids (the executor validates every id and binds the SET;
lib/llm_bridge_route refuses any process outside it); lib.governed_cloud_generation's bridge branch.

Hermetic: the fake bridge replaces lib.llm_bridge_route._call_bridge (no socket); llm_lane is a recording poison
module; fake DB connections. No network, DB, key, token store or model call.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # pragma: no cover - required CI has no psycopg2; the scripts only import it inside get_db
    import psycopg2  # noqa: F401
    import psycopg2.extras  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")
    _pg_extras = types.ModuleType("psycopg2.extras")
    _pg_extras.RealDictCursor = object
    _pg.extras = _pg_extras
    _pg.connect = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("psycopg2 stub"))
    sys.modules.setdefault("psycopg2", _pg)
    sys.modules.setdefault("psycopg2.extras", _pg_extras)

import directive_keyword_enhancer as dke  # noqa: E402
import hermes_cross_source_synthesizer as hcs  # noqa: E402
import holdings_llm_refresh as hlr  # noqa: E402
import incubator_llm_screener as ils  # noqa: E402
import journal_review_builder as jrb  # noqa: E402
import research_intelligence_narrative_enrich as rine  # noqa: E402
import topic_research_synthesizer as trs  # noqa: E402
import watchlist_entry_planner as wep  # noqa: E402
from lib import governed_cloud_generation as gcg  # noqa: E402
from lib import llm_bridge_route as LBR  # noqa: E402

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import governed_process_routes as R  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402

REGISTRY = {p["id"]: p for p in json.loads((ROOT / "config/llm_process_registry.json").read_text())["processes"]}
ROUTING = json.loads((ROOT / "config/llm_routing_policy.json").read_text())["policies"]["default"]["processes"]
ALLOW_DOC = json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())
ALLOW = {e["lane_id"]: e for e in ALLOW_DOC["lanes"]}

RI_SET = ["topic_ingestion", "ri_narrative_enrich", "topic_research_synthesizer"]
#: process -> lane(s) it serves on the n8n path
PROCESSES = {
    "watchlist_entry_planner": "watchlist-entry-planner-limit / -scope",
    "holdings_llm_refresh": "holdings-llm-refresh",
    "hermes_cross_source_synthesizer": "hermes-cross-source-synthesizer",
    "incubator_llm_screener": "incubator-llm-screener",
    "directive_keyword_enhancer": "directive-keyword-enhancer",
    "journal_review_builder": "journal-review-builder",
    **{pid: "run-research-intelligence-overnight" for pid in RI_SET},
}


# ── fixtures ──────────────────────────────────────────────────────────────────────────────────────────────────────


class Poison(types.ModuleType):
    """A module any attribute read of which is recorded and fails: proof a provider path was never touched."""

    def __init__(self, name):
        super().__init__(name)
        self.touched = []

    def __getattr__(self, attr):
        if attr.startswith("__"):
            raise AttributeError(attr)
        self.touched.append(attr)
        raise AttributeError(f"poisoned provider module {self.__name__}.{attr}")


@pytest.fixture
def poison(monkeypatch):
    mods = {}
    for name in ("llm_lane", "cloud_review", "local_llm"):
        mods[name] = Poison(name)
        monkeypatch.setitem(sys.modules, name, mods[name])
    yield mods
    for name, mod in mods.items():
        assert mod.touched == [], f"{name} touched on the bridge path: {mod.touched}"


class FakeBridge:
    """Replaces lib.llm_bridge_route._call_bridge: the real text_via_bridge / process-set checks still run."""

    def __init__(self):
        self.calls = []
        self.reply = "{}"
        self.refuse = False

    def __call__(self, messages, *, process_id, timeout_s):
        self.calls.append({"process_id": process_id, "timeout_s": timeout_s, "prompt": messages[0]["content"]})
        if self.refuse:
            return {"error": {"code": "COST_CAP_EXCEEDED"}, "governance_pass": False}
        return {
            "choices": [{"message": {"content": self.reply}}],
            "_tradeai": {"governance_pass": True, "process_id": process_id, "reservation_id": 7},
        }


def bind(monkeypatch, route):
    """Set exactly the env the n8n run executor binds for this allowlist llm_route."""
    for name in (X.LLM_BRIDGE_ENV, X.LLM_PROCESS_ENV, X.LLM_PROCESS_SET_ENV):
        monkeypatch.delenv(name, raising=False)
    for k, v in X._bind_llm_route({}, {"llm_route": route}).items():
        monkeypatch.setenv(k, v)


@pytest.fixture
def bridge(monkeypatch):
    fb = FakeBridge()
    monkeypatch.setattr(LBR, "_call_bridge", fb)
    return fb


def route(pid):
    return {"via": "cio-governed-bridge", "process_id": pid}


RI_ROUTE = {"via": "cio-governed-bridge", "process_ids": list(RI_SET)}


class Cur:
    def __init__(self, log, one=None, rows=None):
        self.log, self._one, self._rows, self.rowcount = log, one, rows or [], 1

    def execute(self, sql, params=None):
        self.log.append(" ".join(str(sql).split())[:80])
        if "RETURNING id" in str(sql):
            self._one = (101,)

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class Conn:
    def __init__(self, rows=None):
        self.log, self.rows, self.commits = [], rows or [], 0

    def cursor(self, *a, **k):
        return Cur(self.log, rows=self.rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def writes(self):
        return [s for s in self.log if s.split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE")]


# ── 1. registration: both route maps, registry, routing row ───────────────────────────────────────────────────────


@pytest.mark.parametrize("pid", sorted(PROCESSES))
def test_process_is_routed_on_both_sides(pid):
    from scripts.lib import cio_governed_model_bridge as B

    assert R.route_for_process(pid) == ("advisory_desk", pid)
    assert B.resolve_caller("advisory_desk", pid) == pid
    assert B.CALLER_TASK_PROCESS_MAP["advisory_desk"][pid] == pid


@pytest.mark.parametrize("pid", sorted(PROCESSES))
def test_registry_row_is_one_the_bridge_accepts(pid):
    from scripts.lib.consumption_run_manual import validate_paid_cap_config

    row = REGISTRY[pid]
    validate_paid_cap_config(row)  # explicit positive daily_cost_cap_usd + daily_soft_cap (bridge Step 5)
    assert row["tools_allowed"] is False and row["advisory_only"] is True
    assert row["reasoning_tier"] == "standard"
    assert "in terms of n8n, then, we should try OAuth first" in row["routing_decision_20261015"]
    if row.get("allowed_lanes") is not None:
        assert {"grok", "chatgpt"} <= set(row["allowed_lanes"]), pid  # the DeepSeek fallback does not read it
    if row.get("deepseek_allowed_policies"):
        assert {"FAST", "PRO_THINK"} <= set(row["deepseek_allowed_policies"]), pid


@pytest.mark.parametrize("pid", sorted(PROCESSES))
def test_routing_row_is_oauth_first_per_d10(pid):
    from scripts.lib import cio_governed_model_bridge as B

    row = ROUTING[pid]
    assert [row[k]["provider"] for k in ("primary", "secondary", "fallback")] == ["grok", "chatgpt", "deepseek"]
    assert row["transport_failover"] is True and row["route_profile"] == B.OAUTH_FIRST_PROFILE
    assert row["reasoning_lane"] == {"provider": "deepseek", "policy": "PRO_THINK"}


@pytest.mark.parametrize("pid", sorted(PROCESSES))
def test_route_plan_never_skips_an_oauth_lane_for_the_registry(pid, monkeypatch):
    import lib.llm_consumption as lc
    from scripts.lib import cio_governed_model_bridge as B

    cfg = (
        {"allowed_lanes": lc._allowed_lanes_from_registry(REGISTRY[pid])} if REGISTRY[pid].get("allowed_lanes") else {}
    )
    monkeypatch.setattr(B, "enabled_transport_providers", lambda: frozenset({"grok", "chatgpt", "deepseek"}))
    policy = {"provider": "grok", "requested_policy": "FAST", "routing_decision": {"lane_chosen": "primary"}}
    plan = B.route_plan(pid, None, policy, None, cfg)
    assert [(p["provider"], p["skip"]) for p in plan] == [("grok", None), ("chatgpt", None), ("deepseek", None)]


def test_new_incubator_row_keeps_the_cron_line_refused():
    """The cron line names incubator_llm_screener in-process (lane deepseek-flash). Unregistered, should_call refused
    it PROCESS_NOT_REGISTERED; registered as manual it is still refused (manual_mode) without a manual trigger, so the
    registration switches nothing on for cron. The bridge does not read mode."""
    assert REGISTRY["incubator_llm_screener"]["default_mode"] == "manual"
    src = (ROOT / "scripts/lib/llm_consumption.py").read_text()
    assert 'if cfg.get("mode") == "manual" and not manual_trigger:' in src


# ── 2. executor + dispatcher: single route and the compound process SET ───────────────────────────────────────────


def test_entry_planner_allowlist_entries_carry_the_route_and_bind_it():
    for lane in ("watchlist-entry-planner-limit", "watchlist-entry-planner-scope"):
        entry = ALLOW[lane]
        assert entry["llm_route"] == route("watchlist_entry_planner") and entry["live_arg"] is None
        assert X.validate_entry(entry) is None
        env, _block = X.build_child_env({"PATH": "/usr/bin"}, lane, entry)
        assert env[X.LLM_BRIDGE_ENV] == "1" and env[X.LLM_PROCESS_ENV] == "watchlist_entry_planner"
        assert X.LLM_PROCESS_SET_ENV not in env


def _ri_entry(**route_over):
    return {
        "lane_id": "run-research-intelligence-overnight",
        "command": ["bash", "scripts/run_research_intelligence_overnight.sh", "--phase", "full"],
        "lock": "/tmp/ri_overnight_full.lock",
        "lock_kind": "flock",
        "timeout_s": 5400,
        "dry_run_arg": ["--dry-run"],
        "live_arg": None,
        "env_names": ["DB_HOST"],
        "env_allowlist_mode": "report",
        "env_report_reason": "x",
        "output_signal": "data/runtime/run-research-intelligence-overnight_last.json",
        "llm_route": {**RI_ROUTE, **route_over},
    }


@pytest.mark.parametrize("mode", ["off", "report", "enforce"])
def test_compound_lane_binds_its_process_set(mode):
    entry = _ri_entry()
    assert X.validate_entry(entry) is None
    env, block = X.build_child_env(
        {"PATH": "/usr/bin", X.ENV_ALLOWLIST_MODE_ENV: mode, X.LLM_PROCESS_ENV: "stale_inherited"},
        entry["lane_id"],
        entry,
    )
    assert env[X.LLM_BRIDGE_ENV] == "1" and env[X.LLM_PROCESS_SET_ENV] == ",".join(RI_SET)
    assert X.LLM_PROCESS_ENV not in env  # an inherited single binding can never widen or narrow the set


@pytest.mark.parametrize(
    "bad, reason",
    [
        ({"process_ids": ["topic_ingestion", "not_routed_process"]}, "llm_process_route_not_registered"),
        ({"process_ids": []}, "bad_llm_route"),
        ({"process_ids": ["topic_ingestion", "topic_ingestion"]}, "bad_llm_route"),
        ({"process_ids": ["topic_ingestion,ri_narrative_enrich"]}, "bad_llm_route"),
        ({"process_ids": "topic_ingestion"}, "bad_llm_route"),
        ({"process_id": "topic_ingestion"}, "bad_llm_route"),  # both keys
    ],
)
def test_malformed_or_unrouted_process_sets_are_refused(bad, reason):
    assert X.validate_entry(_ri_entry(**bad)) == reason
    env, block = X.build_child_env({"PATH": "/usr/bin"}, "run-research-intelligence-overnight", _ri_entry(**bad))
    assert env is None and block["reason"] == reason


def test_r1_admission_accepts_a_registered_set_and_refuses_an_unregistered_member():
    reg = json.loads((ROOT / "config/lane_registry.json").read_text())
    row = next(r for r in reg["lanes"] if r["lane_id"] == "run-research-intelligence-overnight")
    pend = row["r1_pending"]
    activated = dict(
        row,
        scheduler={**row["scheduler"], **pend["scheduler"]},
        output_signal=pend["output_signal"],
        dispatch=pend["dispatch"],
    )
    ok, why = LD.r1_class_admission(activated, _ri_entry())
    assert ok and why == "r1_admitted:llm", why
    ok, why = LD.r1_class_admission(activated, _ri_entry(process_ids=["topic_ingestion", "nope"]))
    assert not ok and why == "llm_process_unregistered:'nope'"
    ok, why = LD.r1_class_admission(activated, _ri_entry(process_id="topic_ingestion"))
    assert not ok and why.startswith("llm_route_shape:")


def test_bound_set_refuses_any_other_process_before_transport(bridge, monkeypatch):
    bind(monkeypatch, RI_ROUTE)
    assert LBR.text_via_bridge("holdings_llm_refresh", "x") is None and bridge.calls == []
    bridge.reply = '{"ok": 1}'
    assert LBR.text_via_bridge("ri_narrative_enrich", "x") == '{"ok": 1}'
    assert [c["process_id"] for c in bridge.calls] == ["ri_narrative_enrich"]
    bind(monkeypatch, route("holdings_llm_refresh"))
    assert LBR.text_via_bridge("ri_narrative_enrich", "x") is None and len(bridge.calls) == 1


def test_require_text_raises_on_refusal(bridge, monkeypatch):
    bind(monkeypatch, route("holdings_llm_refresh"))
    bridge.refuse = True
    with pytest.raises(LBR.BridgeRouteRefused, match="BRIDGE_ROUTE_REFUSED"):
        LBR.require_text_via_bridge("holdings_llm_refresh", "x")


# ── 3. lib.governed_cloud_generation bridge branch ────────────────────────────────────────────────────────────────


def test_generate_cloud_on_the_bridge_is_one_request_and_never_llm_lane(bridge, poison, monkeypatch):
    bind(monkeypatch, route("holdings_llm_refresh"))
    bridge.reply = " answer "
    assert gcg.generate_cloud(
        "p", process_id="holdings_llm_refresh", task_summary="t", timeout=9, lanes=("grok", "chatgpt")
    ) == ("answer", gcg.BRIDGE_LANE)
    assert bridge.calls == [{"process_id": "holdings_llm_refresh", "timeout_s": 9.0, "prompt": "p"}]


def test_generate_cloud_refusal_fails_closed_with_no_second_request(bridge, poison, monkeypatch):
    bind(monkeypatch, route("holdings_llm_refresh"))
    bridge.refuse = True
    with pytest.raises(RuntimeError, match="CLOUD_GENERATION_FAILED_CLOSED.*BRIDGE_ROUTE_REFUSED"):
        gcg.generate_cloud("p", process_id="holdings_llm_refresh", task_summary="t", lanes=("grok", "chatgpt"))
    assert len(bridge.calls) == 1


def test_generate_cloud_without_the_flag_is_the_unchanged_lane_loop(bridge, monkeypatch):
    for name in (X.LLM_BRIDGE_ENV, X.LLM_PROCESS_ENV, X.LLM_PROCESS_SET_ENV):
        monkeypatch.delenv(name, raising=False)
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "llm_lane",
        types.SimpleNamespace(
            available=lambda lane: lane == "chatgpt",
            generate=lambda prompt, **kw: calls.append(kw["lane"]) or "cron answer",
        ),
    )
    assert gcg.generate_cloud("p", process_id="holdings_llm_refresh", task_summary="t") == ("cron answer", "chatgpt")
    assert calls == ["chatgpt"] and bridge.calls == []


# ── 4. per lane: bridge only, refusal = no output, dry run = no call ──────────────────────────────────────────────


@pytest.fixture
def holdings(monkeypatch):
    for fn in ("fetch_news", "fetch_social", "fetch_agent_views", "fetch_technical"):
        monkeypatch.setattr(hlr, fn, lambda conn, symbol: [])
    monkeypatch.setattr(hlr, "build_holdings_prompt", lambda *a: "HOLDINGS PROMPT")
    monkeypatch.setattr(hlr, "parse_holdings_health_result", lambda raw: json.loads(raw))
    monkeypatch.setitem(
        sys.modules, "lib.agent_decision_payload", types.SimpleNamespace(emit_holdings_health_payload=lambda out: None)
    )
    return Conn()


def test_holdings_via_bridge(holdings, bridge, poison, monkeypatch):
    bind(monkeypatch, route("holdings_llm_refresh"))
    bridge.reply = json.dumps({"health": "STABLE", "action": "HOLD", "confidence": 70})
    out = hlr.refresh_one(holdings, {"symbol": "LMT"})
    assert out["status"] == "refreshed" and out["model"] == "governed-bridge"
    assert [c["process_id"] for c in bridge.calls] == ["holdings_llm_refresh"]
    assert holdings.writes() and holdings.writes()[0].startswith("UPDATE watchlist_items")


def test_holdings_refusal_writes_nothing(holdings, bridge, poison, monkeypatch):
    bind(monkeypatch, route("holdings_llm_refresh"))
    bridge.refuse = True
    out = hlr.refresh_one(holdings, {"symbol": "LMT"})
    assert out["status"] == "error" and "BRIDGE_ROUTE_REFUSED" in out["error"]
    assert holdings.writes() == [] and len(bridge.calls) == 1


def test_holdings_dry_run_makes_no_model_call(holdings, bridge, poison, monkeypatch):
    bind(monkeypatch, route("holdings_llm_refresh"))
    assert hlr.refresh_one(holdings, {"symbol": "LMT"}, dry_run=True)["status"] == "dry_run"
    assert bridge.calls == [] and holdings.log == []


def test_cross_source_via_bridge_and_refusal(bridge, poison, monkeypatch):
    bind(monkeypatch, route("hermes_cross_source_synthesizer"))
    bridge.reply = json.dumps([{"topic": "t", "summary": "s", "thesis": "x"}])
    briefs = hcs.synthesize({"sources": {"news": [1, 2]}})
    assert briefs[0]["_source_lane"] == "bridge"
    assert [c["process_id"] for c in bridge.calls] == ["hermes_cross_source_synthesizer"]
    bridge.refuse = True
    assert hcs.synthesize({"sources": {}}) == [] and len(bridge.calls) == 2


def test_cross_source_dry_run_makes_no_model_call(bridge, poison, monkeypatch, capsys):
    bind(monkeypatch, route("hermes_cross_source_synthesizer"))
    assert hcs.main(["--dry-run", "--apply"]) == 0 and bridge.calls == []
    assert "DRY-RUN hermes-cross-source-synthesizer" in capsys.readouterr().out


@pytest.fixture
def incubator(monkeypatch):
    for fn in ("fetch_news", "fetch_social", "fetch_technical"):
        monkeypatch.setattr(ils, fn, lambda conn, symbol: [] if fn != "fetch_technical" else {})
    monkeypatch.setattr(ils, "build_screen_prompt", lambda *a: "SCREEN PROMPT")
    monkeypatch.setitem(sys.modules, "web_news_fetcher", types.SimpleNamespace(fetch_web_news=lambda *a, **k: []))
    monkeypatch.setenv("CLOUD_REVIEW", "1")  # would call OAuth in-process on the cron path; never on the bridge
    return Conn()


CANDIDATE = {"symbol": "AAA", "latest_score": 55, "strategy_id": ""}


def test_incubator_via_bridge_skips_in_process_cloud_review(incubator, bridge, poison, monkeypatch):
    bind(monkeypatch, route("incubator_llm_screener"))
    bridge.reply = json.dumps({"screen_grade": "B", "verdict": "PROMOTE", "confidence": 61, "reasoning": "r"})
    out = ils.screen_one(incubator, dict(CANDIDATE))
    assert out["status"] == "screened" and out["model"] == "governed-bridge" and out["cloud_review_verdict"] is None
    assert [c["process_id"] for c in bridge.calls] == ["incubator_llm_screener"]
    assert len(incubator.writes()) == 1  # the screen UPDATE only; no cloud_review re-write


def test_incubator_refusal_writes_nothing(incubator, bridge, poison, monkeypatch):
    bind(monkeypatch, route("incubator_llm_screener"))
    bridge.refuse = True
    out = ils.screen_one(incubator, dict(CANDIDATE))
    assert out["status"] == "error" and incubator.writes() == [] and len(bridge.calls) == 1


def test_incubator_dry_run_makes_no_model_call(incubator, bridge, poison, monkeypatch):
    bind(monkeypatch, route("incubator_llm_screener"))
    assert ils.screen_one(incubator, dict(CANDIDATE), dry_run=True)["status"] == "dry_run"
    assert bridge.calls == [] and incubator.log == []


def test_directive_enhancer_is_one_bridge_request(bridge, poison, monkeypatch):
    bind(monkeypatch, route("directive_keyword_enhancer"))
    bridge.reply = json.dumps({"keywords": ["liquid cooling"], "seed_symbols": ["VRT", "bad ticker"]})
    out = dke.enhance("Data center cooling")
    assert out == {"keywords": ["liquid cooling"], "seed_symbols": ["VRT"], "lane": "bridge"}
    assert [c["process_id"] for c in bridge.calls] == ["directive_keyword_enhancer"]


def test_directive_refusal_leaves_the_directive_untouched(bridge, poison, monkeypatch):
    bind(monkeypatch, route("directive_keyword_enhancer"))
    bridge.refuse = True
    conn = Conn(rows=[(1, "Energy storage", "trend", {"keywords": []})])
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn))
    written = []
    monkeypatch.setitem(
        sys.modules,
        "lib.writers.watch_directives_writer",
        types.SimpleNamespace(update_watch_directive=lambda *a, **k: written.append(k)),
    )
    res = dke.backfill(apply=True)
    assert res[0]["lane"] == dke.BRIDGE_REFUSED_LANE and res[0]["keywords"] == []
    assert written == [] and len(bridge.calls) == 1  # no label-derived fallback keyword on this path


def test_directive_dry_run_makes_no_model_call(bridge, poison, monkeypatch, capsys):
    bind(monkeypatch, route("directive_keyword_enhancer"))
    assert dke.main(["--dry-run", "--backfill", "--apply"]) == 0 and bridge.calls == []


@pytest.fixture
def journal(monkeypatch):
    conn = Conn()
    monkeypatch.setattr(jrb, "_conn", lambda: conn)
    row = {
        "symbol": "AAA",
        "account": "paper",
        "cd": "2026-10-14",
        "strategy_id": "s",
        "entry_price": 1,
        "exit_price": 2,
        "shares": 1,
        "pnl": 1,
        "exit_reason": "target",
    }
    monkeypatch.setattr(jrb, "pending_reviews", lambda cur, limit: ([row], [("AAA:paper:2026-10-14", row)], 0))
    return conn


def test_journal_via_bridge(journal, bridge, poison, monkeypatch):
    bind(monkeypatch, route("journal_review_builder"))
    bridge.reply = json.dumps(
        {"setup": "breakout", "entry_grade": "B", "exit_grade": "A", "lesson": "l", "strengths": [], "mistakes": []}
    )
    res = jrb.run()
    assert res["reviewed"] == 1 and res["lane"] == "bridge"
    assert [c["process_id"] for c in bridge.calls] == ["journal_review_builder"]
    assert journal.writes()[0].startswith("INSERT INTO journal_trade_reviews")


def test_journal_refusal_inserts_nothing(journal, bridge, poison, monkeypatch):
    bind(monkeypatch, route("journal_review_builder"))
    bridge.refuse = True
    res = jrb.run()
    assert res["reviewed"] == 0 and res["failed"] == 1 and journal.writes() == []


def test_journal_dry_run_makes_no_model_call(journal, bridge, poison, monkeypatch):
    bind(monkeypatch, route("journal_review_builder"))
    monkeypatch.setattr(
        jrb,
        "_receipt_lib",
        lambda: types.SimpleNamespace(enforce_readonly=lambda conn: None, dry_run_report=lambda *a, **k: None),
    )
    assert jrb.run(dry_run=True)["would_review"] == 1 and bridge.calls == [] and journal.writes() == []


@pytest.fixture
def planner(monkeypatch):
    conn = Conn()
    monkeypatch.setitem(
        sys.modules, "db_adapter", types.SimpleNamespace(_get_conn=lambda: conn, close_thread_conn=lambda: None)
    )
    monkeypatch.setattr(
        wep,
        "_candidates",
        lambda cur, limit, symbols, scope, cap: [
            {"symbol": "AAA", "hermes_composite_score": 1, "hermes_rank": 1, "trend": "up"}
        ],
    )
    monkeypatch.setattr(wep, "_bars", lambda sym: [{"close": 10.0}])
    monkeypatch.setattr(
        wep,
        "_tech",
        lambda bars: {"price": 10.0, "rsi": 50, "atr": 0.5, "swing_high": 11.0, "swing_low": 9.0, "sma50": 10.0},
    )
    monkeypatch.setattr(
        wep,
        "_analyst",
        lambda cur, sym: {
            "tgt_mean": "n/a",
            "tgt_low": "n/a",
            "tgt_high": "n/a",
            "rec_key": "n/a",
            "n_analysts": 0,
            "tgt_mean_num": None,
        },
    )
    monkeypatch.setattr(wep, "_live", lambda c, cur: (c, cur))
    return conn


PLAN = {
    "entry_thesis": "pullback",
    "setup_type": "pullback",
    "entry_zone_low": 9.5,
    "entry_zone_high": 10.5,
    "limit_price": 10.0,
    "stop_price": 9.0,
    "target_price": 13.0,
    "risk_reward": 3.0,
    "urgency": "watch",
    "confidence": 0.5,
    "invalidation": "close < 9",
    "proposal": {"tag": "WAIT"},
}


def test_entry_planner_via_bridge(planner, bridge, poison, monkeypatch):
    bind(monkeypatch, ALLOW["watchlist-entry-planner-limit"]["llm_route"])
    bridge.reply = json.dumps(PLAN)
    res = wep.plan_run(limit=5, alerter=None)
    assert res["planned"] == 1 and res["lane"] == "bridge" and res["fallback_lane"] is None
    assert [c["process_id"] for c in bridge.calls] == ["watchlist_entry_planner"]
    assert any(w.startswith("INSERT INTO watchlist_entry_plans") for w in planner.writes())


def test_entry_planner_refusal_is_a_failed_symbol_with_no_fallback_lane(planner, bridge, poison, monkeypatch):
    bind(monkeypatch, ALLOW["watchlist-entry-planner-scope"]["llm_route"])
    bridge.refuse = True
    res = wep.plan_run(limit=5, scope="proposals", alerter=None)
    assert res["planned"] == 0 and res["failed"] == 1 and len(bridge.calls) == 1
    assert res["output"]["skipped_reasons"] == {"bridge_refused": 1}
    assert planner.writes() == []


def test_entry_planner_dry_run_makes_no_model_call(planner, bridge, poison, monkeypatch, capsys):
    import watchlist_entry_planner_lane as wepl

    bind(monkeypatch, ALLOW["watchlist-entry-planner-limit"]["llm_route"])
    monkeypatch.setattr(wepl, "preview", lambda **kw: {"candidates": 1})
    monkeypatch.setattr(wepl, "plan_run", lambda **kw: pytest.fail("dry run reached plan_run"))
    assert wepl.main(["--limit", "60", "--buy-rated-cap", "400", "--dry-run"]) == 0 and bridge.calls == []


def test_ri_narrative_is_one_bridge_request_and_a_refusal_stops_the_run(bridge, poison, monkeypatch):
    bind(monkeypatch, RI_ROUTE)
    bridge.reply = json.dumps(
        {"headline": "h", "dek": "d", "body": "b", "takeaways": ["t"], "next_action": {"label": "l"}}
    )
    monkeypatch.setattr(rine, "_normalize_narrative", lambda d: d or None)
    nar, lane = rine._generate_parsed("p", ["grok", "chatgpt"], timeout=11)
    assert lane == "bridge" and nar["headline"] == "h"
    assert bridge.calls == [{"process_id": "ri_narrative_enrich", "timeout_s": 11.0, "prompt": "p"}]
    bridge.refuse = True
    with pytest.raises(rine.GovernanceRefused, match="BRIDGE_ROUTE_REFUSED"):
        rine._generate_parsed("p", ["grok", "chatgpt"])
    assert len(bridge.calls) == 2  # one per call, never a second lane


def test_ri_synthesizer_is_one_bridge_request_even_on_refusal(bridge, poison, monkeypatch):
    bind(monkeypatch, RI_ROUTE)
    bridge.refuse = True
    assert trs._synthesize("Roth conversion", "") is None
    assert [c["process_id"] for c in bridge.calls] == ["topic_research_synthesizer"]


def test_ri_ingestion_rating_goes_through_the_bridge(bridge, poison, monkeypatch):
    import topic_ingestion as ti

    bind(monkeypatch, RI_ROUTE)
    bridge.reply = '{"relevant": true, "quality": "high", "summary": "rated"}'
    assert ti._llm_normalize("t", "d", "Roth")["summary"] == "rated"
    bridge.refuse = True
    # A refusal is no model answer: the helper keeps its existing non-LLM default (the description), never a provider
    assert ti._llm_normalize("t", "desc", "Roth")["summary"] == "desc"
    assert [c["process_id"] for c in bridge.calls] == ["topic_ingestion", "topic_ingestion"]


def test_ri_dry_run_is_offline():
    r = subprocess.run(
        ["bash", str(ROOT / "scripts/run_research_intelligence_overnight.sh"), "--phase", "full", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", X.LLM_BRIDGE_ENV: "1", X.LLM_PROCESS_SET_ENV: ",".join(RI_SET)},
    )
    assert r.returncode == 0 and r.stdout.startswith("DRY-RUN run-research-intelligence-overnight phase=full")
    assert "no gate, child, model" in r.stdout


def test_registered_in_the_cio_hardening_gates():
    text = (ROOT / "scripts" / "run_cio_hardening_ci.py").read_text(encoding="utf-8")
    assert "tests/test_n8n_llm_bridge_routes_b1_20261015.py" in text
