"""CIO-LEARNING-001 compares due and matured from the same store.

2026-10-03: the finding "Outcomes due but none matured" stayed raised while the
checkpoint store had 361 matured outcomes, because "matured" was read from
advisory_outcomes_v1.jsonl, which nothing writes.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_observability import build_observability  # noqa: E402

NOW = "2026-10-03T17:00:00+00:00"


def _out(cockpit: dict, learning: dict | None = None) -> dict:
    brain = {"learning_cockpit": cockpit, "learning": learning or {"outcomes": {"matured": 0}},
             "memory_behavior_influence": 0, "as_of": NOW}
    return build_observability(home={}, brain=brain, research_ops={}, data_health={}, now=NOW)


def _ids(out: dict) -> set[str]:
    return {f.get("issue_id") for f in out.get("findings") or []}


def _funnel(out: dict, fid: str) -> int:
    return next(row["count"] for row in out["recommendation_funnel"] if row["id"] == fid)


def test_matured_checkpoints_clear_the_finding():
    out = _out({"outcomes_due": 7, "matured_outcomes": 361})
    assert "CIO-LEARNING-001" not in _ids(out)
    assert _funnel(out, "matured") == 361


def test_finding_still_fires_when_nothing_has_matured():
    out = _out({"outcomes_due": 7, "matured_outcomes": 0})
    assert "CIO-LEARNING-001" in _ids(out)


def test_legacy_learning_count_is_only_a_fallback():
    out = _out({"outcomes_due": 7}, {"outcomes": {"matured": 4}})
    assert "CIO-LEARNING-001" not in _ids(out)
    assert _funnel(out, "matured") == 4
