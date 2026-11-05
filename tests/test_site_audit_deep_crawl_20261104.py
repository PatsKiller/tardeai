"""SITE_AUDIT_DEEP_CRAWL_20261104 — SPEC §6 (operator 2026-11-04 ~12:45 ET).

"Can it actually click every link inside?" The crawl now opens detail views, follows in-page links one level, and still
never presses an action. These tests pin the three mechanics that make that safe and honest, plus the structural rule
that captures never enter the repo.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from site_audit.action_denylist import is_forbidden_action, safe_to_open  # noqa: E402
from site_audit.capture_root import (CaptureRootRefused, assert_capture_root,  # noqa: E402
                                     configured_capture_root, CAPTURE_ROOT_ENV)
from site_audit.completeness import card_severity, thesis_as_of_missing, P1, P2  # noqa: E402
from site_audit.detail_budget import (DETAILS_PER_PAGE, page_kind, runs_to_cover,  # noqa: E402
                                      selected_indices)
from site_audit.lane import run_slot, windows_between  # noqa: E402

# ── never press an action ──────────────────────────────────────────────────────────────────────────────────────
def test_actions_are_refused_by_label_and_role():
    for label in ("Approve", "Decline", "Acknowledge", "Refresh", "Run now", "Apply", "Merge",
                  "Stop", "Engage kill switch", "Place order", "Buy", "Resume trading"):
        assert is_forbidden_action(label, "button") is True, label


def test_navigation_is_not_an_action():
    assert safe_to_open("Approvals", "link") is True          # a hub link, not the Approve button
    assert safe_to_open("Open ADBE", "link") is True
    assert safe_to_open("Trend", "heading") is True
    assert safe_to_open("ADBE approves the thesis", "heading") is True   # text under a heading is not a control


def test_an_unlabelled_button_is_never_pressed():
    assert is_forbidden_action("", "button") is True
    assert is_forbidden_action(None, "button") is True


# ── sampling budget with per-run coverage ──────────────────────────────────────────────────────────────────────
def test_top_lists_take_every_row_and_others_rotate():
    assert selected_indices(7, page="home", run_index=0) == list(range(7))
    assert selected_indices(7, page="best_opportunities", run_index=5) == list(range(7))

    rows = 55
    runs = [set(selected_indices(rows, page="watch", run_index=r)) for r in range(runs_to_cover(rows))]
    assert all(len(r) == DETAILS_PER_PAGE for r in runs)
    assert set().union(*runs) == set(range(rows)), "the rotation never covers every row"


def test_the_real_home_route_is_a_top_list_not_a_capped_page():
    """cx-openai-4 R4 on #2648: the caller passes "/", and only the bare alias "home" was recognised."""
    for route in ("/", "", "/v3", "/v3/", "home", "/home?tab=1"):
        assert page_kind(route) == "home", route
        assert selected_indices(55, page=route, run_index=3) == list(range(55)), route
    assert page_kind("/samples/opens") == "samples_opens"
    assert len(selected_indices(55, page="/samples/opens", run_index=0)) == DETAILS_PER_PAGE


def test_every_row_is_covered_inside_one_week_of_runs():
    """Five scheduled runs a week; a 20-row budget must reach every row of a 55-row table within them."""
    assert runs_to_cover(55) == 3
    assert runs_to_cover(55) <= 5
    covered = set().union(*(set(selected_indices(55, page="samples_opens", run_index=r)) for r in range(5)))
    assert covered == set(range(55))


def test_consecutive_scheduled_runs_get_consecutive_indices():
    """The rotation step is the RUN, not the ISO week: two runs in one week must not sample the same rows."""
    # Sunday 2026-11-01 .. the following Sunday: exactly the week's five scheduled starts (Sun 21:00, Mon/Wed/Fri/Sat 17:30).
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    slots = [run_slot(m) for m in windows_between(start, start + timedelta(days=7))]
    assert len(slots) == 5
    assert slots == list(range(slots[0], slots[0] + 5)), slots
    first = selected_indices(55, page="samples_opens", run_index=slots[0])
    second = selected_indices(55, page="samples_opens", run_index=slots[1])
    assert not set(first) & set(second), "two runs in the same week opened the same rows"


