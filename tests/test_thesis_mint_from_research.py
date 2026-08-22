"""Mint dry-run grades CURRENT vs THIN. No live cio_theses.jsonl writes."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import thesis_mint_from_research as mint
from scripts.lib.thesis_substantiveness import grade_text, join_research_text, pass_fixture


def test_summary_caps_but_keeps_pass_floor():
    text = pass_fixture("JEPI") + " extra clause " * 80
    s = mint._summary_from_rec("JEPI", text, cap=2000)
    assert "JEPI" in s
    assert len(s) <= 2000
    assert len(s) >= 400
    assert grade_text("JEPI", s)["coverage_state"] == "CURRENT"


def test_would_mint_state_thin_not_current_on_short_rec():
    rec = "CSWC: Hold / watch. Insufficient evidence to act."
    g = grade_text("CSWC", mint._summary_from_rec("CSWC", rec))
    assert g["coverage_state"] == "THIN"
    assert g["would_mint"] is True


def test_mint_script_has_no_live_apply_flag():
    src = (ROOT / "scripts/thesis_mint_from_research.py").read_text()
    assert "--apply-live" not in src
    assert "cio_theses.jsonl" in src  # mentioned as forbidden / after 8/27
    assert "apply_after" in src
    assert "substantiveness" in src


def test_joined_body_is_preferred_over_rec_only():
    rec = "PFLT: Hold."
    joined = join_research_text(
        rec,
        "Counter-view: credit spread widening.",
        [{"tag": "fact", "text": pass_fixture("PFLT")}],
    )
    g_rec = grade_text("PFLT", mint._summary_from_rec("PFLT", rec))
    g_join = grade_text("PFLT", mint._summary_from_rec("PFLT", joined))
    assert g_rec["coverage_state"] != "CURRENT"
    assert g_join["coverage_state"] == "CURRENT"


def test_mint_state_grades_rec_only_not_joined():
    src = (ROOT / "scripts/thesis_mint_from_research.py").read_text()
    assert "Grade the stored recommendation, not joined evidence" in src
    assert "g_mint = g_rec" in src
