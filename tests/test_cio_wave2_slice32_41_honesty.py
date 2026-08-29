"""Wave 2 slices 32–41 — data-quality honesty on the operator surfaces.

32  complete→checkpoint lineage reports a REASON, not a fake percentage.
33  temperament.narrative / next_reviews / closest-reentries carry T/D labels.
34  the briefs name which re-entry Surface they are quoting.
35  morning brief carries an earnings line whenever product.earnings is non-empty.
36  evening cash line is live temperament.cash, never portfolio_implication.
37  dark-contract scan (see the ops note; enforced by these tests existing).
38  store_consistency findings stay never_auto_remediate.
39  holdings as_of vs generated_at, and staleness measured on the position date.
40  two cash writers detected and BOTH printed. Never merged.
41  C2 blocks disposal of a dust-only name.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib import holdings_universe as hu
from scripts.lib.cio_advisory_admissibility import DUST_RESIDUAL_BLOCK, admit_advisory
from scripts.lib.cio_operator_renderers import (
    cash_lines,
    eod_text,
    morning_text,
    reentry_surface_label,
    watch_lines,
)
from scripts.lib.cio_p90_voice import apply_operator_voice, stamp_closest_reentries

NOW = datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc)


# ── 33 ───────────────────────────────────────────────────────────────────────

def test_closest_reentries_clause_is_marked_derived_inside_a_template_summary():
    text = "RISK OFF. Nothing requires action today. Closest re-entries: ATAI +3.0% vs exit."
    out = stamp_closest_reentries(text)
    assert "[D] Closest re-entries:" in out
    # the rest of the sentence is untouched
    assert out.startswith("RISK OFF.")


def test_closest_reentries_stamp_is_idempotent():
    once = stamp_closest_reentries("x Closest re-entries: A.")
    assert stamp_closest_reentries(once) == once


def test_summary_without_the_clause_is_unchanged():
    assert stamp_closest_reentries("RISK OFF. Nothing to do.") == "RISK OFF. Nothing to do."


def test_narrative_and_next_reviews_get_labels():
    out = apply_operator_voice({
        "executive_summary": "RISK OFF. Closest re-entries: ATAI +3.0% vs exit.",
        "temperament": {"narrative": "Temperament RISK OFF. FS receipts: 14."},
        "next_reviews": ["next material generation or next session", ""],
    })
    assert out["temperament"]["narrative"].startswith("[T] ")
    assert out["temperament"]["narrative_class"] == "T"
    assert out["next_reviews"][0].startswith("[T] ")
    assert out["next_reviews"][1] == ""              # empty stays empty
    assert out["next_reviews_class"] == "T"
    assert out["closest_reentries_class"] == "D"
    assert "[D] Closest re-entries:" in out["executive_summary"]


def test_voice_labels_do_not_double_stamp():
    once = apply_operator_voice({"temperament": {"narrative": "[T] already"}})
    assert once["temperament"]["narrative"] == "[T] already"


# ── 36 / 40: the two cash writers ────────────────────────────────────────────

AGREE = {"cash": {"cash_usd": 1000.0}, "temperament": {"cash": 1000.0, "cash_pct": 10.0}}
DISAGREE = {
    "cash": {"cash_usd": 630784.82},
    "temperament": {"cash": 578107.50, "cash_pct": 44.88},
}


def test_evening_cash_uses_the_live_temperament_number():
    lines = cash_lines(DISAGREE)
    assert "temperament.cash" in lines[0]
    assert "$578,108" in lines[0]
    assert "44.9% of book" in lines[0]


def test_disagreement_prints_both_and_merges_neither():
    lines = cash_lines(DISAGREE)
    body = " ".join(lines)
    assert "disagree" in body
    assert "$630,785" in body and "$578,108" in body
    assert "604,446" not in body            # the average — must never appear
    assert "Not merged" in body


def test_agreeing_sources_produce_no_warning():
    lines = cash_lines(AGREE)
    assert len(lines) == 1
    assert "disagree" not in lines[0]


def test_cash_line_never_renders_portfolio_implication():
    product = {
        "cash": {"cash_usd": 1000.0},
        "temperament": {
            "cash": 1000.0,
            "portfolio_implication": "Preserve quality growth exposure",
        },
    }
    body = " ".join(cash_lines(product))
    assert "Preserve quality growth" not in body


def test_missing_cash_is_unavailable_not_zero():
    lines = cash_lines({})
    assert "UNAVAILABLE" in lines[0]
    assert "$0" not in lines[0]


def test_eod_brief_carries_the_cash_line():
    text = eod_text({**DISAGREE, "executive_summary": "x"})
    assert "temperament.cash" in text
    assert "disagree" in text


# ── 34: which book is being quoted ───────────────────────────────────────────

def test_surface_is_named_and_the_other_book_is_declared_separate():
    label = reentry_surface_label({"reentry": {"surface": "A", "scope": "former holdings vs exit trigger"}})
    assert "Surface A" in label
    assert "not merged" in label.lower()


def test_unlabeled_surface_says_so_rather_than_guessing_a():
    assert "UNLABELED" in reentry_surface_label({"reentry": {}})
    assert "UNLABELED" in reentry_surface_label({})


def test_both_briefs_name_the_surface():
    product = {"executive_summary": "x", "reentry": {"surface": "A", "scope": "s"}}
    assert "Surface A" in morning_text(product)
    assert "Surface A" in eod_text(product)


# ── watch names (operator question) ──────────────────────────────────────────

WBS = {
    "count": 26,
    "by_reason": {"not_promotion_grade": 26},
    "ready_count": 0, "ready_symbols": [], "near_symbols": [], "fires_s7": False,
    "top": [{"symbol": "FTH", "trade_ai_state": "WAIT"},
            {"symbol": "ANET", "trade_ai_state": "WAIT"},
            {"symbol": "PFLT", "trade_ai_state": "MANAGING"}],
}


def test_block_names_are_surfaced_with_their_state():
    body = " ".join(watch_lines({"watch_block_summary": WBS}))
    assert "FTH (WAIT)" in body and "PFLT (MANAGING)" in body
    assert "Watch BLOCK (26)" in body
    assert "+23 more" in body


def test_zero_ready_is_stated_as_honest_not_hidden():
    body = " ".join(watch_lines({"watch_block_summary": WBS}))
    assert "none (ready 0, fires_s7 False)" in body
    assert "honest zero" in body


def test_block_is_never_relabelled_ready():
    body = " ".join(watch_lines({"watch_block_summary": WBS}))
    assert "READY FTH" not in body
    assert "READY" not in body.split("Watch BLOCK")[0].replace("promotion-grade", "")


def test_named_ready_is_shown_when_it_genuinely_exists():
    wbs = {**WBS, "ready_count": 1, "ready_symbols": ["XYZ"], "top": []}
    body = " ".join(watch_lines({"watch_block_summary": wbs}))
    assert "READY XYZ" in body


def test_no_watch_block_summary_yields_no_watch_lines():
    assert watch_lines({}) == []


# ── 39 / 40: holdings data quality ───────────────────────────────────────────

def _doc(as_of="2026-08-28", generated="2026-08-28 16:45:01 ET", total_cash=100.0):
    return {
        "as_of": as_of,
        "generated_at": generated,
        "portfolio_totals": {"total_cash": total_cash},
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 100.0, "account": "a"},
            {"symbol": "SCHD", "market_value": 1000.0},
        ],
    }


def _patched(monkeypatch, doc):
    monkeypatch.setattr(hu, "load_holdings_doc", lambda *, root=None: doc)


def test_fresh_positions_are_ok(monkeypatch):
    _patched(monkeypatch, _doc(as_of="2026-08-29"))
    q = hu.holdings_data_quality(now=NOW)
    assert q["state"] == "OK"
    assert q["labels"] == []


def test_stale_positions_are_flagged_not_silent(monkeypatch):
    _patched(monkeypatch, _doc(as_of="2026-08-26"))
    q = hu.holdings_data_quality(now=NOW)
    assert q["state"] == hu.DATA_STALE
    assert hu.DATA_STALE in q["labels"]
    assert q["position_date_age_days"] == 3


def test_a_fresh_reprice_does_not_hide_stale_positions(monkeypatch):
    """Reprice today over 3-day-old positions is still stale positions."""
    _patched(monkeypatch, _doc(as_of="2026-08-26", generated="2026-08-29 09:00:00"))
    q = hu.holdings_data_quality(now=NOW)
    assert hu.DATA_STALE in q["labels"]
    assert "REPRICE_AHEAD_OF_POSITIONS" in q["labels"]


def test_cash_writers_that_disagree_are_both_reported_never_merged(monkeypatch):
    _patched(monkeypatch, _doc(total_cash=47.32))
    q = hu.holdings_data_quality(now=NOW)
    cash = q["cash_totals"]
    assert cash["cash_row_sum"] == 100.0
    assert cash["portfolio_totals_total_cash"] == 47.32
    assert cash["delta_rows_minus_declared"] == 52.68
    assert cash["sources_agree"] is False
    assert cash["merged"] is False and cash["reconciled"] is False
    assert "CASH_TOTAL_DISAGREEMENT" in q["labels"]


def test_agreeing_cash_writers_raise_no_label(monkeypatch):
    _patched(monkeypatch, _doc(total_cash=100.0))
    q = hu.holdings_data_quality(now=NOW)
    assert q["cash_totals"]["sources_agree"] is True
    assert "CASH_TOTAL_DISAGREEMENT" not in q["labels"]


def test_empty_holdings_is_data_unavailable(monkeypatch):
    _patched(monkeypatch, {})
    q = hu.holdings_data_quality(now=NOW)
    assert q["state"] == hu.DATA_UNAVAILABLE
    assert q["labels"] == [hu.DATA_UNAVAILABLE]


def test_data_quality_never_auto_remediates(monkeypatch):
    _patched(monkeypatch, _doc())
    assert hu.holdings_data_quality(now=NOW)["auto_remediate"] is False


# ── 38 ───────────────────────────────────────────────────────────────────────

def test_store_consistency_findings_stay_never_auto_remediate():
    import inspect

    from scripts.lib import store_consistency as sc

    src = inspect.getsource(sc)
    assert src.count('"never_auto_remediate": True') >= 2
    assert '"never_auto_remediate": False' not in src


# ── 41 ───────────────────────────────────────────────────────────────────────

HOLD = {"holdings": [
    {"symbol": "SCHD", "market_value": 365694.75, "shares": 10000.25},
    {"symbol": "SCHG", "market_value": 8.09, "shares": 0.2294},
    {"symbol": "CASH", "is_cash": True, "market_value": 100.0},
]}


@pytest.mark.parametrize("action", ["TRIM", "SELL", "EXIT", "REDUCE", "REBALANCE_TRIM"])
def test_c2_blocks_disposal_of_a_dust_only_name(action):
    r = admit_advisory(symbol="SCHG", recommendation=action, holdings=HOLD)
    assert r["admissible"] is False
    assert r["reason"] == DUST_RESIDUAL_BLOCK
    assert r["blocked"] is True


def test_c2_still_admits_trim_of_a_real_position():
    r = admit_advisory(symbol="SCHD", recommendation="TRIM", holdings=HOLD)
    assert r["admissible"] is True


def test_c2_still_blocks_trim_of_an_unheld_name():
    r = admit_advisory(symbol="QCOM", recommendation="TRIM", holdings=HOLD)
    assert r["admissible"] is False
    assert r["reason"] != DUST_RESIDUAL_BLOCK      # the original rule, not the new one


def test_avoid_on_a_dust_name_is_still_admissible():
    """The block is on disposal only. AVOID says nothing about a position."""
    assert admit_advisory(symbol="SCHG", recommendation="AVOID", holdings=HOLD)["admissible"] is True
    assert admit_advisory(symbol="QCOM", recommendation="AVOID", holdings=HOLD)["admissible"] is True


def test_unknown_holdings_still_fail_closed():
    r = admit_advisory(symbol="SCHD", recommendation="TRIM", holdings=None)
    assert r["admissible"] is False
    assert r["reason"] == "unknown_holding_fail_closed"


# ── 32 ───────────────────────────────────────────────────────────────────────

def test_uncomputable_rate_reports_a_reason_not_zero(tmp_path):
    from scripts.lib.cio_plan_outcome_checkpoints import checkpoint_lineage_health

    cio = tmp_path / "data" / "cio"
    cio.mkdir(parents=True)
    (cio / "outcome_checkpoints.jsonl").write_text(
        '{"status":"SCHEDULED","horizon":"1_session","context_receipt":{"symbol":"CASH"}}\n'
        '{"status":"RESOLVED","horizon":"1_session","context_receipt":{"symbol":"SCHD"}}\n',
        encoding="utf-8",
    )
    (cio / "hermes_research_projection.json").write_text(
        '{"by_research_id":{"r1":{"status":"completed","plan_id":"p1"}}}', encoding="utf-8",
    )
    h = checkpoint_lineage_health(root=tmp_path, holdings=HOLD)
    assert h["checkpoints_total"] == 2
    assert h["with_plan_id"] == 0
    assert h["joinable_by_plan_id"] is False
    assert h["rate_state"] == "UNCOMPUTABLE"
    assert h["complete_to_checkpoint_rate"] is None      # never a fabricated 0.0
    assert "do not join" in h["rate_reason"]
    assert h["non_security_subjects"] == {"CASH": 1}


def test_missing_checkpoint_store_is_zero_not_a_crash(tmp_path):
    from scripts.lib.cio_plan_outcome_checkpoints import checkpoint_lineage_health

    h = checkpoint_lineage_health(root=tmp_path)
    assert h["checkpoints_total"] == 0
    assert h["rate_state"] == "UNCOMPUTABLE"


# ── slice 37 follow-through: the root-reading helpers get direct coverage ────

@pytest.fixture()
def book(tmp_path):
    import json

    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "holdings.json").write_text(json.dumps({
        "as_of": "2026-08-29",
        "generated_at": "2026-08-29 09:00:00",
        "portfolio_totals": {"total_cash": 585917.80},
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 585917.80, "account": "ira"},
            {"symbol": "SCHD", "market_value": 365694.75},
            {"symbol": "SPCX", "market_value": 5.00, "account": "taxable"},
            {"symbol": "SPCX", "market_value": 21833.60, "account": "ira"},
            {"symbol": "SCHG", "market_value": 8.09},
            {"symbol": "12507E201", "market_value": 0.0, "account": "taxable",
             "name": "DELISTED — CUSIP 12507E201"},
        ],
    }), encoding="utf-8")
    return tmp_path


def test_held_dust_and_nondust_from_disk(book):
    assert hu.held_dust_tickers(root=book) == ["SCHG"]
    assert hu.held_equity_tickers_nondust(root=book) == ["SCHD", "SPCX"]
    assert hu.held_equity_tickers(root=book) == ["SCHD", "SCHG", "SPCX"]


def test_market_value_aggregates_across_accounts_from_disk(book):
    totals = hu.held_market_value_by_ticker(root=book)
    assert totals["SPCX"] == 21838.60          # 5.00 + 21833.60, not dust
    assert totals["SCHG"] == 8.09


def test_dust_table_labels_every_ticker(book):
    table = {r["symbol"]: r["holding_status"] for r in hu.dust_table(root=book)}
    assert table == {"SCHD": hu.HELD_STATUS, "SPCX": hu.HELD_STATUS,
                     "SCHG": hu.DUST_STATUS}


def test_dust_status_for_uses_the_aggregate(book):
    totals = hu.held_market_value_by_ticker(root=book)
    assert hu.dust_status_for("SPCX", totals) == hu.HELD_STATUS
    assert hu.dust_status_for("SCHG", totals) == hu.DUST_STATUS


def test_instrument_id_rows_from_disk(book):
    rows = hu.held_instrument_id_rows(root=book)
    assert len(rows) == 1
    assert rows[0]["instrument_id"] == "12507E201"
    assert rows[0]["id_type"] == "CUSIP"
    assert rows[0]["is_ticker"] is False


def test_cash_total_sources_from_disk(book):
    cash = hu.cash_total_sources(root=book)
    assert cash["cash_row_sum"] == 585917.80
    assert cash["sources_agree"] is True
    assert cash["by_account"] == {"ira": 585917.80}


def test_snapshot_carries_every_wave2_field(book):
    snap = hu.snapshot(root=book)
    assert snap["dust_n"] == 1 and snap["dust_tickers"] == ["SCHG"]
    assert snap["held_equity_ticker_n"] == 3
    assert snap["held_equity_ticker_nondust_n"] == 2
    assert snap["instrument_id_n"] == 1
    assert snap["dust_policy"]["threshold_usd"] == 50.0


def test_a_string_root_works_everywhere(book):
    """A str root used to raise TypeError inside a fail-soft caller."""
    assert hu.held_dust_tickers(root=str(book)) == ["SCHG"]
    assert hu.holdings_data_quality(root=str(book))["state"] == "OK"
