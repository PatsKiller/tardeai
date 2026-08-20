"""Golden / structural gates for CIO desk synthesis v1.3 (Phase C).

Prefer fixture + dry generate over live Data Broker. Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import re
from typing import Any

from lib.cio_desk_synthesis import generate_desk_synthesis_v1, render_desk_note
from lib.hermes_research_schema import lint_execution_language

# Section headings emitted by render_desk_note (v1.3 institutional bar).
REQUIRED_SECTION_MARKERS = (
    "1. Executive thesis",
    "2. Portfolio state",
    "3. Allocation & concentration",
    "4. Material situations",
    "5. What we are doing and why",
    "6. What would change the call",
    "7. Research agenda",
    "8. Operator loop",
    "9. Evidence map",
)

# Phrases that must never appear as actionable execution language in a desk note.
# lint_execution_language covers the hard set; we also assert the negative fixture hits.
EXEC_NEGATIVE_FIXTURE = (
    "# CIO book memo v1.3.0 · desk@vTEST\n"
    "stance: unknown · cash STAGE_1 · as_of 2026-08-20T00:00:00\n"
    "────────────────\n"
    "🎯 *1. Executive thesis*\n"
    "Operator should buy now the dip and place order for SCHD immediately.\n"
    "📊 *2. Portfolio state*\n"
    "Book DATA_UNAVAILABLE.\n"
    "📐 *3. Allocation & concentration*\n"
    "Sector posture DATA_UNAVAILABLE.\n"
    "📍 *4. Material situations (integrated)*\n"
    "Force fill cash into names.\n"
    "✅ *5. What we are doing and why* (under `desk@vTEST`)\n"
    "1. *BUY* — place order now.\n"
    "🔬 *6. What would change the call*\n"
    "n/a\n"
    "🔬 *7. Research agenda*\n"
    "• none\n"
    "👤 *8. Operator loop*\n"
    "• none\n"
    "📎 *9. Evidence map*\n"
    "• none\n"
)

GOOD_FIXTURE_NOTE = (
    "# CIO book memo v1.3.0 · desk@vTEST\n"
    "stance: defensive_observe · cash STAGE_1 · as_of 2026-08-20T17:00:00\n"
    "────────────────\n"
    "🎯 *1. Executive thesis*\n"
    "Under desk@vTEST the book holds cash optionality; READ_ONLY_ADVISORY — no orders or stops.\n"
    "📊 *2. Portfolio state*\n"
    "Book $1.00M · cash 45.00% · Cash stage *STAGE_1* — paper plan only; no execution language.\n"
    "📐 *3. Allocation & concentration*\n"
    "Top weights (book-aggregated): SCHD 18.0%.\n"
    "📍 *4. Material situations (integrated)*\n"
    "Cash × SCHD × SPCX as one posture; watch-only; no buy-now language.\n"
    "✅ *5. What we are doing and why* (under `desk@vTEST`)\n"
    "1. *HOLD / STAGE cash* — Non-action is first-class.\n"
    "All recommendations remain READ_ONLY_ADVISORY — no orders or stops from this memo.\n"
    "🔬 *6. What would change the call*\n"
    "Cash — Advance beyond STAGE_1 only with operator ack.\n"
    "🔬 *7. Research agenda*\n"
    "• No urgent Hermes commissions; maintain observe.\n"
    "👤 *8. Operator loop*\n"
    "• No SCHD/SPCX dispositions matched this pass.\n"
    "📎 *9. Evidence map*\n"
    "• Spine as_of 2026-08-20T17:00:00 · domains: portfolio.\n"
    "No orders/stops from chat · READ_ONLY_ADVISORY\n"
)


def _minimal_desk_inputs() -> dict[str, Any]:
    """Dry collect_desk_inputs substitute — enough for render + generate schema."""
    return {
        "as_of": "2026-08-20T17:00:00+00:00",
        "pin": "desk@vTEST",
        "thesis": {
            "stance": "defensive_observe",
            "summary": "Preserve capital and optionality under desk@vTEST.",
            "principles": ["Non-action is first-class.", "Evidence before size."],
            "risk_posture_structured": {
                "cash_band_min_pct": 20,
                "max_single_name_weight_pct": 12,
                "concentration_fire_pct": 16.5,
                "deep_dd_threshold_pct": 25,
            },
        },
        "thresholds": {
            "cash_band_min_pct": 20,
            "max_single_name_weight_pct": 12,
            "concentration_fire_pct": 16.5,
            "deep_dd_threshold_pct": 25,
        },
        "portfolio": {
            "total_value": 1_000_000.0,
            "total_cash": 450_000.0,
            "cash_pct": 45.0,
            "day_change_pct": -0.1,
            "holdings_count": 10,
            "heat_pct": 0.1,
            "stops_active": 2,
            "data_quality": "OK",
            "schd_weight_pct": 18.0,
            "top_weights": [{"symbol": "SCHD", "weight_pct": 18.0}],
            "spcx": {"book_weight_pct": 2.0, "dd_from_basis_pct": 27.0},
        },
        "cash_stage": {
            "stage": 1,
            "label": "STAGE_1",
            "name": "Paper plan only",
            "recommendation": "allow sized plan text; require operator ack; no execution language",
            "reason": "cash_pct 45.0% > band 20.0%, quality OK, no operator stage opt-in yet",
        },
        "sector_posture": {
            "quality": "OK",
            "tilt_book_pct": {"DEFENSIVE": 30.0, "OFFENSIVE": 10.0, "UNCLASSIFIED": 5.0},
            "top3": [{"sector": "Financial Services", "weight_pct": 13.0}],
            "correlated_sleeves": [],
            "sector_cap_policy": None,
            "tensions": [],
        },
        "reentry_book": {
            "ok": True,
            "stage": 1,
            "actionable_count": 0,
            "core_full": 0,
            "sub_rr": 0,
            "micro_count": 0,
            "dropped_bad_rr": 0,
            "core_count": 0,
            "has_stage_eligible_core": False,
            "cards": [],
            "core_cards": [],
            "error": None,
        },
        "evidence_spine": {
            "domains_present": ["portfolio", "cash_buying_power"],
            "gaps": [],
            "focus_symbols": ["SCHD", "SPCX"],
            "name_meta": {
                "SCHD": {"book_weight_pct": 18.0},
                "SPCX": {"book_weight_pct": 2.0, "dd_from_basis_pct": 27.0},
            },
            "catalyst_by_symbol": {},
            "technicals_by_symbol": {},
            "hermes_by_plan": {},
        },
        "material_plans": [],
        "learning": [],
        "advisory_desk": {"top_actionable": []},
    }


def _assert_required_sections(note: str) -> None:
    missing = [m for m in REQUIRED_SECTION_MARKERS if m not in note]
    assert not missing, f"missing desk-note sections: {missing}"


def test_fixture_note_has_v1_3_sections_and_no_execution_language():
    """Structural golden on a known-good fixture note string."""
    assert "v1.3" in GOOD_FIXTURE_NOTE
    _assert_required_sections(GOOD_FIXTURE_NOTE)
    assert lint_execution_language(GOOD_FIXTURE_NOTE) is None


def test_negative_fixture_rejects_execution_language():
    """Critical defect: buy now / place order must fail the lint gate."""
    hit = lint_execution_language(EXEC_NEGATIVE_FIXTURE)
    assert hit is not None, "expected execution-language hit on negative fixture"
    assert hit.lower() in {"buy now", "place order", "force fill"}
    # Fixture still has v1.3 section scaffolding so the defect is content, not schema.
    _assert_required_sections(EXEC_NEGATIVE_FIXTURE)


def test_generate_desk_synthesis_v1_schema_and_version(monkeypatch):
    """Dry generate via monkeypatched collect_desk_inputs — version + sections."""
    import lib.cio_desk_synthesis as cds

    monkeypatch.setattr(cds, "collect_desk_inputs", _minimal_desk_inputs)

    out = generate_desk_synthesis_v1()
    assert out.get("ok") is True
    version = str(out.get("version") or "")
    assert "1.3" in version
    assert version == "desk-note-v1.3.0"
    assert out.get("authority") == "READ_ONLY_ADVISORY"

    note = out.get("note") or ""
    assert note, "expected rendered note"
    assert "v1.3" in note
    _assert_required_sections(note)
    assert lint_execution_language(note) is None


def test_render_desk_note_from_fixture_inputs():
    """Direct render path with fixture data (no live broker)."""
    note = render_desk_note(_minimal_desk_inputs(), telegram=False)
    assert re.search(r"v1\.3", note)
    _assert_required_sections(note)
    assert "READ_ONLY" in note
    assert lint_execution_language(note) is None
