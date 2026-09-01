"""cash_letter publishes capital_plan row-sum cash, not the CASH_SLEEVE fossil.

Follow-up to #831 LITMUS_MONEY. The letter and capital_plan must agree in the
same /v3/cio/home body. Sleeve disagreement is retained as prior_cash_*.

Mutations (must go red):
  * letter reads CASH_SLEEVE.cash_usd again as the published dollar
  * rows 630513.62 vs letter 630784.82 in one payload

READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. No holdings write. No wake persist.
"""
from __future__ import annotations

import ast
import io
import tokenize
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib.cio_record_narrative import build_cash_letter

ROOT = Path(__file__).resolve().parents[1]
NARRATIVE = ROOT / "scripts" / "lib" / "cio_record_narrative.py"
API_V2 = ROOT / "scripts" / "api_v2.py"

NOW = datetime(2026, 9, 1, 20, 0, 0, tzinfo=timezone.utc)
ROW_SUM = 630513.62
SLEEVE_FOSSIL = 630784.82
DELTA = round(SLEEVE_FOSSIL - ROW_SUM, 2)  # 271.20 — measured, not invented
CASH_AS_OF = "2026-08-14"


def _plan(*, cash: float = ROW_SUM) -> dict:
    return {
        "cash_total_usd": cash,
        "cash_source": "position_rows",
        "cash_as_of": {
            "as_of": CASH_AS_OF,
            "unstamped": False,
            "source": "holdings rows where is_cash, oldest stamp wins",
        },
        "cash_posture": "ABOVE_BAND",
        "cash_investable_usd": 300000.0,
    }


def _sleeve(*, cash: float = SLEEVE_FOSSIL) -> dict:
    return {
        "subject_key": "SLEEVE:CASH",
        "cash_usd": cash,
        "cash_written_at": "2026-08-29T23:28:23.648735+00:00",
        "cash_source": "position_rows",
        "next_eligible_at": "2026-09-15T13:30:00+00:00",
        "cc_narrative": {
            "what": "Cash sleeve held as optionality.",
            "recommendation_option_id": "hold_cash",
            "writer": "agent:cio_cash_lane",
        },
    }


def test_letter_cash_equals_capital_plan_not_sleeve():
    letter = build_cash_letter(_sleeve(), capital_plan=_plan(), now=NOW)
    assert letter["cash_usd"] == ROW_SUM
    assert letter["cash_usd"] == _plan()["cash_total_usd"]
    assert letter["cash_usd"] != SLEEVE_FOSSIL
    assert letter["prior_cash_usd"] == SLEEVE_FOSSIL
    assert letter["prior_cash_written_at"] == "2026-08-29T23:28:23.648735+00:00"
    assert abs(letter["prior_cash_usd"] - letter["cash_usd"] - DELTA) < 0.001
    assert letter["as_of"] == CASH_AS_OF
    assert letter["composed_at"] == NOW.isoformat()
    assert letter["cash_source"] == "position_rows"


def test_letter_without_plan_does_not_fall_back_to_sleeve_dollar():
    """No capital_plan cash → published dollar absent; sleeve stays prior."""
    letter = build_cash_letter(_sleeve(), capital_plan={}, now=NOW)
    assert letter["cash_usd"] is None
    assert letter["prior_cash_usd"] == SLEEVE_FOSSIL
    assert letter["as_of"] is None


def test_matching_sleeve_and_plan_omits_prior():
    letter = build_cash_letter(
        _sleeve(cash=ROW_SUM), capital_plan=_plan(cash=ROW_SUM), now=NOW)
    assert letter["cash_usd"] == ROW_SUM
    assert "prior_cash_usd" not in letter


def test_mutation_rows_vs_letter_disagree_is_red():
    """Acceptance mutant: rows 630513.62, letter 630784.82 → must fail."""
    letter = build_cash_letter(_sleeve(), capital_plan=_plan(), now=NOW)
    rows = ROW_SUM
    # The live contract:
    assert letter["cash_usd"] == rows
    # The forbidden shape (pre-fix) would be:
    forbidden_letter = SLEEVE_FOSSIL
    assert not (rows == ROW_SUM and forbidden_letter == SLEEVE_FOSSIL
                and letter["cash_usd"] == forbidden_letter), (
        "letter must not publish the sleeve fossil beside the live row sum"
    )


def _strip_comments(src: str) -> str:
    out = io.StringIO()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        out.write(tok.string)
    return out.getvalue()


def test_mutation_letter_reads_sleeve_cash_usd_again_is_red():
    """Source guard: published cash_usd must not be assigned from rec/sleeve first.

    Strip comments so a comment cannot fake the contract. Walk build_cash_letter
    and refuse `cash_usd = rec.get("cash_usd")` (or equivalent) as the publish path.
    """
    src = NARRATIVE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "build_cash_letter")

    # Collect simple assignments to cash_usd / plan_cash / sleeve_cash
    assigned = {}
    for node in fn.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name):
                assigned[t.id] = node.value

    # cash_usd must come from plan_cash / cp.get("cash_total_usd"), not rec.get("cash_usd")
    cash_val = assigned.get("cash_usd")
    assert cash_val is not None, "build_cash_letter must assign cash_usd"
    # Accept Name('plan_cash') or cp.get("cash_total_usd")
    ok = False
    if isinstance(cash_val, ast.Name) and cash_val.id == "plan_cash":
        ok = True
    if isinstance(cash_val, ast.Call):
        f = cash_val.func
        if isinstance(f, ast.Attribute) and f.attr == "get":
            if cash_val.args and isinstance(cash_val.args[0], ast.Constant):
                if cash_val.args[0].value == "cash_total_usd":
                    ok = True
    assert ok, (
        "cash_usd must be assigned from capital_plan.cash_total_usd / plan_cash; "
        f"got {ast.dump(cash_val)}"
    )

    # And the stripped source must not contain the old prefer-sleeve pattern
    # as the publish assignment (rec.get("cash_usd") used as cash_usd directly).
    stripped = _strip_comments(src)
    # The defect shape: cash_usd = rec.get("cash_usd") before any plan read wins.
    assert 'cash_usd = rec.get("cash_usd")' not in stripped
    assert "cash_usd = rec.get('cash_usd')" not in stripped


def test_api_v2_proof_sentence_no_longer_claims_630784_gap_zero():
    """The ~2605 comment cited 630,784.82 gap 0.00 — that live claim is false."""
    src = API_V2.read_text(encoding="utf-8")
    # Still allowed to mention the historical number as a dated fossil.
    assert "630,784.82" in src or "630784.82" in src
    # Must not claim gap 0.00 as current proof without the correction.
    # (Comment is line-wrapped; match durable fragments.)
    assert "longer true as a live claim" in src
    assert "LITMUS_MONEY" in src
    assert "271.20" in src or "$271" in src
    assert "Do not resurrect" in src
