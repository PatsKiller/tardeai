"""Q1-derived substantiveness grades. PASS mints CURRENT; B/C mint THIN."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.thesis_substantiveness import (
    grade_text,
    join_research_text,
    mint_state_for,
    pass_fixture,
    score_text,
)


def test_pass_fixture_is_grade_a():
    text = pass_fixture("JEPI")
    g = grade_text("JEPI", text)
    assert g["grade"] == "A"
    assert g["bucket"] == "PASS"
    assert g["coverage_state"] == "CURRENT"
    assert mint_state_for(g) == "CURRENT"
    assert g["thesis_survivable"] is True
    assert g["n_chars"] >= 400


def test_sub_300_generic_is_thin_c():
    text = (
        "Hold / watch. Insufficient fresh evidence. Do not initiate. "
        "Not a sound candidate. Maintain paper-trading watchlist. " * 2
    )
    assert len(text) < 300
    g = grade_text("ZZZZ", text)
    assert g["grade"] == "C"
    assert g["bucket"] == "THIN"
    assert mint_state_for(g) == "THIN"
    assert g["coverage_state"] == "THIN"


def test_forty_char_floor_is_thin_not_current():
    text = "BND is a ballast sleeve we continue to hold in size."
    assert 40 <= len(text) < 300
    g = grade_text("BND", text)
    assert g["coverage_state"] == "THIN"
    assert g["grade"] == "C"
    assert mint_state_for(g) != "CURRENT"


def test_under_40_is_skip():
    g = grade_text("AA", "too short to be a thesis")
    assert g["grade"] == "F"
    assert g["coverage_state"] == "RESEARCH_REQUIRED"
    assert mint_state_for(g) == "SKIP"
    assert g["would_mint"] is False


def test_numeric_fidelity_fail_blocks_pass():
    text = pass_fixture("SCHD")
    # Inject a restated number close to context (5–40% off, ≥0.5 abs).
    text = text + " Trailing yield cited as 7.20 versus packet."
    ctx = "SCHD distribution yield 8.10 percent in the latest filing."
    g = grade_text("SCHD", text, ctx)
    assert g["numeric_fidelity_fail"] is True
    assert g["coverage_state"] != "CURRENT"
    assert g["grade"] != "A"


def test_joined_evidence_can_lift_grade():
    rec = "SCHD: Hold. Wait for clearer evidence on the sleeve."
    evidence = [
        {"tag": "fact", "text": "SCHD dividend yield 3.4 from the latest 10-K filing."},
        {
            "tag": "risk",
            "text": (
                "Invalidation is a distribution cut or earnings miss. Role is income ballast. "
                "Trim if concentration breaks policy. Catalyst is the next ex-div. "
                "Why own SCHD: dividend sleeve, not a trade. SEC filing must stay current. "
            )
            * 3,
        },
    ]
    joined = join_research_text(rec, None, evidence)
    g_rec = grade_text("SCHD", rec)
    g_join = grade_text("SCHD", joined)
    assert mint_state_for(g_rec) in ("THIN", "SKIP")
    assert g_join["n_chars"] > g_rec["n_chars"]


def test_score_text_matches_grade_survivable():
    text = pass_fixture("DIV")
    sc = score_text("DIV", text)
    g = grade_text("DIV", text)
    assert sc["thesis_survivable"] is True
    assert g["thesis_survivable"] is True
    assert g["grade"] == "A"
