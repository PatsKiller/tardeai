"""LQ-20261107-1010 (Fable Q5): the four LLM lanes 3c216df08 did not fix, and the gateway that let them drift.

Review 999 measured the previous package and found 3 of 4 lanes untouched:

* **keepalive quota burn** — the ``*/30`` cron sent a real generate on each free OAuth lane every run
  (~2,597 in 30 days) and graded a 429 as a dead lane (54 failed runs in a row). Now: ping only when
  the token needs a roll (a stated expiry inside 2 h, or 6 h idle → ~4/day), with
  ``_skip_consumption=True``; a 429 is ``ok_rate_limited`` — no alert, no regression, exit 0.
* **adjudicator provider mismatch** — the gateway walked the whole provider order, so a process whose
  allowlist is ``[fast, deepseek-flash]`` was served by grok (129 calls / 14 d). Now the allowlist
  binds. The adjudicator also stops hand-parsing: ``lib.llm_json_contract.recover_json_object`` reads
  strict → fenced → embedded, the object is validated against ``contradiction_verdict.v1``, and an
  off-contract answer gets ONE retry on a different allowed lane before the UNRESOLVED row is written.
* **curator serial calls** — one lane call per 5 articles / per transcript. Now: deterministic
  pre-filter, 20-row batches, and a run-wide wall budget that leaves unreached rows pending.
* **iris timeout** — the Sunday gap-recommendation site passed 20 s, below the lane's own successful
  tail (grok p95 29.3 s, max ok 29.5 s), and its answer was swallowed into "(LLM unavailable)". Now
  the process adopts the LQ-865 resolver; ``config/llm_lane_budgets.json`` sizes it at 40 s.

Hermetic: fake connections, fake lanes, fake probes, tmp state roots. No DB, no network, no LLM call.
"""
from __future__ import annotations

import ast
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import contradiction_adjudicator as ca  # noqa: E402
import iris_taxonomy_agent as iris  # noqa: E402
import oauth_lane_keepalive as keep  # noqa: E402
import topic_curator as tc  # noqa: E402
from lib import anthropic_routing as routing  # noqa: E402
from lib import llm_consumption as lc  # noqa: E402

# The two modules this package adds to are imported defensively ONLY so that the fail-before run
# (the same file dropped on the pre-LQ-1010 tree) reports a failing test per behaviour instead of one
# collection error. A missing module is never a skip: the stub raises when a test touches it.
try:
    from lib import llm_lane_budgets as budgets  # noqa: E402
except ImportError:  # pragma: no cover - only on a tree that predates LQ-865
    def _missing(name):
        raise AssertionError(f"{name} is missing: this tree predates the LQ-1010 package")

    budgets = types.SimpleNamespace(
        budget_s=lambda pid: _missing("lib.llm_lane_budgets.budget_s"),
        derive_budget_s=lambda *a, **k: _missing("lib.llm_lane_budgets.derive_budget_s"),
    )

try:
    from lib.llm_json_contract import JsonContractError, is_json_response, recover_json_object  # noqa: E402
except ImportError:  # pragma: no cover - only on a tree that predates LQ-1010
    class JsonContractError(ValueError):  # type: ignore[no-redef] -- the raising stub shadows the real import on a pre-LQ-1010 tree
        pass

    def recover_json_object(text, **kw):  # type: ignore[misc] -- raising stub, deliberately signature-compatible with the real reader
        raise AssertionError("lib.llm_json_contract.recover_json_object is missing: pre-LQ-1010 tree")

    def is_json_response(text, **kw):  # type: ignore[misc] -- same: a stub that fails loudly, never a skip
        raise AssertionError("lib.llm_json_contract.is_json_response is missing: pre-LQ-1010 tree")

ADJUDICATOR_ALLOWLIST = ["fast", "deepseek-flash"]
REAL_429 = ("429 Client Error: Too Many Requests for url: "
            "http://127.0.0.1:8646/v1/chat/completions")
FENCED_VERDICT = '```json\n{"verdict": "RIGHT", "confidence": 0.6, "rationale": "x"}\n```'


# ══ 1. the shared JSON contract: one reader for every lane ═════════════════════════════════════════

def test_a_fenced_object_is_read_and_named_as_a_recovery():
    obj, how = recover_json_object(FENCED_VERDICT)
    assert obj["verdict"] == "RIGHT" and how == "fenced"


