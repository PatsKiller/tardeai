"""l3_judgment_author must carry a process cost ceiling (2026-09-11 defect)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_l3_judgment_author_in_registry_with_cost_cap():
    reg = json.loads((ROOT / "config" / "llm_process_registry.json").read_text(encoding="utf-8"))
    row = next(p for p in reg["processes"] if p.get("id") == "l3_judgment_author")
    assert row.get("daily_cost_cap_usd") is not None
    assert float(row["daily_cost_cap_usd"]) > 0
    assert int(row.get("daily_soft_cap") or 0) > 0
    assert row.get("advisory_only") is True
    assert "deepseek" in str(row.get("lane_policy") or "")


def test_l3_judgment_author_in_sync_caps():
    src = (ROOT / "scripts" / "sync_cio_process_caps.py").read_text(encoding="utf-8")
    assert '"l3_judgment_author"' in src
    assert '"l3_independent_critic"' in src
