"""A critique-validated finding must reach a surface — and nothing more.

Before this, rule 2's non-blocked branch cleared `research_blocked`, recorded an
outcome string, and produced nothing the operator would ever see. The gate's own
reason code explains why the ceiling exists:

    POSITIVE_DELTA_MAY_RAISE_COMPLETENESS_NOT_ACTION

That rule is kept. A positive delta now reaches the operator through the three
cognition fields MBI_COGNITION=1 already permits — notify_priority,
cc_narrative, next_research_question — and touches no behaviour field.
MBI_BEHAVIOR stays 0.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib import cio_rehydrate as rh  # noqa: E402
from scripts.lib.cio_instrument_record import (  # noqa: E402
    BehaviorWriteRefused, new_record,
)


def _apply(delta):
    rec = new_record("HELD", "SCHD")
    return rh.apply_after_cycle(
        rec,
        artifact={"verdict": "VALID", "artifact_id": "res_1",
                  "delta_classification": delta},
        strict=False,
    )


def test_a_confirming_delta_raises_priority_and_asks_the_next_question():
    rec, changed = _apply("CONFIRMS")
    assert rec["notify_priority"] == "cc"
    assert rec["next_research_question"]
    assert "wrong" in rec["next_research_question"].lower()
    assert "notify_priority" in changed


def test_a_strengthening_delta_also_reaches_the_surface():
    rec, _ = _apply("STRENGTHENS")
    assert rec["notify_priority"] == "cc"
    assert "strengthen" in (rec["cc_narrative"] or {}).get("what", "").lower()


def test_an_honest_negative_stays_silent():
    """NO_NEW_INFO must not page. A lane that notifies on every completion is a
    lane the operator mutes, and then nothing reaches them at all."""
    for delta in ("NO_NEW_INFO", "INSUFFICIENT_DATA", ""):
        rec, _ = _apply(delta)
        assert rec.get("notify_priority") in (None, "none"), delta


def test_the_narrative_names_its_writer():
    rec, _ = _apply("CONFIRMS")
    assert (rec["cc_narrative"] or {}).get("writer") == "cognition:research_positive_delta"


def test_it_never_touches_a_behaviour_field():
    """The ceiling. apply_cognition refuses these outright, and the research
    path must not attempt them."""
    src = (ROOT / "scripts/lib/cio_rehydrate.py").read_text(encoding="utf-8")
    i = src.index("_POSITIVE_DELTAS")
    block = src[src.index("if _delta in _POSITIVE_DELTAS"):][:2000]
    for banned in ("size_usd", "shares", "qty", "target_weight_pct",
                   "recommended_delta_usd", "order", "stop"):
        assert f'"{banned}"' not in block, banned


def test_behaviour_writes_still_raise():
    """Proof the rail is intact, not merely unused."""
    with pytest.raises(BehaviorWriteRefused):
        from scripts.lib.cio_instrument_record import apply_cognition
        apply_cognition(new_record("HELD", "X"),
                        next_research_question="q", size_usd=1000)


def test_mbi_behaviour_stays_zero():
    rec, _ = _apply("CONFIRMS")
    assert rec.get("memory_behavior_influence", 0) == 0