def test_prose_around_the_object_is_read():
    obj, how = recover_json_object('prose first {"verdict": "LEFT"} trailing')
    assert obj["verdict"] == "LEFT" and how == "embedded"


def test_text_with_no_object_is_a_contract_error_not_an_empty_dict():
    with pytest.raises(JsonContractError):
        recover_json_object("no json here")
    assert is_json_response("no json here") is False
    assert is_json_response(FENCED_VERDICT) is True


# ══ 2. the adjudicator: the contract + one retry on another lane ═══════════════════════════════════

def test_the_fenced_answer_the_gateway_used_to_throw_away_is_now_a_verdict():
    """116 adjudicator answers in 14 d were paid for and discarded by a bare ``json.loads``."""
    v = ca.parse_verdict(FENCED_VERDICT)
    assert v["verdict"] == "RIGHT" and v["confidence"] == 0.6
    assert not v.get("schema_invalid")


def test_an_off_contract_verdict_is_schema_invalid_not_a_row():
    v = ca.parse_verdict('{"verdict": "MAYBE", "confidence": 0.6}')
    assert v["verdict"] == "UNRESOLVED" and v["schema_invalid"] is True
    assert "SCHEMA_INVALID" in v["rationale"]


def test_an_off_contract_confidence_is_normalised_not_failed():
    """``confidence: 1.7`` used to be clamped by hand; it still is, and the object now validates."""
    v = ca.parse_verdict('{"verdict": "left", "confidence": 1.7}')
    assert v["verdict"] == "LEFT" and v["confidence"] == 1.0 and not v.get("schema_invalid")


def test_a_missing_confidence_is_the_schema_default_not_certain_zero():
    """Absent is not zero (tq-py-missing-as-zero): the model said nothing, so 0.5 — never 0.0."""
    v = ca.parse_verdict('{"verdict": "LEFT"}')
    assert v["confidence"] == 0.5 and not v.get("schema_invalid")
    v2 = ca.parse_verdict('{"verdict": "LEFT", "confidence": "high"}')
    assert v2["verdict"] == "UNRESOLVED" and v2["schema_invalid"] is True
    assert "not a number" in v2["rationale"]


def test_the_retry_lane_is_a_different_lane_from_the_allowlist():
    assert ca.retry_lane("deepseek-flash", lanes=ADJUDICATOR_ALLOWLIST) == "fast"
    assert ca.retry_lane("fast", lanes=ADJUDICATOR_ALLOWLIST) == "deepseek-flash"
    assert ca.retry_lane("deepseek-flash", lanes=["deepseek-flash"]) is None


def test_the_shipped_adjudicator_row_allows_only_deepseek_family_lanes():
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text())
    row = {p["id"]: p for p in reg["processes"]}["contradiction_adjudicator"]
    lanes = lc._allowed_lanes_from_registry(row)
    assert lanes == ADJUDICATOR_ALLOWLIST
    assert not {"grok", "chatgpt"} & set(lanes)


def test_judge_passes_the_lane_it_was_given():
    seen = {}
    fake = types.SimpleNamespace(
        gate_and_generate=lambda prompt, **kw: seen.update(kw) or ("{}", {"model": "m"}))
    old = sys.modules.get("llm_consumption")
    sys.modules["llm_consumption"] = fake
    try:
        ca.judge({"candidate_id": "c1"}, lane="fast")
    finally:
        if old is None:
            sys.modules.pop("llm_consumption", None)
        else:
            sys.modules["llm_consumption"] = old
    assert seen["lane"] == "fast" and seen["process_id"] == "contradiction_adjudicator"


def test_one_off_contract_answer_is_retried_once_on_a_different_lane():
    calls = []

    def judge_fn(request, *, lane):
        calls.append(lane)
        return (FENCED_VERDICT if lane == "fast" else "garbage", {"model": lane})

    v, prov, lane_used = ca.judge_with_retry({"candidate_id": "c1"}, judge_fn=judge_fn)
    assert calls == ["deepseek-flash", "fast"]        # default lane first, then the other allowed lane
    assert v["verdict"] == "RIGHT" and lane_used == "fast" and prov["model"] == "fast"


def test_two_off_contract_answers_write_unresolved_and_stop_retrying():
    calls = []

    def judge_fn(request, *, lane):
        calls.append(lane)
        return ("garbage", {})

    v, _, lane_used = ca.judge_with_retry({"candidate_id": "c1"}, judge_fn=judge_fn)
    assert len(calls) == 2                             # exactly one retry, never a loop
    assert v["verdict"] == "UNRESOLVED" and v["schema_invalid"] is True
    assert lane_used == ca.LLM_LANE


