"""MODEL_CHOOSER_TASK_CLASS_20261107 — the chooser reads config/llm_task_classes.json (LQ-20261107-197).

The matrix names tiers, never raw model ids; every class resolves through the credit policy's tier models; a
process with no task class reports TASK_CLASS_UNASSIGNED; the lane decision is unchanged by the task class.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib import model_chooser as mc  # noqa: E402

MATRIX = json.loads((ROOT / "config/llm_task_classes.json").read_text(encoding="utf-8"))
POLICY = json.loads((ROOT / "config/anthropic_credit_policy.json").read_text(encoding="utf-8"))
DESIGN = {"extract": "bulk", "summarize": "bulk", "score": "bulk", "reason": "mid", "critique": "mid",
          "diagnose": "mid", "verdict": "standard"}


def test_matrix_names_tiers_never_raw_model_ids():
    assert set(MATRIX["classes"]) == set(DESIGN)
    model_ids = {v for v in POLICY["models"].values()}
    chains = json.dumps({k: v["chain"] for k, v in MATRIX["classes"].items()})
    for mid in model_ids | {"deepseek-flash"}:
        assert mid not in chains
    for cls, spec in MATRIX["classes"].items():
        first = spec["chain"][0]
        assert first == {"provider": "anthropic", "tier": DESIGN[cls]}, cls
        for step in spec["chain"]:
            assert step["provider"] in ("anthropic", "deepseek", "grok")
            assert step["provider"] != "chatgpt"


def test_every_class_resolves_through_the_credit_policy_tier_models():
    for cls in MATRIX["classes"]:
        route = mc.task_class_route(cls, env={})
        assert route["status"] == "OK"
        assert route["primary_model"] == POLICY["models"][DESIGN[cls]]
        assert not any(s["unresolved"] for s in route["chain"]), cls


def test_verdict_fails_closed_with_no_third_step():
    route = mc.task_class_route("verdict", env={})
    assert route["fail_closed"] is True and len(route["chain"]) == 2
    assert [s["tier"] for s in route["chain"]] == ["standard", "mid"]


def test_a_tier_change_moves_the_route_without_code(tmp_path):
    pol = dict(POLICY, models=dict(POLICY["models"], bulk="synthetic-bulk-next"))
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(pol), encoding="utf-8")
    route = mc.task_class_route("extract", env={"TRADEAI_ANTHROPIC_CREDIT_POLICY": str(p)})
    assert route["primary_model"] == "synthetic-bulk-next"
    missing = tmp_path / "nomodels.json"
    missing.write_text(json.dumps(dict(POLICY, models={})), encoding="utf-8")
    route = mc.task_class_route("extract", env={"TRADEAI_ANTHROPIC_CREDIT_POLICY": str(missing)})
    assert route["primary_model"] is None and route["chain"][0]["unresolved"] is True  # flagged, not guessed


def test_unassigned_and_unknown_classes_are_named(tmp_path):
    assert mc.task_class_route(None, env={})["status"] == mc.TASK_CLASS_UNASSIGNED
    assert mc.task_class_route("no-such-class", env={})["status"] == mc.TASK_CLASS_UNKNOWN


def test_choose_reports_the_task_class_and_keeps_its_lane(tmp_path):
    reg = tmp_path / "procs.json"
    reg.write_text(json.dumps({"processes": [
        {"id": "p_with", "allowed_lanes": ["fast", "grok"], "task_class": "reason"},
        {"id": "p_without", "allowed_lanes": ["fast", "grok"]}]}), encoding="utf-8")
    env = {"TRADEAI_LLM_PROCESS_REGISTRY": str(reg)}
    with_tc = mc.choose("p_with", env=env)
    without = mc.choose("p_without", env=env)
    assert with_tc["task_class"] == "reason" and with_tc["task_class_status"] == "OK"
    assert with_tc["task_class_primary_model"] == POLICY["models"]["mid"]
    assert without["task_class_status"] == mc.TASK_CLASS_UNASSIGNED and without["task_class_route"] == []
    assert with_tc["lane"] == without["lane"] and with_tc["reason"] == without["reason"]
    # an explicit task_class argument overrides the registry row
    assert mc.choose("p_without", env=env, task_class="verdict")["task_class_primary_model"] == POLICY["models"]["standard"]
