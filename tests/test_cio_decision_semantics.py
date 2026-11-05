"""Phase 3 — decision semantics hygiene (pure, no DB/broker)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_decision_semantics as ds  # noqa: E402
from scripts.lib import cio_capital_plan as cp  # noqa: E402
from scripts.lib import cio_sector_opportunity as so  # noqa: E402


def test_infer_stance_from_advisory_trim_label():
    assert ds.infer_stance_from_text("Advisory TRIM — SCHD") == "TRIM"
    # RE_ENTER is non-authoritative in free text: only explicit verdict=RE_ENTER
    # creates RE_ENTER (P0-1 re-entry text bypass closure).
    assert ds.infer_stance_from_text("Advisory RE_ENTER — ADBE") is None
    assert ds.infer_stance_from_text("Re-enter ADBE") is None
    assert ds.infer_stance_from_text("Defense income — XLI") is None


def test_stance_for_symbol_reads_label_when_verdict_null():
    queue = {"items": [
        {"symbol": "SCHD", "verdict": None, "directive_label": "Advisory TRIM — SCHD",
         "source": "advisory"},
        {"symbol": "SCHD", "verdict": None, "directive_label": "Defense income — SCHD",
         "source": "defense"},
    ]}
    assert ds.stance_for_symbol("SCHD", queue) == "TRIM"
    # capital plan wiring
    assert cp.stance_for("SCHD", queue) == "TRIM"


def test_no_hold_trim_contradiction_in_decisions():
    rows = [
        {"symbol": "SCHD", "cio_stance": "HOLD", "why_now": "Advisory TRIM — SCHD",
         "current_value_usd": 100_000.0, "current_weight_pct": 10.0,
         "recommended_delta_usd": 0.0, "risk": "concentration > cap", "account": "ira"},
        {"symbol": "SCHD", "cio_stance": "HOLD", "why_now": "Advisory TRIM — SCHD",
         "current_value_usd": 20_000.0, "current_weight_pct": 2.0,
         "recommended_delta_usd": 0.0, "risk": "within single-name cap", "account": "taxable"},
        {"symbol": "V", "cio_stance": "HOLD", "why_now": "Advisory TRIM — V",
         "current_value_usd": 50_000.0, "current_weight_pct": 5.0,
         "recommended_delta_usd": 0.0, "risk": "within single-name cap", "account": "ira"},
        {"symbol": "V", "cio_stance": "HOLD", "why_now": "Advisory TRIM — V",
         "current_value_usd": 40_000.0, "current_weight_pct": 4.0,
         "recommended_delta_usd": 0.0, "risk": "within single-name cap", "account": "taxable"},
    ]
    dec = ds.sanitize_decisions_now(rows, portfolio_value=1_000_000.0, limit=8)
    by = {d["symbol"]: d for d in dec}
    assert "SCHD" in by and "V" in by
    # Aggregated — one row each
    assert by["SCHD"]["current_value_usd"] == 120_000.0
    assert by["V"]["current_value_usd"] == 90_000.0
    assert by["SCHD"]["account_count"] == 2
    # Stance is Trim, not Hold
    assert by["SCHD"]["stance"] == "Trim"
    assert by["SCHD"]["stance_code"] == "TRIM"
    assert by["V"]["stance_code"] == "TRIM"
    # No duplicate symbols
    assert len(dec) == len({d["symbol"] for d in dec})


def test_pseudo_sector_iwm_spy_rejected():
    assert ds.is_pseudo_sector("Iwm−Spy") is True
    assert ds.is_pseudo_sector("IWM-SPY") is True
    assert ds.is_pseudo_sector("Spy/Qqq") is True
    assert ds.is_pseudo_sector("Technology") is False
    assert so.canonical_sector("Iwm−Spy") == ""
    assert so.canonical_sector("IWM-SPY") == ""
    assert so.normalize_sector_row({
        "sector": "Iwm−Spy", "state": "IMPROVING", "rs20": 1, "slope": 1,
    }) is None


def test_filter_sector_opportunities_drops_pseudo_and_professionalizes():
    sectors = [
        {"sector": "Technology", "state": "LEADING", "opportunity": True,
         "recommendation": "STAGED_DEPLOYMENT", "current_exposure_pct": 7.4},
        {"sector": "Iwm−Spy", "state": "IMPROVING", "opportunity": True,
         "recommendation": "RESEARCH_FIRST"},
        {"sector": "Energy", "state": "LEADING", "opportunity": True,
         "recommendation": "RESEARCH_FIRST"},
    ]
    clean = ds.filter_sector_opportunities(sectors)
    names = [c["sector"] for c in clean]
    assert "Iwm−Spy" not in names
    assert "Technology" in names and "Energy" in names
    tech = next(c for c in clean if c["sector"] == "Technology")
    assert tech["recommendation"] == "Staged deployment"
    assert tech["recommendation_code"] == "STAGED_DEPLOYMENT"


def test_you_ticker_requires_name():
    bad = ds.symbol_identity_status("YOU")
    assert bad["ok"] is False
    assert bad["reason"] == "ambiguous_ticker_unproven"
    good = ds.symbol_identity_status("YOU", name="Clear Secure Inc")
    assert good["ok"] is True


def test_cusip_requires_name():
    bad = ds.symbol_identity_status("12507E201")
    assert bad["ok"] is False
    good = ds.symbol_identity_status("12507E201", name="Some Fund")
    assert good["ok"] is True


def test_allocation_usd_to_weight():
    alloc = {"Cash & Equivalents": 578107.5, "Equities": 704326.01, "Other": 0.0}
    assert ds.looks_like_dollar_allocation(alloc) is True
    w = ds.allocation_weights_from_usd(alloc)
    assert abs(w["Cash & Equivalents"] + w["Equities"] + w["Other"] - 100.0) < 0.05
    assert w["Cash & Equivalents"] == round(578107.5 / (578107.5 + 704326.01) * 100, 2)
    # Never 578107%
    assert w["Cash & Equivalents"] < 100.0


def test_professional_labels():
    assert ds.professional_label("STAGED_DEPLOYMENT") == "Staged deployment"
    assert ds.professional_label("RESEARCH_FIRST") == "Research first"
    assert ds.professional_stance("TRIM") == "Trim"
    assert ds.professional_stance("RE_ENTER") == "Re-enter"


def test_build_position_decisions_aggregates_and_trims():
    queue = {"items": [
        {"symbol": "V", "verdict": None, "directive_label": "Advisory TRIM — V",
         "source": "advisory"},
    ]}
    pv = 500_000.0
    positions = [
        cp.normalize_position(
            {"symbol": "V", "market_value": 40_000.0, "account": "schwab_rollover_ira"}, pv),
        cp.normalize_position(
            {"symbol": "V", "market_value": 30_000.0, "account": "schwab_taxable"}, pv),
        cp.normalize_position(
            {"symbol": "NVDA", "market_value": 60_000.0, "account": "schwab_taxable"}, pv),
    ]
    rows = cp.build_position_decisions(
        positions, queue=queue, portfolio_value=pv,
    )
    by = {r["symbol"]: r for r in rows}
    assert "V" in by
    # One aggregated V row
    assert sum(1 for r in rows if r["symbol"] == "V") == 1
    assert by["V"]["cio_stance"] == "TRIM" or by["V"].get("stance_code") == "TRIM"
    assert by["V"]["current_value_usd"] == 70_000.0
    # Trim delta ≈ -10% of 70k (aggregated)
    assert by["V"]["recommended_delta_usd"] == -7_000.0


# ── FQ-103: the docstring's order is the order the function obeys ────────────────────────────────────────────
# An explicit formal verdict is the only input that records what the CIO decided. Free text (and desk readiness)
# may speak only when no actionable verdict was recorded. Before this, all three went through the decisive-stance
# merge, so a stronger word in a label outranked an explicit verdict — text deciding a position.

def test_an_explicit_verdict_outranks_free_text():
    from scripts.lib.cio_decision_semantics import stance_from_queue_item

    # The case the decision-path trace measured: an explicit ADD with an EXIT in the prose became EXIT.
    assert stance_from_queue_item(
        {"symbol": "SYNX", "verdict": "ADD", "directive_label": "Advisory EXIT — SYNX"}
    ) == "ADD"
    assert stance_from_queue_item(
        {"symbol": "SYNX", "verdict": "TRIM", "note": "ADD on a breakout, deploy here"}
    ) == "TRIM"
    assert stance_from_queue_item({"symbol": "SYNX", "verdict": "EXIT", "label": "HOLD for now"}) == "EXIT"


def test_free_text_still_speaks_when_no_verdict_was_recorded():
    from scripts.lib.cio_decision_semantics import stance_from_queue_item

    assert stance_from_queue_item({"symbol": "SCHD", "directive_label": "Advisory TRIM — SCHD"}) == "TRIM"
    assert stance_from_queue_item({"symbol": "SCHD", "label": "Advisory EXIT — SCHD"}) == "EXIT"


def test_the_reentry_guard_survives_the_precedence_fix():
    from scripts.lib.cio_decision_semantics import stance_from_queue_item

    # A governed RE_ENTER verdict is still the only way to RE_ENTER, and it still wins over prose.
    assert stance_from_queue_item(
        {"symbol": "ADBE", "verdict": "RE_ENTER", "directive_label": "HOLD, wait for the trigger"}
    ) == "RE_ENTER"
    # Desk readiness plus a "Re-enter" label remains REVIEW — never RE_ENTER.
    assert stance_from_queue_item(
        {"symbol": "ADBE", "state": "READY TO REVIEW", "directive_label": "Re-enter ADBE"}
    ) == "REVIEW"


def test_hold_and_review_are_explicit_verdicts_too():
    from scripts.lib.cio_decision_semantics import stance_from_queue_item

    # cc2's BLOCK at b5b61888: HOLD and REVIEW are recorded verdicts, not absences — an explicit HOLD is a decision
    # that prose cannot overrule. These two were the smallest repair the audit contract asked for.
    assert stance_from_queue_item(
        {"symbol": "SYNX", "verdict": "HOLD", "directive_label": "Advisory EXIT — SYNX"}
    ) == "HOLD"
    assert stance_from_queue_item(
        {"symbol": "SYNX", "verdict": "REVIEW", "directive_label": "Advisory ADD — SYNX"}
    ) == "REVIEW"
    # and an explicit HOLD outranks a typed desk state, as the contract order says.
    assert stance_from_queue_item({"symbol": "SYNX", "verdict": "HOLD", "state": "NEAR ENTRY"}) == "HOLD"


def test_placeholder_verdicts_are_not_verdicts():
    from scripts.lib.cio_decision_semantics import stance_from_queue_item

    # Only a real recorded value counts. An empty/placeholder/unrecognised value is a gap, so the label still speaks.
    for blank in ("", "—", "-", "N/A", "UNKNOWN", "SOMETHING_NEW"):
        assert stance_from_queue_item(
            {"symbol": "SCHD", "verdict": blank, "directive_label": "Advisory TRIM — SCHD"}
        ) == "TRIM", blank


def test_a_desk_state_outranks_prose_when_no_verdict_is_recorded():
    """cc-deepseek-6 at 8b7da7bee: the docstring's order is verdict > state > label, and the code obeyed only the first.

    With no recorded verdict the two lower inputs went through `merge_stances`, which keeps the STRONGER stance — so a
    label reading "Advisory EXIT" turned a READY TO REVIEW desk into EXIT. Free text deciding a position is exactly
    what FQ-103 exists to stop, one level below the verdict guard.
    """
    from scripts.lib.cio_decision_semantics import stance_from_queue_item

    for state in ("READY TO REVIEW", "NEAR ENTRY", "OVERSOLD REVIEW"):
        assert stance_from_queue_item({"symbol": "ADBE", "state": state,
                                       "directive_label": "Advisory EXIT — ADBE"}) == "REVIEW", state
        assert stance_from_queue_item({"symbol": "ADBE", "state": state,
                                       "directive_label": "Exit now"}) == "REVIEW", state
    # The label still speaks when the desk state says nothing at all — prose is the last resort, not a banned input.
    assert stance_from_queue_item({"symbol": "ADBE", "directive_label": "Advisory EXIT — ADBE"}) == "EXIT"
    # And a recorded verdict is untouched by any of this.
    assert stance_from_queue_item({"symbol": "ADBE", "verdict": "ADD",
                                   "state": "READY TO REVIEW", "directive_label": "Advisory EXIT"}) == "ADD"


def test_a_decisive_stance_is_never_overridden_by_prose_at_the_display_layer():
    """cc-deepseek-6's FQ-103 finding, found again one function over while repairing it.

    `resolve_display_stance` merged the formal stance with a stance inferred from `why_now` prose and kept the
    stronger, so `("ADD", "Advisory EXIT — SYNX")` rendered EXIT — a recorded ADD called an exit. A decisive formal
    stance now wins unconditionally.
    """
    from scripts.lib.cio_decision_semantics import resolve_display_stance

    assert resolve_display_stance("ADD", "Advisory EXIT — SYNX") == "ADD"
    assert resolve_display_stance("TRIM", "Advisory ADD — SYNX") == "TRIM"
    assert resolve_display_stance("REVIEW", "Advisory EXIT — SYNX") == "REVIEW"
    assert resolve_display_stance("EXIT", "adding on the pullback") == "EXIT"
    # The contradiction the function exists for is unchanged: no formal stance, decisive prose.
    assert resolve_display_stance(None, "Advisory TRIM — SCHD") == "TRIM"
    assert resolve_display_stance("", "Advisory EXIT — SYNX") == "EXIT"