def test_a_good_first_answer_is_not_retried():
    calls = []

    def judge_fn(request, *, lane):
        calls.append(lane)
        return (FENCED_VERDICT, {"model": "m"})

    v, _, _ = ca.judge_with_retry({"candidate_id": "c1"}, judge_fn=judge_fn)
    assert calls == [ca.LLM_LANE] and v["verdict"] == "RIGHT"


# ══ 3. the gateway: allowed_lanes binds the plan ═══════════════════════════════════════════════════

POLICY = {
    "provider_order": ["anthropic", "deepseek", "grok", "chatgpt"],
    "models": {"standard": "claude-test-model"},
    "enabled": True,
    "provider_enabled": True,
    "expires_at": "2099-01-01T00:00:00Z",
    "anthropic_only_processes": {},
    "excluded_processes": {},
}


def _plan(cfg, enabled):
    return routing.configured_plan(
        "contradiction_adjudicator", cfg,
        {"requested_policy": "FAST", "credit_tier": "standard"},
        enabled=enabled, model_for_provider=lambda provider, name: "m",
        env={"ANTHROPIC_API_KEY": True}, policy=POLICY,
    )


def test_a_deepseek_allowlist_admits_only_deepseek():
    assert routing.enabled_providers({"allowed_lanes": ADJUDICATOR_ALLOWLIST}) == frozenset({"deepseek"})


def test_anthropic_is_admitted_only_by_anthropic_first():
    assert routing.enabled_providers(
        {"allowed_lanes": ADJUDICATOR_ALLOWLIST, "anthropic_first": True}
    ) == frozenset({"deepseek", "anthropic"})
    assert routing.enabled_providers({"allowed_lanes": ["grok", "chatgpt"]}) == frozenset({"grok", "chatgpt"})


def test_a_hand_built_cfg_keeps_the_historical_full_set():
    """A dict that is not a registry row (a test double) must not silently lose its providers."""
    assert routing.enabled_providers({}) == frozenset({"anthropic", "grok", "chatgpt", "deepseek"})


def test_the_plan_marks_the_out_of_allowlist_providers_no_transport():
    cfg = {"allowed_lanes": ADJUDICATOR_ALLOWLIST, "anthropic_first": True,
           "daily_cost_cap_usd": 0.5, "daily_soft_cap": 60}
    plan = {row["provider"]: row for row in _plan(cfg, routing.enabled_providers(cfg))}
    assert plan["deepseek"]["skip"] is None                  # the allowlisted lane is usable
    assert plan["anthropic"]["skip"] is None                 # anthropic_first admits the promotion
    assert plan["grok"]["skip"] == "no_transport"            # 129 grok calls used to land here
    assert plan["chatgpt"]["skip"] == "no_transport"


def test_a_process_without_anthropic_first_cannot_reach_anthropic():
    """Caps and credit can both be healthy; without anthropic_first the promotion is not in the plan."""
    cfg = {"allowed_lanes": ADJUDICATOR_ALLOWLIST, "daily_cost_cap_usd": 0.5, "daily_soft_cap": 60}
    plan = {row["provider"]: row for row in _plan(cfg, routing.enabled_providers(cfg))}
    assert plan["anthropic"]["skip"] == "no_transport"


def test_should_call_no_longer_exempts_grok_on_the_anthropic_route(monkeypatch):
    cfg = {"registered": True, "mode": "automated", "allowed_lanes": ADJUDICATOR_ALLOWLIST,
           "anthropic_first": True, "daily_cost_cap_usd": 0.5, "daily_soft_cap": 60,
           "local_only": False}
    monkeypatch.setattr(lc, "get_process_config", lambda pid: dict(cfg))
    assert lc.should_call("contradiction_adjudicator", "grok", _anthropic_route=True)["allow"] is False
    assert lc.should_call("contradiction_adjudicator", "grok", _anthropic_route=True)["reason"] == "POLICY_NOT_ALLOWED"
    assert lc.should_call("contradiction_adjudicator", "deepseek-flash", _anthropic_route=True)["allow"] is True
    assert lc.should_call("contradiction_adjudicator", "anthropic", _anthropic_route=True)["allow"] is True


# ══ 4. keepalive: the quota is spent only when a roll is needed, and a 429 is not a failure ═════════

NOW = 1_800_000_000


