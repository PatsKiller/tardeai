"""LQ-20261107-538 Part 1: due-diligence curation tries the free OAuth lanes first, on every path.

Operator directive 2026-11-07 21:08 ET: "critical problem. Make sure free is first." This supersedes the 2026-09-06
flash-first curation order.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

ANSWER = json.dumps({"narrative": [], "questions": []})
CHANGE = {"symbol": "ZZTEST", "kind": "volume", "observed_value": 2, "baseline": 1, "magnitude": 2.0,
          "observed_at": "2026-11-07"}
ITEMS = [{"id": "news:1", "date": "2026-11-07", "text": "x"}]


@pytest.fixture()
def ddq(monkeypatch):
    mod = pytest.importorskip("due_diligence_questions")
    monkeypatch.setattr(mod, "via_bridge", lambda: False)
    return mod


def _wire(monkeypatch, ddq, *, oauth_ok: bool, flash_ok: bool = True):
    calls: list[str] = []

    def oauth(prompt):
        calls.append("oauth")
        return {"text": ANSWER, "lane": "grok-oauth"} if oauth_ok else None

    def deepseek(prompt, model):
        calls.append(f"deepseek:{model}")
        return {"text": ANSWER, "lane": model, "model": model} if flash_ok else None

    monkeypatch.setattr(ddq, "_curate_via_oauth", oauth)
    monkeypatch.setattr(ddq, "_curate_via_deepseek", deepseek)
    return calls


def test_free_oauth_is_tried_before_any_paid_lane(monkeypatch, ddq):
    calls = _wire(monkeypatch, ddq, oauth_ok=True)
    out = ddq.ask_model(CHANGE, ITEMS)
    assert calls == ["oauth"], "a free answer must never be preceded or followed by a paid call"
    assert out["lane"] == "grok-oauth"


def test_paid_flash_runs_only_after_oauth_failed(monkeypatch, ddq):
    calls = _wire(monkeypatch, ddq, oauth_ok=False)
    out = ddq.ask_model(CHANGE, ITEMS)
    assert calls == ["oauth", f"deepseek:{ddq.CURATION_MODEL}"]
    assert out["lane"] == ddq.CURATION_MODEL


def test_every_lane_down_reaches_the_operator_stop_after_oauth_flash_pro(monkeypatch, ddq):
    calls = _wire(monkeypatch, ddq, oauth_ok=False, flash_ok=False)
    import lib.llm_escalation as esc

    class Stopped(RuntimeError):
        pass

    def stop(prompt, purpose):
        calls.append("ask")
        raise Stopped(purpose)

    monkeypatch.setattr(esc, "run_with_escalation", stop)
    with pytest.raises(Stopped):
        ddq.ask_model(CHANGE, ITEMS)
    assert calls == ["oauth", f"deepseek:{ddq.CURATION_MODEL}", f"deepseek:{ddq.CURATION_MODEL_PRO}", "ask"]


def test_the_module_docstring_records_free_first():
    src = (ROOT / "scripts/due_diligence_questions.py").read_text(encoding="utf-8")
    head = src[src.index("CURATION LANE ORDER"):src.index("GROUNDING IS ENFORCED")]
    assert head.index("free OAuth") < head.index("deepseek-flash"), "the documented order must put free first"
    assert "2026-11-07" in head


def test_the_bridge_route_is_grok_then_chatgpt_then_deepseek():
    """The n8n path's order lives in the routing policy, not in this module. Pin it: free, free, then paid."""
    root = json.loads((ROOT / "config/llm_routing_policy.json").read_text())
    row = root["policies"][root.get("default_policy_id", "default")]["processes"]["due_diligence_questions"]
    order = [row[k]["provider"] for k in ("primary", "secondary", "fallback")]
    assert order == ["grok", "chatgpt", "deepseek"]
    assert row["route_profile"] == "n8n_oauth_first"
