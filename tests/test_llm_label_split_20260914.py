"""Each caller that shared advisory_desk_opinion bills to its own process id.

2026-09-14: 88% of the week's $5.45 was logged as "Advisory Desk per-row opinion", but that id carried at
least six different callers:
- operator replies;
- plan enrichment;
- the prompt judge;
- the usefulness scorer;
- CIO Hermes research;
- the golden judge.

Nobody could say which one spent it, or move a scheduled one off-peak without also moving answers to the
operator. The operator approved splitting it.

Offline: no bridge, no provider, no database.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.lib.cio_governed_model_bridge as bridge  # noqa: E402

SPLIT = {
    "operator_reply": "cio_operator_reply",
    "plan_enrichment": "cio_plan_enrichment",
    "prompt_judge": "cio_prompt_judge",
    "research_circle": "research_circle_analyzer",
    "hermes_cloud_json": "hermes_cloud_json",
    "usefulness_score": "hermes_usefulness_score",
    "hermes_research_job": "cio_hermes_research",
    "golden_judge": "hermes_golden_judge",
}


@pytest.mark.parametrize("task,process", sorted(SPLIT.items()))
def test_each_task_type_resolves_to_its_own_registered_flash_process(task, process):
    assert bridge.resolve_caller("advisory_desk", task) == process
    policy = bridge.resolve_model_policy(process)
    assert policy is not None and policy["requested_policy"] == "FAST"
    registry = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    row = next(p for p in registry["processes"] if p["id"] == process)
    assert "FAST" in row["deepseek_allowed_policies"] and row["daily_cost_cap_usd"] > 0 and row["daily_soft_cap"] > 0


def test_the_advisory_engine_keeps_its_id_and_unknown_tasks_fall_back_to_it():
    assert bridge.resolve_caller("advisory_desk", "advisory_opinion") == "advisory_desk_opinion"
    assert bridge.resolve_caller("advisory_desk", "something_new") == "advisory_desk_opinion"


def test_operator_answers_are_manual_and_scheduled_callers_automated():
    registry = {
        p["id"]: p for p in json.loads((ROOT / "config" / "llm_process_registry.json").read_text())["processes"]
    }
    assert registry["cio_operator_reply"]["default_mode"] == "manual"
    assert registry["research_circle_analyzer"]["default_mode"] == "manual"
    for pid in ("cio_plan_enrichment", "hermes_usefulness_score", "cio_hermes_research", "hermes_cloud_json"):
        assert registry[pid]["default_mode"] == "automated"


def test_the_bridge_logs_manual_processes_as_ad_hoc():
    src = (ROOT / "scripts" / "lib" / "cio_governed_model_bridge.py").read_text(encoding="utf-8")
    assert 'trigger_mode="manual" if str(cfg.get("mode") or "") == "manual" else "automated"' in src


def test_caps_sync_covers_every_split_process():
    src = (ROOT / "scripts" / "sync_cio_process_caps.py").read_text(encoding="utf-8")
    for process in SPLIT.values():
        assert f'"{process}"' in src


def test_plan_enrichment_sends_the_callers_task_type(monkeypatch):
    import urllib.request

    from scripts.lib import cio_plan_enrichment as pe

    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "{}"}}], "usage": {}}).encode()

    def fake_urlopen(req, timeout=None):
        seen.update({k.lower(): v for k, v in req.header_items()})
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    policy = {"llm": {"caller_flash": "advisory_desk", "task_type_flash": "plan_enrichment"}}
    pe.call_governed_llm([{"role": "user", "content": "x"}], policy, use_pro=False, task_type="operator_reply")
    assert seen["x-tradeai-task-type"] == "operator_reply"
    pe.call_governed_llm([{"role": "user", "content": "x"}], policy, use_pro=False)
    assert seen["x-tradeai-task-type"] == "plan_enrichment"


@pytest.mark.parametrize(
    "path,needle",
    [
        ("scripts/lib/cio_telegram_converse.py", 'task_type="operator_reply"'),
        ("scripts/lib/cio_operator_desk_loop.py", 'task_type="operator_reply"'),
        ("scripts/lib/cio_prompt_judge.py", 'task_type="prompt_judge"'),
        ("scripts/lib/research_circle.py", 'task_type="research_circle"'),
        ("scripts/hermes_external_feedback_loop.py", 'task_type="usefulness_score"'),
        ("scripts/lib/hermes_bridge_backend.py", '"hermes_research_job"'),
        ("scripts/lib/hermes_golden_judge.py", '"golden_judge"'),
        ("scripts/hermes_llm_failover.py", '"hermes_cloud_json"'),
        ("config/cio_llm_policy.yaml", 'task_type_flash: "plan_enrichment"'),
    ],
)
def test_each_caller_names_itself(path, needle):
    assert needle in (ROOT / path).read_text(encoding="utf-8")


def test_the_operator_desk_loop_names_all_three_of_its_calls():
    src = (ROOT / "scripts" / "lib" / "cio_operator_desk_loop.py").read_text(encoding="utf-8")
    assert src.count('task_type="operator_reply"') == 3


def test_chat_json_passes_task_type_and_still_rejects_local_options(monkeypatch):
    import hermes_llm_failover as hf

    seen = {}

    def fake_chat(prompt, *, timeout_s=None, task_type=None):
        seen["task_type"] = task_type
        return '{"ok": true}'

    monkeypatch.setattr(hf, "_bridge_flash_chat", fake_chat)
    hf.chat_json("x", task_type="usefulness_score")
    assert seen["task_type"] == "usefulness_score"
    with pytest.raises(hf.HermesLlmError):
        hf.chat_json("x", num_ctx=4096)