def test_a_recently_rolled_token_is_not_pinged_again():
    need, why = keep._needs_ping("chatgpt", {"last_ok": NOW - 3600}, NOW)
    assert need is False and why == "idle_within_window"


def test_a_token_unrolled_for_over_six_hours_is_pinged():
    need, why = keep._needs_ping("chatgpt", {"last_ok": NOW - 7 * 3600}, NOW)
    assert need is True and why == "max_idle_exceeded"


def test_the_first_ever_run_pings():
    assert keep._needs_ping("grok", {}, NOW) == (True, "no_prior_ok")


def test_a_stated_expiry_inside_the_lead_pings_even_though_the_idle_window_has_not_passed():
    need, why = keep._needs_ping("grok", {"last_ok": NOW - 60, "token_expires_at": NOW + 3600}, NOW)
    assert need is True and why == "expiry_within_lead"


def test_a_lane_known_rate_limited_is_not_pinged_inside_the_quota_window():
    need, why = keep._needs_ping("chatgpt", {"last_ok": 0, "rate_limited_until": NOW + 600}, NOW)
    assert need is False and why == "rate_limited_upstream"


def test_read_only_lanes_are_always_checked():
    assert keep._needs_ping("local", {"last_ok": NOW}, NOW) == (True, "read_only_check")


def test_four_pings_a_day_at_the_half_hour_cron():
    """The cron ticks every 30 min; the planner must turn that into ~4 rolls/day (was 48)."""
    last_ok, rolls = NOW - 7 * 3600, 0
    for t in range(NOW, NOW + 24 * 3600, 1800):
        need, _ = keep._needs_ping("grok", {"last_ok": last_ok}, t)
        if need:
            rolls += 1
            last_ok = t
    assert rolls == 4                                   # 24 h / 6 h, not 48


def test_a_skipped_lane_is_not_probed_and_is_recorded_as_skipped():
    probes = []
    alerts, out, regressions = keep._evaluate(
        ["chatgpt"], {"chatgpt": {"ok": True, "last_ok": NOW - 60}}, NOW,
        lambda lane: probes.append(lane) or (True, "rolled"),
        planner=keep._needs_ping,
    )
    assert probes == [] and alerts == [] and regressions == []
    assert out["chatgpt"]["skipped"] is True and out["chatgpt"]["skip_reason"] == "idle_within_window"


def test_the_ping_excludes_itself_from_consumption_caps(monkeypatch):
    seen = {}
    fake = types.SimpleNamespace(generate=lambda prompt, **kw: seen.update(kw) or "OK")
    monkeypatch.setitem(sys.modules, "llm_lane", fake)
    ok, _ = keep._ping_lane("grok")
    assert ok is True
    assert seen["_skip_consumption"] is True and seen["lane"] == "grok"


def test_a_rate_limited_real_run_exits_zero_and_sends_nothing(tmp_path, monkeypatch):
    rt = tmp_path / "data" / "runtime"
    rt.mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    status = rt / "oauth_lane_status.json"
    status.write_text(json.dumps({"chatgpt": {"ok": True, "last_ok": NOW - 7200, "last_alert": 0}}))
    monkeypatch.setattr(keep, "STATUS_FILE", status)
    monkeypatch.setattr(keep, "KEEPALIVE_MAX_IDLE_S", 0)
    monkeypatch.setattr(keep.time, "time", lambda: NOW)
    monkeypatch.setattr(keep, "_ping_lane", lambda lane: (False, REAL_429))
    sent = []
    fake = types.SimpleNamespace(send_telegram=lambda text, **kw: sent.append(text) or True)
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)

    assert keep.main(["chatgpt"]) == 0
    assert sent == []
    rec = json.loads((rt / "oauth_lane_keepalive_last.json").read_text())
    assert rec["status"] == "ok" and rec["summary"]["quota_exhausted"] == ["chatgpt"]
    st = json.loads(status.read_text())
    assert st["chatgpt"]["rate_limited_until"] == NOW + keep.KEEPALIVE_QUOTA_COOLDOWN_S
    assert st["chatgpt"]["last_ok"] == NOW - 7200        # a refused ping does not fake a roll


# ══ 5. curator: pre-filter, wider batches, wall budget ═════════════════════════════════════════════

def test_the_prefilter_settles_only_what_the_prompt_already_states():
    assert tc._prefilter({"title": "", "summary": ""}) == ("low_quality", "prefilter: no text to rate")
    assert tc._prefilter({"title": "股市 大跌 消息 分析 报告", "summary": ""}) == ("blocked", "prefilter: non-English")
    assert tc._prefilter({"title": "NVDA earnings beat", "summary": "Data center demand"}) is None