def test_an_empty_list_costs_nothing():
    assert selected_indices(0, page="watch", run_index=3) == []
    assert runs_to_cover(0) == 0


# ── completeness, with the top-list P1 rule ────────────────────────────────────────────────────────────────────
COMPLETE = {
    "price": 248.85, "rsi": 54.2, "macd": 1.1,
    "sma_20": 240.0, "sma_50": 230.0, "sma_200": 210.0,
    "support_1": 240.0, "support_2": 230.0, "resistance_1": 252.0, "resistance_2": 260.0,
    "trend": "up", "cio_stance": "HOLD", "cio_as_of": "2026-11-04T14:00:00Z",
}


def test_a_complete_card_is_complete():
    assert card_severity(COMPLETE, top_list=True) == (None, [])


def test_a_top_list_card_missing_evidence_is_p1():
    card = {**COMPLETE}
    card.pop("rsi")
    severity, gaps = card_severity(card, top_list=True)
    assert severity == P1 and gaps[0]["field"] == "rsi"


def test_an_explained_gap_away_from_a_top_list_is_p2_and_an_unexplained_one_is_p1():
    explained = {**COMPLETE, "rsi": None, "rsi_reason": "quote is stale; the indicator is not computed"}
    assert card_severity(explained, top_list=False)[0] == P2
    unexplained = {**COMPLETE, "rsi": None}
    assert card_severity(unexplained, top_list=False)[0] == P1


def test_a_thesis_without_an_as_of_is_flagged():
    assert thesis_as_of_missing({**COMPLETE, "cio_as_of": None}) is True
    assert thesis_as_of_missing(COMPLETE) is False


# ── the captured detail TEXT is graded by the same rule (cx-cloud CX2 on #2648) ─────────────────────────────────
def test_detail_text_is_parsed_into_the_card_the_checks_grade():
    from site_audit.completeness import assess_detail_text

    text = "\n".join([
        "NVDA", "Price 248.85", "RSI 54.2", "MACD 1.1", "SMA 20 240.0", "SMA 50 230.0", "SMA 200 210.0",
        "Support 1 240.0", "Support 2 230.0", "Resistance 1 252.0", "Resistance 2 260.0", "Trend up",
        "CIO stance HOLD", "As of 2026-11-04",
    ])
    got = assess_detail_text(text)
    assert got["evaluated"] is True and got["severity"] is None, got

    without_cio = assess_detail_text(text.replace("CIO stance HOLD\nAs of 2026-11-04", ""))
    assert without_cio["evaluated"] is True and without_cio["severity"] == P1
    assert any(g["field"] == "cio_stance_or_thesis" for g in without_cio["gaps"]), without_cio


def test_a_value_the_surface_marks_absent_is_a_gap_not_evidence():
    from site_audit.completeness import assess_detail_text

    text = "NVDA\nPrice —\nRSI n/a\nMACD 1.1\nTrend up\nCIO stance HOLD\nAs of 2026-11-04"
    got = assess_detail_text(text)
    fields = {g["field"] for g in got["gaps"]}
    assert {"price", "rsi"} <= fields, got
    assert "macd" not in fields, got


def test_the_grouped_technical_rows_the_product_renders_are_parsed():
    """cx-cloud CX7 on #2648: OpportunityModal prints three fields in one row, and the parser saw only the first."""
    from site_audit.completeness import assess_detail_text

    text = "\n".join([
        "NVDA", "Current price $248.85", "RSI (14) 54.2", "MACD 1.1 · hist up", "Trend Bullish",
        "Support 1 / 2 $240.00 / $232.00",
        "Resistance 1 / 2 $252.00 / $260.00",
        "20 / 50 / 200-day $245.00 / $238.00 / $210.00",
        "CIO thesis Hold until margins improve", "As of 2026-11-04",
    ])
    got = assess_detail_text(text)
    assert got["evaluated"] is True, got
    assert got["severity"] is None, got
    for name in ("support_1", "support_2", "resistance_1", "resistance_2",
                 "sma_20", "sma_50", "sma_200"):
        assert got["card"].get(name) == "present", (name, got["card"])


