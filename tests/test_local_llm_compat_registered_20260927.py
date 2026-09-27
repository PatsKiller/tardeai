"""local_llm_compat is registered with a hard cap and refusals are logged (2026-09-27).

Before: unregistered, so every call from the shim's 18 importers was refused and
they silently got "". Hermetic: no model call, no DB.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]


def test_registered_with_hard_caps():
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text())
    p = {x["id"]: x for x in reg["processes"]}["local_llm_compat"]
    assert p["allowed_lanes"] == ["deepseek-flash"]
    assert p["daily_cost_cap_usd"] <= 0.25 and p["daily_soft_cap"] <= 150
    assert p["fallback_allowed"] is False and p["advisory_only"] is True


def test_refusal_is_logged_once_not_swallowed(monkeypatch, caplog):
    import local_llm
    import llm_lane

    def refuse(*a, **k):
        raise RuntimeError("PROCESS_NOT_REGISTERED: local_llm_compat")

    monkeypatch.setattr(llm_lane, "available", lambda lane: True)
    monkeypatch.setattr(llm_lane, "generate", refuse)
    local_llm._REFUSALS_LOGGED.clear()
    with caplog.at_level(logging.WARNING, logger="local_llm"):
        assert local_llm.generate("hi") == ""
        assert local_llm.generate("hi again") == ""
    hits = [r for r in caplog.records if "local_llm_compat call failed" in r.getMessage()]
    assert len(hits) == 1 and "PROCESS_NOT_REGISTERED" in hits[0].getMessage()