class _Cursor:
    def __init__(self, results):
        self.results = list(results)
        self.updates = []

    def execute(self, sql, params=None):
        self.updates.append((" ".join(str(sql).split()), params))

    def fetchall(self):
        return self.results.pop(0) if self.results else []

    def fetchone(self):
        return None


class _Conn:
    def __init__(self, results):
        self.cur = _Cursor(results)

    def cursor(self, **kwargs):
        return self.cur

    def commit(self):
        pass


def _articles(n):
    return [{"id": i, "title": f"Company {i} dividend increase announced", "summary": "s",
             "strategy_type": "ssdi", "relevance_score": 0.1} for i in range(1, n + 1)]


def _patch_rate(monkeypatch, n_articles):
    import lib.writers.news_articles_writer as naw

    monkeypatch.setattr(naw, "approve_pending_by_relevance", lambda *a, **k: 0, raising=False)
    monkeypatch.setattr(naw, "set_rag_status", lambda *a, **k: None, raising=False)
    conn = _Conn([_articles(n_articles), []])
    prompts = []

    def fake_gen(prompt):
        prompts.append(prompt)
        return json.dumps([{"id": i, "rag": "approved", "reason": "ok"} for i in range(1, 51)])

    monkeypatch.setattr(tc, "_free_lane_gen", fake_gen)
    return conn, prompts


def test_articles_are_batched_twenty_per_call(monkeypatch):
    conn, prompts = _patch_rate(monkeypatch, 45)
    total, approved, _ = tc.rate_pending_content(conn, budget=None)
    assert len(prompts) == 3 and total == 45 and approved == 45     # 20 + 20 + 5, not 9 calls
    assert "20. Company 20" in prompts[0] and "21." not in prompts[0]
    assert "5. Company 45" in prompts[2]


def test_the_wall_budget_stops_the_step_and_leaves_the_rows_pending(monkeypatch):
    conn, prompts = _patch_rate(monkeypatch, 45)
    budget = tc.LlmWallBudget(seconds=0)
    total, approved, _ = tc.rate_pending_content(conn, budget=budget)
    assert prompts == [] and total == 0 and approved == 0
    assert budget.deferred == 45 and budget.stopped_steps == ["rate_articles"]
    assert budget.as_dict()["deferred"] == 45


def test_the_budget_is_a_run_wide_clock():
    b = tc.LlmWallBudget(seconds=60)
    assert b.expired() is False and b.remaining_s() <= 60
    assert b.as_dict()["budget_s"] == 60.0


# ══ 6. iris adopts the LQ-865 resolver; no fourth hand literal ═════════════════════════════════════

def test_no_iris_call_site_passes_a_timeout_literal():
    tree = ast.parse((ROOT / "scripts" / "iris_taxonomy_agent.py").read_text())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "llm_generate":
            for kw in node.keywords:
                if kw.arg == "timeout":
                    offenders.append(node.lineno)
    assert offenders == []                               # 516/541 passed 30 s, 1691 passed 20 s


def test_iris_llm_generate_defaults_to_the_resolver(monkeypatch):
    seen = {}

    def fake_cloud(prompt, **kw):
        seen.update(kw)
        return ("{}", "grok")

    monkeypatch.setattr(iris, "generate_cloud", fake_cloud)
    iris.llm_generate("prompt")
    assert seen["timeout"] is None and seen["process_id"] == "iris_taxonomy_agent"
    iris.llm_generate("prompt", timeout=25)
    assert seen["timeout"] == 25                         # an explicit number is still honoured verbatim


def test_the_budgets_file_sizes_iris_above_the_tail_that_was_being_cut():
    """20 s < max ok 29.5 s: the Sunday site cut answers the lane gave. 40 s covers the tail + margin."""
    assert budgets.budget_s("iris_taxonomy_agent") == 40.0
    raw = json.loads((ROOT / "config" / "llm_lane_budgets.json").read_text())
    row = raw["lanes"]["iris_taxonomy_agent"]
    assert row["max_ok_ms"] == 29514 and row["old_budget_s"] == [20, 30]
    assert budgets.derive_budget_s(float(row["p95_ms"]), float(row["max_ok_ms"]),
                                   margin=raw["margin"], cap_s=raw["cap_s"]) == 40.0