def test_a_grouped_row_marks_only_the_value_the_surface_actually_printed():
    """A slash-separated "—" is that one field's gap, not evidence for the whole row."""
    from site_audit.completeness import assess_detail_text

    text = "\n".join([
        "NVDA", "Current price $248.85", "RSI (14) 54.2", "MACD 1.1", "Trend Bullish",
        "Support 1 / 2 $240.00 / —",
        "Resistance 1 / 2 $252.00 / $260.00",
        "20 / 50 / 200-day $245.00 / — / $210.00",
        "CIO thesis Hold until margins improve", "As of 2026-11-04",
    ])
    got = assess_detail_text(text)
    gaps = {g["field"] for g in got["gaps"]}
    assert {"support_2", "sma_50"} <= gaps, got
    assert not {"support_1", "resistance_1", "resistance_2", "sma_20", "sma_200"} & gaps, got


def test_a_detail_that_is_not_a_symbol_card_is_not_graded():
    """A proposal/options detail must not become a "missing technicals" finding."""
    from site_audit.completeness import assess_detail_text

    got = assess_detail_text("Proposal 41\nApprove or decline\nRequested by Maria")
    assert got["evaluated"] is False and got["severity"] is None and got["gaps"] == [], got


def test_a_blank_detail_is_a_p1_not_an_ungraded_unknown():
    from site_audit.completeness import assess_detail_text

    got = assess_detail_text("   \n")
    assert got["evaluated"] is True and got["severity"] == P1
    assert got["gaps"][0]["field"] == "detail_text"


# ── captures never enter the repo ──────────────────────────────────────────────────────────────────────────────
def test_a_capture_root_inside_the_repo_is_refused():
    try:
        assert_capture_root(ROOT / "page-audit-x", repo_root=ROOT)
    except CaptureRootRefused:
        pass
    else:
        raise AssertionError("an in-repo capture root was accepted")


def test_the_capture_root_is_configuration_outside_the_repo(tmp_path, monkeypatch):
    # Unset: refused, with the variable named — the lane supplies it, the code does not guess.
    monkeypatch.delenv(CAPTURE_ROOT_ENV, raising=False)
    try:
        configured_capture_root(repo_root=ROOT)
    except CaptureRootRefused as exc:
        assert CAPTURE_ROOT_ENV in str(exc)
    else:
        raise AssertionError("a capture root was accepted without configuration")

    outside = tmp_path / "audit"
    monkeypatch.setenv(CAPTURE_ROOT_ENV, str(outside))
    resolved = configured_capture_root(repo_root=ROOT)
    assert ROOT not in resolved.parents

    # ...and a configured root inside the checkout is still refused.
    monkeypatch.setenv(CAPTURE_ROOT_ENV, str(ROOT / "page-audit-x"))
    try:
        configured_capture_root(repo_root=ROOT)
    except CaptureRootRefused:
        pass
    else:
        raise AssertionError("a configured in-repo capture root was accepted")


def test_capture_artifacts_are_ignored_by_git():
    for sample in ("page-audit-20261104T0000Z/index.json", "x/site-audit-capture/a.png", "audit-captures/b.txt"):
        out = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", sample])
        assert out.returncode == 0, f"{sample} is not ignored"


def test_the_imported_capture_script_cannot_write_into_the_repo():
    src = (ROOT / "scripts" / "site_audit" / "page_audit_capture.py").read_text()
    assert 'REPO = Path(__file__).resolve().parents[2]' in src
    assert "configured_capture_root(" in src
