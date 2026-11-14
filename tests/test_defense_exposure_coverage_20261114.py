"""DR-D01 (sprint 8H-2 b1): the exposure figure carries its coverage, and an unmeasured book is not a calm zero.

Before this change the projection published `stressed_usd` / `stressed_pct_invested` and nothing about what the
figure was computed from: a position with no look-through contributed $0 to the numerator while its dollars sat in
the denominator, so "the look-through failed" and "the book is not exposed" both printed "$0 · 0 % of invested".
The builder now publishes the counts and the basis it used, and `_exposure_section` passes them through; the v3
view refuses to print a figure unless the projection says `coverage_status: "measured"`.

Synthetic tickers and values only (the repo is public).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import defense_engine as de  # noqa: E402
from lib import market_risk_book_dollars as bd  # noqa: E402

AS_OF = "2030-01-07T14:00:00+00:00"
HEATMAP = [{"key": "semis", "kind": "sector", "state": "STRESS"}]


def _store(holdings: list[dict]) -> dict:
    # a position with no market_value contributes its shares, not a number, to the total
    return {"holdings": holdings,
            "portfolio_totals": {"total_value": sum(h["market_value"] or 0 for h in holdings)},
            "data_as_of": AS_OF}


def _row(symbol: str, mv: float) -> dict:
    return {"symbol": symbol, "account": "acct_a", "market_value": mv, "shares": 10.0, "canonical_mark": 100.0}


def _build(holdings: list[dict], positions: dict) -> dict:
    out = bd.build({"heatmap": HEATMAP, "positions": positions}, _store(holdings),
                   stops=[], policy={}, label_fn=lambda k: k, canon_fn=lambda k: k)
    return out["book_exposure"]


FULLY_MAPPED = {"ZZAA": {"look_through": {"groups": {"semis": 1.0}, "basis": "fund_holdings"}},
                "ZZBB": {"look_through": {"groups": {"energy": 1.0}, "basis": "fund_holdings"}}}


def test_a_fully_mapped_book_is_measured_and_names_its_basis():
    be = _build([_row("ZZAA", 1000.0), _row("ZZBB", 500.0)], FULLY_MAPPED)
    assert be["coverage_status"] == "measured"
    assert (be["positions_count"], be["mapped_count"], be["unmapped_count"]) == (2, 2, 0)
    assert be["unmapped_usd"] == 0 and be["mapped_usd"] == 1500.0
    assert be["look_through_basis"] == ["fund_holdings"]
    # the figure itself is unchanged by this contract addition
    assert be["stressed_usd"] == 1000.0


def test_a_book_with_an_unmapped_position_is_partial_never_measured():
    be = _build([_row("ZZAA", 1000.0), _row("ZZBB", 500.0), _row("ZZCC", 250.0)],
                {k: v for k, v in FULLY_MAPPED.items()})  # ZZCC has no look-through
    assert be["coverage_status"] == "partial"
    assert (be["positions_count"], be["mapped_count"], be["unmapped_count"]) == (3, 2, 1)
    assert be["unmapped_usd"] == 250.0 and be["mapped_usd"] == 1500.0
    assert [u["symbol"] for u in be["unmapped"]] == ["ZZCC"]


def test_an_empty_book_is_unknown_not_a_measured_zero():
    be = _build([], {})
    assert be["coverage_status"] == "unknown"
    assert be["stressed_usd"] == 0.0  # the figure is still what the engine computed; it is just not printable as calm


def test_the_projection_passes_coverage_through_and_defaults_to_unknown():
    be = _build([_row("ZZAA", 1000.0), _row("ZZCC", 250.0)], dict(FULLY_MAPPED))
    sec = de._exposure_section({"book_exposure": be}, 12, None)
    assert sec["coverage_status"] == "partial"
    assert (sec["positions_count"], sec["mapped_count"], sec["unmapped_count"]) == (2, 1, 1)
    assert sec["unmapped_usd"] == 250.0 and sec["look_through_basis"] == ["fund_holdings"]
    # no book exposure joined at all: the section says so and publishes no status to be trusted as measured
    missing = de._exposure_section({}, 12, None)
    assert missing["coverage_status"] == "unknown" and missing["as_of"] is None


# ── F1 / F2 (REVIEW-S2-defense-reentry-b1-cc-deepseek-3) ──────────────────────────────────────────────────────
def _unpriced(symbol: str) -> dict:
    return {"symbol": symbol, "account": "acct_a", "market_value": None, "shares": 4.0, "price": 25.0}


def test_f1_a_position_with_no_value_makes_coverage_partial_never_measured():
    # the reviewer's probe: two non-cash positions, one unpriced. Before F1 this printed positions_count 1,
    # coverage_status measured — a coverage claim wider than what was measured.
    be = _build([_row("ZZAA", 1000.0), _unpriced("ZZPP")], dict(FULLY_MAPPED))
    assert be["coverage_status"] == "partial", "an unpriced position was dropped from the denominator silently"
    assert be["unpriced_count"] == 1
    assert (be["positions_count"], be["mapped_count"], be["unmapped_count"]) == (1, 1, 0)
    assert be["unpriced_symbols"] == ["ZZPP"]


def test_f1_a_measured_book_with_no_unpriced_position_still_says_measured():
    be = _build([_row("ZZAA", 1000.0)], dict(FULLY_MAPPED))
    assert be["coverage_status"] == "measured" and be["unpriced_count"] == 0


def test_f2_an_empty_book_publishes_a_count_so_the_copy_can_say_which_unknown():
    be = _build([], {})
    assert be["coverage_status"] == "unknown" and be["positions_count"] == 0 and be["unpriced_count"] == 0


def test_f1_the_projection_passes_the_unpriced_fields_through():
    be = _build([_row("ZZAA", 1000.0), _unpriced("ZZPP")], dict(FULLY_MAPPED))
    sec = de._exposure_section({"book_exposure": be}, 12, None)
    assert sec["coverage_status"] == "partial"
    assert sec["unpriced_count"] == 1 and sec["unpriced_symbols"] == ["ZZPP"]
    # no book joined at all: even the count is unpublished, which is not the same as zero
    missing = de._exposure_section({}, 12, None)
    assert missing["unpriced_count"] is None and missing["unpriced_symbols"] == []
