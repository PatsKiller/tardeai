"""P8 — Outcome/lesson MBI partition diligence.

Exit gate (master plan Phase 8): lessons affect research question / priority /
narrative only — never size / orders / broker. CI-oriented proofs that
InstrumentRecord and CIOOperatorProduct stamp MBI_BEHAVIOR=0 and reject
behavior fields.

Gap: G-MBI-01. READ_ONLY_ADVISORY. MBI_BEHAVIOR=0 immutable.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from scripts.lib.cio_instrument_record import (
    BEHAVIOR_FIELDS,
    COGNITION_FIELDS,
    BehaviorWriteRefused,
    apply_cognition,
    cc_narrative,
    new_record,
)
from scripts.lib import cio_operator_product as op

REPO = Path(__file__).resolve().parents[1]

# Modules that mint advisory products / records — must stamp MBI=0.
STAMP_MODULES = (
    "scripts/lib/cio_instrument_record.py",
    "scripts/lib/cio_operator_product.py",
    "scripts/lib/cio_situation_notify_bridge.py",
    "scripts/lib/cio_council_synthesis.py",
)

# Forbidden: raising the ceiling or reading MBI to size.
BEHAVIOR_TOKENS = (
    "recommended_delta_usd",
    "size_usd",
    "shares",
    "qty",
    "order",
    "stop",
    "limit",
    "target_weight_pct",
    "trade",
    "execution",
)


def _src(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8", errors="replace")


# ── stamp: product + instrument record ─────────────────────────────────────

def test_p8_instrument_record_stamps_mbi_behavior_zero():
    rec = new_record("HELD", "SCHD")
    assert rec["memory_behavior_influence"] == 0
    assert rec.get("memory_cognition_influence") == 1
    assert rec["authority"] == "READ_ONLY_ADVISORY"


def test_p8_operator_product_module_declares_mbi_zero():
    assert getattr(op, "MBI", None) == 0
    text = _src("scripts/lib/cio_operator_product.py")
    assert re.search(r"\bMBI\s*=\s*0\b", text)
    assert '"memory_behavior_influence": MBI' in text


@pytest.mark.parametrize("field", BEHAVIOR_FIELDS)
def test_p8_behavior_fields_rejected_on_cognition_apply(field):
    rec = new_record("HELD", "SCHD")
    with pytest.raises(BehaviorWriteRefused):
        apply_cognition(rec, next_research_question="ok?", **{field: 1})


# ── lessons: cognition only ────────────────────────────────────────────────

def test_p8_lesson_moves_research_priority_narrative_only():
    rec = new_record("HELD", "SCHD")
    out, changed = apply_cognition(
        rec,
        next_research_question="Did the ex-div buffer change?",
        notify_priority="digest",
        narrative=cc_narrative(what="lesson deferred; ask again after earnings"),
        lesson={"lesson_id": "L_p8", "claim": "defer honored — do not chase"},
    )
    assert set(changed) <= set(COGNITION_FIELDS)
    assert "next_research_question" in changed
    assert "notify_priority" in changed
    assert "cc_narrative" in changed
    assert out["memory_behavior_influence"] == 0
    les = out["lessons"][-1]
    assert les["support_only"] is True
    assert les["applied_to"] == "cognition"
    for bad in BEHAVIOR_FIELDS:
        assert bad not in out or out.get(bad) in (None, 0, "", [], {})


def test_p8_lesson_cannot_smuggle_size_or_orders():
    rec = new_record("EXIT", "AXTI")
    with pytest.raises(BehaviorWriteRefused):
        apply_cognition(
            rec,
            next_research_question="revisit exit",
            lesson={"lesson_id": "L_bad"},
            recommended_delta_usd=-25000,
        )
    with pytest.raises(BehaviorWriteRefused):
        apply_cognition(
            rec,
            next_research_question="revisit exit",
            size_usd=10000,
            order={"side": "BUY", "qty": 100},
        )


def test_p8_cognition_fields_are_exactly_the_partition():
    """Contract: only research / eligibility / notify priority / narrative."""
    assert COGNITION_FIELDS == (
        "next_research_question",
        "next_eligible_at",
        "notify_priority",
        "cc_narrative",
    )
    # Behavior partition must include size/order family.
    for required in ("recommended_delta_usd", "size_usd", "shares", "qty",
                     "order", "stop", "execution"):
        assert required in BEHAVIOR_FIELDS


# ── CI gate: MBI never rises (G-MBI-01) ─────────────────────────────────────

def test_p8_ci_mbi_never_rises_in_stamp_modules():
    """G-MBI-01: continuous gate — no module may assign MBI > 0."""
    offenders = []
    for rel in STAMP_MODULES:
        text = _src(rel)
        # Literal assignments MBI = N or memory_behavior_influence = N with N!=0
        for m in re.finditer(
            r"(?:MBI|memory_behavior_influence)\s*=\s*([1-9]\d*)", text):
            offenders.append(f"{rel}: assigns {m.group(0)}")
        # Dict literals with non-zero influence
        for m in re.finditer(
            r'["\']memory_behavior_influence["\']\s*:\s*([1-9]\d*)', text):
            offenders.append(f"{rel}: stamps {m.group(0)}")
    assert not offenders, offenders


def test_p8_ci_instrument_record_module_hardcodes_mbi_behavior_zero():
    tree = ast.parse(_src("scripts/lib/cio_instrument_record.py"))
    found = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "MBI_BEHAVIOR":
                    assert isinstance(node.value, ast.Constant)
                    found = node.value.value
    assert found == 0


def test_p8_council_synthesis_never_reads_mbi_to_act():
    """Council join must not consume MBI for sizing (Wave 3B pin retained)."""
    text = _src("scripts/lib/cio_council_synthesis.py")
    assert "memory_behavior_influence" not in text
    assert "MBI" not in text
