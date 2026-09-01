"""An absent field must never render as an affirmative value.

The brief printed `Data quality: OK` under every decision in a document whose
own holdings verdict was ATTENTION with REPRICE_AHEAD_OF_POSITIONS and
CASH_TOTAL_DISAGREEMENT. "OK" was not a verdict computed for that decision -- it
was a default asserted by `operator_decision_contract` when the field was
absent, then rendered as if it were a judgment.

Meanwhile `field_status` and `completeness.grade = OPERATOR_PRODUCT_PARTIAL` were
computed on every entry and reached no operator surface: the reader saw four
confident-looking lines while the machine had already recorded them unpopulated.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.operator_human_renderer import render_decision  # noqa: E402

ENTRY = {
    "symbol": "SCHG",
    "cio_decision": "HOLD",
    "field_status": {
        "confidence": "NOT_PROVIDED",
        "supporting_evidence": "PROVIDED",
        "counter_evidence": "NOT_PROVIDED",
        "blocking_conditions": "PROVIDED",
        "next_review_at": "NOT_PROVIDED",
    },
}
PRODUCT = {
    "confidence": 0.55,
    "completeness": {"grade": "OPERATOR_PRODUCT_PARTIAL"},
    "holdings_data_quality": {
        "state": "ATTENTION",
        "labels": ["REPRICE_AHEAD_OF_POSITIONS", "CASH_TOTAL_DISAGREEMENT"],
    },
}


def _line(text: str, prefix: str) -> str:
    for ln in text.splitlines():
        if ln.startswith(prefix):
            return ln
    return ""


def test_absent_data_quality_never_renders_as_ok():
    """A2. The regression: absence must read as absence."""
    line = _line(render_decision(dict(ENTRY)), "Data quality:")
    assert line, "no Data quality line rendered"
    assert line != "Data quality: OK"
    assert "not computed" in line


def test_the_real_verdict_is_rendered_when_the_product_carries_it():
    """A2. ATTENTION and its labels, not a default."""
    line = _line(render_decision(dict(ENTRY), PRODUCT), "Data quality:")
    assert "ATTENTION" in line
    assert "REPRICE_AHEAD_OF_POSITIONS" in line


def test_an_explicit_ok_is_still_honoured():
    """A2 must not invert into refusing a genuinely computed OK."""
    entry = dict(ENTRY, data_quality="OK")
    assert _line(render_decision(entry, PRODUCT), "Data quality:") == "Data quality: OK"


def test_completeness_is_rendered():
    """A3. The system already computed this and said nothing."""
    line = _line(render_decision(dict(ENTRY), PRODUCT), "Completeness:")
    assert "3 of 5 fields unpopulated" in line
    assert "OPERATOR_PRODUCT_PARTIAL" in line
    for field in ("confidence", "counter_evidence", "next_review_at"):
        assert field in line


def test_product_level_confidence_is_labelled_as_product_level():
    """A3. Name the value that exists -- never imply it was computed per decision."""
    line = _line(render_decision(dict(ENTRY), PRODUCT), "Confidence:")
    assert "product-level: 0.55" in line
    assert "not computed for this decision" in line


def test_a_per_decision_confidence_still_wins():
    entry = dict(ENTRY, confidence_text="0.81")
    assert _line(render_decision(entry, PRODUCT), "Confidence:") == "Confidence: 0.81"


def test_single_argument_callers_still_work():
    """Two existing call sites pass one argument; they must degrade honestly."""
    text = render_decision(dict(ENTRY))
    assert "Data quality: not computed for this decision" in text
    assert "Completeness:" in text


def test_the_guard_can_see_the_old_behaviour():
    """Guard the guard: the assertion must be able to fail on the defect."""
    old = "Data quality: %s" % (ENTRY.get("data_quality") or "OK")
    assert old == "Data quality: OK", "the mutation no longer reproduces the defect"
