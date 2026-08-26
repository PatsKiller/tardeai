"""Phase A — S3 notify only with capital ACT_NOW / governed RE_ENTER."""
from __future__ import annotations

from scripts.lib.cio_plan_enrichment import is_material_plan, s3_capital_act_now


def _s3_plan(**extra):
    p = {
        "plan_id": "plan_s3_test",
        "situation_type": "S3_REENTRY_CANDIDATE",
        "symbols": ["AMD"],
        "status": "proposed",
        "fire_reasons": ["reentry_READY"],
        "summary": "reentry desk READY",
        "recommendation": "Surface only",
        "options": [{"id": "watch", "label": "Watch", "pros": "", "cons": ""}],
        "evidence_refs": [
            {"domain": "reentry", "as_of": "2026-08-20"},
            {"domain": "holdings_detail", "as_of": "2026-08-20"},
        ],
    }
    p.update(extra)
    return p


def test_s3_bare_ready_not_material():
    assert s3_capital_act_now(_s3_plan()) is False
    assert is_material_plan(_s3_plan()) is False


def test_s3_act_now_flag_is_material():
    p = _s3_plan(act_now=True)
    assert s3_capital_act_now(p) is True
    assert is_material_plan(p) is True


def test_s3_capital_act_now_flag_is_material():
    p = _s3_plan(capital_act_now=True)
    assert s3_capital_act_now(p) is True
    assert is_material_plan(p) is True


def test_s3_fire_reason_act_now_is_material():
    p = _s3_plan(fire_reasons=["reentry_READY", "act_now"])
    assert s3_capital_act_now(p) is True
    assert is_material_plan(p) is True


def test_s6_still_always_material():
    assert is_material_plan({
        "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
        "symbols": ["SCHD"],
        "fire_reasons": ["weight_above_cap"],
    }) is True
